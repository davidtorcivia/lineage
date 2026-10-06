"""python test_serve.py — the password gate lets nothing but the viewer and its data out, and only after the password."""
import os, subprocess, sys, time, urllib.request, urllib.error
PORT, HERE = 8779, os.path.dirname(os.path.abspath(__file__))
srv = subprocess.Popen([sys.executable, os.path.join(HERE, 'serve.py'), str(PORT)], env={**os.environ, 'PASSWORD': 'pw'})
op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a): return None
raw = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect)

def get(path, cookie=''):
    try: r = op.open(urllib.request.Request(f'http://127.0.0.1:{PORT}{path}', headers={'Cookie': cookie})); return r.status, r.read()
    except urllib.error.HTTPError as e: return e.code, e.read()
def login(pw):
    try: raw.open(f'http://127.0.0.1:{PORT}/login', data=f'password={pw}'.encode())
    except urllib.error.HTTPError as e: return e.headers.get('Location'), e.headers.get('Set-Cookie') or ''
try:
    time.sleep(1.5)
    secret = ['/lineage.db', '/.wt_cookies', '/serve.py', '/pull.py', '/../lineage.db', '/bios/../lineage.db', '/%2e%2e/lineage.db', '/bios/x.json']
    assert b'name="password"' in get('/')[1]
    assert get('/tree.json')[0] == 401
    assert get('/og.png')[0] == 200 and get('/favicon.svg')[0] == 200     # previews and tabs work signed out
    assert b'content="http://127.0.0.1:%d/og.png"' % PORT in get('/')[1]  # og:image is absolute, on the visitor's host
    assert login('nope') == ('/?wrong', '')
    loc, cookie = login('pw'); cookie = cookie.split(';')[0]
    assert loc == '/' and cookie.startswith('t=') and 'HttpOnly' in login('pw')[1]
    assert get('/', cookie)[1].startswith(b'<!doctype html>') and b'deck.gl' in get('/', cookie)[1]
    assert get('/tree.json', cookie)[0] == 200
    for p in secret: assert get(p, cookie)[0] == 404, p
    assert get('/tree.json', 't=' + '0' * 64)[0] == 401
    for _ in range(3): login('nope')
    assert login('nope')[0] == '/?wait'                 # the 5th wrong try in the window locks this visitor out...
    assert login('pw') == ('/?wait', '')                # ...even with the right password, until the window passes
    print('ok')
finally: srv.kill()
