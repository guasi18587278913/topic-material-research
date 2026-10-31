#!/usr/bin/env python3
"""Read-only research capture. Quote first; one paid request per run, no auto retry."""
import argparse
import html
import ipaddress
import json
import os
import re
import socket
import subprocess
import sys
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from _common import (Budget, ResearchError, SENSITIVE, canonical, digest, inside, money,
                     now, read_json, redact, request, require_success, sse_events, write_json)


OPS = {
    'getxapi': {
        'search': ('advanced_search_tweets', '/twitter/tweet/advanced_search', 'advanced-search'),
        'detail': ('get_tweet_detail', '/twitter/tweet/detail', 'detail'),
        'thread': ('get_tweet_thread', '/twitter/tweet/thread', 'thread'),
        'replies': ('get_tweet_replies', '/twitter/tweet/replies', 'replies'),
    },
    'tikhub': {
        'xhs-search': ('GET', '/api/v1/xiaohongshu/app_v2/search_notes', ['keyword'],
                       {'sort_type': 'general', 'time_filter': '不限', 'page': '1'}, ['keyword', 'sort_type', 'time_filter', 'page']),
        'xhs-comments': ('GET', '/api/v1/xiaohongshu/app_v2/get_note_comments', ['note_id'],
                         {'sort_strategy': 'latest_v2', 'index': 0}, ['note_id', 'sort_strategy', 'index']),
        'xhs-image-detail': ('GET', '/api/v1/xiaohongshu/app_v2/get_image_note_detail', ['note_id'], {}, ['note_id']),
        'xhs-video-detail': ('GET', '/api/v1/xiaohongshu/app_v2/get_video_note_detail', ['note_id'], {}, ['note_id']),
        'xhs-user-posts': ('GET', '/api/v1/xiaohongshu/app_v2/get_user_posted_notes', ['user_id'],
                          {}, ['user_id', 'cursor']),
        'dy-search': ('POST', '/api/v1/douyin/search/fetch_video_search_v2', ['keyword'],
                      {'cursor': 0, 'sort_type': '0', 'publish_time': '0', 'filter_duration': '0',
                       'content_type': '0', 'search_id': '', 'backtrace': ''},
                      ['keyword', 'cursor', 'sort_type', 'publish_time', 'filter_duration', 'content_type', 'search_id', 'backtrace']),
    },
    'agentkey': {
        'serper-search': 'Serper/search',
        'serper-news': 'Serper/searchNews',
        'jina-read': 'Jina/readUrlGet',
    },
}


def validate_params(params, schema=None):
    if not isinstance(params, dict):
        raise ResearchError('Parameters must be a JSON object')
    for k, v in params.items():
        if SENSITIVE.fullmatch(k) or k.lower() in {'headers', 'cookies', 'actions', 'javascript', 'proxy'}:
            raise ResearchError('Credentials or active actions are not allowed in research parameters')
        if isinstance(v, (dict, list)):
            raise ResearchError('Only documented scalar parameters are supported by this adapter')
    if schema is None:
        return
    props = schema.get('properties', {})
    if set(params) - set(props):
        raise ResearchError('Unknown parameters: ' + ', '.join(sorted(set(params) - set(props))))
    for k in schema.get('required', []):
        if k not in params or params[k] in (None, ''):
            raise ResearchError('Missing required parameter: ' + k)
    types = {'string': str, 'boolean': bool, 'integer': int, 'number': (int, float)}
    for k, v in params.items():
        prop = props[k]; typ = prop.get('type')
        if typ in types and (not isinstance(v, types[typ]) or typ in {'integer', 'number'} and isinstance(v, bool)):
            raise ResearchError('Wrong parameter type: ' + k)
        if 'enum' in prop and v not in prop['enum']:
            raise ResearchError('Unsupported parameter value: ' + k)


def public_url(url, resolve=False):
    p = urllib.parse.urlsplit(url)
    if p.scheme not in {'https', 'http'} or not p.hostname or p.username or p.password:
        raise ResearchError('Expected a public URL without embedded credentials')
    host = p.hostname.lower().rstrip('.')
    if host in {'localhost', 'localhost.localdomain'} or host.endswith(('.local', '.internal')):
        raise ResearchError('Local/private URLs are not supported')
    try:
        if not ipaddress.ip_address(host).is_global:
            raise ResearchError('Local/private URLs are not supported')
    except ValueError:
        try:
            # inet_aton accepts legacy decimal, hex and shortened IPv4 literals.
            address = ipaddress.ip_address(socket.inet_aton(host))
        except OSError:
            address = None
        if address is not None and not address.is_global:
            raise ResearchError('Local/private URLs are not supported')
    if resolve:
        try:
            answers = socket.getaddrinfo(host, p.port or (443 if p.scheme == 'https' else 80), type=socket.SOCK_STREAM)
        except OSError:
            raise ResearchError('Public URL host could not be resolved; no provider fetch sent')
        if not answers or any(not ipaddress.ip_address(a[4][0]).is_global for a in answers):
            raise ResearchError('Public URL resolves to a private or reserved address')
    for k in urllib.parse.parse_qs(p.query):
        if SENSITIVE.fullmatch(k) or k.lower() in {'token', 'key'}:
            raise ResearchError('Credential-bearing URLs are not supported')


def account_credits(account):
    """The 2026-10-24 verified free account envelope; never inspect source text."""
    credits = account.get('credits') if isinstance(account, dict) else None
    if not isinstance(credits, dict) or 'remaining' not in credits or isinstance(credits['remaining'], bool):
        raise ResearchError('AgentKey account envelope has no verified credits.remaining field')
    return money(credits['remaining'])


class Client:
    def __init__(self, transport=request):
        self.http = transport
        self.secrets = []
        self.keys = {}
        self.last_response = None
        self.verified_charge = None

    def key(self, provider):
        if provider in self.keys:
            return self.keys[provider]
        envs = ['GETXAPI_KEY'] if provider == 'getxapi' else ['TIKHUB_API_KEY', 'TIKHUB_KEY', 'TIKHUB_TOKEN']
        key = next((os.environ[k] for k in envs if os.environ.get(k)), '')
        if not key and sys.platform == 'darwin':
            service, account = ('GetXAPI', 'GETXAPI_KEY') if provider == 'getxapi' else ('TikHub', 'TIKHUB_API_KEY')
            run = subprocess.run(['/usr/bin/security', 'find-generic-password', '-s', service, '-a', account, '-w'], capture_output=True, text=True)
            if run.returncode == 0:
                key = run.stdout.strip()
        if not key:
            raise ResearchError(provider + ' credential is unavailable; no data request sent')
        self.keys[provider] = key; self.secrets.append(key)
        return key

    def provider_http(self, provider, path, params, method='GET'):
        base = {'getxapi': 'https://api.getxapi.com', 'tikhub': 'https://api.tikhub.io'}[provider]
        headers = {'Authorization': 'Bearer ' + self.key(provider)}
        url, body = base + path, None
        if method == 'GET':
            url += '?' + urllib.parse.urlencode(params)
        else:
            body = canonical(params); headers['Content-Type'] = 'application/json'
        return self.http(url, method=method, headers=headers, body=body)

    def agent_config(self):
        url = os.environ.get('AGENTKEY_MCP_URL')
        if url:
            headers = {}
            if os.environ.get('AGENTKEY_API_KEY'):
                headers['Authorization'] = 'Bearer ' + os.environ['AGENTKEY_API_KEY']
        else:
            cfg = read_json(Path.home() / '.claude.json')
            entry = cfg.get('mcpServers', {}).get('agentkey', {})
            url, headers = entry.get('url'), dict(entry.get('headers', {}))
        parsed = urllib.parse.urlsplit(url or '')
        if parsed.scheme != 'https' or parsed.hostname != 'api.agentkey.app' or parsed.username or parsed.password:
            raise ResearchError('Configured AgentKey HTTPS endpoint is unavailable or unsupported')
        for value in headers.values():
            self.secrets.extend([str(value), str(value).removeprefix('Bearer ')])
        for values in urllib.parse.parse_qs(parsed.query).values():
            self.secrets.extend(values)
        return url, headers

    def rpc(self, name, arguments):
        url, headers = self.agent_config()
        headers.update({'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream'})
        status, payload = self.http(url, method='POST', headers=headers,
            body=canonical({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': name, 'arguments': arguments}}))
        # Preserve every block/envelope before interpreting business success.
        self.last_response = {'http_status': status, 'body': payload}
        if isinstance(payload, str):
            matches = []
            for event in sse_events(payload):
                if not event['complete'] or not event['has_data']:
                    continue
                try:
                    candidate = json.loads(event['data'])
                except ValueError:
                    continue
                if isinstance(candidate, dict) and candidate.get('id') == 1:
                    matches.append(candidate)
            if not matches:
                raise ResearchError('Unrecognised AgentKey MCP response')
            payload = matches[-1]
        if not isinstance(payload, dict):
            raise ResearchError('Invalid AgentKey MCP envelope type')
        require_success(status, payload)
        if payload.get('jsonrpc') != '2.0' or payload.get('id') != 1 or 'result' not in payload:
            raise ResearchError('Missing or mismatched AgentKey JSON-RPC result envelope')
        result = payload.get('result', {})
        if not isinstance(result, dict):
            raise ResearchError('Invalid AgentKey MCP result type')
        require_success(status, result)
        if 'structuredContent' in result and not isinstance(result['structuredContent'], dict):
            raise ResearchError('Invalid AgentKey structuredContent type')
        if 'content' not in result and 'structuredContent' not in result:
            raise ResearchError('AgentKey result has no content fields')
        data = result.get('structuredContent')
        if data is None:
            blocks = result.get('content', [])
            if not isinstance(blocks, list) or any(not isinstance(c, dict) for c in blocks):
                raise ResearchError('Invalid AgentKey content blocks')
            text = '\n'.join(c.get('text', '') for c in blocks if c.get('type') == 'text' and isinstance(c.get('text'), str))
            try:
                data = json.loads(text)
            except ValueError:
                data = {'text': text}
        return status, data

    def quote(self, provider, operation, params, purpose):
        if provider not in OPS or operation not in OPS[provider]:
            raise ResearchError('Unsupported public-read operation; inspect the provider catalog for other capabilities')
        if not purpose.strip():
            raise ResearchError('A concrete research purpose is required')
        validate_params(params)
        meta = {}
        if provider == 'getxapi':
            tool_name, expected_path, doc = OPS[provider][operation]
            status, manifest = self.http('https://api.getxapi.com/mcp/manifest')
            require_success(status, manifest)
            tool = next((t for t in manifest.get('tools', []) if t.get('name') == tool_name), None)
            if not tool or tool.get('path') != expected_path or tool.get('method') != 'GET' or tool.get('annotations', {}).get('readOnlyHint') is not True:
                raise ResearchError('GetXAPI manifest no longer matches this public-read operation')
            validate_params(params, tool['inputSchema'])
            price_url = 'https://docs.getxapi.com/docs/tweets/' + doc
            code, page = self.http(price_url)
            require_success(code, page)
            plain = html.unescape(re.sub(r'<[^>]+>', ' ', page if isinstance(page, str) else json.dumps(page)))
            match = re.search(r'This endpoint costs\s*[`\s]*\$\s*([0-9]+(?:\.[0-9]+)?)', plain, re.I)
            if not match:
                raise ResearchError('Cannot extract an exact current GetXAPI endpoint price; no data request sent')
            amount, unit, path, method = str(money(match.group(1))), 'USD', expected_path, 'GET'
            meta = {'price_source': price_url, 'schema': tool['inputSchema'], 'manifest': 'https://api.getxapi.com/mcp/manifest'}
        elif provider == 'tikhub':
            method, path, required, defaults, allowed = OPS[provider][operation]
            params = {**defaults, **params}
            if set(params) - set(allowed) or any(params.get(k) in (None, '') for k in required):
                raise ResearchError('Unknown or missing TikHub parameters')
            if any(not isinstance(params[k], str) or not params[k].strip() for k in required):
                raise ResearchError('TikHub required identifiers/keywords must be non-empty strings')
            status, info = self.provider_http('tikhub', '/api/v1/tikhub/user/get_endpoint_info', {'endpoint': path})
            require_success(status, info)
            data = info.get('data', {})
            if data.get('endpoint_uri') != path or 'endpoint_cost' not in data:
                raise ResearchError('TikHub quote does not match requested endpoint')
            amount, unit = str(money(data['endpoint_cost'])), 'USD'
            meta = {'price_source': 'https://api.tikhub.io/api/v1/tikhub/user/get_endpoint_info', 'endpoint_quote': data}
        else:
            name = OPS[provider][operation]
            status, info = self.rpc('describe_tool', {'name': name})
            require_success(status, info)
            if not isinstance(info, dict) or info.get('tool', info.get('name')) != name or info.get('execute_as', {}).get('name') != name:
                raise ResearchError('AgentKey descriptor does not match the allowed tool')
            validate_params(params, info.get('params', {}))
            if operation == 'jina-read':
                if 'url' not in params:
                    raise ResearchError('Jina public URL is required')
                public_url(params['url'], resolve=True)
            cost = info.get('cost', {})
            if 'credits_per_call' not in cost:
                raise ResearchError('AgentKey did not provide a per-call price')
            if re.search(r'metered|per.?token|per.?page|variable', json.dumps(cost), re.I):
                raise ResearchError('Variable billing needs a verified upper bound; adapter did not execute')
            amount, unit, path, method = str(money(cost['credits_per_call'])), 'credits', name, 'MCP'
            _, account = self.rpc('execute_tool', {'name': 'agentkey_account'})
            available = account_credits(account)
            if available < money(amount):
                raise ResearchError('AgentKey available credits could not be verified or are insufficient')
            meta = {'price_source': 'AgentKey describe_tool', 'descriptor': info, 'available_credits': str(available)}
        if money(amount) <= 0:
            raise ResearchError('This paid-data adapter requires a positive verified quote')
        payload = {'provider': provider, 'operation': operation, 'method': method, 'path': path, 'params': params}
        quote = {**payload, 'purpose': purpose, 'amount': amount, 'unit': unit, 'quoted_at': now(),
                 'fingerprint': digest(canonical(payload)), 'metadata': redact(meta, self.secrets)}
        quote['quote_digest'] = digest(canonical(quote))
        return quote

    def execute(self, quote):
        self.last_response = None
        self.verified_charge = None
        if quote['provider'] == 'agentkey':
            return self.rpc('execute_tool', {'name': quote['path'], 'params': quote['params']})
        return self.provider_http(quote['provider'], quote['path'], quote['params'], quote['method'])


def validate_quote(q):
    check = dict(q); recorded = check.pop('quote_digest', None)
    if digest(canonical(check)) != recorded:
        raise ResearchError('Quote was changed; re-quote the exact request')
    try:
        dt = datetime.fromisoformat(q['quoted_at'])
        if dt.tzinfo is None or datetime.now(timezone.utc) - dt > timedelta(hours=24) or dt > datetime.now(timezone.utc) + timedelta(minutes=5):
            raise ResearchError('Quote expired or has invalid time; refresh pricing')
        op = OPS[q['provider']][q['operation']]
    except (KeyError, ValueError, TypeError):
        raise ResearchError('Invalid quote contract')
    expected = op if q['provider'] == 'agentkey' else op[1]
    expected_method = 'MCP' if q['provider'] == 'agentkey' else ('GET' if q['provider'] == 'getxapi' else op[0])
    if q['path'] != expected or q['method'] != expected_method or q['unit'] != ('credits' if q['provider'] == 'agentkey' else 'USD'):
        raise ResearchError('Quote does not match an allowed read operation')
    validate_params(q['params'])
    payload = {k: q[k] for k in ['provider', 'operation', 'method', 'path', 'params']}
    if digest(canonical(payload)) != q['fingerprint'] or money(q['amount']) <= 0:
        raise ResearchError('Quote fingerprint or amount is invalid')


def run_quote(root, quote, client=None, refresh=False):
    validate_quote(quote)
    root = Path(root).resolve(); client = client or Client(); budget = Budget(root)
    reservation = budget.reserve(quote, refresh=refresh)
    attempt = reservation['attempt']
    if reservation['cached']:
        if attempt.get('status') == 'ok':
            try:
                raw = inside(root, attempt.get('raw_path') or '')
                if not raw.is_file() or not attempt.get('raw_sha256') or digest(raw.read_bytes()) != attempt['raw_sha256']:
                    raise ResearchError('Cached raw evidence is missing or changed')
            except (OSError, ResearchError):
                return {'cached': True, **attempt, 'status': 'cache_invalid',
                        'error': 'Cached raw evidence missing/changed; no new paid request sent. Restore it or explicitly refresh.'}
        return {'cached': True, **attempt}
    raw_path = 'raw/' + attempt['id'] + '.json'
    captured, state, error = None, 'ok', None
    try:
        code, data = client.execute(quote)
        captured = {'http_status': code, 'data': data}
        if getattr(client, 'last_response', None) is not None:
            captured['transport'] = client.last_response
        require_success(code, data)
    except (ResearchError, OSError, ValueError, TypeError, KeyError) as e:
        state, error = 'error', str(e) if isinstance(e, ResearchError) else type(e).__name__
        if getattr(client, 'last_response', None) is not None:
            captured = {'transport': client.last_response}
    saved_path, raw_hash = None, None
    if captured is not None:
        captured.update(captured_at=now(), provider=quote['provider'], request_fingerprint=quote['fingerprint'])
        try:
            target = inside(root, raw_path)
            write_json(target, redact(captured, client.secrets))
            saved_path, raw_hash = raw_path, digest(target.read_bytes())
        except (ResearchError, OSError, ValueError) as e:
            state, error = 'error', 'Complete raw capture failed (' + type(e).__name__ + ')'
    # Never recurse into source content looking for billing. Only a verified
    # transport-envelope adapter may set verified_charge; unknown stays reserved.
    actual = getattr(client, 'verified_charge', None) if quote['provider'] == 'agentkey' else None
    receipt = budget.settle(attempt, state, saved_path, error=error, actual=actual, raw_sha256=raw_hash)
    write_json(inside(root, 'receipts/' + attempt['id'] + '.json'), receipt)
    return {'cached': False, **receipt, 'budget': budget.status()}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    subs = p.add_subparsers(dest='cmd', required=True)
    b = subs.add_parser('budget'); b.add_argument('root')
    b.add_argument('--usd', default='0'); b.add_argument('--credits', default='0')
    b.add_argument('--max-calls', type=int, required=True); b.add_argument('--authorization', required=True)
    s = subs.add_parser('status'); s.add_argument('root')
    subs.add_parser('operations')
    d = subs.add_parser('discover'); d.add_argument('--prefix', required=True)
    q = subs.add_parser('quote'); q.add_argument('root')
    q.add_argument('--provider', required=True, choices=OPS); q.add_argument('--operation', required=True)
    q.add_argument('--params', required=True); q.add_argument('--purpose', required=True); q.add_argument('--name', required=True)
    r = subs.add_parser('run'); r.add_argument('root'); r.add_argument('--quote', required=True)
    r.add_argument('--refresh', action='store_true')
    a = p.parse_args()
    try:
        if a.cmd == 'budget': out = Budget(a.root).initialize(a.usd, a.credits, a.max_calls, a.authorization)
        elif a.cmd == 'status': out = Budget(a.root).status()
        elif a.cmd == 'operations': out = {k: list(v) for k, v in OPS.items()}
        elif a.cmd == 'discover':
            client = Client(); _, result = client.rpc('find_tools', {'prefix': a.prefix}); out = redact(result, client.secrets)
        elif a.cmd == 'quote':
            if not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', a.name): raise ResearchError('Use a simple unique quote name')
            root = Path(a.root).resolve(); target = inside(root, 'receipts/' + a.name + '.quote.json')
            if target.exists(): raise ResearchError('Quote name already exists; choose a new name')
            client = Client(); quote = client.quote(a.provider, a.operation, json.loads(a.params), a.purpose)
            write_json(target, quote)
            out = {'quote': str(target), 'provider': a.provider, 'operation': a.operation, 'amount': quote['amount'],
                   'unit': quote['unit'], 'params': quote['params'], 'paid_data_calls': 0}
        else:
            out = run_quote(a.root, read_json(inside(a.root, a.quote)), refresh=a.refresh)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        if a.cmd == 'run' and out.get('status') != 'ok': return 1
        return 0
    except (ResearchError, ValueError, OSError, KeyError, TypeError) as e:
        print(json.dumps({'ok': False, 'error': str(e) if isinstance(e, ResearchError) else type(e).__name__}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
