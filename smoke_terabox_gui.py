"""Opt-in native Tkinter smoke check: python smoke_terabox_gui.py.

Uses a withdrawn, task-owned window, synthetic streams and temporary files.
Never reads Firefox profiles/settings, connects to TeraBox or launches children.
"""
import io
import os
import tempfile
import time
import tkinter as tk
from pathlib import Path
from unittest.mock import patch

import terabox
from firefox_session import FirefoxProfile


BODY = b'synthetic video\n' * (256 * 1024)


class SyntheticResponse(io.BytesIO):
    status = 200
    headers = {'Content-Type': 'application/octet-stream', 'Content-Length': str(len(BODY))}

    def read(self, size):
        time.sleep(.04)
        return super().read(size)


class SyntheticClient(terabox.TeraBox):
    instances = []

    def __init__(self, cancel, status, profile, pause=None):
        super().__init__(cancel, status, pause=pause)
        self.instances.append(self)

    def find_videos(self, link):
        return [terabox.Video(name, len(BODY), str(index), 'https://terabox.com/synthetic')
                for index, name in enumerate(('first.mp4', 'second.mp4'))]

    def verify_login(self):
        self.cancel.wait(.15)
        self.check_cancel()
        return True

    def open(self, *args, **kwargs):
        self.check_cancel()
        return SyntheticResponse(BODY)


def main():
    print(f'Smoke PID {os.getpid()}; Python native Tk {tk.TkVersion}; withdrawn window; synthetic data only', flush=True)
    # The normal sandbox temp directory may not permit nested file access.
    with tempfile.TemporaryDirectory(prefix='tera-smoke-', dir=Path(__file__).parent) as folder:
        real_tk = tk.Tk
        errors, passed = [], []
        state = {'step': 'login', 'run': 0, 'deadline': time.monotonic() + 15}

        def create_root():
            root = real_tk()
            root.withdraw()

            def widgets(parent):
                for widget in parent.winfo_children():
                    yield widget
                    yield from widgets(widget)

            def fail(error):
                errors.append(error)
                for client in SyntheticClient.instances:
                    client.cancel.set()
                root.destroy()

            root.report_callback_exception = lambda kind, error, trace: fail(error)

            def drive():
                try:
                    assert time.monotonic() < state['deadline'], f'Smoke timeout: {state}'
                    controls = list(widgets(root))
                    buttons = {str(w.cget('text')): w for w in controls if w.winfo_class() == 'TButton'}
                    download = buttons['Download queue']
                    pause = buttons.get('Pause', buttons.get('Resume'))
                    progress = next(w for w in controls if w.winfo_class() == 'TProgressbar')
                    status_vars = [str(w.cget('textvariable')) for w in controls
                                   if w.winfo_class() == 'TLabel' and w.cget('textvariable')]
                    status = str(root.getvar(status_vars[-1]))
                    destination = next(w for w in controls if w.winfo_class() == 'TEntry')
                    step = state['step']
                    if step == 'finishing':
                        assert 'Paused.' not in status and 'Pausing' not in status, status
                    if step == 'login':
                        source = next(w for w in controls if w.winfo_class() == 'TCombobox')
                        source.current(1)
                        buttons['Check login'].invoke()
                        assert pause.instate(['disabled'])
                        state['step'] = 'checking'
                    elif step == 'checking':
                        assert pause.instate(['disabled'])
                        if not download.instate(['disabled']):
                            assert status == 'Login check finished.', status
                            next(w for w in controls if w.winfo_class() == 'TCombobox').set('No login')
                            state['step'] = 'start'
                    elif step == 'start':
                        assert pause.instate(['disabled'])
                        links = next(w for w in controls if w.winfo_class() == 'Text')
                        links.delete('1.0', 'end')
                        links.insert('1.0', 'https://terabox.com/s/1synthetic')
                        destination.delete(0, 'end')
                        destination.insert(0, str(Path(folder) / str(state['run'])))
                        download.invoke()
                        assert not pause.instate(['disabled'])
                        state['step'] = 'downloading'
                    elif step == 'downloading' and float(progress['value']) > 0:
                        pause.invoke()
                        assert 'Pausing' in root.getvar(status_vars[-1])
                        state['step'] = 'pausing'
                    elif step == 'pausing' and 'Paused.' in status:
                        state.update(step='paused', value=float(progress['value']), until=time.monotonic() + .2)
                    elif step == 'paused':
                        assert 'Paused.' in status, status
                        assert float(progress['value']) == state['value']
                        assert not buttons['Cancel'].instate(['disabled'])
                        if time.monotonic() >= state['until']:
                            if state['run'] == 0:
                                pause.invoke()
                                if not state.get('retoggled'):
                                    pause.invoke()
                                    state.update(step='pausing', retoggled=True)
                                else:
                                    state['step'] = 'finishing'
                            elif state['run'] == 1:
                                buttons['Cancel'].invoke()
                                state['step'] = 'cancelling'
                            else:
                                root.tk.call(root.protocol('WM_DELETE_WINDOW'))
                                state['step'] = 'closing'
                    elif step in ('finishing', 'cancelling') and not download.instate(['disabled']):
                        assert pause.instate(['disabled']) and str(pause['text']) == 'Pause'
                        saved = Path(folder) / str(state['run'])
                        if step == 'finishing':
                            assert '2 saved, 0 failed' in status, status
                            assert sorted(p.name for p in saved.iterdir()) == ['first.mp4', 'second.mp4']
                            assert all(p.read_bytes() == BODY for p in saved.iterdir())
                        else:
                            assert 'Cancelled' in status, status
                            assert list(saved.iterdir()) == []
                        passed.append(step)
                        state.update(step='start', run=state['run'] + 1)
                    if state['step'] == 'closing':
                        # The real poll handler destroys the window only after worker cleanup.
                        return
                    root.after(20, drive)
                except Exception as error:
                    fail(error)

            root.after(0, drive)
            root.after(16000, lambda: fail(AssertionError('Window did not close')))
            return root

        try:
            with patch('tkinter.Tk', side_effect=create_root), \
                 patch.object(terabox, 'profiles', return_value=[FirefoxProfile('Synthetic', Path(folder))]), \
                 patch.object(terabox, 'load_settings', return_value={'firefox_profile': None}), \
                 patch.object(terabox, 'save_settings', return_value=None), \
                 patch.object(terabox, 'TeraBox', SyntheticClient), \
                 patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('Unexpected network')):
                terabox.gui()
            assert not errors, errors
            assert passed == ['finishing', 'cancelling'], passed
            assert state['step'] == 'closing', state
            assert list((Path(folder) / '2').iterdir()) == []
            print('PASS: native Tkinter pause acknowledgement, stable paused progress, resume and exact files, cancel/reset, close cleanup')
        finally:
            for client in SyntheticClient.instances:
                client.cancel.set()


if __name__ == '__main__':
    main()
