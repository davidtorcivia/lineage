"""Pull someone's whole direct-ancestor tree from WikiTree:  python pull.py <WikiTree-ID> [authcode]

Writes (each step is checkpointed, delete a file to redo that step):
  raw.json    every direct ancestor (structure + vitals)
  kids.json   children of every ancestor
  bios.json   rendered bio HTML + spouses, loaded lazily by the viewer
  tree.json   what the viewer loads up front
Places are geocoded separately by geocode.py.

Auth: browser visits api.wikitree.com/api.php?action=clientLogin&returnURL=http://localhost:8765/authed,
the redirect lands in the local server log with ?authcode=..; pass that code after the ID (single use).
The session cookies are kept in .wt_cookies so re-runs don't need a new code."""
import json, sys, time, os, urllib.request, urllib.parse, urllib.error, http.cookiejar
sys.stdout.reconfigure(encoding='utf-8')
API, APP = 'https://api.wikitree.com/api.php', 'Lineage'
if len(sys.argv) < 2: sys.exit('usage: python pull.py <WikiTree-ID> [authcode]')
ROOT = sys.argv[1]
HERE = os.path.dirname(os.path.abspath(__file__))
jar = http.cookiejar.LWPCookieJar(os.path.join(HERE, '.wt_cookies'))
if os.path.exists(jar.filename): jar.load(ignore_discard=True)
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
UA = {'User-Agent': 'Lineage genealogy viewer'}
path = lambda f: os.path.join(HERE, f)
def save(f, obj): json.dump(obj, open(path(f), 'w', encoding='utf-8'), ensure_ascii=False)
def load(f): return json.load(open(path(f), encoding='utf-8')) if os.path.exists(path(f)) else None

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

if len(sys.argv) > 2:
    r = api(action='clientLogin', authcode=sys.argv[2])
    print('login:', r.get('clientLogin', {}).get('result')); jar.save(ignore_discard=True)

F = ('Id,Name,FirstName,MiddleName,RealName,Nicknames,LastNameAtBirth,LastNameCurrent,Suffix,Prefix,Gender,'
     'BirthDate,DeathDate,BirthLocation,DeathLocation,DataStatus,Father,Mother,Photo,PhotoData,IsLiving,Privacy')
def people(keys, fields=F, **extra):
    got, start = {}, 0
    while True:
        r = api(action='getPeople', keys=','.join(map(str, keys)), fields=fields, limit=1000, start=start, **extra)[0]
        ppl = r.get('people') or {}
        got.update({int(k): v for k, v in ppl.items() if int(k) > 0})
        if len(ppl) < 1000: return got
        start += 1000

# 1. ancestors: getPeople ancestors=10, then keep going from the frontier
P = {int(k): v for k, v in (load('raw.json') or {}).items()}
if not P:
    todo = {ROOT}
    while todo:
        batch = list(todo)[:50]; todo -= set(batch)
        P.update(people(batch, ancestors=10))
        todo |= {pid for p in P.values() for pid in (p.get('Father'), p.get('Mother')) if pid and pid > 0 and pid not in P}
        print('people', len(P), 'frontier', len(todo))
    save('raw.json', P)
root = next(p['Id'] for p in P.values() if p.get('Name') == ROOT)
anc, q = {root}, [root]
while q:
    p = P[q.pop()]
    for pid in (p.get('Father'), p.get('Mother')):
        if pid and pid > 0 and pid in P and pid not in anc: anc.add(pid); q.append(pid)
ids = sorted(anc)
print('direct ancestors', len(ids))

# 2. children of every ancestor (descendants=1 returns the kids, carrying Father/Mother ids)
kids = {int(k): v for k, v in (load('kids.json') or {}).items()}
if not kids:
    KF = 'Id,Name,FirstName,RealName,LastNameAtBirth,BirthDate,DeathDate,Gender,Father,Mother'
    for i in range(0, len(ids), 50):
        for k, c in people(ids[i:i + 50], fields=KF, descendants=1).items():
            for par in (c.get('Father'), c.get('Mother')):
                if par in anc and k != par:
                    kids.setdefault(par, []).append({'Id': k, 'Name': c.get('Name'), 'FirstName': c.get('FirstName') or c.get('RealName'),
                        'LastNameAtBirth': c.get('LastNameAtBirth'), 'BirthDate': c.get('BirthDate'), 'DeathDate': c.get('DeathDate'), 'Gender': c.get('Gender')})
        if i % 1000 == 0: print('children', i, '/', len(ids))
    kids = {k: sorted({c['Id']: c for c in v}.values(), key=lambda c: c.get('BirthDate') or '9999') for k, v in kids.items()}
    save('kids.json', kids)

# 3. bios (rendered HTML) + spouses, checkpointed as we go
bios = {int(k): v for k, v in (load('bios.json') or {}).items()}
todo = [i for i in ids if i not in bios]
for n, i in enumerate(range(0, len(todo), 25)):
    r = api(action='getPeople', keys=','.join(map(str, todo[i:i + 25])), fields='Id,Bio,Spouses', bioFormat='html')[0]
    for k, v in (r.get('people') or {}).items():
        sp = v.get('Spouses')
        bios[int(k)] = {'bio': v.get('bioHTML') or v.get('Bio') or '', 'spouses': list(sp.values()) if isinstance(sp, dict) else []}
    if n % 40 == 0: print('bios', len(bios), '/', len(ids)); save('bios.json', bios)
save('bios.json', bios)

# 3b. categories and templates (Notables, military service, Mayflower, Magna Carta...) for the viewer's highlights
cats = {int(k): v for k, v in (load('cats.json') or {}).items()}
todo = [i for i in ids if i not in cats]
for n, i in enumerate(range(0, len(todo), 100)):
    r = api(action='getPeople', keys=','.join(map(str, todo[i:i + 100])), fields='Id,Categories,Templates')[0]
    for k, v in (r.get('people') or {}).items():
        if int(k) > 0: cats[int(k)] = {'c': v.get('Categories') or [], 't': [t.get('name') if isinstance(t, dict) else t for t in v.get('Templates') or []]}
    if n % 20 == 0: print('categories', len(cats), '/', len(ids)); save('cats.json', cats)
save('cats.json', cats)

# 4. tree.json: everything the viewer needs up front (no bios)
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
print('wrote tree.json', len(out))

# 5. shard bios so opening a person loads ~1MB, not the whole file
os.makedirs(path('bios'), exist_ok=True)
for s in range(64):
    save(f'bios/{s}.json', {i: b['bio'] for i, b in bios.items() if i % 64 == s and b.get('bio')})
print('sharded bios')
