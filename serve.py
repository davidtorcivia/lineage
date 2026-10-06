"""Password-gated server for sharing the viewer:  PASSWORD=... python serve.py [port]   (deployed by deploy.sh)

Serves only the viewer, its exported data (index.html, tree.json, places.json, bios/N.json) and art/*.png, plus the
favicon and link-preview image to anyone; everything else in the
folder (lineage.db, session cookies, scripts) is never reachable. One shared password; a correct one sets a year-long
cookie that is an HMAC of the password, so changing the password signs everyone out."""
import hmac, hashlib, os, re, sys, threading, time, urllib.parse
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

PASSWORD = os.environ.get('PASSWORD') or sys.exit('set PASSWORD')
TOKEN = hmac.new(PASSWORD.encode(), b'tributaries', hashlib.sha256).hexdigest()
PUBLIC = re.compile(r'/(index\.html|tree\.json|places\.json|bios/\d{1,2}\.json|art/[a-z-]+\.png)?')
HERE = os.path.dirname(os.path.abspath(__file__))
OPEN = re.compile(r'/(favicon\.svg|apple-touch-icon\.png|og\.png)')   # no secrets: link previews and browser tabs need these signed out
ROOT = os.environ.get('DATA', HERE)   # where index.html and the exported data live (the container mounts them at /data)
LOGIN = open(os.path.join(HERE, 'login.html'), 'rb').read()
WINDOW, TRIES = 15 * 60, 5          # 5 wrong passwords in 15 minutes locks that visitor out until the window passes
FAILS, LOCK = {}, threading.Lock()

def recent(ip, add=False):   # this visitor's failures inside the window (optionally recording a new one)
    now = time.time()
    with LOCK:
        if len(FAILS) > 10000: FAILS.clear()   # ponytail: crude memory cap; a flood of addresses just resets everyone's count
        t = [x for x in FAILS.get(ip, []) if now - x < WINDOW] + ([now] if add else [])
        if t: FAILS[ip] = t
        else: FAILS.pop(ip, None)
        return len(t)

class Gate(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k): super().__init__(*a, directory=ROOT, **k)

    def authed(self):
        m = re.search(r'(?:^|;\s*)t=([0-9a-f]{64})', self.headers.get('Cookie', ''))
        return bool(m) and hmac.compare_digest(m.group(1), TOKEN)

    def send(self, code, body=b'', **headers):
        self.send_response(code)
        for k, v in headers.items(): self.send_header(k.replace('_', '-'), v)
        self.send_header('Content-Length', str(len(body))); self.end_headers()
        if self.command != 'HEAD': self.wfile.write(body)

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        if OPEN.fullmatch(path): return (super().do_HEAD if self.command == 'HEAD' else super().do_GET)()
        if not PUBLIC.fullmatch(path): return self.send(404, b'not found')
        if not self.authed():   # the login page stands in for anything asked for while signed out
            page = path in ('/', '/index.html')
            # link previews only ever see this page: give its og:image an absolute address on whatever host the tunnel serves
            host = re.sub(r'[^\w.:-]', '', self.headers.get('Host', ''))
            proto = 'http' if host.startswith(('localhost', '127.')) else 'https'
            return self.send(200 if page else 401, LOGIN.replace(b'__ORIGIN__', f'{proto}://{host}'.encode()) if page else b'',
                             Content_Type='text/html; charset=utf-8', Cache_Control='no-store')
        (super().do_HEAD if self.command == 'HEAD' else super().do_GET)()
    do_HEAD = do_GET

    def do_POST(self):
        if urllib.parse.urlsplit(self.path).path != '/login': return self.send(404)
        n = min(int(self.headers.get('Content-Length') or 0), 1000)
        pw = urllib.parse.parse_qs(self.rfile.read(n).decode(errors='replace')).get('password', [''])[0]
        ip = self.headers.get('CF-Connecting-IP') or self.client_address[0]   # the port is loopback-only, so this header comes from the tunnel
        if recent(ip) >= TRIES: return self.send(303, Location='/?wait')
        if hmac.compare_digest(pw.strip().encode(), PASSWORD.encode()):
            return self.send(303, Location='/', Set_Cookie=f't={TOKEN}; Max-Age=31536000; Path=/; HttpOnly; Secure; SameSite=Lax')
        recent(ip, add=True); time.sleep(1)
        self.send(303, Location='/?wait' if recent(ip) >= TRIES else '/?wrong')

    def end_headers(self):
        if self.path.split('?')[0].endswith('.json'): self.send_header('Cache-Control', 'private, no-cache')
        super().end_headers()
    def log_message(self, fmt, *a):   # Cloudflare's tunnel connects from localhost; log who it says the visitor is
        sys.stderr.write(f"{(getattr(self, 'headers', None) or {}).get('CF-Connecting-IP', self.client_address[0])} {fmt % a}\n")

if __name__ == '__main__':
    ThreadingHTTPServer(('', int(sys.argv[1]) if len(sys.argv) > 1 else 8080), Gate).serve_forever()
