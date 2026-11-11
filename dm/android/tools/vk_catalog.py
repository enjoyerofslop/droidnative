#!/usr/bin/env python3
# The Vulkan driver catalog's upkeep (dm/android/vk_drivers.json, read by dm/android/desktop/vk_drivers.py).
#   python3 dm/android/tools/vk_catalog.py check
#       each entry's zip against what its GitHub release lists now: the asset there, its size, and the SHA-256 digest GitHub keeps for it. Nothing is downloaded.
#       Exit 1 when an asset changed or went: an owner can delete an asset and upload another under its name, which the app's hash check then refuses.
#       Uses GITHUB_TOKEN when set (the API allows 60 requests an hour without one). .github/workflows/vk-catalog.yml runs it weekly.
#   python3 dm/android/tools/vk_catalog.py entry <package> <release asset URL> <release page URL>
#       a new entry's checked fields from a package downloaded by hand (vk_driver_pkg checks it), as JSON to paste and complete: its id, name, gpus, tested,
#       mesh_shaders, licence and notes are the maintainer's to write.
import hashlib, json, os, re, sys, urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
CATALOG = REPO / 'dm/android/vk_drivers.json'
ASSET = re.compile(r'https://github\.com/([^/]+)/([^/]+)/releases/download/([^/]+)/([^/]+)$')


def api(url):
    h = {'User-Agent': 'DroidPlay', 'Accept': 'application/vnd.github+json'}
    if os.environ.get('GITHUB_TOKEN'): h['Authorization'] = f'Bearer {os.environ["GITHUB_TOKEN"]}'
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=20) as r: return json.load(r)


def check(entries, get=api):
    """→ the problems, one line each (empty: every entry matches its release)"""
    out = []
    for e in entries:
        m = ASSET.match(e['url'])
        if not m: out.append(f'{e["id"]}: {e["url"]} is not a GitHub release asset'); continue
        owner, repo, tag, name = m.groups()
        try: rel = get(f'https://api.github.com/repos/{owner}/{repo}/releases/tags/{tag}')
        except Exception as x: out.append(f'{e["id"]}: the release {owner}/{repo} {tag} could not be read ({x})'); continue
        a = next((a for a in rel.get('assets') or [] if a.get('name') == urllib.request.url2pathname(name)), None)
        if not a: out.append(f'{e["id"]}: {name} is no longer in {owner}/{repo} {tag}'); continue
        if a.get('digest') != f'sha256:{e["zip_sha256"]}': out.append(f'{e["id"]}: {name} has changed: GitHub lists {a.get("digest") or "no digest"}, the catalog sha256:{e["zip_sha256"]}')
        elif a.get('size') != e['size']: out.append(f'{e["id"]}: {name} is {a.get("size")} bytes, the catalog says {e["size"]}')
    return out


def entry(package, url, page):
    sys.path.insert(0, str(REPO / 'dm/android/tools')); import vk_driver_pkg as vkpkg   # pyright: ignore[reportMissingImports]
    d = vkpkg.read(package); raw = Path(package).read_bytes(); m = d.meta or {}
    return {'id': '', 'name': m.get('name', ''), 'builder': m.get('author', ''), 'page': page, 'url': url, 'zip_sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw),
            'library': d.library, 'library_sha256': d.sha256, 'library_size': len(d.data), 'meta': {k: v for k, v in m.items() if k != 'description'}, 'min_api': d.min_api,
            'mesa': '', 'gpus': [], 'tested': [], 'mesh_shaders': None, 'env': [], 'licence': '', 'notes': ''}


if __name__ == '__main__':
    a = sys.argv[1:]
    if a == ['check']:
        entries = json.loads(CATALOG.read_text(encoding='utf-8'))['drivers']
        bad = check(entries)
        for line in bad: print(line)
        print(f'{len(entries) - len({b.split(":")[0] for b in bad})} of {len(entries)} entries match their releases')
        sys.exit(1 if bad else 0)
    if len(a) == 4 and a[0] == 'entry': print(json.dumps(entry(*a[1:]), indent=1)); sys.exit(0)
    sys.exit('vk_catalog.py check | entry <package> <release asset URL> <release page URL>')
