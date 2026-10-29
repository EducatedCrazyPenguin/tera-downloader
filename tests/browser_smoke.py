"""Explicit headless Edge test with a loopback-only fake website; no real media."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import threading
import tempfile
from urllib.parse import urlsplit

from edge_helper import browser_factory
from stream_smoke import PLAYER, SHARE
from terabox import Cancelled, DownloadError


def check_browser_helper(base, browser='edge'):
    base = Path(base); base.mkdir(parents=True, exist_ok=True)
    # Camoufox/uBlock creates long IndexedDB filenames; keep test profiles under
    # the short OS temp root, as the production helper normally does.
    temporary = tempfile.TemporaryDirectory(prefix='tera-cf-check-') if browser == 'camoufox' else None
    profile_path = Path(temporary.name)/'profile' if temporary else base/'profile'
    hits = []; mode = ['success']
    class Handler(BaseHTTPRequestHandler):
        def handle(self):
            try:
                super().handle()
            except (ConnectionResetError, BrokenPipeError):
                pass  # The owned browser closes idle/preconnect sockets during cleanup.
        def log_message(self, *_):
            pass
        def do_GET(self):
            path = urlsplit(self.path).path; hits.append(path)
            if path == '/download' and mode[0] == 'success':
                body = ('''<!doctype html><title>Isolated Tera fixture</title>
                <button id="one">Watch Online</button><button id="two">Watch Online</button>
                <script>
                let clicks = 0;
                one.onclick = () => { clicks++; document.body.dataset.clicks=clicks; one.textContent='Ready'; window.open(PLAYER, '_blank'); };
                two.onclick = () => { clicks++; document.body.dataset.clicks=clicks; window.open(PLAYER.replace('sample.mp4','second.mp4'), '_blank'); };
                </script>'''.replace('PLAYER', json.dumps(PLAYER))).encode()
                self.send_response(200); self.send_header('Content-Type', 'text/html')
            elif path == '/download':
                body = b'<!doctype html><title>Empty synthetic listing</title><p>No files</p>'
                self.send_response(200); self.send_header('Content-Type', 'text/html')
            else:
                body = b'not media'; self.send_response(404)
            self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
    origin = 'http://127.0.0.1:' + str(server.server_port)
    try:
        engine = browser_factory(browser)
        with engine(headless=True, origin=origin, profile_dir=profile_path) as browser:
            profile = browser.profile; child = browser.child
            print(f'Owned headless {browser.name} PID', child.pid, flush=True)
            errors = []; original_event = browser.cdp.on_event if browser.cdp else None
            def event(message):
                if message.get('method') == 'Runtime.exceptionThrown' or message.get('method') == 'log.entryAdded' and message.get('params', {}).get('level') == 'error':
                    errors.append('runtime_exception')
                original_event(message)
            if browser.cdp:
                browser.cdp.on_event = event
            if browser.name == 'Edge':
                browser.page('Runtime.enable')
            elif browser.cdp:
                browser.cdp.call('session.subscribe', {'events':['log.entryAdded']})
            sources = browser.resolve(SHARE, threading.Event(), lambda _: None, timeout=10)
            assert sources == [PLAYER, PLAYER.replace('sample.mp4','second.mp4')], f'Player capture did not cover both rows: count={len(sources)}, first={PLAYER in sources}, second={PLAYER.replace("sample.mp4","second.mp4") in sources}'
            value = browser.evaluate('Number(document.body.dataset.clicks)')
            assert value == 2, 'Ordinary buttons did not run exactly once'
            assert not errors, 'Injected handoff had a JavaScript runtime error'
            assert hits.count('/download') == 1
            cancel = threading.Event(); cancel.set()
            try:
                browser.resolve(SHARE, cancel, lambda _: None, timeout=2)
            except Cancelled:
                pass
            else:
                raise AssertionError('Cancellation was ignored')
            assert hits.count('/download') == 1, 'Cancelled helper started another navigation'
            browser.evaluate("(() => {document.cookie='tera_fixture=kept; Max-Age=3600; SameSite=Lax'; return true;})()")
            mode[0] = 'empty'
            try:
                browser.resolve(SHARE, threading.Event(), lambda _: None, timeout=.7)
            except DownloadError:
                pass
            else:
                raise AssertionError('Empty listing was incorrectly marked successful')
        assert child.poll() is not None and profile.exists(), 'Owned process cleanup/profile retention failed'
        with engine(headless=True, origin=origin, profile_dir=profile) as restored:
            print(f'Owned headless {restored.name} restart PID',restored.child.pid,flush=True)
            restored.navigate(origin+'/download')
            import time
            end=time.monotonic()+5
            while time.monotonic()<end:
                cookies=restored.evaluate('location.origin === '+json.dumps(origin)+' ? document.cookie : ""')
                if cookies and 'tera_fixture=kept' in cookies:break
                time.sleep(.05)
            else:raise AssertionError('Synthetic first-party browser cookie did not survive restart')
        print(f'PASS: real headless {browser.name}, two automatic ordinary clicks, exact player capture, no player/media navigation, cancellation, owned cleanup and synthetic cookie persistence after restart', flush=True)
    finally:
        server.shutdown(); server.server_close(); worker.join(2)
        if temporary:
            temporary.cleanup()
