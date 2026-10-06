"""Pull (or update) someone's whole direct-ancestor tree from WikiTree:  python pull.py <WikiTree-ID> [authcode] [--kids]

Everything lands in lineage.db (store.py) as it arrives. Each run walks the tree (cheap), compares every profile's
WikiTree 'Touched' timestamp with the stored one, and fetches bios, categories and children only for profiles that are
new or edited since. --kids re-checks every ancestor's children (a child added elsewhere doesn't always touch the parent).
Then it exports tree.json and bios/<Id % 64>.json for the viewer. Places are geocoded by geocode.py.

Auth: browser visits api.wikitree.com/api.php?action=clientLogin&returnURL=http://localhost:8765/authed,
the redirect lands in the local server log with ?authcode=..; pass that code after the ID (single use).
The session cookies are kept in .wt_cookies so later runs need only the ID."""
import json, sys, time, os, urllib.request, urllib.parse, urllib.error, http.cookiejar
import store
sys.stdout.reconfigure(encoding='utf-8')
API, APP = 'https://api.wikitree.com/api.php', 'Lineage'
args = [a for a in sys.argv[1:] if not a.startswith('--')]
if not args: sys.exit('usage: python pull.py <WikiTree-ID> [authcode] [--kids]')
ROOT, ALL_KIDS = args[0], '--kids' in sys.argv
HERE = os.path.dirname(os.path.abspath(__file__))
jar = http.cookiejar.LWPCookieJar(os.path.join(HERE, '.wt_cookies'))
if os.path.exists(jar.filename): jar.load(ignore_discard=True)
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
UA = {'User-Agent': 'Lineage genealogy viewer'}
path = lambda f: os.path.join(HERE, f)
def save(f, obj): json.dump(obj, open(path(f), 'w', encoding='utf-8'), ensure_ascii=False)

def api(**p):
    p['appId'] = APP
    for tries in range(6):
        try:
            req = urllib.request.Request(API, data=urllib.parse.urlencode(p).encode(), headers=UA)
            out = json.load(op.open(req, timeout=120)); time.sleep(.4); return out
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
            if getattr(e, 'code', None) not in (None, 429, 500, 502, 503, 504): raise
            time.sleep(8 * (tries + 1))
    raise RuntimeError('API kept failing')

if len(args) > 1:
    r = api(action='clientLogin', authcode=args[1])
    print('login:', r.get('clientLogin', {}).get('result')); jar.save(ignore_discard=True)
store.migrate()

F = ('Id,Name,FirstName,MiddleName,RealName,Nicknames,LastNameAtBirth,LastNameCurrent,Suffix,Prefix,Gender,'
     'BirthDate,DeathDate,BirthLocation,DeathLocation,DataStatus,Father,Mother,Photo,PhotoData,IsLiving,Privacy,Touched')
def people(keys, fields=F, **extra):
    got, start = {}, 0
    while True:
        r = api(action='getPeople', keys=','.join(map(str, keys)), fields=fields, limit=1000, start=start, **extra)[0]
        ppl = r.get('people') or {}
        got.update({int(k): v for k, v in ppl.items() if int(k) > 0})
        if len(ppl) < 1000: return got
        start += 1000

# 1. walk the ancestors (getPeople ancestors=10, then onward from the frontier), saving each batch; note what changed
P, changed, todo = {}, set(), {ROOT}
while todo:
    batch = list(todo)[:50]; todo -= set(batch)
    for i, p in people(batch, ancestors=10).items():
        if i in P: continue
        P[i] = p
        old, touched = store.get('person', i)
        if old is None or (touched and touched != p.get('Touched')): changed.add(i)   # new, or edited since we stored it
        store.put('person', i, p, p.get('Touched'))
    store.commit()
    todo |= {pid for p in P.values() for pid in (p.get('Father'), p.get('Mother')) if pid and pid > 0 and pid not in P}
    print('people', len(P), 'frontier', len(todo))
root = next(p['Id'] for p in P.values() if p.get('Name') == ROOT)
anc, q = {root}, [root]
while q:
    p = P[q.pop()]
    for pid in (p.get('Father'), p.get('Mother')):
        if pid and pid > 0 and pid in P and pid not in anc: anc.add(pid); q.append(pid)
ids = sorted(anc)
print('direct ancestors', len(ids), 'new or edited', len(changed & anc))

def refresh(table, have, size, fetch):   # fetch only what's missing or changed, committing each batch
    todo = [i for i in ids if i in changed or i not in have]
    for n, s in enumerate(range(0, len(todo), size)):
        fetch(todo[s:s + size]); store.commit()
        if n % 20 == 0: print(table, min(s + size, len(todo)), '/', len(todo))

# 2. children (descendants=1 returns the kids, carrying Father/Mother ids)
KF = 'Id,Name,FirstName,RealName,LastNameAtBirth,BirthDate,DeathDate,Gender,Father,Mother'
def fetch_kids(batch):
    found = {i: {} for i in batch}
    for k, c in people(batch, fields=KF, descendants=1).items():
        for par in (c.get('Father'), c.get('Mother')):
            if par in found and k != par:
                found[par][k] = {'Id': k, 'Name': c.get('Name'), 'FirstName': c.get('FirstName') or c.get('RealName'), 'LastNameAtBirth': c.get('LastNameAtBirth'),
                                 'BirthDate': c.get('BirthDate'), 'DeathDate': c.get('DeathDate'), 'Gender': c.get('Gender')}
    for i, k in found.items(): store.put('kids', i, sorted(k.values(), key=lambda c: c.get('BirthDate') or '9999'))
refresh('kids', set() if ALL_KIDS else store.has('kids'), 50, fetch_kids)

# 3. bios (rendered HTML) + spouses
def fetch_bios(batch):
    r = api(action='getPeople', keys=','.join(map(str, batch)), fields='Id,Bio,Spouses', bioFormat='html')[0]
    for k, v in (r.get('people') or {}).items():
        sp = v.get('Spouses')
        if int(k) > 0: store.put('bio', int(k), {'bio': v.get('bioHTML') or v.get('Bio') or '', 'spouses': list(sp.values()) if isinstance(sp, dict) else []})
refresh('bios', store.has('bio'), 25, fetch_bios)

# 4. categories and templates (Notables, military service, Mayflower, Magna Carta...) for the viewer's highlights
def fetch_cats(batch):
    r = api(action='getPeople', keys=','.join(map(str, batch)), fields='Id,Categories,Templates')[0]
    for k, v in (r.get('people') or {}).items():
        if int(k) > 0: store.put('cats', int(k), {'c': v.get('Categories') or [], 't': [t.get('name') if isinstance(t, dict) else t for t in v.get('Templates') or []]})
refresh('categories', store.has('cats'), 100, fetch_cats)

# 5. export for the viewer: tree.json (everything up front, no bios) + bios sharded by Id % 64 (~1MB per open)
kids, bios, cats = store.everything('kids'), store.everything('bio'), store.everything('cats')
out = {}
for i in ids:
    p = {k: v for k, v in P[i].items() if k not in ('PhotoData', 'Privacy') and not k.startswith('Privacy_')}
    pd, ph = P[i].get('PhotoData'), P[i].get('Photo')
    p['photo'] = f"https://www.wikitree.com{pd['dir']}/{ph}/300px-{ph}" if pd and ph and pd.get('dir') else None
    p['Kids'] = kids.get(i, [])
    sp = bios.get(i, {}).get('spouses', [])
    p['Marriages'] = [{'date': s.get('marriage_date'), 'place': s.get('marriage_location'), 'Id': s.get('Id')} for s in sp]
    p['hasBio'] = bool(bios.get(i, {}).get('bio'))
    p['Cats'], p['Tpl'] = cats.get(i, {}).get('c', []), cats.get(i, {}).get('t', [])
    out[i] = p
save('tree.json', {'root': root, 'people': out})
store.export_bios(ids)
print('wrote tree.json', len(out))
