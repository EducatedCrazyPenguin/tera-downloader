"""Firefox's supported WebDriver BiDi in a Tera-owned profile, no geckodriver."""
import json
import os
import re
from pathlib import Path
import subprocess
import time

from browser_native import BrowserJob, DevTools
from edge_helper import OwnedEdge, SITE, HOOK, allowed_request, captured_source
from terabox import DownloadError


def firefox_path():
    for key in ('PROGRAMFILES', 'PROGRAMFILES(X86)'):
        if os.environ.get(key):
            path = Path(os.environ[key]) / 'Mozilla Firefox' / 'firefox.exe'
            if path.is_file():
                return path
    raise DownloadError('Firefox is not installed in its usual location. Choose Edge, or install Firefox first.')


def firefox_command(executable, profile, headless=False):
    command = [str(executable), '-no-remote', '--profile', str(profile),
               '--remote-debugging-port=0', '--width', '820', '--height', '680']
    if headless:
        command.append('--headless')
    return [*command, 'about:blank']


class OwnedFirefox(OwnedEdge):
    name = 'Firefox'

    def __enter__(self):
        try:
            executable = firefox_path(); self.prepare_profile()
            # Only a new, explicitly owned profile receives first-run defaults.
            preferences = self.profile / 'user.js'
            if not preferences.exists() and not (self.profile / 'prefs.js').exists():
                preferences.write_text('''user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("browser.startup.page", 0);
user_pref("browser.startup.homepage", "about:blank");
user_pref("browser.aboutwelcome.enabled", false);
user_pref("startup.homepage_welcome_url", "");
user_pref("startup.homepage_welcome_url.additional", "");
''', encoding='utf-8')
            identity_file = self.profile / 'WebDriverBiDiServer.json'
            identity_file.unlink(missing_ok=True)
            self.job = BrowserJob()
            self.child = subprocess.Popen(firefox_command(executable, self.profile, self.headless),
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW)
            self.job.assign(self.child)
            (self.profile / 'tera-owner.txt').write_text(f'Owned Firefox PID {self.child.pid}\n', encoding='ascii')
            deadline = time.monotonic() + 10
            identity = None
            while time.monotonic() < deadline:
                if self.child.poll() is not None and not self.job.alive():
                    break
                try:
                    identity = json.loads(identity_file.read_text(encoding='utf-8'))
                    break
                except (OSError, ValueError):
                    time.sleep(.05)
            if not identity or identity.get('ws_host') not in ('127.0.0.1', 'localhost'):
                raise DownloadError('The separate Firefox helper did not start. Close any Tera helper setup window before retrying.')
            port = identity['ws_port']
            if type(port) is not int or not 1 <= port <= 65535:
                raise OSError('Invalid owned Firefox port.')
            self.cdp = DevTools(f'ws://127.0.0.1:{port}/session', port, protocol='bidi')
            session = self.cdp.call('session.new', {'capabilities':{'alwaysMatch':{'acceptInsecureCerts':False}}})
            if session['capabilities'].get('browserName') != 'firefox':
                raise OSError('The owned browser is not Firefox.')
            tree = self.cdp.call('browsingContext.getTree', {'maxDepth':0})['contexts']
            pages = [item for item in tree if item['url'] in ('', 'about:blank')]
            if not pages:
                raise OSError('Firefox did not create its isolated blank page.')
            self.context = pages[0]['context']; self.found = []
            if not self.setup:
                self.cdp.call('session.subscribe', {'events':['network.beforeRequestSent', 'browsingContext.contextCreated', 'browsingContext.navigationFailed', 'log.entryAdded']})
                self.cdp.call('script.addPreloadScript', {
                    'functionDeclaration':'() => {' + HOOK.replace('__TERA_ORIGIN__', json.dumps(self.origin)) + ';}',
                    'contexts':[self.context]})
                self.cdp.call('network.addIntercept', {'phases':['beforeRequestSent'], 'contexts':[self.context]})
            self.cdp.on_event = self._event
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def navigate(self, url):
        self.navigation = self.cdp.send('browsingContext.navigate', {'context':self.context, 'url':url, 'wait':'none'})

    def evaluate(self, expression):
        result = self.cdp.call('script.evaluate', {
            'expression':'JSON.stringify(' + expression + ')', 'target':{'context':self.context},
            'awaitPromise':False, 'resultOwnership':'none'})
        if result.get('type') != 'success':
            raise DownloadError('The Firefox helper script could not run on this page.')
        value = result.get('result', {})
        if value.get('type') != 'string':
            return None
        return json.loads(value['value'])

    def _event(self, event):
        if self.setup:
            return
        method = event.get('method'); params = event.get('params', {})
        if method == 'log.entryAdded':
            text = params.get('text', '')
            match = re.search(r'\[Cloudflare Turnstile\]\s*Error:\s*(\d{6})(?!\d)', text) if isinstance(text, str) else None
            if match:
                self.challenge_error = match.group(1)
        elif method == 'network.beforeRequestSent' and params.get('isBlocked'):
            request = params['request']; source = captured_source(request['url'])
            self.remember(source)
            if source:
                self.cdp.send('script.evaluate', {'expression':'if (window.__teraHandoff) window.__teraHandoff.pending = false',
                    'target':{'context':self.context}, 'awaitPromise':False})
            media = request.get('destination') in ('audio', 'video')
            allow = allowed_request(request['url'], 'Media' if media else '', self.origin)
            self.cdp.send('network.continueRequest' if allow else 'network.failRequest', {'request':request['request']})
        elif method == 'browsingContext.contextCreated':
            if params.get('originalOpener') == self.context:
                self.remember(captured_source(params.get('url')))
                self.cdp.send('browsingContext.close', {'context':params['context']})
        elif method == 'browsingContext.navigationFailed' and params.get('context') == self.context:
            self.navigation_failed = True
        elif event.get('id') == getattr(self, 'navigation', None) and event.get('type') == 'error':
            self.navigation_failed = True

    def close_browser(self):
        self.cdp.call('browser.close')
