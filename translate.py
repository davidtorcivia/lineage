"""Translate non-English bios (mostly French, from Nouvelle-France records) into English, once.

Each translation is stored in lineage.db against a hash of the original bio, so a bio is re-translated only when it
changes on WikiTree. Requests go through the Message Batches API (asynchronous, half price); an interrupted run
resumes the same batch. Needs Claude credentials (ANTHROPIC_API_KEY, or `ant auth login`).

    python translate.py            # estimate, submit, wait, store, export
    python translate.py --dry-run  # just show what would be translated
    python translate.py --split 16 / --import   # or hand the work to agents as files (see below)"""
import hashlib, os, re, sys, time
import anthropic   # only needed for the Batches path
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import Request
import store
sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
PENDING = os.path.join(HERE, '_translate_batch.txt')
MODEL = 'claude-opus-5-5'
SYSTEM = ('You translate genealogy biographies from WikiTree into English. The input is HTML. Translate the human-language '
          'text into natural English and keep everything else exactly as it is: every HTML tag and attribute, links, footnote '
          'markers, dates, and the original spelling of personal names and place names (do not translate or modernise them). '
          'Keep archival titles in their original language. Return only the translated HTML.')

WORDS = {'en': 'the and was of in born he she his her to with at on married died son daughter',
         'fr': 'le la les et est né née fils fille de du des à mariée marié décédé épouse au dans il elle sa son baptisé inhumé',
         'de': 'der die das und ist geboren sohn tochter verheiratet gestorben mit im',
         'it': 'il la di e nato nata figlio figlia sposato morto con nel'}
WORDS = {k: set(v.split()) for k, v in WORDS.items()}
def language(html):
    w = re.findall(r"[a-zàâçéèêëîïôûùüÿñæœäöüß']+", re.sub(r'<[^>]+>', ' ', html).lower())
    score = {k: sum(x in s for x in w) for k, s in WORDS.items()}
    return max(score, key=score.get) if w else 'en'
digest = lambda html: hashlib.sha1(html.encode()).hexdigest()

store.db.execute('create table if not exists tr (id integer primary key, data text, touched text, fetched text)')
bios, done = store.everything('bio'), store.everything('tr')
todo = {i: b['bio'] for i, b in bios.items() if b.get('bio') and language(b['bio']) != 'en' and done.get(i, {}).get('hash') != digest(b['bio'])}
chars = sum(len(h) for h in todo.values())
print(f'{len(todo)} bios to translate, ~{chars / 3.2 / 1e6:.2f}M tokens each way')
if '--dry-run' in sys.argv: sys.exit()

# Agent mode: hand the work to agents as files instead of the Batches API.
#   --split N   writes _tr/in/<id>.html (one tag per line) and _tr/chunk_<k>.txt (N lists of ids)
#   --import    reads _tr/out/<id>.html back in, stores each against the original's hash, re-exports
TR = os.path.join(HERE, '_tr')
if '--split' in sys.argv:
    n = int(sys.argv[sys.argv.index('--split') + 1])
    os.makedirs(os.path.join(TR, 'in'), exist_ok=True); os.makedirs(os.path.join(TR, 'out'), exist_ok=True)
    ids = sorted(todo, key=lambda i: -len(todo[i]))
    for i in ids: open(os.path.join(TR, 'in', f'{i}.html'), 'w', encoding='utf-8').write(re.sub(r'>\s*<', '>\n<', todo[i]))
    for k in range(n): open(os.path.join(TR, f'chunk_{k:02d}.txt'), 'w').write('\n'.join(map(str, ids[k::n])))
    print('split into', n, 'chunks'); sys.exit()
if '--import' in sys.argv:
    out, ok = os.path.join(TR, 'out'), 0
    for f in os.listdir(out):
        i = int(f.split('.')[0])
        if i not in todo: continue
        html = open(os.path.join(out, f), encoding='utf-8').read().strip()
        if html: store.put('tr', i, {'hash': digest(todo[i]), 'lang': language(todo[i]), 'html': html}); ok += 1
    store.commit(); store.export_bios(); print('imported', ok, 'of', len(todo)); sys.exit()

if not (todo or os.path.exists(PENDING)): sys.exit()

client = anthropic.Anthropic()
if os.path.exists(PENDING):
    batch_id = open(PENDING).read().strip()
else:
    batch = client.messages.batches.create(requests=[Request(custom_id=str(i), params=MessageCreateParamsNonStreaming(
        model=MODEL, max_tokens=32000, output_config={'effort': 'low'},   # straightforward work: keep thinking short
        system=SYSTEM, messages=[{'role': 'user', 'content': html}])) for i, html in todo.items()])
    batch_id = batch.id; open(PENDING, 'w').write(batch_id)
print('batch', batch_id)
while (b := client.messages.batches.retrieve(batch_id)).processing_status != 'ended':
    print('processing', b.request_counts.processing, 'succeeded', b.request_counts.succeeded); time.sleep(60)

ok = failed = 0
for r in client.messages.batches.results(batch_id):
    i = int(r.custom_id)
    if r.result.type != 'succeeded' or r.result.message.stop_reason != 'end_turn': failed += 1; continue
    html = ''.join(b.text for b in r.result.message.content if b.type == 'text').strip()
    src = bios[i]['bio']
    store.put('tr', i, {'hash': digest(src), 'lang': language(src), 'html': html}); ok += 1
store.commit(); os.remove(PENDING)
print('translated', ok, 'failed', failed, '(failed ones are retried next run)')
store.export_bios()
