"""Small local primitives for complete capture and conservative budget accounting."""
import contextlib
import fcntl
import hashlib
import json
import math
import os
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path


class ResearchError(Exception):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def money(value):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ResearchError('Invalid monetary amount')
    if not result.is_finite() or result < 0:
        raise ResearchError('Amount must be finite and non-negative')
    return result


def inside(root, relative):
    root = Path(root).resolve()
    rel = Path(relative)
    if rel.is_absolute():
        raise ResearchError('Expected a path relative to the task directory')
    target = (root / rel).resolve()
    if not target.is_relative_to(root):
        raise ResearchError('Path escapes the task directory')
    return target


def write_bytes(path, body):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.capture-', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'wb') as f:
            os.fchmod(f.fileno(), 0o600)
            f.write(body)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def write_json(path, value):
    write_bytes(path, (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode())


def read_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError) as e:
        raise ResearchError('Cannot read JSON: ' + Path(path).name + ' (' + type(e).__name__ + ')')


SENSITIVE = re.compile(r'^(authorization|proxy-authorization|cookie|set-cookie|x-api-key|api[_-]?key|access[_-]?token|auth[_-]?token|password|secret|ct0|twid)$', re.I)


def sse_events(text):
    """Assemble complete SSE events, joining data fields with LF (WHATWG SSE).

    Preserve non-data fields and incomplete tail for capture; incomplete events
    are never dispatched as successful RPC results.
    """
    normalized = text.removeprefix('\ufeff').replace('\r\n', '\n').replace('\r', '\n')
    lines = normalized.split('\n')
    if normalized.endswith('\n'):
        lines.pop()  # line terminator is not itself a second blank line
    events, block = [], []

    def event(raw, complete):
        data, fields = [], []
        for line in raw:
            if line.startswith(':'):
                fields.append({':': line[1:]}); continue
            key, separator, value = line.partition(':')
            if value.startswith(' '): value = value[1:]
            if key == 'data': data.append(value)
            else: fields.append({key: value if separator else ''})
        return {'fields': fields, 'data': '\n'.join(data), 'has_data': bool(data), 'complete': complete}

    for line in lines:
        if line == '':
            if block: events.append(event(block, True)); block = []
        else: block.append(line)
    if block: events.append(event(block, False))
    return events


def redact(value, secrets=()):
    if isinstance(value, dict):
        return {k: '[REDACTED]' if SENSITIVE.fullmatch(str(k)) else redact(v, secrets) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, secrets) for v in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, '[REDACTED]').replace(urllib.parse.quote(secret, safe=''), '[REDACTED]')
        # MCP may deliver JSON inside SSE strings or text blocks. Redact those
        # structures too, including upstream credentials unknown to this client.
        if any(line.removeprefix('\ufeff').startswith('data:') for line in value.splitlines()):
            rendered = []
            for event in sse_events(value):
                lines = []
                for field in redact(event['fields'], secrets):
                    for key, item in field.items():
                        lines.append(':' + item if key == ':' else key + ': ' + item)
                if event['has_data']:
                    # Crucially redact the assembled event, not individual lines.
                    payload = str(redact(event['data'], secrets))
                    lines.extend('data: ' + line for line in payload.split('\n'))
                rendered.append('\n'.join(lines) + ('\n\n' if event['complete'] else ''))
            return ''.join(rendered)
        try:
            decoded = json.loads(value)
        except ValueError:
            decoded = None
        if isinstance(decoded, (dict, list)):
            return json.dumps(redact(decoded, secrets), ensure_ascii=False)
        value = re.sub(r'(?i)(Bearer\s+)[A-Za-z0-9._~+/=-]{12,}', r'\1[REDACTED]', value)
        value = re.sub(r'(?i)([?&](?:api_?key|access_token|auth_token|password|token)=)[^&#\s"<>]+', r'\1[REDACTED]', value)
        value = re.sub(r'(?im)^([ \t]*(?:authorization|proxy-authorization|cookie|set-cookie|x-api-key)[ \t]*:[ \t]*)(?:[^\r\n]*(?:\r?\n[ \t]+[^\r\n]*)*)', r'\1[REDACTED]', value)
        value = re.sub(r'''(?ix)((?:["']?)(?:authorization|proxy-authorization|cookie|set-cookie|x-api-key)(?:["']?)\s*[:=]\s*)(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')''', r'\1"[REDACTED]"', value)
    return value


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request(url, method='GET', headers=None, body=None, timeout=30, max_bytes=32 * 1024 * 1024):
    """No retry or redirect. A too-large body is a failure, never a silent truncation."""
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != 'https' or parsed.username or parsed.password:
        raise ResearchError('Only HTTPS requests without URL userinfo are allowed')
    req = urllib.request.Request(url, data=body, method=method, headers={'User-Agent': 'Mozilla/5.0 material-research/1', **(headers or {})})
    try:
        response = urllib.request.build_opener(NoRedirect()).open(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        response = e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ResearchError('Network failure (' + type(e).__name__ + '); no automatic retry')
    with response:
        raw = response.read(max_bytes + 1)
        status = response.code
    if len(raw) > max_bytes:
        raise ResearchError('Response exceeded capture limit; complete source was not obtained')
    text = raw.decode('utf-8', 'replace')
    try:
        payload = json.loads(text)
    except ValueError:
        payload = text
    return status, payload


def require_success(status, payload):
    if not 200 <= status < 300:
        raise ResearchError('HTTP ' + str(status))
    if isinstance(payload, dict):
        if payload.get('error') or payload.get('isError') is True or payload.get('success') is False:
            raise ResearchError('Provider reported a business error')
        if 'code' in payload and payload['code'] not in (0, 200, '0', '200', None):
            raise ResearchError('Provider business code indicates failure')


class Budget:
    def __init__(self, root):
        self.root = Path(root).resolve()

    @contextlib.contextmanager
    def locked(self):
        self.root.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(self.root / '.budget.lock'), os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        with os.fdopen(fd, 'a+') as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            yield

    def events(self):
        path = inside(self.root, 'ledger.jsonl')
        if not path.exists():
            return []
        try:
            return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        except ValueError:
            raise ResearchError('Ledger is invalid; refusing to reset or ignore prior calls')

    def append(self, event):
        path = inside(self.root, 'ledger.jsonl')
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        with os.fdopen(fd, 'a') as f:
            os.fchmod(f.fileno(), 0o600)
            f.write(json.dumps(event, ensure_ascii=False, allow_nan=False) + '\n')
            f.flush()
            os.fsync(f.fileno())

    def initialize(self, usd, credits, max_calls, authorization):
        if not authorization.strip() or max_calls < 1:
            raise ResearchError('Authorization scope and a positive call cap are required')
        limits = {'USD': str(money(usd)), 'credits': str(money(credits))}
        with self.locked():
            path = inside(self.root, 'budget.json')
            if path.exists() or self.events():
                raise ResearchError('Budget already exists; refusing to reset cumulative usage')
            data = {'created_at': now(), 'authorization': authorization, 'limits': limits, 'max_calls': max_calls}
            write_json(path, data)
        return data

    def attempts(self):
        attempts = {}
        for event in self.events():
            if event.get('phase') == 'reserve':
                attempts[event['id']] = dict(event)
            elif event.get('phase') == 'settle':
                if event['id'] not in attempts:
                    raise ResearchError('Orphan ledger settlement')
                attempts[event['id']].update(event)
        return list(attempts.values())

    def status(self):
        cfg = read_json(inside(self.root, 'budget.json'))
        attempts = self.attempts()
        spent = {'USD': Decimal('0'), 'credits': Decimal('0')}
        reported = {'USD': Decimal('0'), 'credits': Decimal('0')}
        for a in attempts:
            spent[a['unit']] += money(a.get('debit', a['reserved']))
            if a.get('provider_charged') is not None:
                reported[a['unit']] += money(a['provider_charged'])
        return {'limits': cfg['limits'], 'max_calls': cfg['max_calls'], 'attempts': len(attempts),
                'accounted': {k: str(v) for k, v in spent.items()},
                'provider_reported': {k: str(v) for k, v in reported.items()},
                'uncertain_attempts': sum(a.get('cost_basis') != 'provider_receipt' for a in attempts),
                'blocked': any(a.get('over_quote', False) for a in attempts)}

    def reserve(self, quote, refresh=False):
        with self.locked():
            cfg = read_json(inside(self.root, 'budget.json'))
            attempts = self.attempts()
            same = [a for a in attempts if a['fingerprint'] == quote['fingerprint']]
            if same and not refresh:
                return {'cached': True, 'attempt': same[-1]}
            state = self.status()
            if state['blocked']:
                raise ResearchError('Prior actual charge exceeded quote; budget is blocked for review')
            unit = quote['unit']
            if unit not in cfg['limits']:
                raise ResearchError('Unknown billing unit')
            if len(attempts) >= cfg['max_calls']:
                raise ResearchError('Maximum paid request attempts reached')
            if money(state['accounted'][unit]) + money(quote['amount']) > money(cfg['limits'][unit]):
                raise ResearchError('Request would exceed cumulative ' + unit + ' budget')
            event = {'phase': 'reserve', 'id': uuid.uuid4().hex, 'at': now(), 'provider': quote['provider'],
                     'operation': quote['operation'], 'fingerprint': quote['fingerprint'], 'unit': unit,
                     'reserved': str(money(quote['amount'])), 'status': 'in_flight', 'purpose': quote['purpose']}
            self.append(event)
            return {'cached': False, 'attempt': event}

    def settle(self, attempt, status, raw_path=None, error=None, actual=None, raw_sha256=None):
        event = {'phase': 'settle', 'id': attempt['id'], 'at': now(), 'status': status,
                 'raw_path': raw_path, 'raw_sha256': raw_sha256, 'error': error,
                 'debit': attempt['reserved'], 'cost_basis': 'quote_reserved'}
        if actual is not None:
            event.update(debit=str(max(money(actual), money(attempt['reserved']))), provider_charged=str(money(actual)), cost_basis='provider_receipt',
                         over_quote=money(actual) > money(attempt['reserved']))
        with self.locked():
            if not any(a['id'] == attempt['id'] and a.get('phase') == 'reserve' for a in self.attempts()):
                raise ResearchError('Attempt already settled or not found')
            self.append(event)
        return event
