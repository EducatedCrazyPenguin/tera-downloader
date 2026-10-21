"""Explicit, bounded Windows check: owned Tk/tray, synthetic state, no providers.

May briefly show the owned Tera window. Notifications are intercepted. The real
pythonw launcher uses empty APPDATA/LOCALAPPDATA; only its PID receives WM_CLOSE.
"""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import tkinter as tk
from unittest.mock import patch

from app_state import StateError, StateStore
from desktop_integration import Desktop, available, make_icon
from queue_manager import QueueManager
from smoke_terabox_gui import BODY, LINK, SyntheticClient
from tera_gui import TeraApp


def tray_check(base):
    errors, messages, owned = [], [], []
    def factory(events):
        def icon_factory(dispatch):
            icon = make_icon(dispatch)
            icon.notify = lambda message, title: messages.append((message, title))
            return icon
        return Desktop(events, icon_factory)
    def create(directory, desktop_factory=factory):
        root = tk.Tk()
        root.withdraw()
        root.report_callback_exception = lambda kind, error, trace: errors.append(error)
        manager = QueueManager(directory, SyntheticClient)
        app = TeraApp(root, manager, SyntheticClient, available_profiles=[], desktop_factory=desktop_factory)
        owned.append((root, manager, app))
        return root, manager, app
    deadline = time.monotonic() + 25
    def wait(predicate, label):
        until = min(deadline, time.monotonic() + 5)
        while time.monotonic() < until:
            if not app.destroyed:
                root.update()
            assert not errors, errors
            if predicate(): return
            time.sleep(.01)
        raise AssertionError(label + ': ' + app.status.get() + '; tray=' + app.desktop_status.get() + '; failure=' + str(app.desktop.failure))
    with patch('tera_gui.profiles', side_effect=AssertionError('Real profiles forbidden')), \
         patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('Network forbidden')):
        try:
            root, manager, app = create(base / 'tray')
            wait(lambda: app.initialized, 'startup')
            assert app.desktop.thread is None and not app.notify_enabled.get()
            app.notify_check.invoke()
            wait(lambda: app.snapshot['preferences'].get('notifications') is True and app.desktop.ready.is_set(), 'opt-in')
            app.tray_button.invoke()
            wait(lambda: app.tray_hidden, 'hide after native registration')
            assert root.state() == 'withdrawn'
            icon = app.desktop.icon
            icon.menu.items[0](icon)
            wait(lambda: not app.tray_hidden, 'tray restore')
            assert root.state() == 'normal'
            app.tray_button.invoke()
            wait(lambda: app.tray_hidden, 'second hide')
            manager.request('review', links=[LINK], folder=str(base / 'videos'), profile=None)
            wait(lambda: not app.snapshot['review_busy'] and bool(app.snapshot['jobs']), 'review')
            manager.post('select', job_ids=[app.snapshot['jobs'][0]['id']])
            wait(lambda: bool(app.snapshot['active']), 'active transfer')
            icon.menu.items[1](icon)
            wait(lambda: app.snapshot['pause_acknowledged'], 'tray pause')
            count = app.snapshot['received']
            time.sleep(.12)
            root.update()
            assert app.snapshot['received'] == count
            icon.menu.items[2](icon)
            wait(lambda: not app.snapshot['manual_paused'], 'tray resume')
            wait(lambda: app.snapshot['jobs'][0]['status'] == 'completed' and not app.snapshot['running'], 'completion')
            assert Path(app.snapshot['jobs'][0]['path']).read_bytes() == BODY
            wait(lambda: len(messages) == 1, 'one generic notification')
            assert messages == [('Downloads finished. Open Tera for results.', 'Tera')]
            manager.request('select', job_ids=[j['id'] for j in app.snapshot['jobs'] if j['status'] == 'excluded'])
            wait(lambda: bool(app.snapshot['active']), 'cancel transfer')
            icon.menu.items[3](icon)
            wait(lambda: not app.snapshot['active'] and not app.snapshot['running'], 'tray cancel')
            assert app.pause_button.instate(['disabled']) and app.cancel_button.instate(['disabled'])
            icon.menu.items[4](icon)
            wait(lambda: app.destroyed, 'tray save and exit')
            assert app.desktop.stopped.is_set() and manager.closed.is_set()
            app.desktop.thread.join(1)
            assert not app.desktop.thread.is_alive()
            assert not ctypes.windll.user32.IsWindow(icon._hwnd)
            with StateStore(base / 'tray') as saved:
                assert saved.load_preferences()['notifications'] is True

            from pystray._util import win32
            original_notify = win32.Shell_NotifyIcon
            def reject_registration(code, data):
                return False if code == win32.NIM_ADD else original_notify(code, data)
            with patch.object(win32, 'Shell_NotifyIcon', side_effect=reject_registration):
                root, manager, app = create(base / 'failure')
                wait(lambda: app.initialized, 'failure startup')
                app.tray_button.invoke()
                wait(lambda: not app.desktop_supported, 'Windows registration failure')
                assert not app.tray_hidden and not app.tray_pending
                assert app.tray_button.instate(['disabled'])
                assert not app.closing
                app.close()
                wait(lambda: app.destroyed, 'failed tray X exit')
        finally:
            for owned_root, owned_manager, owned_app in owned:
                owned_app.desktop.stop()
                owned_manager.post('close')
                assert owned_manager.closed.wait(3)
                assert owned_app.desktop.stopped.wait(3)
                owned_manager.thread.join(1)
                owned_app.destroy()


def launcher_check(base):
    """Exercise the actual .pyw file, its environment handoff, and owned WM_CLOSE."""
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    def window(pid):
        found = []
        @callback_type
        def inspect(hwnd, unused):
            owner = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if owner.value == pid:
                title = ctypes.create_unicode_buffer(128)
                user32.GetWindowTextW(hwnd, title, len(title))
                if title.value == 'Tera — download queue' and user32.IsWindowVisible(hwnd):
                    found.append(hwnd)
            return True
        user32.EnumWindows(inspect, 0)
        return found[0] if found else None
    base.mkdir()
    environment = os.environ.copy()
    environment.update(APPDATA=str(base / 'empty-roaming'), LOCALAPPDATA=str(base / 'empty-local'), TMP=str(base), TEMP=str(base))
    pythonw = Path(sys.base_prefix) / 'pythonw.exe'
    state = base / 'state'
    parent = None
    handle = None
    pid = None
    with (base / 'process.log').open('w') as log:
        try:
            command = [sys.executable] if getattr(sys, 'frozen', False) else [str(pythonw), str(Path(__file__).with_name('Start Tera.pyw'))]
            environment.update(TERA_DATA_DIR=str(state), PYTHONPATH='', PYTHONHOME='')
            if getattr(sys, 'frozen', False):
                environment['PATH'] = os.environ.get('SystemRoot', r'C:\Windows') + r'\System32'
            parent = subprocess.Popen(command + ['--data-dir', str(state)],
                                      cwd=str(Path(__file__).parent), env=environment, stdin=subprocess.DEVNULL,
                                      stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
            print(f'Owned quiet launcher PID: {parent.pid}', flush=True)
            until = time.monotonic() + 8
            hwnd = None
            while time.monotonic() < until:
                if (state / 'launcher.log').exists():
                    text = (state / 'launcher.log').read_text()
                    matches = re.findall(r'pid=(\d+) started', text)
                    if matches:
                        pid = int(matches[-1])
                        hwnd = window(pid)
                        if hwnd: break
                time.sleep(.03)
            assert hwnd and pid, 'Quiet launcher did not create the isolated Tera window'
            print(f'Owned quiet app PID: {pid}', flush=True)
            handle = kernel32.OpenProcess(0x100000, False, pid)
            assert handle
            # The first process hands off before any queue store is opened.
            if getattr(sys, 'frozen', False):
                assert pid == parent.pid
            else:
                assert parent.wait(timeout=2) == 0 and pid != parent.pid
            try:
                with StateStore(state):
                    raise AssertionError('Running launcher did not own its state lock')
            except StateError:
                pass
            user32.PostMessageW(hwnd, 0x10, 0, 0)
            assert kernel32.WaitForSingleObject(handle, 5000) == 0, 'Quiet app did not exit on owned WM_CLOSE'
            assert 'exited' in (state / 'launcher.log').read_text()
            assert 'failed' not in (state / 'launcher.log').read_text()
            with StateStore(state) as saved:
                assert saved.load_jobs() == []
        finally:
            if pid and handle and kernel32.WaitForSingleObject(handle, 0) != 0:
                hwnd = window(pid)
                if hwnd: user32.PostMessageW(hwnd, 0x10, 0, 0)
                if kernel32.WaitForSingleObject(handle, 3000) != 0:
                    # Only this synthetic, task-owned process is eligible for cleanup.
                    kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
                    cleanup = kernel32.OpenProcess(1, False, pid)
                    if cleanup:
                        kernel32.TerminateProcess(cleanup, 1)
                        kernel32.CloseHandle(cleanup)
            if handle: kernel32.CloseHandle(handle)
            if parent and parent.poll() is None:
                parent.kill()
                parent.wait(2)


def main(workspace=None):
    assert os.name == 'nt' and available(), 'Run with the optional desktop environment on Windows'
    print(f'Owned desktop smoke PID: {os.getpid()}', flush=True)
    with tempfile.TemporaryDirectory(prefix='tera-desktop-', dir=workspace or Path(__file__).parent) as folder:
        base = Path(folder)
        tempfile.tempdir = str(base)
        tray_check(base)
        launcher_check(base / 'launcher')
    print('PASS: native tray readiness/hide/restore/pause/resume/cancel/reset/exit; one mocked generic notification; failed backend stays accessible')
    print('PASS: real quiet packaged startup, isolated state owner, WM_CLOSE save/exit, no remaining owned process' if getattr(sys, 'frozen', False)
          else 'PASS: real quiet .pyw / pythonw handoff, isolated state owner, WM_CLOSE save/exit, no remaining owned window/process')


if __name__ == '__main__':
    main()
