"""Optional Camoufox runtime. Private pipes, owned profiles and bounded processes."""
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time

from browser_native import BrowserJob
from edge_helper import OwnedEdge, SITE, captured_source
from terabox import Cancelled, DownloadError, share_id

RUNTIME_VERSION = '158.0-beta.40'
RUNTIME_MARKER = {'browser': RUNTIME_VERSION, 'playwright': '1.62.1', 'node': '24.22.1', 'ublock': '1.75.0'}


def runtime_directory():
    return Path(os.environ.get('LOCALAPPDATA', Path.home()/'AppData'/'Local'))/'Tera'/'browser-runtime'/('camoufox-'+RUNTIME_VERSION)


def checked_runtime():
    root = runtime_directory()
    try:
        if json.loads((root/'tera-runtime.json').read_text(encoding='utf-8')) != RUNTIME_MARKER:
            raise ValueError
        for name in ('node.exe', 'native/camoufox.exe', 'playwright-core/index.js', 'addons/ublock/manifest.json'):
            if not (root/name).is_file():
                raise ValueError
    except (OSError, ValueError):
        raise DownloadError('The optional Camoufox browser is not installed completely. Install its pinned runtime, or choose Firefox or Edge in Settings → Connection.') from None
    return root


class OwnedCamoufox(OwnedEdge):
    name = 'Camoufox'

    def __init__(self, *, headless=None, origin=SITE, profile_dir=None, setup=False):
        super().__init__(headless=not setup if headless is None else headless, origin=origin, profile_dir=profile_dir, setup=setup)
        self.messages = queue.Queue(); self.command_id = 0; self.reader = None

    def __enter__(self):
        try:
            runtime = checked_runtime()
            self.prepare_profile()
            script = Path(__file__).resolve().with_name('camoufox_worker.cjs')
            env = {key:value for key,value in os.environ.items()
                   if not key.startswith(('CAMOU_', 'NODE_', 'PW_', 'PLAYWRIGHT_')) and key != 'DEBUG'}
            env.update(DEBUG='', PWDEBUG='0', PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD='1')
            self.job = BrowserJob()
            self.child = subprocess.Popen([str(runtime/'node.exe'), str(script)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW, env=env)
            self.job.assign(self.child)
            (self.profile/'tera-owner.txt').write_text(f'Owned Camoufox controller PID {self.child.pid}\n', encoding='ascii')
            def read_messages():
                try:
                    while True:
                        line = self.child.stdout.readline(1024*1024+1)
                        if not line:
                            break
                        if len(line)>1024*1024 or not line.endswith(b'\n'):
                            break
                        try:
                            self.messages.put(json.loads(line))
                        except (ValueError, UnicodeError):
                            break
                finally:
                    self.messages.put(None)
            self.reader = threading.Thread(target=read_messages, daemon=True, name='TeraCamoufoxPipe')
            self.reader.start()
            self.info = self._call('init', timeout=25, runtime=str(runtime), profile=str(self.profile),
                                   headless=self.headless, origin=self.origin, setup=self.setup)
            return self
        except BaseException:
            self.__exit__(None,None,None)
            raise

    def _send(self, op, **values):
        self.command_id += 1
        message = {'id':self.command_id, 'op':op, **values}
        self.child.stdin.write((json.dumps(message)+'\n').encode('utf-8')); self.child.stdin.flush()
        return self.command_id

    def _call(self, op, *, timeout=10, cancel=None, status=lambda _:None, **values):
        identifier = self._send(op, **values)
        end = time.monotonic()+timeout
        while time.monotonic()<end:
            if cancel is not None and cancel.is_set():
                raise Cancelled('Website helper cancelled.')
            try:
                message = self.messages.get(timeout=.1)
            except queue.Empty:
                continue
            if message is None:
                raise DownloadError('The Camoufox helper closed before finishing. Retry or choose another browser.')
            if not isinstance(message, dict) or message.get('id')!=identifier:
                raise DownloadError('The Camoufox helper returned an invalid response.')
            if message.get('event')=='challenge':
                status('Waiting for website verification in the background…')
                continue
            if message.get('error'):
                code = message['error']
                text = {'verification':'The website security verification failed. Retry manually when the website is reachable.',
                        'timeout':'The website did not provide a player link in time. Retry, or use a generated player link.',
                        'navigation':'Could not reach the website in Camoufox. Check the connection and retry.',
                        'startup':'Camoufox could not start. Close its setup window and retry.',
                        'too_many':'The website returned too many player links. Use a smaller share.'}.get(code,
                        'The Camoufox website helper stopped. Retry or choose another browser.')
                raise DownloadError(text)
            return message.get('result')
        raise DownloadError('The Camoufox helper exceeded its time limit. Retry when the website is reachable.')

    def resolve(self, share, cancel, status, *, timeout=180):
        share_id(share)
        if cancel.is_set():
            raise Cancelled('Website helper cancelled.')
        status('Resolving the share automatically with Camoufox…')
        values = self._call('resolve', timeout=timeout+3, cancel=cancel, status=status,
                            share=share, seconds=max(.1,min(180,timeout)))
        if not isinstance(values,list) or not 0<len(values)<=100 or any(not captured_source(value) for value in values):
            raise DownloadError('Camoufox did not return supported player links. No download was queued.')
        return list(dict.fromkeys(values))

    def navigate(self,url):
        return self._call('navigate', url=url, timeout=15)

    def evaluate(self, expression):
        return self._call('evaluate', expression=expression)

    def __exit__(self,*_):
        if self.child:
            try:
                if self.child.poll() is None:
                    self._send('close')
                    self.child.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                pass
            if self.job:
                self.job.close(); self.job=None
            if self.child.poll() is None:
                self.child.terminate(); self.child.wait(timeout=3)
            for pipe in (self.child.stdin,self.child.stdout):
                if pipe:
                    pipe.close()
            if self.reader:
                self.reader.join(timeout=1)
        super().__exit__(None,None,None)
