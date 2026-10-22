"""Opt-in native check: brief mapped layout checks, then withdrawn synthetic flows.

No profiles/settings from the user, shell opens, network, or child processes.
"""
import io
from datetime import datetime, timedelta, timezone
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
from app_version import VERSION
from firefox_session import FirefoxProfile
from queue_manager import QueueManager
from tera_gui import TeraApp


BODY = b'synthetic video\n' * (128 * 1024)
LINK = 'https://terabox.com/s/1synthetic'


class SyntheticResponse(io.BytesIO):
    def __init__(self, body, offset=0):
        super().__init__(body[offset:])
        self.status = 206 if offset else 200
        self.headers = {'Content-Type': 'application/octet-stream', 'Content-Length': str(len(body) - offset), 'ETag': '"synthetic-v1"'}
        if offset:
            self.headers['Content-Range'] = f'bytes {offset}-{len(body)-1}/{len(body)}'

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

    def download(self, video, folder, progress, *, checkpoint=None, policy=None):
        self.calls.append(('download', video.fid))
        if video.fid == 'broken' and type(self).fail_once:
            type(self).fail_once = False
            raise terabox.DownloadError('Synthetic unavailable file.')
        if checkpoint and checkpoint.record['offset']:
            original = checkpoint.verification
            def verification(done, total):
                original(done, total)
                if done == 0 and total:
                    self.cancel.wait(.3)
                    self.check_cancel()
            checkpoint.verification = verification
        return super().download(video, folder, progress, checkpoint=checkpoint, policy=policy)

    def open(self, *args, **kwargs):
        self.check_cancel()
        headers = kwargs.get('headers') or {}
        offset = int(headers.get('Range', 'bytes=0-')[6:-1])
        self.calls.append(('range', offset))
        return SyntheticResponse(BODY, offset)


def check_run_limits(base):
    """A single bounded native scenario combining D with C's recovery path."""
    body = b'policy-data' * 512
    calls, owned, errors = [], [], []
    class TinyClient(SyntheticClient):
        fail_second = True
        def find_videos(self, link):
            self.metadata = {'shareid': '999'}
            return [terabox.Video(name + '.mp4', len(body), name, 'https://terabox.com/policy-' + name)
                    for name in ('first', 'second', 'third')]
        def download(self, video, folder, progress, *, checkpoint=None, policy=None):
            return terabox.TeraBox.download(self, video, folder, progress, checkpoint=checkpoint, policy=policy)
        def open(self, url, data=None, headers=None):
            self.check_cancel()
            name = url.rsplit('-', 1)[-1]
            offset = int((headers or {}).get('Range', 'bytes=0-')[6:-1])
            calls.append((name, offset))
            if name == 'second' and type(self).fail_second:
                type(self).fail_second = False
                raise terabox.DownloadError('Synthetic retry wait.', kind='transient', retry_after=.35)
            response = io.BytesIO(body[offset:])
            response.status = 206 if offset else 200
            response.headers = {'Content-Type': 'application/octet-stream', 'Content-Length': str(len(body) - offset), 'ETag': '"policy-' + name + '"'}
            if offset:
                response.headers['Content-Range'] = f'bytes {offset}-{len(body)-1}/{len(body)}'
            return response

    def create():
        manager = QueueManager(base / 'state', TinyClient)
        root = tk.Tk()
        root.withdraw()
        root.report_callback_exception = lambda kind, error, trace: errors.append(error)
        app = TeraApp(root, manager, TinyClient, available_profiles=[])
        owned.append((root, manager, app))
        return root, manager, app

    expires = time.monotonic() + 40
    def wait(predicate, label, seconds=4):
        deadline = min(expires, time.monotonic() + seconds)
        while time.monotonic() < deadline:
            root.update()
            assert not errors, errors
            if predicate(): return app.snapshot
            time.sleep(.01)
        raise AssertionError(f'Run limits {label}: {app.status.get()}; ' + repr(app.snapshot))

    local = datetime(2026, 10, 20, 8, 59, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    with patch('run_policy.local_now', return_value=local) as clock:
        try:
            root, manager, app = create()
            wait(lambda: app.initialized, 'startup')
            app.limit_speed.set('8')
            app.limit_bytes.set(str((len(body) + 1000) / (1024 * 1024)))
            app.window_start.set('09:00')
            app.window_end.set('10:00')
            app.window_enabled.set(True)
            app.apply_limits_button.invoke()
            wait(lambda: app.snapshot['run_options']['speed_bps'] == 8192, 'settings applied')
            assert 'UTC' in app.timezone_text.get()
            app.destination.set(str(base / 'videos'))
            app.links_box.insert('1.0', LINK)
            app.add_button.invoke()
            wait(lambda: app.pending_add is None and not app.snapshot['review_busy']
                 and len(app.snapshot['jobs']) == 3 and all(j['video'] for j in app.snapshot['jobs']), 'review')
            app.selected_button.invoke()
            wait(lambda: app.snapshot['policy_hold'] == 'schedule' and app.snapshot['running'], 'armed schedule')
            assert calls == [] and app.start_button.instate(['disabled'])
            assert not app.pause_button.instate(['disabled'])
            app.pause_button.invoke()
            wait(lambda: app.snapshot['manual_paused'], 'manual hold outside window')
            clock.return_value = local.replace(hour=9)
            wait(lambda: app.snapshot['policy_hold'] == '', 'window opening')
            assert calls == [] and app.snapshot['manual_paused']
            app.start_button.invoke()
            wait(lambda: app.snapshot['run_state']['bytes'] > 0, 'capped transfer')
            app.limit_speed.set(str(1 / 1024))
            app.apply_limits_button.invoke()
            wait(lambda: app.snapshot['run_options']['speed_bps'] == 1, 'hot cap change')
            app.pause_button.invoke()
            wait(lambda: app.snapshot['manual_paused'] and app.snapshot['pause_acknowledged'], 'pause while throttled')
            job = next(j for j in app.snapshot['jobs'] if j['id'] == app.snapshot['active'])
            prefix = job['checkpoint']['offset']
            assert prefix == job['received'] == app.snapshot['run_state']['bytes'] and prefix > 0
            app.close()
            wait(lambda: manager.closed.is_set() and app.destroyed, 'save/exit under cap')
            before = len(calls)
            root, manager, app = create()
            wait(lambda: app.initialized, 'restore')
            assert len(calls) == before and not app.snapshot['running']
            assert app.snapshot['run_state']['bytes'] == prefix and app.snapshot['run_options']['speed_bps'] == 1
            app.limit_speed.set('8')
            app.apply_limits_button.invoke()
            wait(lambda: app.snapshot['run_options']['speed_bps'] == 8192, 'restore cap')
            app.start_button.invoke()
            wait(lambda: app.snapshot['active'] and app.snapshot['received'] > prefix, 'validated capped continuation')
            app.boundary_button.invoke()
            clock.return_value = local.replace(hour=10)
            held = wait(lambda: not app.snapshot['active'] and app.snapshot['manual_paused'], 'boundary/window hold')
            assert [j['status'] for j in held['jobs']] == ['completed', 'pending', 'pending']
            assert held['run_state']['bytes'] == len(body) and calls[-1] == ('first', prefix)
            clock.return_value = local.replace(day=21, hour=9)
            wait(lambda: app.snapshot['policy_hold'] == '', 'next window with manual hold')
            assert app.snapshot['manual_paused'] and calls[-1] == ('first', prefix)
            app.start_button.invoke()
            wait(lambda: any(j['status'] == 'retry_wait' for j in app.snapshot['jobs']), 'bounded retry')
            clock.return_value = local.replace(day=21, hour=10)
            wait(lambda: app.snapshot['policy_hold'] == 'schedule' and not app.snapshot['active'], 'retry/window hold')
            app.pause_button.invoke()
            wait(lambda: app.snapshot['manual_paused'], 'manual retry hold')
            before = len(calls)
            clock.return_value = local.replace(day=22, hour=9)
            wait(lambda: app.snapshot['policy_hold'] == '', 'window cannot override retry pause')
            assert len(calls) == before
            app.start_button.invoke()
            held = wait(lambda: app.snapshot['policy_hold'] == 'bytes' and not app.snapshot['active'], 'byte budget boundary')
            assert [j['status'] for j in held['jobs']] == ['completed', 'completed', 'pending']
            assert held['run_state']['bytes'] == 2 * len(body) and held['jobs'][1]['cycle_attempts'] == 2
            assert app.start_button.instate(['disabled']) and not app.new_run_button.instate(['disabled'])
            app.window_enabled.set(False)
            app.apply_limits_button.invoke()
            wait(lambda: not app.snapshot['run_options']['schedule_enabled'], 'disable schedule without releasing budget')
            assert app.snapshot['policy_hold'] == 'bytes'
            app.new_run_button.invoke()
            finished = wait(lambda: all(j['status'] == 'completed' for j in app.snapshot['jobs']), 'explicit new run')
            assert finished['run_state']['bytes'] == len(body)
            assert all(Path(j['path']).read_bytes() == body for j in finished['jobs'])
            assert app.pause_button.instate(['disabled']) and app.cancel_button.instate(['disabled'])
            app.close()
            wait(lambda: manager.closed.is_set() and app.destroyed, 'clean exit')
        finally:
            for owned_root, owned_manager, owned_app in owned:
                if not owned_manager.closed.is_set(): owned_manager.post('close')
                assert owned_manager.closed.wait(4)
                owned_manager.thread.join(1)
                try: owned_app.destroy()
                except tk.TclError: pass


def check_layout(base, capture_dir=None):
    """Mapped windows catch clipping that invoking withdrawn widgets cannot detect."""
    checked = 0
    for scale in (4 / 3, 2):
        root = tk.Tk()
        root.withdraw()
        root.tk.call('tk', 'scaling', scale)
        manager = QueueManager(base / str(scale), SyntheticClient)
        app = TeraApp(root, manager, SyntheticClient, available_profiles=[])
        errors = []
        root.report_callback_exception = lambda kind, error, trace: errors.append(error)
        def wait(predicate):
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                root.update()
                assert not errors, errors
                if predicate():
                    return
                time.sleep(.01)
            raise AssertionError('Mapped quick-start flow timed out: ' + app.status.get())
        try:
            root.deiconify()
            wait(lambda: app.initialized)
            app.destination.set(str(base / str(scale) / 'videos'))
            app.links_box.insert('1.0', LINK)
            app.download_button.invoke()
            wait(lambda: app.snapshot['received'] > 0)
            assert app.notebook.select() == str(app.queue_page)
            assert not app.links_box.get('1.0', 'end').strip()
            app.pause_button.invoke()
            wait(lambda: app.snapshot['pause_acknowledged'])
            frozen = app.snapshot['received']
            for width, height in ((1020, 760), (880, 680)):
                root.geometry(f'{width}x{height}')
                root.deiconify()
                root.update()
                for page in app.notebook.tabs():
                    app.notebook.select(page)
                    root.update()
                    widgets = [app.start_button, app.pause_button, app.cancel_button]
                    if page == str(app.queue_page):
                        widgets += [app.download_button, app.add_button, app.file_actions_button]
                        assert app.queue_tree.identify_region(30, 10) == 'heading', 'Downloads heading hidden'
                        for identifier in app.queue_tree.get_children()[:3]:
                            box = app.queue_tree.bbox(identifier)
                            assert box and box[1] + box[3] <= app.queue_tree.winfo_height(), \
                                f'Filename row {box} clipped in height {app.queue_tree.winfo_height()} at {width}x{height}, scale {scale}'
                    elif page == str(app.review_page):
                        widgets += [app.selected_button, app.review_saved_button]
                    for widget in widgets:
                        assert widget.winfo_ismapped(), f'{widget["text"]} hidden at {width}x{height}, scale {scale}'
                        child = widget
                        while child is not root:
                            parent = child.master
                            assert (0 <= child.winfo_x() and 0 <= child.winfo_y()
                                    and child.winfo_x() + child.winfo_width() <= parent.winfo_width()
                                    and child.winfo_y() + child.winfo_height() <= parent.winfo_height()), \
                                f'{widget["text"]} clipped at {width}x{height}, scale {scale}'
                            child = parent
                    checked += 1
                assert app.snapshot['received'] == frozen
                if capture_dir and ((scale == 4 / 3 and width == 1020) or (scale == 2 and width == 880)):
                    import ctypes
                    from PIL import ImageGrab
                    ancestor = ctypes.windll.user32.GetAncestor
                    ancestor.argtypes, ancestor.restype = [ctypes.c_void_p, ctypes.c_uint], ctypes.c_void_p
                    app.notebook.select(app.queue_page)
                    root.update()
                    capture_dir.mkdir(parents=True, exist_ok=True)
                    name = 'windows-desktop.png' if scale == 4 / 3 else 'windows-small-large-text.png'
                    ImageGrab.grab(window=ancestor(root.winfo_id(), 2)).save(capture_dir / name)
            app.start_button.invoke()
            wait(lambda: not app.snapshot['running'] and not app.snapshot['active'])
            completed = [j for j in app.snapshot['jobs'] if j['status'] == 'completed']
            assert completed and all(Path(j['path']).read_bytes() == BODY for j in completed)
            assert app.pause_button.instate(['disabled']) and app.cancel_button.instate(['disabled'])
        finally:
            manager.post('close')
            assert manager.closed.wait(3), 'Layout test coordinator did not close'
            manager.thread.join(1)
            app.destroy()
    print(f'PASS: download and queue controls fully visible across {checked} mapped tab/size/scaling combinations', flush=True)


def main(workspace=None, capture_dir=None):
    print(f'Smoke PID {os.getpid()}; native Tk {tk.TkVersion}; brief mapped layout check then withdrawn windows; synthetic data only', flush=True)
    SyntheticClient.calls, SyntheticClient.fail_once = [], True
    with tempfile.TemporaryDirectory(prefix='tera-smoke-', dir=workspace or Path(__file__).parent) as directory, \
         patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('Unexpected network')), \
         patch('tera_gui.profiles', side_effect=AssertionError('Unexpected real profile read')):
        base = Path(directory)
        check_layout(base / 'layout', capture_dir)
        SyntheticClient.calls, SyntheticClient.fail_once = [], True
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
            previous = {j['id'] for j in app.snapshot['jobs']}
            app.destination.set(str(folder))
            app.per_share.set(per_share)
            app.links_box.delete('1.0', 'end')
            app.links_box.insert('1.0', link)
            app.add_button.invoke()
            # A save acknowledgement can precede the first discovery snapshot.
            wait(lambda: app.pending_add is None and not app.snapshot['review_busy']
                 and any(j['id'] not in previous for j in app.snapshot['jobs'])
                 and all(j['status'] not in {'unreviewed', 'reviewing'} for j in app.snapshot['jobs']
                         if j['id'] not in previous), 'review completed')

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
            app.review_search.set('FIRST')
            assert len(app.review_tree.get_children()) == 1
            app.choose_visible(False)
            wait(lambda: app.snapshot['jobs'][0]['status'] == 'excluded', 'filtered deselection')
            assert '2 selected' in app.review_summary.get()
            app.choose_visible(True)
            wait(lambda: app.snapshot['jobs'][0]['status'] == 'review', 'filtered selection')
            app.review_search.set('')
            app.review_sort.set('Name Z–A')
            assert app.review_tree.get_children()[0] == app.snapshot['jobs'][2]['id']
            app.review_sort.set('Original order')
            app.review_tree.selection_set([j['id'] for j in app.snapshot['jobs']])
            with patch('tera_gui.filedialog.askdirectory', return_value=str(base / 'videos')) as picker:
                app.change_destination(app.review_tree)
                assert picker.call_count == 1
            wait(lambda: 'Destinations updated' in app.status.get(), 'batch destination')
            second = app.snapshot['jobs'][1]['id']
            app.review_tree.selection_set(second)
            app.toggle_review(SimpleNamespace(keysym='space'))
            wait(lambda: app.snapshot['jobs'][1]['status'] == 'excluded', 'exclude video')
            assert '2 selected' in app.review_summary.get()
            app.selected_button.invoke()
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
            app.selected_button.invoke()
            wait(lambda: sum(j['status'] == 'pending' for j in app.snapshot['jobs']) == 4, 'append selection')
            assert app.snapshot['paused']
            last = next(j for j in app.snapshot['jobs'] if j['id'] == additions[-1]['id'])
            app.queue_tree.selection_set(last['id'])
            app.configure_controls()
            app.file_actions_menu.invoke(0)
            wait(lambda: [j['id'] for j in app.snapshot['jobs']].index(last['id']) < [j['id'] for j in app.snapshot['jobs']].index(additions[1]['id']), 'reorder')
            app.file_actions_menu.invoke(2)
            wait(lambda: not any(j['id'] == last['id'] for j in app.snapshot['jobs']), 'remove pending')
            app.start_button.invoke()
            wait(lambda: not app.snapshot['paused'], 'resume for boundary')
            app.file_actions_menu.invoke(6)
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
            app.history_search.set('APPROVED')
            assert len(app.history_tree.get_children()) == 1
            app.history_sort.set('Newest first')
            app.history_search.set('')
            with patch('tera_gui.filedialog.asksaveasfilename', return_value=str(base / 'diagnostics.json')):
                app.diagnostics_button.invoke()
            wait(lambda: 'Diagnostics saved' in app.status.get(), 'diagnostics export')
            report = (base / 'diagnostics.json').read_text(encoding='utf-8')
            assert VERSION in report and 'completed' in report
            assert LINK not in report and 'approved.mp4' not in report and str(base) not in report
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
            app.selected_button.invoke()
            wait(lambda: any(j['status'] == 'attention' for j in app.snapshot['jobs']), 'conflict hold')
            app.queue_tree.selection_set(pending['id'])
            with patch('tera_gui.filedialog.askdirectory', return_value=str(base / 'corrected')):
                app.change_destination(app.queue_tree)
            wait(lambda: any(j['id'] == pending['id'] and j['status'] == 'pending' for j in app.snapshot['jobs']), 'folder correction')
            app.start_button.invoke()
            wait(lambda: any(j['id'] == pending['id'] and j['status'] == 'completed' for j in app.snapshot['jobs']), 'corrected file')
            assert conflict.read_bytes() == b'keep this file'
            submit(LINK.replace('synthetic', 'restorex'), base / 'restore')
            app.selected_button.invoke()
            wait(lambda: bool(app.snapshot['active']) and app.snapshot['received'] > 0, 'cancel transfer')
            app.cancel_button.invoke()
            wait(lambda: not app.snapshot['active'] and not app.snapshot['running'], 'cancel complete')
            assert not list(base.glob('restore/*.part'))
            assert app.pause_button.instate(['disabled']) and app.cancel_button.instate(['disabled'])
            submit(LINK.replace('synthetic', 'restore2x'), base / 'restore2')
            app.selected_button.invoke()
            wait(lambda: bool(app.snapshot['active']) and app.snapshot['received'] > 0, 'save/exit transfer')
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
            assert list(base.glob('restore2/.tera-*.part'))
            assert any(j['checkpoint'].get('offset', 0) > 0 for j in app.snapshot['jobs'])
            app.start_button.invoke()
            wait(lambda: app.status.get().startswith('Checking saved download:'), 'native verification progress')
            assert app.snapshot['speed'] == 0
            wait(lambda: not app.snapshot['running'] and not any(j['status'] in {'pending', 'downloading'} for j in app.snapshot['jobs']), 'restored queue')
            assert any(kind == 'range' and value > 0 for kind, value in SyntheticClient.calls[calls:])
            assert all(Path(j['path']).read_bytes() == BODY for j in app.snapshot['jobs'] if j['status'] == 'completed')
            app.clear_button.invoke()
            wait(lambda: not any(j['status'] == 'completed' for j in app.snapshot['jobs']), 'clear receipts before restart scenario')
            submit(LINK.replace('synthetic', 'restartx'), base / 'restart-check')
            candidates = [j for j in app.snapshot['jobs'] if j['status'] == 'review']
            for candidate in candidates[1:]:
                app.review_tree.selection_set(candidate['id'])
                app.toggle_review(SimpleNamespace(keysym='space'))
            wait(lambda: sum(j['status'] == 'review' for j in app.snapshot['jobs']) == 1, 'restart scenario selection')
            identifier = candidates[0]['id']
            def interrupt_then_ignore(client, *args, **kwargs):
                response = SyntheticResponse(BODY)
                if not (kwargs.get('headers') or {}).get('Range'):
                    read = response.read
                    def interrupted(size):
                        if response.tell() >= 512 * 1024:
                            raise terabox.DownloadError('Synthetic connection interruption.', kind='transient', retry_after=.01)
                        return read(size)
                    response.read = interrupted
                return response
            with patch.object(SyntheticClient, 'open', autospec=True, side_effect=interrupt_then_ignore):
                app.selected_button.invoke()
                wait(lambda: any(j['id'] == identifier and j['status'] == 'restart' for j in app.snapshot['jobs']), 'rejected HTTP continuation', seconds=7)
            app.queue_tree.selection_set(identifier)
            app.configure_controls()
            assert app.start_button.instate(['disabled']) and not app.restart_button.instate(['disabled'])
            saved = next(j for j in app.snapshot['jobs'] if j['id'] == identifier)
            partial = Path(saved['folder']) / ('.tera-' + saved['checkpoint']['token'] + '.part')
            assert partial.read_bytes() == BODY[:512 * 1024]
            app.restart_button.invoke()
            wait(lambda: any(j['id'] == identifier and j['status'] == 'pending' and not j['checkpoint'] for j in app.snapshot['jobs']), 'explicit restart selection')
            assert not partial.exists()
            app.start_button.invoke()
            wait(lambda: any(j['id'] == identifier and j['status'] == 'completed' for j in app.snapshot['jobs']), 'explicit full restart')
            saved = next(j for j in app.snapshot['jobs'] if j['id'] == identifier)
            assert Path(saved['path']).read_bytes() == BODY
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
            terabox.main()
        assert startup['passed']
        startup['app'].manager.thread.join(1)
        assert startup['app'].manager.closed.is_set()
        check_run_limits(base / 'run-limits')
        print('PASS: native review/checkbox selection, duplicate inputs/aliases, exclusions, per-share folders, rename/folder conflict correction')
        print('PASS: favorites, login isolation, failed-save recovery, queue append/edit, pause/rapid toggles, finish-current pause, cancel/reset')
        print('PASS: byte-exact files, history/retry/clear, reveal stub, save/exit, held restore, isolated real CLI startup/exit')
        print('PASS: retained durable bytes, validated Range continuation, bounded retry, rejected 200 response, explicit Restart control')
        print('PASS: native cap changes/throttle pause, schedule/manual precedence, boundary hold, retry/window interaction, byte budget, explicit new run, save/restore and exact files')


if __name__ == '__main__':
    main()
