"""Durable local store (SQLite, lineage.db): every fetched profile, bio, category set, child list and geocode is saved
as it arrives, so nothing is ever fetched twice unless WikiTree says it changed."""
import json, os, sqlite3
HERE = os.path.dirname(os.path.abspath(__file__))
db = sqlite3.connect(os.path.join(HERE, 'lineage.db'), timeout=60)   # pull and geocode may write at once
db.execute('pragma journal_mode=wal')
for t in ('person', 'bio', 'cats', 'kids', 'tr'):
    db.execute(f'create table if not exists {t} (id integer primary key, data text, touched text, fetched text)')
db.execute('create table if not exists place (loc text primary key, data text, fetched text)')

def get(t, i):
    row = db.execute(f'select data, touched from {t} where id = ?', (i,)).fetchone()
    return (json.loads(row[0]), row[1]) if row else (None, None)
def put(t, i, data, touched=None):   # caller commits (once per API batch)
    db.execute(f"insert or replace into {t} values (?, ?, ?, datetime('now'))", (i, json.dumps(data, ensure_ascii=False), touched))
def has(t): return {i for (i,) in db.execute(f'select id from {t}')}
def touched(t): return dict(db.execute(f'select id, touched from {t}'))
def everything(t): return {i: json.loads(d) for i, d in db.execute(f'select id, data from {t}')}
def place(loc):
    row = db.execute('select data from place where loc = ?', (loc,)).fetchone()
    return json.loads(row[0]) if row else None
def put_place(loc, data):
    db.execute("insert or replace into place values (?, ?, datetime('now'))", (loc, json.dumps(data, ensure_ascii=False))); db.commit()
def places(): return {l: json.loads(d) for l, d in db.execute('select loc, data from place')}
def commit(): db.commit()

def migrate():   # one-time import of the older JSON checkpoints
    def load(f):
        p = os.path.join(HERE, f)
        return json.load(open(p, encoding='utf-8')) if os.path.exists(p) else {}
    if not has('person'):
        for i, p in load('raw.json').items(): put('person', int(i), p, None)
        for i, k in load('kids.json').items(): put('kids', int(i), k)
        for i, b in load('bios.json').items(): put('bio', int(i), b)
        for i, c in load('cats.json').items(): put('cats', int(i), c)
        commit()
    if not db.execute('select 1 from place limit 1').fetchone():
        for l, v in load('places.json').items(): db.execute("insert or replace into place values (?, ?, datetime('now'))", (l, json.dumps(v)))
        commit()

def export_bios(ids=None):   # bios/<Id % 64>.json for the viewer: the bio, plus its English translation when there is one
    bios, tr = everything('bio'), everything('tr')
    ids = ids or list(bios)
    os.makedirs(os.path.join(HERE, 'bios'), exist_ok=True)
    for s in range(64):
        out = {}
        for i in ids:
            b = bios.get(i, {}).get('bio')
            if i % 64 != s or not b: continue
            t = tr.get(i)
            out[i] = {'o': b, 'en': t['html'], 'lang': t['lang']} if t else b
        json.dump(out, open(os.path.join(HERE, 'bios', f'{s}.json'), 'w', encoding='utf-8'), ensure_ascii=False)
