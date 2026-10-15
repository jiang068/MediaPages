"""Stable media page URLs, independent of the playback transport URL."""
import json
import re
from pathlib import Path
from urllib.parse import quote, urlsplit

ROUTE_PREFIX = '/watch'
REWRITE = '/watch/* / 200'


def assign_media_paths(nodes):
    used = set()

    def visit(items, parents):
        for item in items:
            name = str(item.get('name') or '媒体')
            if item.get('type') == 'folder':
                visit(item.get('children') or [], parents + [name])
            elif item.get('type') in ('video', 'audio', 'image'):
                segments = parents + [name]
                encoded = [quote('_' + s if s in ('.', '..') else s, safe='') for s in segments]
                base = ROUTE_PREFIX + '/' + '/'.join(encoded)
                path, suffix = base, 2
                while path in used:
                    path = base + '~' + str(suffix)
                    suffix += 1
                used.add(path)
                item['path'] = path
    visit(nodes, [])
    return nodes


def configure_media_paths(dist_dir, redirects_source=None, range_prefix=None):
    dist = Path(dist_dir)
    index = dist / 'index.json'
    if index.is_file():
        nodes = assign_media_paths(json.loads(index.read_text(encoding='utf-8')))
        index.write_text(json.dumps(nodes, ensure_ascii=False, indent=2), encoding='utf-8')
        routes = {}
        def visit(items):
            for item in items:
                if item.get('type') == 'folder':
                    visit(item.get('children') or [])
                elif item.get('path') and item.get('src'):
                    route = {'src': item['src'], 'type': item.get('type')}
                    source = urlsplit(item['src'])
                    if range_prefix and not source.scheme and source.path.startswith(range_prefix + '/'):
                        stream_id = source.path[len(range_prefix) + 1:]
                        if stream_id and '/' not in stream_id:
                            route['streamId'] = stream_id
                    routes[item['path']] = route
        visit(nodes)
        catalog = dist / 'player/media-routes.json'
        catalog.parent.mkdir(parents=True, exist_ok=True)
        catalog.write_text(json.dumps({'version': 1, 'routes': routes}, ensure_ascii=False, indent=2), encoding='utf-8')

    entry = dist / 'index.html'
    if entry.is_file():
        html = entry.read_text(encoding='utf-8')
        # All theme scripts and media sidecars are relative to the site root,
        # even when the entry page is served at a deeply nested watch URL.
        if re.search(r'<base\b[^>]*>', html, flags=re.I):
            html = re.sub(r'<base\b[^>]*>', '<base href="/">', html, count=1, flags=re.I)
        else:
            html = re.sub(r'(<head\b[^>]*>)', r'\1\n    <base href="/">', html, count=1, flags=re.I)
        entry.write_text(html, encoding='utf-8')

    redirects = Path(redirects_source) if redirects_source is not None else dist / '_redirects'
    original = redirects.read_text(encoding='utf-8') if redirects.is_file() else ''
    # /watch is now handled by a Function, which negotiates HTML versus media.
    lines = [line for line in original.splitlines() if line.strip() not in (REWRITE, '/watch/* /index.html 200')]
    (dist / '_redirects').write_text('\n'.join(lines).strip() + '\n', encoding='utf-8')
    route_file = dist / '_routes.json'
    rules = json.loads(route_file.read_text(encoding='utf-8')) if route_file.is_file() else {'version': 1, 'include': [], 'exclude': []}
    rules['include'] = list(dict.fromkeys(rules.get('include', []) + ['/watch/*']))
    rules.setdefault('exclude', [])
    route_file.write_text(json.dumps(rules, indent=2), encoding='utf-8')
