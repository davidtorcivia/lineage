"""Geocode the places in tree.json into places.json, verified against the rest of each place name.

For "Eastham, Barnstable, Plymouth Colony" we look up "Eastham" (Open-Meteo's GeoNames search: fast, no 1/s limit) and
keep only a candidate whose county/state/country agree with the other parts ("Barnstable" -> Barnstable County,
"Plymouth Colony" -> Massachusetts). If the most specific part can't be verified we try the next part ("Hull with
Appleton, Cheshire" -> "Cheshire"), recording how far we had to fall back. A candidate is never accepted on a bare
name match when the rest of the name disagrees, and the country must be one the name implies.
Entries: [lon, lat, cut, country_code, matched_parts]; [] = verified miss. Every result is saved to lineage.db the moment it's
found (store.py), and places.json is exported for the viewer as it goes; older unverified entries are redone."""
import json, os, re, sys, time, unicodedata, urllib.request, urllib.parse
import store
from collections import Counter
sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
PF = os.path.join(HERE, 'places.json')
export = lambda: json.dump(store.places(), open(PF, 'w', encoding='utf-8'), ensure_ascii=False)
UA = {'User-Agent': 'Lineage genealogy viewer'}

CC = [  # keyword in a part of the name -> plausible modern country codes
    (r'qu[ée]bec|nouvelle-france|new france|bas-canada|lower canada|canada|acadi|nova scotia|new brunswick|ontario', 'ca'),
    (r'france|francia|francie|royaume des francs|lorraine|alsace|normandie|normandy|bretagne|brittany|perche|aquitaine|gascogne|gascony|provence|toulouse|bourgogne|burgundy|savoie|anjou|poitou|champagne|limoges|picardie|isle-de-france|[iî]le-de-france|armorica|neustria', 'fr'),
    (r'gen[èe]ve', 'ch,fr'),
    (r'(?<!new )england|angleterre|britain|britannia|brittania|wessex|mercia|northumbria|east anglia|united kingdom', 'gb'),
    (r'wales|cymru|powys|gwynedd|dyfed|deheubarth|gwent|anglesey|scotland|alba\b|strathclyde|cornwall|dumnonia|orkney', 'gb'),
    (r'ireland|[ée]ire', 'ie,gb'), (r'isle of man', 'im'), (r'jersey', 'je'), (r'guernsey', 'gg'),
    (r'german|deutsch|alemanha|preu(ss|ß)en|prussia|bayern|bavaria|rhein|westfal|hessen|baden|w[üu]rtt|sachsen|saxony|hannover|hanover|pfalz|palatinate|th[üu]ring|swabia|schwaben|nordgau|frisia|austrasi|fr[äa]nkisch', 'de,nl,fr,pl'),
    (r'posen|pomm?er|silesia|schlesien', 'pl,de'),
    (r'holy roman|heilig|saint-empire|sacro romano|lotharingia', 'de,nl,be,lu,ch,at,cz,it,fr'),
    (r'netherlands|nederland|holland', 'nl'), (r'belgi|flanders|flandre|vlaanderen|brabant|hainaut', 'be,fr,nl'),
    (r'luxemb', 'lu'), (r'switzerland|schweiz|suisse', 'ch'), (r'austria|[öo]sterreich|carinthia', 'at'),
    (r'ital|sicil|sardegna|sardinia|napoli|toscan|lombard|venezia|saluzzo|regno d', 'it'),
    (r'spain|españa|espana|castil|le[óo]n|arag[oó]n|navarr|pamplona|asturias|galicia|barcelona|catalu|ribagorza|besal|urgell|hispania', 'es'),
    (r'portugal', 'pt'), (r'greece', 'gr'), (r'byzant|constantinople|turkey|anatolia', 'tr,gr'), (r'armenia', 'am,tr'),
    (r'jerusalem|acre\b|akko', 'il,ps,lb,sy,jo'), (r'syria|antioch', 'sy,tr'), (r'egypt', 'eg'), (r'cyprus', 'cy'), (r'albania|durazzo', 'al'),
    (r'norway|norge|vestfold|hedmark|telemark|agder|akershus|oppland|tr[øo]ndelag|m[øo]re|sogn|[øo]stlandet', 'no'),
    (r'denmark|danmark|jutland|hleithra', 'dk'), (r'haithabu', 'de'), (r'sweden|sverige|uppsala', 'se'), (r'iceland', 'is'),
    (r'scandi', 'no,se,dk'),
    (r'poland|polska|wielkopolska', 'pl'), (r'kiev|kyiv|ukrain', 'ua'), (r'russia|novgorod|\brus\b|rus\'|yakutia', 'ru,ua,by'), (r'polotsk', 'by'),
    (r'hungar|magyar|pannonia', 'hu'), (r'bohemia|[čc]echy|morav', 'cz'), (r'croatia', 'hr'), (r'serbia', 'rs'), (r'bulgaria', 'bg'), (r'lithuania', 'lt'),
    (r'\b(usa|united states|america|colony|new england|plymouth|new york|pennsylvania|massachusetts|connecticut|new jersey|rhode island|vermont|new hampshire|maine|ohio|michigan|illinois|wisconsin|minnesota|maryland|virginia|delaware|florida|california|kentucky|indiana|iowa|missouri|carolina|georgia)\b', 'us'),
]
ALIAS = {   # historical or local names -> the modern admin names GeoNames uses
    'plymouth colony': 'massachusetts', 'massachusetts bay colony': 'massachusetts', 'province of massachusetts bay': 'massachusetts',
    'connecticut colony': 'connecticut', 'new haven colony': 'connecticut', 'province of new hampshire': 'new hampshire',
    'province of new york': 'new york', 'new netherland': 'new york|new jersey', 'new england': 'massachusetts|connecticut|rhode island|new hampshire|vermont|maine',
    'nouvelle-france': 'quebec', 'new france': 'quebec', 'bas-canada': 'quebec', 'lower canada': 'quebec', 'province of quebec': 'quebec',
    'province de quebec': 'quebec', 'canada': 'quebec|ontario|new brunswick|nova scotia', 'acadie': 'nova scotia|new brunswick',
    'posen': 'greater poland|kujawsko|kuyavian|wielkopolskie', 'prussia': 'poland|germany|brandenburg|north rhine|westphalia|greater poland|kuyavian|pomeranian|warmian|saxony|lower saxony|hesse|rhineland',
    'rhineland': 'north rhine|rhineland', 'rheinprovinz': 'north rhine|rhineland', 'westfalen': 'north rhine', 'westphalia': 'north rhine',
    'bayern': 'bavaria', 'sicilia': 'sicily', 'sachsen': 'saxony', 'hessen': 'hesse', 'preussen': 'poland|germany', 'deutschland': 'germany',
    'italia': 'italy', 'espana': 'spain', 'norge': 'norway', 'danmark': 'denmark', 'sverige': 'sweden', 'cymru': 'wales', 'eire': 'ireland',
    'bretagne': 'brittany', 'normandie': 'normandy', 'isle-de-france': 'ile-de-france', 'royaume de france': 'france', 'german empire': 'germany',
    'holy roman empire': 'germany|netherlands|belgium|austria|czechia|switzerland|luxembourg|france|italy',
}
BROAD = {'prussia', 'preussen', 'german empire', 'holy roman empire', 'new england', 'canada', 'deutschland', 'germany', 'france', 'england', 'italy', 'italia', 'spain', 'espana', 'united states', 'usa'}   # agreeing with these is weak evidence
POLITY = re.compile(r'kingdom|royaume|reino|regno|empire|reich|imperium|imperio|duchy|duché|ducado|county of|comté|condado|comtat|principality|jarldom|central asia|^europe$|colony$', re.I)

def norm(s):
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode().lower()
    s = re.sub(r'\(.*?\)', ' ', s)
    s = re.sub(r'\b(county|province|provincia|provinz|departement|department|region|regione|shire|of|the|de|du|la|le|di|von|im|in|landkreis|kreis|arrondissement|city|town|parish|township|borough|district)\b', ' ', s)
    return re.sub(r'[^a-z ]', ' ', s).split()
def key(s): return ' '.join(norm(s))
ALIAS = {key(k): v for k, v in ALIAS.items()}   # look up aliases by the same normalised key
def agree(part, cand):   # does one part of the place name agree with this candidate's admin areas?
    fields = [key(cand.get(f) or '') for f in ('admin1', 'admin2', 'admin3', 'admin4', 'country')]
    fields = [f for f in fields if f]
    k = key(part)
    if not k: return False
    targets = [k] + (ALIAS.get(k, '') or ALIAS.get(part.strip().lower(), '')).split('|')
    for t in filter(None, targets):
        for f in fields:
            if t in f or f in t or (len(t) >= 5 and len(f) >= 5 and t[:5] == f[:5]): return True
    return False
def expect(loc):
    codes = set()
    for part in loc.split(','):
        for rx, cc in CC:
            if re.search(rx, part.strip(), re.I): codes.update(cc.split(','))
    return codes

cache = {}
def search(name, codes):
    k = (name, tuple(sorted(codes)))
    if k in cache: return cache[k]
    p = {'name': name, 'count': 30, 'language': 'en', 'format': 'json'}
    if len(codes) == 1: p['countryCode'] = next(iter(codes)).upper()
    for tries in range(5):
        try:
            res = json.load(urllib.request.urlopen(urllib.request.Request('https://geocoding-api.open-meteo.com/v1/search?' + urllib.parse.urlencode(p), headers=UA), timeout=30)).get('results') or []
            break
        except urllib.error.HTTPError as e:
            if e.code == 429: time.sleep(30 * (tries + 1)); continue
            res = []; break
        except Exception:
            time.sleep(3); res = []
    time.sleep(.12)
    cache[k] = [r for r in res if 'longitude' in r and 'latitude' in r and (not codes or r.get('country_code', '').lower() in codes)]
    return cache[k]

def region(name, codes):   # Nominatim knows states and countries; one polite request per such name
    p = {'q': name, 'format': 'json', 'limit': 5, 'countrycodes': ','.join(sorted(codes))}
    try: res = json.load(urllib.request.urlopen(urllib.request.Request('https://nominatim.openstreetmap.org/search?' + urllib.parse.urlencode(p), headers=UA), timeout=60))
    except Exception: res = []
    time.sleep(1.1)
    for r in res:
        if r.get('addresstype') in ('state', 'country', 'region', 'province', 'county') or r.get('type') == 'administrative':
            return [round(float(r['lon']), 4), round(float(r['lat']), 4)]
    return None

def geocode(loc):
    parts = [x.strip() for x in loc.split(',') if x.strip()]
    codes = expect(loc)
    for cut, name in enumerate(parts):
        k, extra = key(name), []
        if k.endswith(' colony'): extra, name = ALIAS.get(k, '').split('|')[:1], name[:-len(' colony')]   # "Plymouth Colony" -> Plymouth, in Massachusetts
        elif k in ALIAS or POLITY.search(name): continue                          # a region or polity names an area, not a place
        ctx = parts[cut + 1:] + extra
        cands = search(re.sub(r'\(.*?\)', '', name).strip(), codes)
        if not cands: continue
        # the last part is usually the country: agreeing with it is weak evidence; any nearer part is strong evidence
        def score(r): return sum((.4 if key(c) in BROAD or (i == len(ctx) - 1 and not extra) else 1) for i, c in enumerate(ctx) if c and agree(c, r))
        scored = sorted(((score(r), r.get('population') or 0, r) for r in cands), key=lambda t: (-t[0], -t[1]))
        best, pop, r = scored[0]
        if not ctx and not codes: continue                 # a lone word with no country: don't guess
        if not ctx:   # a bare region name ("Pennsylvania", "England"): only a region-level match will do
            cands = [c for c in cands if re.match(r'ADM|PCL|RGN|ISL|AREA', c.get('feature_code') or '')]
            if not cands and codes:
                reg = region(name, codes)
                if reg: return reg + [cut, '', 0]
        if not cands: continue
        scored = sorted(((score(r), r.get('population') or 0, r) for r in cands), key=lambda t: (-t[0], -t[1]))
        best, pop, r = scored[0]
        strong = any(key(c) not in BROAD for c in ctx[:-1]) or bool(extra)   # nearer, specific parts exist, so one of them must agree
        if ctx and best < (1 if strong else .4) and not (codes and len(cands) == 1 and not strong): continue
        return [round(r['longitude'], 4), round(r['latitude'], 4), cut, r.get('country_code', '').lower(), round(best, 1)]
    k = key(parts[-1]) if parts else ''   # only a historical region is left ("Nouvelle-France", "Massachusetts Bay Colony"): use its modern region
    if k in ALIAS and codes:
        reg = region(ALIAS[k].split('|')[0], codes)
        if reg: return reg + [len(parts) - 1, '', 0]
    return []

if __name__ == '__main__':
    T = json.load(open(os.path.join(HERE, 'tree.json'), encoding='utf-8')); tree = T['people']
    gen, q = {str(T['root']): 0}, [str(T['root'])]   # nearest generations first, so close family is placed right away
    while q:
        i = q.pop(0)
        for k in ('Father', 'Mother'):
            j = str(tree[i].get(k) or 0)
            if j in tree and j not in gen: gen[j] = gen[i] + 1; q.append(j)
    near = {}
    store.migrate()
    locs = Counter()
    for p in tree.values():
        for k in ('BirthLocation', 'DeathLocation'):
            if (p.get(k) or '').strip(): locs[p[k].strip()] += 2 if k == 'BirthLocation' else 1; near[p[k].strip()] = min(near.get(p[k].strip(), 99), gen.get(str(p['Id']), 99))
        for m in p.get('Marriages') or []:
            if (m.get('place') or '').strip(): locs[m['place'].strip()] += 1
    def stale(l): v = store.place(l); return v is None or 0 < len(v) < 5
    todo = sorted((l for l in locs if stale(l)), key=lambda l: (near.get(l, 99) // 4, -locs[l]))
    print('places', len(locs), 'to geocode', len(todo))
    for n, loc in enumerate(todo):
        try: store.put_place(loc, geocode(loc))
        except Exception as e: print('skipped', repr(loc), e)   # left unverified, so the next run retries it
        if n % 25 == 0: export(); print('geocoded', n, '/', len(todo))
    export()
    print('done', sum(1 for v in store.places().values() if v), 'hits')
