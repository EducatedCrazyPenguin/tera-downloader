"""Normal website handoff in a disposable Edge window; never solve verification."""
import http.client
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from urllib.parse import urlsplit, urlencode

from browser_native import BrowserJob, DevTools
from terabox import Cancelled, DownloadError, share_id
from website_stream import parse_source

SITE = 'https://teradownloader.com'
UNREACHABLE = 'The download website could not be reached. The browser helper cannot fix a website or network timeout. Try again when the site opens normally.'

# Only the site's ordinary Watch Online buttons are automated. Challenge frames,
# verification tokens, browser cookies and storage are never inspected or changed.
HOOK = r'''(() => {
  if (location.origin !== __TERA_ORIGIN__) return;
  const state = {links: [], pending: false, clicked: new WeakSet()};
  window.__teraHandoff = state;
  window.open = url => {
    try { if (state.links.length < 100) state.links.push(new URL(String(url || ''), location.href).href.slice(0, 32768)); } catch (_) {}
    return null;
  };
  document.addEventListener('click', event => {
    const a = event.target.closest && event.target.closest('a[target="_blank"]');
    if (a) { event.preventDefault(); state.links.push(a.href.slice(0, 32768)); }
  }, true);
})()'''

POLL = r'''(() => {
  const s = window.__teraHandoff;
  if (!s) return {ready: false};
  const buttons = [...document.querySelectorAll('button')].filter(b =>
    b.textContent.trim() === 'Watch Online' && b.getClientRects().length && !b.disabled);
  const next = buttons.find(b => !s.clicked.has(b));
  if (!s.pending && next) { s.pending = true; s.clicked.add(next); next.click(); }
  const links = s.links.splice(0, 100);
  if (links.length) s.pending = false;
  return {ready: document.readyState !== 'loading', links, pending: s.pending,
          remaining: buttons.filter(b => !s.clicked.has(b)).length,
          verification: !!document.querySelector('iframe[src*="challenges.cloudflare.com"]')};
})()'''


def captured_source(value):
    if not isinstance(value, str):
        return None
    try:
        parse_source(value)
        return value
    except (DownloadError, ValueError):
        return None


def allowed_request(url, resource, origin=SITE):
    if resource == 'Media' or captured_source(url):
        return False
    try:
        p = urlsplit(url); target = urlsplit(origin)
        if p.username or p.password or p.fragment:
            return False
        return ((p.scheme, p.hostname, p.port) == (target.scheme, target.hostname, target.port)
                or p.scheme == 'https' and p.hostname == 'challenges.cloudflare.com' and p.port in (None, 443))
    except ValueError:
        return False


def edge_path():
    for key in ('PROGRAMFILES(X86)', 'PROGRAMFILES', 'LOCALAPPDATA'):
        base = os.environ.get(key)
        if base:
            path = Path(base) / 'Microsoft' / 'Edge' / 'Application' / 'msedge.exe'
            if path.is_file():
                return path
    raise DownloadError('Microsoft Edge is needed for the small browser helper. A generated player link can still be pasted below.')


def browser_command(executable, profile, headless=False):
    command = [str(executable), '--user-data-dir=' + str(profile), '--remote-debugging-port=0',
               '--remote-debugging-address=127.0.0.1', '--no-first-run', '--no-default-browser-check',
               '--disable-sync', '--disable-background-mode',
               '--disable-background-networking', '--disable-component-update',
               '--window-size=820,680', '--new-window', 'about:blank']
    if headless:
        command.insert(-1, '--headless=new')
    return command


class OwnedEdge:
    name = 'Edge'
    def __init__(self, *, headless=False, origin=SITE, profile_dir=None, setup=False):
        self.headless, self.origin, self.setup = headless, origin, setup
        self.profile_dir = Path(profile_dir).resolve() if profile_dir is not None else None
        self.profile_guard = None
        self.child = self.job = self.cdp = self.profile = None

    def prepare_profile(self):
        if self.profile_dir is None:
            self.profile = Path(tempfile.mkdtemp(prefix='tera-browser-')).resolve()
        else:
            marker = self.profile_dir / 'tera-helper-profile.txt'
            expected = f'Tera {self.name} helper profile v1\n'
            try:
                self.profile_dir.mkdir(parents=True, exist_ok=False)
                marker.write_text(expected, encoding='ascii')
            except FileExistsError:
                if not marker.is_file() or marker.read_text(encoding='ascii') != expected:
                    raise DownloadError("Choose Tera's own helper profile; an existing browser profile cannot be automated.") from None
            self.profile = self.profile_dir
        import msvcrt
        guard = (self.profile / 'tera-helper.lock').open('a+b')
        try:
            if guard.tell() == 0:
                guard.write(b'0'); guard.flush()
            guard.seek(0); msvcrt.locking(guard.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            guard.close()
            raise DownloadError('This Tera browser helper is already in use. Close its setup window before retrying.') from None
        self.profile_guard = guard

    def _json(self, path):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=2)
        try:
            connection.request('GET', path)
            response = connection.getresponse(); body = response.read(131073)
            if response.status != 200 or len(body) > 131072:
                raise OSError('Invalid owned-browser identity.')
            return json.loads(body)
        finally:
            connection.close()

    def __enter__(self):
        try:
            executable = edge_path()
            self.prepare_profile()
            (self.profile / 'DevToolsActivePort').unlink(missing_ok=True)
            self.job = BrowserJob()
            self.child = subprocess.Popen(browser_command(executable, self.profile, self.headless),
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW)
            self.job.assign(self.child)
            # Record ownership only; never the share, page HTML or browser stderr.
            (self.profile / 'tera-owner.txt').write_text(f'Owned Edge PID {self.child.pid}\n', encoding='ascii')
            deadline = time.monotonic() + 10
            while not (self.profile / 'DevToolsActivePort').is_file():
                if self.child.poll() is not None or time.monotonic() > deadline:
                    raise DownloadError('The isolated Edge helper did not start. It did not attach to your normal browser.')
                time.sleep(.05)
            port, path, *_ = (self.profile / 'DevToolsActivePort').read_text(encoding='ascii').splitlines()
            self.port = int(port)
            if not 1 <= self.port <= 65535:
                raise OSError('Invalid owned-browser port.')
            identity = self._json('/json/version')
            endpoint = identity['webSocketDebuggerUrl']
            if urlsplit(endpoint).path != path:
                raise OSError('Owned-browser identity did not match.')
            self.cdp = DevTools(endpoint, self.port)
            deadline = time.monotonic() + 2
            pages = []
            while not pages and time.monotonic() < deadline:
                pages = [p for p in self.cdp.call('Target.getTargets')['targetInfos']
                         if p['type'] == 'page' and p['url'] in ('', 'about:blank')]
                if not pages:
                    time.sleep(.05)
            if len(pages) != 1:
                raise OSError('The browser is not an isolated blank instance.')
            self.target = pages[0]['targetId']
            self.session = self.cdp.call('Target.attachToTarget', {'targetId':self.target, 'flatten':True})['sessionId']
            if not self.setup:
                self.cdp.call('Browser.setDownloadBehavior', {'behavior':'deny'})
            self.page('Page.enable')
            if not self.setup:
                self.page('Page.addScriptToEvaluateOnNewDocument', {'source':HOOK.replace('__TERA_ORIGIN__', json.dumps(self.origin))})
                self.page('Fetch.enable', {'patterns':[{'urlPattern':'*','requestStage':'Request'}]})
            self.cdp.on_event = self._event
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def page(self, method, params=None):
        return self.cdp.call(method, params, self.session)

    def remember(self, source):
        if source and source not in self.found:
            if len(self.found) >= 100:
                raise DownloadError('The website returned too many player links. Use a smaller share.')
            self.found.append(source)

    def _event(self, event):
        if self.setup:
            return
        if event.get('method') == 'Fetch.requestPaused':
            p = event['params']; url = p['request']['url']
            source = captured_source(url)
            self.remember(source)
            if source:
                self.cdp.send('Runtime.evaluate', {'expression':'if (window.__teraHandoff) window.__teraHandoff.pending = false'}, self.session)
            allow = allowed_request(url, p.get('resourceType'), self.origin)
            params = {'requestId':p['requestId']}
            if not allow:
                params['errorReason'] = 'Aborted'
            self.cdp.send('Fetch.continueRequest' if allow else 'Fetch.failRequest', params, event.get('sessionId'))
        elif event.get('method') == 'Target.targetCreated':
            target = event['params']['targetInfo']
            if target.get('openerId') == self.target:
                source = captured_source(target.get('url'))
                self.remember(source)
                self.cdp.send('Target.closeTarget', {'targetId':target['targetId']})
        elif event.get('id') == getattr(self, 'navigation', None) and event.get('result', {}).get('errorText'):
            self.navigation_failed = True

    def navigate(self, url):
        self.cdp.call('Target.setDiscoverTargets', {'discover':True})
        self.navigation = self.cdp.send('Page.navigate', {'url':url}, self.session)

    def evaluate(self, expression):
        response = self.page('Runtime.evaluate', {'expression':expression, 'returnByValue':True})
        if response.get('exceptionDetails'):
            raise DownloadError('The website helper script could not run on this page.')
        return response.get('result', {}).get('value')

    def close_browser(self):
        self.cdp.call('Browser.close')

    def resolve(self, share, cancel, status, *, timeout=180):
        share_id(share)
        if cancel.is_set():
            raise Cancelled('Website helper cancelled.')
        self.found = []; self.navigation_failed = False; self.challenge_error = None
        self.navigate(self.origin + '/download?' + urlencode({'l':share}))
        deadline = time.monotonic() + timeout; loading = time.monotonic() + min(60, timeout)
        quiet = None; ready = False
        while time.monotonic() < deadline:
            if cancel.is_set():
                raise Cancelled('Website helper cancelled.')
            state = self.evaluate(POLL) or {}
            if self.navigation_failed:
                raise DownloadError(UNREACHABLE)
            ready = ready or state.get('ready', False)
            if not ready and time.monotonic() > loading:
                raise DownloadError(UNREACHABLE)
            for value in state.get('links', [])[:100]:
                source = captured_source(value)
                self.remember(source)
            if self.found and not state.get('pending') and not state.get('remaining'):
                quiet = quiet or time.monotonic()
                if time.monotonic() - quiet >= .7:
                    return self.found
            else:
                quiet = None
            if self.challenge_error:
                status(f'Cloudflare verification failed ({self.challenge_error}). Retry verification in the browser or Cancel; Tera is still waiting.')
            else:
                status(f'Complete human verification in the small {self.name} window if shown. Tera will capture the player link automatically.'
                       if not self.found else 'Captured a player link; finishing the website handoff…')
            if cancel.wait(.2):
                raise Cancelled('Website helper cancelled.')
        raise DownloadError('The website did not provide a supported player link within the allowed time. Complete any verification shown, or paste a generated player link manually.')

    def __exit__(self, *_):
        controlled = self.cdp is not None
        if self.cdp:
            try:
                self.close_browser()
            except OSError:
                pass
            self.cdp.close(); self.cdp = None
        deadline = time.monotonic() + 5
        while controlled and self.job and self.job.alive() and time.monotonic() < deadline:
            time.sleep(.05)
        if self.child:
            try:
                self.child.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
        if self.job:
            self.job.close(); self.job = None
        if self.child and self.child.poll() is None:
            self.child.terminate(); self.child.wait(timeout=3)
        if self.profile_guard:
            self.profile_guard.close(); self.profile_guard = None
        if self.profile_dir is not None:
            self.profile = None
            return
        if self.profile:
            # Only the exact task-created temporary directory can be removed.
            base = Path(tempfile.gettempdir()).resolve()
            if self.profile.parent != base or not self.profile.name.startswith('tera-browser-'):
                raise OSError('Refused browser-profile cleanup outside the owned temporary folder.')
            for attempt in range(2):
                try:
                    shutil.rmtree(self.profile)
                    break
                except OSError:
                    if attempt:
                        raise DownloadError('The helper closed, but its temporary browser profile could not be removed. No links were queued. A temporary browser folder may remain in Windows Temp.') from None
                    time.sleep(.2)
            self.profile = None


def browser_factory(browser):
    if browser == 'edge':
        return OwnedEdge
    if browser == 'firefox':
        from firefox_helper import OwnedFirefox
        return OwnedFirefox
    if browser == 'camoufox':
        from camoufox_helper import OwnedCamoufox
        return OwnedCamoufox
    raise DownloadError('Choose Camoufox, Firefox or Edge for the website helper.')


def configure_browser(browser, profile_dir, cancel, status):
    if browser == 'camoufox':
        raise DownloadError('Camoufox includes uBlock. Choose Firefox or Edge to manage helper extensions.')
    factory = browser_factory(browser)
    with factory(profile_dir=profile_dir, setup=True) as helper:
        helper.navigate('about:addons' if browser in ('firefox','camoufox') else 'edge://extensions/')
        status('Install the extensions you want in this Tera-only browser, then close that window or click Done here. Setup closes after 10 minutes.')
        end = time.monotonic() + 600
        while not cancel.wait(.2) and time.monotonic() < end and helper.job.alive():
            pass


def resolve_shares(shares, cancel, status, *, browser='edge', profile_dir=None, origins=None):
    """All shares succeed before any result is queued; closing the helper cancels."""
    unique = list(dict.fromkeys(shares))
    for share in unique:
        share_id(share)
    if cancel.is_set():
        raise Cancelled('Website helper cancelled.')
    result = []
    try:
        factory = browser_factory(browser)
        with factory(profile_dir=profile_dir) as helper:
            for index, share in enumerate(unique):
                if cancel.is_set():
                    raise Cancelled('Website helper cancelled.')
                status(f'Resolving share {index + 1} of {len(unique)} with {helper.name}…')
                resolved = helper.resolve(share,cancel,status)
                if origins is not None and len(resolved)==1:origins[resolved[0]]=share
                for source in resolved:
                    if source not in result:
                        result.append(source)
        return result
    except DownloadError:
        raise
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        raise DownloadError('The isolated website helper stopped or could not connect. Your normal browser was not used. Retry when the website is reachable, or paste a generated player link below.') from None
