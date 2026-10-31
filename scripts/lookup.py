#!/usr/bin/env python3
"""Read complete dated Wiki snapshots; no network and no summarisation."""
import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--query')
    group.add_argument('--read')
    parser.add_argument('--limit', type=int, default=8)
    args = parser.parse_args()
    data = json.loads((Path(__file__).resolve().parent.parent / 'references/wiki-snapshots.json').read_text())
    pages = data['pages']
    if args.read:
        page = next((p for p in pages if p['requested_slug'] == args.read), None)
        if page is None:
            parser.exit(1, 'Not in the selected snapshot. Retrieve this page from Wiki; do not infer its method from the title.\n')
        print('Dated snapshot:', page['retrieved_at'], '|', page['requested_slug'])
        print(page['content'])
        return
    if args.limit < 1:
        parser.error('--limit must be positive')
    terms = args.query.casefold().split()
    scored = []
    for p in pages:
        haystack = (p['requested_slug'] + ' ' + p['title'] + ' ' + p['content']).casefold()
        score = sum(haystack.count(t) for t in terms)
        if score:
            scored.append((score, p))
    scored.sort(key=lambda pair: (-pair[0], pair[1]['requested_slug']))
    print(json.dumps({'snapshot_date': data['snapshot_date'], 'matches': [
        {'slug': p['requested_slug'], 'heading': p['content'].splitlines()[0], 'chars': len(p['content'])}
        for _, p in scored[:args.limit]]}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
