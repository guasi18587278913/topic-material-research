#!/usr/bin/env python3
"""Check evidence links, exact excerpts and readiness; editorial judgment is separate."""
import argparse
import hashlib
import json
import re
from pathlib import Path
from _common import ResearchError, inside, read_json, write_json

ACCESS = {'full_text', 'transcript', 'direct_record', 'search_snippet', 'metadata'}
STATUS = {'verified', 'attributed', 'unverified', 'inference', 'contradicted'}


def strings(value):
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [s for v in value for s in strings(v)]
    if isinstance(value, dict):
        return [s for v in value.values() for s in strings(v)]
    return []


def normalize(text):
    return re.sub(r'\s+', ' ', text).strip()


def check(root):
    root = Path(root).resolve()
    data = read_json(root / 'bundle.json')
    errors, warnings = [], []
    if data.get('schema_version') != 1 or not data.get('topic'):
        errors.append('schema_version=1 and topic are required')
    indexes = {}
    for kind in ['sources', 'materials', 'angles']:
        rows = data.get(kind, [])
        if not isinstance(rows, list):
            errors.append(kind + ' must be an array'); rows = []
        index = {}
        for row in rows:
            rid = row.get('id') if isinstance(row, dict) else None
            if not rid or rid in index:
                errors.append('Missing or duplicate ' + kind + ' id')
            else:
                index[rid] = row
        indexes[kind] = index
    source_text = {}
    for sid, s in indexes['sources'].items():
        if s.get('access') not in ACCESS or not s.get('origin_group') or not s.get('url'):
            errors.append(sid + ': access, origin_group and url are required')
        try:
            path = inside(root, s.get('raw_path', ''))
            body = path.read_bytes()
            if hashlib.sha256(body).hexdigest() != s.get('sha256'):
                errors.append(sid + ': source hash mismatch')
            try:
                texts = strings(json.loads(body))
            except ValueError:
                texts = [body.decode('utf-8', 'replace')]
            source_text[sid] = [normalize(t) for t in texts]
        except (ResearchError, OSError):
            errors.append(sid + ': raw file missing or escapes task')
    for mid, m in indexes['materials'].items():
        sid = m.get('source_id')
        if sid not in indexes['sources']:
            errors.append(mid + ': unknown source_id')
        if m.get('status') not in STATUS:
            errors.append(mid + ': invalid status')
        if m.get('claim_scope', 'event') not in {'event', 'source_record'}:
            errors.append(mid + ': invalid claim_scope')
        if not all(m.get(k) for k in ['locator', 'detail', 'supports', 'limits']):
            errors.append(mid + ': locator, detail, supports and limits are required')
        quote = normalize(m.get('excerpt', ''))
        if quote and not any(quote in t for t in source_text.get(sid, [])):
            errors.append(mid + ': excerpt is not present in source text')
        if not quote:
            warnings.append(mid + ': no literal excerpt; review locator and paraphrase (quoting is optional)')
    for aid, a in indexes['angles'].items():
        if a.get('readiness') not in {'explore', 'draftable', 'blocked'} or not a.get('question'):
            errors.append(aid + ': readiness and question are required')
        basis = a.get('basis_material_ids', [])
        if any(mid not in indexes['materials'] for mid in basis):
            errors.append(aid + ': unknown basis material')
        if a.get('readiness') == 'draftable':
            if not basis or a.get('missing'):
                errors.append(aid + ': draftable requires basis and no missing core evidence')
            for mid in basis:
                m = indexes['materials'].get(mid, {})
                s = indexes['sources'].get(m.get('source_id'), {})
                access_ok = s.get('access') in {'full_text', 'transcript', 'direct_record'}
                # Metadata can directly evidence an observation about that record
                # (e.g. its displayed author/date), not the underlying event.
                if (s.get('access') == 'metadata' and m.get('claim_scope') == 'source_record'
                        and m.get('status') == 'verified'):
                    access_ok = True
                if m.get('status') not in {'verified', 'attributed'} or not access_ok:
                    errors.append(aid + ': weak or unverified central evidence ' + str(mid))
    for m in data.get('methods', []):
        if m.get('decision') not in {'used', 'needs_material', 'not_applicable'} or not m.get('slug') or not m.get('action'):
            errors.append('Method requires slug, decision and concrete action')
        if any(mid not in indexes['materials'] for mid in m.get('material_ids', [])):
            errors.append('Method references unknown material')
    groups = {}
    for sid, s in indexes['sources'].items():
        groups.setdefault(s.get('origin_group'), []).append(sid)
    for group, ids in groups.items():
        if len(ids) > 1:
            warnings.append('Same original source group ' + str(group) + ': ' + ', '.join(ids))
    return {'ok': not errors, 'sources': len(indexes['sources']), 'materials': len(indexes['materials']),
            'angles': len(indexes['angles']), 'errors': errors, 'warnings': warnings,
            'limit': 'Structural evidence checks only; methods and creative usefulness require review.'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    subs = p.add_subparsers(dest='cmd', required=True)
    init = subs.add_parser('init'); init.add_argument('root'); init.add_argument('--topic', required=True)
    add = subs.add_parser('add-source'); add.add_argument('root')
    for arg in ['id', 'url', 'origin-group', 'access', 'raw-path']:
        add.add_argument('--' + arg, required=True)
    chk = subs.add_parser('check'); chk.add_argument('root')
    a = p.parse_args()
    try:
        root = Path(a.root).resolve(); path = root / 'bundle.json'
        if a.cmd == 'init':
            if path.exists(): raise ResearchError('Bundle already exists')
            write_json(path, {'schema_version': 1, 'topic': a.topic, 'sources': [], 'materials': [], 'angles': [], 'methods': [], 'gaps': []})
            print(json.dumps({'ok': True, 'bundle': str(path)}))
        elif a.cmd == 'add-source':
            data = read_json(path)
            if a.access not in ACCESS or any(s['id'] == a.id for s in data['sources']):
                raise ResearchError('Invalid access or duplicate source id')
            raw = inside(root, a.raw_path)
            data['sources'].append({'id': a.id, 'url': a.url, 'origin_group': a.origin_group, 'access': a.access,
                                    'raw_path': a.raw_path, 'sha256': hashlib.sha256(raw.read_bytes()).hexdigest()})
            write_json(path, data); print(json.dumps({'ok': True, 'source_id': a.id}))
        else:
            result = check(root); print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result['ok'] else 1
    except (ResearchError, OSError, KeyError, TypeError) as e:
        print(json.dumps({'ok': False, 'error': str(e) if isinstance(e, ResearchError) else type(e).__name__}))
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
