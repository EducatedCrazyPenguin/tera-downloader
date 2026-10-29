"""Optional Windows tray. Callbacks enqueue actions; they never touch Tk or jobs."""
from __future__ import annotations

import importlib.util
import os
import threading


def available():
    return os.name == 'nt' and all(importlib.util.find_spec(name) for name in ('pystray', 'PIL'))


def make_icon(dispatch):
    import ctypes
    import pystray
    from PIL import Image, ImageDraw
    from pystray._util import win32

    class CheckedIcon(pystray.Icon):
        # The pinned backend otherwise ignores failed Windows registration.
        def _message(self, code, flags, **kwargs):
            accepted = win32.Shell_NotifyIcon(code, win32.NOTIFYICONDATAW(
                cbSize=ctypes.sizeof(win32.NOTIFYICONDATAW), hWnd=self._hwnd,
                hID=id(self), uFlags=flags, **kwargs))
            if not accepted and (code == win32.NIM_ADD or code == win32.NIM_MODIFY and self.visible):
                raise OSError('Tray operation unavailable.')

    image = Image.new('RGB', (64, 64), '#A5262D')
    draw = ImageDraw.Draw(image)
    draw.rectangle((12, 12, 51, 23), fill='white')
    draw.rectangle((26, 20, 37, 52), fill='white')
    def action(name):
        return lambda icon, item: dispatch(name)
    menu = pystray.Menu(
        pystray.MenuItem('Show Tera', action('restore'), default=True),
        pystray.MenuItem('Pause now', action('pause')),
        pystray.MenuItem('Resume / Start queue', action('resume')),
        pystray.MenuItem('Cancel queue', action('cancel')),
        pystray.MenuItem('Save queue and exit', action('exit')))
    return CheckedIcon('Tera', image, 'Tera', menu)


class Desktop:
    def __init__(self, events, factory=make_icon):
        self.events, self.factory = events, factory
        self.icon = None
        self.thread = None
        self.stop_thread = None
        self.failure = None
        self.ready = threading.Event()
        self.stopping = threading.Event()
        self.stopped = threading.Event()
        self.stopped.set()

    def dispatch(self, action):
        self.events.put(('desktop', action))

    def start(self):
        if self.thread is not None:
            return
        self.stopped.clear()
        self.thread = threading.Thread(target=self._run, name='Tera tray', daemon=True)
        self.thread.start()

    def _setup(self, icon):
        try:
            if self.stopping.is_set():
                icon.stop()
                return
            icon.visible = True
            self.ready.set()
            self.dispatch('ready')
        except Exception as error:
            self.failure = type(error).__name__
            self.dispatch('failed')
            icon.stop()

    def _run(self):
        try:
            self.icon = self.factory(self.dispatch)
            if not self.stopping.is_set():
                self.icon.run(setup=self._setup)
        except Exception as error:
            self.failure = type(error).__name__  # Never retain exception text or URLs.
        finally:
            self.ready.clear()
            self.dispatch('stopped' if self.stopping.is_set() else 'failed')
            self.stopped.set()

    def stop(self):
        if self.stopping.is_set():
            return
        self.stopping.set()
        if self.thread is None:
            return
        def work():
            # Setup handles a stop requested before the native loop is ready.
            while not self.stopped.is_set():
                if not self.ready.wait(.05):
                    continue
                try:
                    self.icon.stop()
                except Exception:
                    self.dispatch('failed')
                break
        self.stop_thread = threading.Thread(target=work, name='Tera tray stop', daemon=True)
        self.stop_thread.start()

    def notify(self, message):
        if self.ready.is_set() and not self.stopping.is_set():
            try:
                self.icon.notify(message, 'Tera')
            except Exception:
                self.dispatch('notification_failed')


class Notifications:
    def __init__(self):
        self.previous = None
        self.seen = set()

    def observe(self, snapshot):
        previous, self.previous = self.previous, snapshot
        if previous is None:
            return []  # Restored history is not a new outcome.
        messages = []
        old = {j['id']: j for j in previous['jobs']}
        for job in snapshot['jobs']:
            key = (job['id'], job['attempt'], job['status'])
            if (job['status'] in {'failed', 'attention', 'login', 'restart'} and key not in self.seen
                    and old.get(job['id'], {}).get('status') != job['status']):
                self.seen.add(key)
                messages.append('Downloads need attention. Open Tera for details.')
        reason = snapshot['policy_hold']
        key = (snapshot['run_state']['id'], reason)
        if snapshot['running'] and not snapshot['active'] and reason in {'bytes', 'deadline', 'recovery'} and key not in self.seen:
            self.seen.add(key)
            messages.append('Run limit reached. Open Tera to start a new run.')
        if previous['running'] and not snapshot['running'] and snapshot['message'].startswith('Queue finished:'):
            messages.append('Downloads finished. Open Tera for results.')
        if snapshot['closing'] or snapshot['preferences'].get('notifications') is not True:
            return []
        return list(dict.fromkeys(messages))
