"""Opt-in native Tkinter smoke check: python smoke_terabox_gui.py.

Uses a withdrawn, task-owned window, synthetic streams and temporary files.
Never reads Firefox profiles/settings, connects to TeraBox or launches children.
"""
import io
import os
import tempfile
import time
import traceback
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
    from queue_manager import QueueManager
    from app_state import StateError
    from tera_gui import TeraApp
    from terabox import DownloadError

    class ProductClient(SyntheticClient):
        calls = []
        fail_once = True

        def find_videos(self, link):
            self.calls.append(('list', link))
            return [terabox.Video(name + '.mp4', len(BODY), name, 'https://terabox.com/synthetic')
                    for name in ('first', 'broken', 'last')]

        def download(self, video, folder, progress=lambda done, total: None):
            self.calls.append(('download', video.fid))
            if video.fid == 'broken' and type(self).fail_once:
                type(self).fail_once = False
                raise DownloadError('Synthetic unavailable file.')
            return super().download(video, folder, progress)

    with tempfile.TemporaryDirectory(prefix='tera-smoke-', dir=Path(__file__).parent) as folder:
        base = Path(folder)
        errors = []
        state = {'step': 'login', 'again': False}
        original_ids = []
        injection = [None]
        sources = [FirefoxProfile('Synthetic', base / 'profile')]
        calls_before_restore = None
        for reopen in (False, True):
            manager = QueueManager(base / 'state', ProductClient)
            root = tk.Tk()
            root.withdraw()
            app = TeraApp(root, manager, ProductClient, available_profiles=sources)
            deadline = time.monotonic() + 20
            if reopen:
                state['step'] = 'restored'

            def fail(error):
                errors.append((state['step'], repr(error), traceback.format_exc()))
                if injection[0] is not None:
                    injection[0].stop()
                    injection[0] = None
                manager.post('close')
                manager.closed.wait(3)
                root.destroy()

            root.report_callback_exception = lambda kind, error, trace: fail(error)

            def drive():
                try:
                    assert time.monotonic() < deadline, f'Smoke timeout: {state}'
                    if not app.initialized:
                        root.after(20, drive)
                        return
                    snapshot = app.snapshot
                    step = state['step']
                    if step == 'login':
                        app.source_box.current(1)
                        app.source_changed()
                        app.check_button.invoke()
                        assert app.pause_button.instate(['disabled'])
                        state['step'] = 'checking'
                    elif step == 'checking' and not app.login_busy:
                        assert 'verified' in app.login_status.get()
                        app.disconnect_button.invoke()
                        app.destination.set(str(base / 'videos'))
                        with patch('tera_gui.simpledialog.askstring', return_value='Movies'):
                            app.favorite_button.invoke()
                        state['step'] = 'favorite'
                    elif step == 'favorite' and snapshot['preferences'].get('favorites'):
                        app.destination.set(str(base / 'wrong'))
                        app.favorite.set('Movies')
                        app.choose_favorite()
                        assert app.destination.get() == str(base / 'videos')
                        injection[0] = patch('app_state.protect', side_effect=StateError('Synthetic link protection failure.'))
                        injection[0].start()
                        app.links_box.insert('1.0', 'https://terabox.com/s/1synthetic')
                        app.add_button.invoke()
                        state['step'] = 'save_failed'
                    elif step == 'save_failed' and app.pending_add is None and 'Synthetic link protection failure.' in app.status.get():
                        assert app.links_box.get('1.0', 'end').strip() == 'https://terabox.com/s/1synthetic'
                        assert not manager.request('snapshot')['jobs']
                        assert ProductClient.calls == []
                        injection[0].stop()
                        injection[0] = None
                        app.add_button.invoke()
                        state['step'] = 'queued'
                    elif step == 'queued' and snapshot['jobs']:
                        app.start_button.invoke()
                        state['step'] = 'downloading'
                    elif step == 'downloading' and snapshot['received'] > 0:
                        app.pause_button.invoke()
                        assert 'Pausing' in app.status.get()
                        state['step'] = 'pausing'
                    elif step == 'pausing' and snapshot['pause_acknowledged']:
                        assert snapshot['paused']
                        assert snapshot['speed'] == 0 and snapshot['eta'] is None
                        state.update(step='paused', received=snapshot['received'], until=time.monotonic() + .15)
                    elif step == 'paused':
                        assert snapshot['received'] == state['received']
                        assert snapshot['speed'] == 0
                        if time.monotonic() >= state['until']:
                            if state['again']:
                                app.start_button.invoke()
                                state['step'] = 'finishing'
                            else:
                                last = next(j for j in snapshot['jobs'] if j['video'] and j['video']['fid'] == 'last')
                                app.queue_tree.selection_set(last['id'])
                                app.configure_controls()
                                app.up_button.invoke()
                                app.destination.set(str(base / 'extra'))
                                app.links_box.insert('1.0', 'https://terabox.com/s/1anotherx')
                                app.add_button.invoke()
                                state['step'] = 'editing'
                    elif step == 'editing' and len(snapshot['jobs']) == 4:
                        added = next(j for j in snapshot['jobs'] if not j['video'])
                        app.queue_tree.selection_set(added['id'])
                        app.configure_controls()
                        app.remove_button.invoke()
                        state['step'] = 'removed'
                    elif step == 'removed' and len(snapshot['jobs']) == 3:
                        app.links_box.insert('1.0', 'https://terabox.com/s/1anotherx')
                        app.add_button.invoke()
                        state['step'] = 'added'
                    elif step == 'added' and len(snapshot['jobs']) == 4:
                        app.start_button.invoke()
                        state['step'] = 'resume_then_pause'
                    elif step == 'resume_then_pause' and not snapshot['paused']:
                        app.pause_button.invoke()
                        state.update(step='pausing', again=True)
                    elif step == 'finishing' and not snapshot['running'] and not snapshot['active']:
                        assert sum(j['status'] == 'completed' for j in snapshot['jobs']) == 5
                        failed = [j for j in snapshot['jobs'] if j['status'] == 'failed']
                        assert len(failed) == 1
                        assert [c[1] for c in ProductClient.calls if c[0] == 'download'][:3] == ['first', 'last', 'broken']
                        app.history_tree.selection_set(failed[0]['id'])
                        app.configure_controls()
                        app.retry_button.invoke()
                        state['step'] = 'retry_ready'
                    elif step == 'retry_ready' and any(j['status'] == 'pending' for j in snapshot['jobs']):
                        assert not snapshot['running']
                        app.start_button.invoke()
                        state['step'] = 'retried'
                    elif step == 'retried' and not snapshot['running'] and not snapshot['active'] and not any(j['status'] == 'pending' for j in snapshot['jobs']):
                        assert len(snapshot['jobs']) == 6
                        assert all(j['status'] == 'completed' and Path(j['path']).read_bytes() == BODY for j in snapshot['jobs']), [(j['status'], j['error']) for j in snapshot['jobs']]
                        app.history_tree.selection_set(snapshot['jobs'][0]['id'])
                        app.configure_controls()
                        with patch('tera_gui.os.startfile') as opened:
                            app.reveal_button.invoke()
                            opened.assert_called_once_with(str(base / 'videos'))
                        app.clear_button.invoke()
                        state['step'] = 'cleared'
                    elif step == 'cleared' and not snapshot['jobs']:
                        assert len(list(base.glob('videos/*.mp4'))) == 3
                        assert len(list(base.glob('extra/*.mp4'))) == 3
                        app.destination.set(str(base / 'restore'))
                        app.links_box.insert('1.0', 'https://terabox.com/s/1restorex')
                        app.add_button.invoke()
                        state['step'] = 'exit_ready'
                    elif step == 'exit_ready' and snapshot['jobs']:
                        app.start_button.invoke()
                        state['step'] = 'exit_transfer'
                    elif step == 'exit_transfer' and snapshot['received'] > 0:
                        app.pause_button.invoke()
                        state['step'] = 'exit_paused'
                    elif step == 'exit_paused' and snapshot['pause_acknowledged']:
                        original_ids[:] = [j['id'] for j in snapshot['jobs']]
                        root.tk.call(root.protocol('WM_DELETE_WINDOW'))
                        state['step'] = 'closing'
                        return
                    elif step == 'restored':
                        assert [j['id'] for j in snapshot['jobs']] == original_ids
                        assert all(j['status'] == 'pending' and j['received'] == 0 for j in snapshot['jobs'])
                        assert not snapshot['running'] and not snapshot['active']
                        assert len(ProductClient.calls) == calls_before_restore
                        assert app.destination.get() == str(base / 'restore')
                        assert snapshot['preferences']['favorites'][0]['name'] == 'Movies'
                        assert snapshot['preferences']['firefox_profile'] is None
                        assert not list(base.glob('restore/*.part'))
                        app.start_button.invoke()
                        state['step'] = 'restore_started'
                    elif step == 'restore_started' and not snapshot['running'] and all(j['status'] == 'completed' for j in snapshot['jobs']):
                        assert len(snapshot['jobs']) == 3
                        assert all(Path(j['path']).read_bytes() == BODY for j in snapshot['jobs'])
                        root.tk.call(root.protocol('WM_DELETE_WINDOW'))
                        state['step'] = 'done'
                        return
                    root.after(20, drive)
                except Exception as error:
                    fail(error)

            root.after(20, drive)
            root.after(21000, lambda: fail(AssertionError('Window did not close')))
            with patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('Unexpected network')):
                root.mainloop()
            if not manager.closed.wait(3):
                manager.post('close')
                assert manager.closed.wait(3)
            assert not errors, errors
            manager.thread.join(1)
            assert not manager.thread.is_alive()
            calls_before_restore = len(ProductClient.calls)
        assert state['step'] == 'done'
        # Exercise the real command-line entry point with an isolated data directory.
        import runpy
        real_tk, original_app = tk.Tk, TeraApp
        startup = {'app': None, 'passed': False}
        def owned_root():
            root = real_tk()
            root.withdraw()
            return root
        def startup_app(root, manager):
            app = original_app(root, manager, available_profiles=[])
            startup['app'] = app
            expires = time.monotonic() + 5
            def check():
                if app.initialized:
                    assert not app.snapshot['running'] and not app.snapshot['jobs']
                    startup['passed'] = True
                    app.close()
                elif time.monotonic() >= expires:
                    errors.append('Isolated CLI startup did not initialize')
                    app.close()
                else:
                    root.after(20, check)
            root.after(20, check)
            return app
        with patch('sys.argv', ['terabox.py', '--data-dir', str(base / 'cli-state')]), \
             patch('tkinter.Tk', side_effect=owned_root), \
             patch('tera_gui.TeraApp', side_effect=startup_app), \
             patch('tera_gui.profiles', side_effect=AssertionError('Unexpected real profile read')), \
             patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('Unexpected network')):
            runpy.run_path(str(Path(__file__).parent / 'terabox.py'), run_name='__main__')
        assert startup['passed'] and not errors, errors
        startup['app'].manager.thread.join(1)
        assert startup['app'].manager.closed.is_set()
        print('PASS: native Tkinter login isolation, favorites, queue edits, pause/rapid toggles, exact files, history/retry, reveal stub, save/exit and held restore')
        print('PASS: real command-line entry point, isolated data directory and native Tk startup/exit without profile or network access')
        print('PASS: injected protection failure keeps pasted links and starts no network work; explicit recovery succeeds')


if __name__ == '__main__':
    main()
