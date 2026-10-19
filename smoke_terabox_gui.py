"""Opt-in native check: withdrawn task-owned Tk roots, synthetic streams only.

No profiles/settings from the user, shell opens, network, or child processes.
"""
import io
import os
import runpy
import tempfile
import time
import tkinter as tk
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import terabox
from app_state import StateError
from firefox_session import FirefoxProfile
from queue_manager import QueueManager
from tera_gui import TeraApp


BODY = b'synthetic video\n' * (128 * 1024)
LINK = 'https://terabox.com/s/1synthetic'


class SyntheticResponse(io.BytesIO):
    status = 200
    headers = {'Content-Type': 'application/octet-stream', 'Content-Length': str(len(BODY))}

    def read(self, size):
        time.sleep(.04)
        return super().read(size)


class SyntheticClient(terabox.TeraBox):
    calls = []
    fail_once = True

    def __init__(self, cancel, status, profile, pause=None):
        super().__init__(cancel, status, pause=pause)

    def find_videos(self, link):
        self.calls.append(('list', link))
        self.metadata = {'shareid': '123' if 'synthetic' in link else '456'}
        return [terabox.Video(name + '.mp4', len(BODY), name, 'https://terabox.com/synthetic')
                for name in ('first', 'broken', 'last')]

    def verify_login(self):
        self.cancel.wait(.05)
        self.check_cancel()

    def download(self, video, folder, progress):
        self.calls.append(('download', video.fid))
        if video.fid == 'broken' and type(self).fail_once:
            type(self).fail_once = False
            raise terabox.DownloadError('Synthetic unavailable file.')
        return super().download(video, folder, progress)

    def open(self, *args, **kwargs):
        self.check_cancel()
        return SyntheticResponse(BODY)


def main():
    print(f'Smoke PID {os.getpid()}; native Tk {tk.TkVersion}; withdrawn windows; synthetic data only', flush=True)
    SyntheticClient.calls, SyntheticClient.fail_once = [], True
    with tempfile.TemporaryDirectory(prefix='tera-smoke-', dir=Path(__file__).parent) as directory, \
         patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('Unexpected network')), \
         patch('tera_gui.profiles', side_effect=AssertionError('Unexpected real profile read')):
        base = Path(directory)
        owned, errors = [], []
        expires = time.monotonic() + 50

        def create():
            manager = QueueManager(base / 'state', SyntheticClient)
            root = tk.Tk()
            root.withdraw()
            root.report_callback_exception = lambda kind, error, trace: errors.append(error)
            app = TeraApp(root, manager, SyntheticClient, [FirefoxProfile('Synthetic', base / 'profile')])
            owned.append((root, manager, app))
            return root, manager, app

        def wait(predicate, label, seconds=5):
            deadline = min(expires, time.monotonic() + seconds)
            while time.monotonic() < deadline:
                root.update()
                assert not errors, errors
                if predicate():
                    return app.snapshot
                time.sleep(.01)
            raise AssertionError(f'{label}: {app.status.get()}; ' + repr([(j['status'], j['error']) for j in (app.snapshot or {}).get('jobs', [])]))

        def submit(link, folder, per_share=False):
            app.destination.set(str(folder))
            app.per_share.set(per_share)
            app.links_box.delete('1.0', 'end')
            app.links_box.insert('1.0', link)
            app.add_button.invoke()
            wait(lambda: app.pending_add is None and not app.snapshot['review_busy'], 'review completed')

        try:
            root, manager, app = create()
            wait(lambda: app.initialized, 'initialization')
            app.source_box.current(1)
            app.source_changed()
            app.check_button.invoke()
            wait(lambda: not app.login_busy, 'synthetic login')
            assert 'verified' in app.login_status.get()
            app.disconnect_button.invoke()
            app.destination.set(str(base / 'videos'))
            with patch('tera_gui.simpledialog.askstring', return_value='Movies'):
                app.favorite_button.invoke()
            wait(lambda: bool(app.snapshot['preferences'].get('favorites')), 'favorite save')
            app.destination.set(str(base / 'wrong'))
            app.favorite.set('Movies')
            app.choose_favorite()
            assert app.destination.get() == str(base / 'videos')
            with patch('app_state.protect', side_effect=StateError('Synthetic protection failure.')):
                app.links_box.insert('1.0', LINK)
                app.add_button.invoke()
                wait(lambda: app.pending_add is None and 'Synthetic protection failure.' in app.status.get(), 'failed save')
                assert not app.snapshot['jobs'] and not SyntheticClient.calls
                assert app.links_box.get('1.0', 'end').strip() == LINK
            submit(LINK + '\n' + LINK + '#view', base / 'videos')
            assert len(app.snapshot['jobs']) == 3 and len(SyntheticClient.calls) == 1
            assert '3 selected' in app.review_summary.get()
            second = app.snapshot['jobs'][1]['id']
            app.review_tree.selection_set(second)
            app.toggle_review(SimpleNamespace(keysym='space'))
            wait(lambda: app.snapshot['jobs'][1]['status'] == 'excluded', 'exclude video')
            assert '2 selected' in app.review_summary.get()
            app.download_button.invoke()
            wait(lambda: app.snapshot['received'] > 0, 'download start')
            app.pause_button.invoke()
            wait(lambda: app.snapshot['pause_acknowledged'], 'pause acknowledged')
            frozen = app.snapshot['received']
            until = time.monotonic() + .15
            wait(lambda: time.monotonic() >= until, 'paused wait')
            assert app.snapshot['received'] == frozen and app.snapshot['speed'] == 0
            assert app.snapshot['eta'] is None
            app.start_button.invoke()
            wait(lambda: not app.snapshot['paused'], 'resume')
            app.pause_button.invoke()
            wait(lambda: app.snapshot['pause_acknowledged'], 'rapid pause')
            submit(LINK.replace('synthetic', 'anotherx'), base / 'extra', per_share=True)
            additions = [j for j in app.snapshot['jobs'] if j['status'] == 'review']
            assert len(additions) == 3
            app.review_tree.selection_set(additions[0]['id'])
            with patch('tera_gui.simpledialog.askstring', return_value='approved.mp4'):
                app.rename_selected(app.review_tree)
            wait(lambda: any(j['output_name'] == 'approved.mp4' for j in app.snapshot['jobs']), 'rename selection')
            app.download_button.invoke()
            wait(lambda: sum(j['status'] == 'pending' for j in app.snapshot['jobs']) == 4, 'append selection')
            assert app.snapshot['paused']
            last = next(j for j in app.snapshot['jobs'] if j['id'] == additions[-1]['id'])
            app.queue_tree.selection_set(last['id'])
            app.configure_controls()
            app.up_button.invoke()
            wait(lambda: [j['id'] for j in app.snapshot['jobs']].index(last['id']) < [j['id'] for j in app.snapshot['jobs']].index(additions[1]['id']), 'reorder')
            app.remove_button.invoke()
            wait(lambda: not any(j['id'] == last['id'] for j in app.snapshot['jobs']), 'remove pending')
            app.start_button.invoke()
            wait(lambda: not app.snapshot['paused'], 'resume for boundary')
            app.boundary_button.invoke()
            wait(lambda: app.snapshot['paused'] and not app.snapshot['active'], 'finish-current hold')
            assert sum(j['status'] == 'completed' for j in app.snapshot['jobs']) == 1
            assert app.boundary_button.instate(['disabled']) and app.start_button['text'] == 'Resume'
            app.start_button.invoke()
            wait(lambda: not app.snapshot['running'] and not app.snapshot['active'] and any(j['status'] == 'failed' for j in app.snapshot['jobs']), 'remaining downloads')
            failed = next(j for j in app.snapshot['jobs'] if j['status'] == 'failed')
            app.history_tree.selection_set(failed['id'])
            app.configure_controls()
            app.retry_button.invoke()
            wait(lambda: any(j['status'] == 'pending' for j in app.snapshot['jobs']), 'retry queued')
            app.start_button.invoke()
            wait(lambda: not app.snapshot['running'] and not any(j['status'] in {'pending', 'downloading'} for j in app.snapshot['jobs']), 'retry complete')
            completed = [j for j in app.snapshot['jobs'] if j['status'] == 'completed']
            assert len(completed) == 4 and all(Path(j['path']).read_bytes() == BODY for j in completed)
            app.history_tree.selection_set(completed[0]['id'])
            app.configure_controls()
            with patch('tera_gui.os.startfile') as opened:
                app.reveal_button.invoke()
                opened.assert_called_once_with(completed[0]['folder'])
            submit(LINK.replace('terabox.com', 'terasharelink.com'), base / 'elsewhere')
            duplicates = [j for j in app.snapshot['jobs'] if 'Prior download' in j['error']]
            assert len(duplicates) == 2 and all(j['status'] == 'excluded' for j in duplicates)
            # The excluded first share video remains downloadable from an alias.
            reviews = [j for j in app.snapshot['jobs'] if j['status'] == 'review']
            assert len(reviews) == 1
            app.remove_selected(app.review_tree)  # no selected rows: harmless
            app.clear_button.invoke()
            wait(lambda: not any(j['status'] == 'completed' for j in app.snapshot['jobs']), 'history clear')
            assert all(Path(j['path']).read_bytes() == BODY for j in completed)
            # Existing target is held and user-approved folder correction works.
            pending = reviews[0]
            conflict = Path(pending['folder']) / pending['video']['name']
            conflict.parent.mkdir(parents=True)
            conflict.write_bytes(b'keep this file')
            app.download_button.invoke()
            wait(lambda: any(j['status'] == 'attention' for j in app.snapshot['jobs']), 'conflict hold')
            app.queue_tree.selection_set(pending['id'])
            with patch('tera_gui.filedialog.askdirectory', return_value=str(base / 'corrected')):
                app.change_destination(app.queue_tree)
            wait(lambda: any(j['id'] == pending['id'] and j['status'] == 'pending' for j in app.snapshot['jobs']), 'folder correction')
            app.start_button.invoke()
            wait(lambda: any(j['id'] == pending['id'] and j['status'] == 'completed' for j in app.snapshot['jobs']), 'corrected file')
            assert conflict.read_bytes() == b'keep this file'
            submit(LINK.replace('synthetic', 'restorex'), base / 'restore')
            app.download_button.invoke()
            wait(lambda: bool(app.snapshot['active']) and app.snapshot['received'] > 0, 'cancel transfer')
            app.cancel_button.invoke()
            wait(lambda: not app.snapshot['active'] and not app.snapshot['running'], 'cancel complete')
            assert not list(base.glob('restore/*.part'))
            assert app.pause_button.instate(['disabled']) and app.cancel_button.instate(['disabled'])
            submit(LINK.replace('synthetic', 'restore2x'), base / 'restore2')
            app.download_button.invoke()
            wait(lambda: bool(app.snapshot['active']), 'save/exit transfer')
            app.pause_button.invoke()
            wait(lambda: app.snapshot['pause_acknowledged'], 'save/exit pause')
            original = [j['id'] for j in app.snapshot['jobs']]
            root.tk.call(root.protocol('WM_DELETE_WINDOW'))
            wait(lambda: manager.closed.is_set() and app.destroyed, 'save/exit')
            manager.thread.join(1)
            calls = len(SyntheticClient.calls)
            root, manager, app = create()
            wait(lambda: app.initialized, 'restore')
            assert [j['id'] for j in app.snapshot['jobs']] == original
            assert len(SyntheticClient.calls) == calls and not app.snapshot['running']
            assert any(j['status'] == 'excluded' for j in app.snapshot['jobs'])
            assert app.snapshot['preferences']['favorites'][0]['name'] == 'Movies'
            assert not list(base.glob('restore2/*.part'))
            app.start_button.invoke()
            wait(lambda: not app.snapshot['running'] and not any(j['status'] in {'pending', 'downloading'} for j in app.snapshot['jobs']), 'restored queue')
            assert all(Path(j['path']).read_bytes() == BODY for j in app.snapshot['jobs'] if j['status'] == 'completed')
            app.close()
            wait(lambda: manager.closed.is_set() and app.destroyed, 'restored exit')
        finally:
            for owned_root, owned_manager, owned_app in owned:
                if not owned_manager.closed.is_set():
                    owned_manager.post('close')
                assert owned_manager.closed.wait(3), 'Owned coordinator did not close'
                owned_manager.thread.join(1)
                try:
                    owned_app.destroy()
                except tk.TclError:
                    pass

        real_tk, original_app = tk.Tk, TeraApp
        startup = {}
        def owned_root():
            root = real_tk()
            root.withdraw()
            return root
        def startup_app(root, manager):
            app = original_app(root, manager, available_profiles=[])
            startup['app'] = app
            deadline = time.monotonic() + 5
            def check():
                if app.initialized or time.monotonic() >= deadline:
                    startup['passed'] = app.initialized and not app.snapshot['jobs']
                    app.close()
                else:
                    root.after(20, check)
            root.after(20, check)
            return app
        with patch('sys.argv', ['terabox.py', '--data-dir', str(base / 'cli-state')]), \
             patch('tkinter.Tk', side_effect=owned_root), patch('tera_gui.TeraApp', side_effect=startup_app):
            runpy.run_path(str(Path(__file__).parent / 'terabox.py'), run_name='__main__')
        assert startup['passed']
        startup['app'].manager.thread.join(1)
        assert startup['app'].manager.closed.is_set()
        print('PASS: native review/checkbox selection, duplicate inputs/aliases, exclusions, per-share folders, rename/folder conflict correction')
        print('PASS: favorites, login isolation, failed-save recovery, queue append/edit, pause/rapid toggles, finish-current pause, cancel/reset')
        print('PASS: byte-exact files, history/retry/clear, reveal stub, save/exit, held restore, isolated real CLI startup/exit')


if __name__ == '__main__':
    main()
