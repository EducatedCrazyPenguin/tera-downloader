import io
import queue
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from queue_manager import QueueManager, SpeedMeter
from app_state import StateError, StateStore
from firefox_session import FirefoxProfile
from terabox import DownloadError, TeraBox, Video


LINK = 'https://terabox.com/s/1synthetic'


class Body(io.BytesIO):
    status = 200
    headers = {'Content-Type': 'application/octet-stream', 'Content-Length': '5'}


class Client(TeraBox):
    calls = []
    release = threading.Event()
    fail = set()

    def __init__(self, cancel, status, profile, pause=None):
        super().__init__(cancel, status, pause=pause)

    def find_videos(self, link):
        self.calls.append(('list', link))
        return [Video(name + '.mp4', 5, name, 'https://terabox.com/synthetic')
                for name in ('first', 'second', 'third')]

    def download(self, video, folder, progress, *, checkpoint=None):
        self.calls.append(('download', video.fid))
        while not self.release.wait(.01):
            self.check_cancel()
        if video.fid in self.fail:
            raise DownloadError('Synthetic file unavailable.')
        return super().download(video, folder, progress, checkpoint=checkpoint)

    def open(self, *args, **kwargs):
        self.check_cancel()
        return Body(b'movie')


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.folder = Path(self.directory.name)
        Client.calls = []
        Client.fail = set()
        Client.release = threading.Event()
        self.manager = self.make_manager()

    def make_manager(self, factory=Client):
        manager = QueueManager(self.folder / 'state', client_factory=factory)
        self.addCleanup(self.stop_manager, manager)
        self.assertTrue(manager.ready.wait(3))
        if manager.startup_error:
            raise manager.startup_error
        return manager

    def stop_manager(self, manager):
        if not manager.closed.is_set():
            manager.post('close')
            self.assertTrue(manager.closed.wait(3), 'Coordinator did not close')

    def wait_for(self, predicate):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            snapshot = self.manager.request('snapshot')
            if predicate(snapshot):
                return snapshot
            try:
                self.manager.events.get(timeout=.05)
            except queue.Empty:
                pass
        self.fail('Queue did not reach the expected state')

    def add_and_resolve(self):
        self.manager.request('add', links=[LINK], folder=str(self.folder / 'videos'), profile=None)
        self.manager.request('start')
        return self.wait_for(lambda s: s['active'] and any(c[0] == 'download' for c in Client.calls))

    def test_restore_is_held_without_authentication_or_network(self):
        self.manager.request('add', links=[LINK], folder=str(self.folder / 'videos'), profile=None)
        saved = self.manager.request('snapshot')['jobs'][0]['id']
        self.stop_manager(self.manager)
        self.manager = self.make_manager()
        restored = self.manager.request('snapshot')
        self.assertFalse(restored['running'])
        self.assertEqual(restored['jobs'][0]['id'], saved)
        self.assertEqual(restored['jobs'][0]['status'], 'pending')
        self.assertEqual(Client.calls, [])

    def test_reorder_remove_add_and_stable_results_during_transfer(self):
        snapshot = self.add_and_resolve()
        first, second, third = snapshot['jobs']
        self.manager.request('move', job_id=third['id'], direction=-1)
        self.manager.request('remove', job_id=second['id'])
        self.manager.request('add', links=['https://terabox.com/s/1anotherx'], folder=str(self.folder / 'other'), profile=None)
        Client.release.set()
        finished = self.wait_for(lambda s: not s['running'] and not s['active'])
        self.assertEqual([call[1] for call in Client.calls if call[0] == 'download'],
                         ['first', 'third', 'first', 'second', 'third'])
        by_id = {job['id']: job for job in finished['jobs']}
        self.assertEqual(by_id[first['id']]['status'], 'completed')
        self.assertEqual(by_id[third['id']]['status'], 'completed')
        self.assertNotIn(second['id'], by_id)
        self.assertTrue(all(Path(j['path']).read_bytes() == b'movie' for j in by_id.values()))

    def test_skip_only_current_and_late_attempt_events_are_ignored(self):
        snapshot = self.add_and_resolve()
        current = snapshot['active']
        self.manager.request('skip')
        self.wait_for(lambda s: next(j for j in s['jobs'] if j['id'] == current)['status'] == 'skipped')
        self.manager.post('_progress', job_id=current, attempt=0, received=999, total=999)
        Client.release.set()
        finished = self.wait_for(lambda s: not s['running'] and not s['active'])
        self.assertEqual([j['status'] for j in finished['jobs']], ['skipped', 'completed', 'completed'])
        self.assertFalse((self.folder / 'videos' / 'first.mp4').exists())
        self.assertEqual(next(j for j in finished['jobs'] if j['id'] == current)['received'], 0)

    def test_close_active_keeps_pending_job_and_retry_failed_is_selective(self):
        snapshot = self.add_and_resolve()
        current = snapshot['active']
        self.stop_manager(self.manager)
        self.manager = self.make_manager()
        self.assertEqual(self.manager.request('snapshot')['jobs'][0]['status'], 'pending')
        self.assertEqual(self.manager.request('snapshot')['jobs'][0]['id'], current)
        Client.fail = {'second'}
        Client.release.set()
        self.manager.request('start')
        finished = self.wait_for(lambda s: not s['running'] and not s['active'])
        failed = next(j for j in finished['jobs'] if j['status'] == 'failed')
        Client.fail.clear()
        calls_before = len([c for c in Client.calls if c[0] == 'download'])
        self.manager.request('retry', job_ids=[failed['id']])
        self.assertFalse(self.manager.request('snapshot')['running'])
        self.manager.request('start')
        self.wait_for(lambda s: not s['running'] and not s['active'])
        self.assertEqual(len([c for c in Client.calls if c[0] == 'download']), calls_before + 1)
        self.manager.request('clear_history')
        self.assertEqual(self.manager.request('snapshot')['jobs'], [])
        self.assertEqual(len(list((self.folder / 'videos').glob('*.mp4'))), 3)

    def test_cancel_marks_pending_cancelled_and_resume_does_not_restart_them(self):
        self.add_and_resolve()
        self.manager.request('cancel')
        snapshot = self.wait_for(lambda s: not s['active'])
        self.assertTrue(all(j['status'] == 'cancelled' for j in snapshot['jobs']))
        self.manager.request('start')
        self.assertFalse(self.manager.request('snapshot')['running'])

    def test_source_preferences_and_favorites_survive_restart(self):
        self.manager.request('preferences', changes={'last_destination': str(self.folder),
            'favorites': [{'name': 'Movies', 'path': str(self.folder)}], 'firefox_profile': None})
        self.stop_manager(self.manager)
        self.manager = self.make_manager()
        preferences = self.manager.request('snapshot')['preferences']
        self.assertEqual(preferences['favorites'][0]['name'], 'Movies')
        self.assertEqual(preferences['last_destination'], str(self.folder))

    def test_failed_save_does_not_launch_network_or_lose_saved_pending_job(self):
        self.manager.request('add', links=[LINK], folder=str(self.folder / 'videos'), profile=None)
        identifier = self.manager.request('snapshot')['jobs'][0]['id']
        with patch.object(StateStore, 'save_jobs', side_effect=StateError('Synthetic persistence failure')):
            with self.assertRaises(StateError):
                self.manager.request('start')
        snapshot = self.manager.request('snapshot')
        self.assertFalse(snapshot['running'])
        self.assertIsNone(snapshot['active'])
        self.assertEqual(snapshot['jobs'][0]['id'], identifier)
        self.assertEqual(snapshot['jobs'][0]['status'], 'pending')
        self.assertEqual(Client.calls, [])

    def test_transport_url_is_never_serialized_and_history_cannot_clear_mid_run(self):
        self.add_and_resolve()
        self.assertNotIn(b'https://terabox.com/synthetic', (self.folder / 'state' / 'queue.sqlite').read_bytes())
        with self.assertRaises(StateError):
            self.manager.request('clear_history')
        self.manager.post('_progress', job_id='removed-old-job', attempt=1, received=999, total=999)
        self.assertEqual(len(self.manager.request('snapshot')['jobs']), 3)

    def test_invalid_preferences_are_reported_without_stopping_queue_owner(self):
        with self.assertRaises(StateError):
            self.manager.request('preferences', changes={'favorites': None})
        self.assertFalse(self.manager.closed.is_set())
        self.assertEqual(self.manager.request('snapshot')['jobs'], [])

    def test_disconnect_blocks_stored_authenticated_jobs_without_anonymous_fallback(self):
        profile = FirefoxProfile('Synthetic profile', self.folder / 'synthetic-profile')
        self.manager.request('add', links=[LINK], folder=str(self.folder / 'videos'), profile=profile)
        identifier = self.manager.request('snapshot')['jobs'][0]['id']
        self.manager.request('disconnect')
        self.manager.request('retry', job_ids=[identifier])
        self.manager.request('start')
        snapshot = self.manager.request('snapshot')
        self.assertEqual(snapshot['jobs'][0]['status'], 'failed')
        self.assertTrue(snapshot['jobs'][0]['source_blocked'])
        self.assertIsNone(snapshot['jobs'][0]['profile'])
        self.assertIsNone(snapshot['preferences']['firefox_profile'])
        self.assertEqual(Client.calls, [])

    def test_interrupted_persisted_job_restores_held_without_reusing_bytes(self):
        self.stop_manager(self.manager)
        with StateStore(self.folder / 'state') as store:
            store.save_jobs([{'id': 'interrupted', 'link': LINK, 'folder': str(self.folder / 'videos'),
                              'status': 'downloading', 'received': 3,
                              'video': {'name': 'first.mp4', 'size': 5, 'fid': 'first'}}])
        self.manager = self.make_manager()
        snapshot = self.manager.request('snapshot')
        self.assertFalse(snapshot['running'])
        self.assertEqual(snapshot['jobs'][0]['status'], 'pending')
        self.assertEqual(snapshot['jobs'][0]['received'], 0)
        self.assertEqual(Client.calls, [])

    def test_skip_inside_real_stream_cleans_partial_and_runs_next_file(self):
        started = threading.Event()
        class StreamingClient(Client):
            def download(self, video, folder, progress, *, checkpoint=None):
                def update(received, total):
                    progress(received, total)
                    if video.fid == 'first':
                        started.set()
                        while not self.cancel.wait(.01):
                            self.check_cancel()
                        self.check_cancel()
                return TeraBox.download(self, video, folder, update, checkpoint=checkpoint)
        self.stop_manager(self.manager)
        self.manager = self.make_manager(StreamingClient)
        self.manager.request('add', links=[LINK], folder=str(self.folder / 'videos'), profile=None)
        self.manager.request('start')
        self.assertTrue(started.wait(3))
        snapshot = self.manager.request('snapshot')
        job = next(j for j in snapshot['jobs'] if j['id'] == snapshot['active'])
        self.assertTrue((self.folder / 'videos' / ('.tera-' + job['checkpoint']['token'] + '.part')).exists())
        self.manager.request('skip')
        finished = self.wait_for(lambda s: not s['running'] and not s['active'])
        self.assertEqual([j['status'] for j in finished['jobs']], ['skipped', 'completed', 'completed'])
        self.assertFalse(list((self.folder / 'videos').glob('*.part')))
        self.assertFalse((self.folder / 'videos' / 'first.mp4').exists())


class SpeedTests(unittest.TestCase):
    def test_rate_window_and_resume_baseline_excludes_existing_bytes(self):
        meter = SpeedMeter()
        meter.reset(0, 0)
        meter.update(100, 1)
        meter.update(300, 3)
        self.assertEqual(meter.rate, 100)
        meter.reset(300, 20)
        self.assertEqual(meter.rate, 0)
        meter.update(500, 22)
        self.assertEqual(meter.rate, 100)
        meter.update(700, 30)
        self.assertEqual(meter.rate, 25)
        self.assertEqual(meter.rate_at(36), 0)


if __name__ == '__main__':
    unittest.main()
