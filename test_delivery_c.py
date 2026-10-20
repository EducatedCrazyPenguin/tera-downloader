from copy import deepcopy
import hashlib
import io
import queue
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from app_state import StateError
from app_state import StateStore
from queue_manager import QueueManager
from terabox import DownloadError, TeraBox, Video
from transfer_state import Checkpoint


BODY = b'0123456789' * (256 * 1024)
LINK = 'https://terabox.com/s/1synthetic'


class Body(io.BytesIO):
    def __init__(self, offset=0):
        super().__init__(BODY[offset:])
        self.status = 206 if offset else 200
        self.headers = {'Content-Type': 'application/octet-stream', 'Content-Length': str(len(BODY) - offset), 'ETag': '"version1"'}
        if offset:
            self.headers['Content-Range'] = f'bytes {offset}-{len(BODY)-1}/{len(BODY)}'


class Client(TeraBox):
    calls = []
    gate = threading.Event()
    started = threading.Event()
    failures = 0

    def __init__(self, cancel, status, profile, pause=None):
        super().__init__(cancel, status, pause=pause)

    def find_videos(self, link):
        self.metadata = {'shareid': '123'}
        return [Video('movie.mp4', len(BODY), '1', 'https://terabox.com/synthetic')]

    def open(self, url, data=None, headers=None):
        offset = int((headers or {}).get('Range', 'bytes=0-')[6:-1])
        self.calls.append(offset)
        if type(self).failures:
            type(self).failures -= 1
            raise DownloadError('Synthetic transient connection failure.', kind='transient', retry_after=.01)
        response = Body(offset)
        client = self
        class Stream:
            status, headers = response.status, response.headers
            def __enter__(self): return self
            def __exit__(self, *args): response.close()
            def read(self, size):
                if response.tell() >= 1024 * 1024 and not client.gate.is_set():
                    client.started.set()
                    while not client.gate.wait(.01):
                        client.check_cancel()
                return response.read(size)
        return Stream()


class QueueFixture(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.folder = Path(self.directory.name)
        Client.calls, Client.gate, Client.started, Client.failures = [], threading.Event(), threading.Event(), 0
        self.manager = self.make_manager()

    def make_manager(self):
        manager = QueueManager(self.folder / 'state', Client)
        self.addCleanup(self.stop, manager)
        self.assertTrue(manager.ready.wait(3))
        self.assertIsNone(manager.startup_error)
        return manager

    def stop(self, manager):
        if not manager.closed.is_set():
            manager.post('close')
            self.assertTrue(manager.closed.wait(4), 'Coordinator did not close')
        manager.thread.join(1)

    def wait(self, predicate):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            snapshot = self.manager.request('snapshot')
            if predicate(snapshot): return snapshot
            try: self.manager.events.get(timeout=.02)
            except queue.Empty: pass
        self.fail('Unexpected queue state: ' + repr(snapshot))

    def start(self):
        self.manager.request('review', links=[LINK], folder=str(self.folder / 'videos'), profile=None)
        reviewed = self.wait(lambda s: not s['review_busy'])
        self.manager.request('select', job_ids=[reviewed['jobs'][0]['id']])


class DeliveryCTests(QueueFixture):

    def test_save_exit_keeps_durable_bytes_and_reopen_uses_range(self):
        self.start()
        self.assertTrue(Client.started.wait(3))
        self.stop(self.manager)
        self.manager = self.make_manager()
        restored = self.manager.request('snapshot')
        job = restored['jobs'][0]
        self.assertGreater(job['checkpoint']['offset'], 0)
        self.assertEqual(job['received'], job['checkpoint']['offset'])
        self.assertFalse(restored['running'])
        before = len(Client.calls)
        Client.gate.set()
        self.manager.request('start')
        done = self.wait(lambda s: s['jobs'][0]['status'] == 'completed')
        self.assertEqual(Client.calls[before:], [job['received']])
        self.assertEqual(Path(done['jobs'][0]['path']).read_bytes(), BODY)

    def test_cancel_deletes_owned_partial_and_no_other_files(self):
        self.start()
        self.assertTrue(Client.started.wait(3))
        foreign = self.folder / 'videos' / 'other.part'
        foreign.write_bytes(b'other')
        self.manager.request('cancel')
        done = self.wait(lambda s: not s['active'])
        self.assertEqual(done['jobs'][0]['status'], 'cancelled')
        self.assertEqual(list((self.folder / 'videos').glob('.tera-*.part')), [])
        self.assertEqual(foreign.read_bytes(), b'other')

    def test_resume_rejected_holds_until_explicit_restart(self):
        self.start()
        self.assertTrue(Client.started.wait(3))
        self.stop(self.manager)
        self.manager = self.make_manager()
        Client.gate.set()
        with patch.object(Client, 'open', return_value=Body()):
            self.manager.request('start')
            held = self.wait(lambda s: s['jobs'][0]['status'] == 'restart')
        self.assertTrue(held['paused'])
        original = held['jobs'][0]['checkpoint']['offset']
        with self.assertRaises(StateError):
            self.manager.request('start')
        self.assertEqual(self.manager.request('snapshot')['jobs'][0]['status'], 'restart')
        self.manager.request('restart', job_id=held['jobs'][0]['id'])
        self.assertGreater(original, 0)
        self.manager.request('start')
        done = self.wait(lambda s: s['jobs'][0]['status'] == 'completed')
        self.assertEqual(Client.calls[-1], 0)
        self.assertEqual(Path(done['jobs'][0]['path']).read_bytes(), BODY)

    def test_transient_budget_is_bounded_and_persists_across_restart(self):
        Client.failures = 3
        Client.gate.set()
        self.start()
        failed = self.wait(lambda s: s['jobs'][0]['status'] == 'failed')
        self.assertEqual(len(Client.calls), 2)
        self.assertEqual(failed['jobs'][0]['cycle_attempts'], 2)
        self.stop(self.manager)
        self.manager = self.make_manager()
        self.manager.request('start')
        self.assertEqual(len(Client.calls), 2)
        self.manager.request('retry', job_ids=[failed['jobs'][0]['id']])
        self.manager.request('start')
        done = self.wait(lambda s: s['jobs'][0]['status'] == 'completed')
        self.assertEqual(len(Client.calls), 4)
        self.assertEqual(Path(done['jobs'][0]['path']).read_bytes(), BODY)

    def test_retry_wait_can_be_cancelled_and_does_not_resume_manual_hold(self):
        with patch.object(Client, 'open', side_effect=DownloadError('Wait.', kind='transient', retry_after=30)):
            self.start()
            self.wait(lambda s: s['jobs'][0]['status'] == 'retry_wait')
            self.manager.request('pause')
            self.assertTrue(self.manager.request('snapshot')['paused'])
            self.manager.request('cancel')
            done = self.wait(lambda s: not s['active'])
        self.assertEqual(done['jobs'][0]['status'], 'cancelled')

    def test_expired_media_url_refreshes_metadata_once_without_anonymous_fallback(self):
        original = Client.find_videos
        with patch.object(Client, 'find_videos', autospec=True, side_effect=original) as metadata, \
             patch.object(Client, 'open', side_effect=[DownloadError('Expired.', kind='login', retry_after=.01), Body()]):
            self.start()
            done = self.wait(lambda s: s['jobs'][0]['status'] == 'completed')
        self.assertEqual(metadata.call_count, 3)  # Review and both bounded transfer attempts.
        self.assertEqual(Path(done['jobs'][0]['path']).read_bytes(), BODY)

    def test_login_failure_holds_without_retry_and_restart_cannot_bypass_disconnect(self):
        from firefox_session import FirefoxProfile
        self.manager.request('review', links=[LINK], folder=str(self.folder / 'videos'), profile=FirefoxProfile('Synthetic', self.folder / 'profile'))
        reviewed = self.wait(lambda s: not s['review_busy'])
        with patch.object(Client, 'find_videos', side_effect=DownloadError('Login required.', kind='login')):
            self.manager.request('select', job_ids=[reviewed['jobs'][0]['id']])
            held = self.wait(lambda s: s['jobs'][0]['status'] == 'login')
        self.assertEqual(held['jobs'][0]['cycle_attempts'], 1)
        self.assertTrue(held['paused'])
        self.assertEqual(Client.calls, [])
        self.manager.request('cancel')
        self.manager.request('disconnect')
        with self.assertRaises(StateError):
            self.manager.request('restart', job_id=held['jobs'][0]['id'])

    def test_fake_clock_retry_after_cannot_override_manual_pause(self):
        with patch('queue_manager.time.time', return_value=100) as clock, \
             patch.object(Client, 'open', side_effect=[DownloadError('Wait.', kind='transient', retry_after=30), Body()]) as opened:
            self.start()
            self.wait(lambda s: s['jobs'][0]['status'] == 'retry_wait')
            self.manager.request('pause')
            clock.return_value = 131
            held = self.manager.request('snapshot')
            self.assertEqual(held['jobs'][0]['status'], 'retry_wait')
            self.assertEqual(opened.call_count, 1)
            self.manager.request('start')
            self.wait(lambda s: s['jobs'][0]['status'] == 'completed')
            self.assertEqual(opened.call_count, 2)

    def test_partial_without_validator_is_never_silently_restarted(self):
        response = Body()
        response.headers.pop('ETag')
        read = response.read
        def interrupted(size):
            if response.tell() >= 256 * 1024:
                raise DownloadError('Interrupted.', kind='transient', retry_after=.01)
            return read(size)
        response.read = interrupted
        with patch.object(Client, 'open', return_value=response) as opened:
            self.start()
            held = self.wait(lambda s: s['jobs'][0]['status'] == 'restart')
            self.assertEqual(opened.call_count, 1)
        self.assertEqual(held['jobs'][0]['checkpoint']['offset'], 256 * 1024)

    def test_failed_checkpoint_commit_preserves_last_record_and_holds_worker(self):
        original = StateStore.save_jobs
        def fail_synced_update(store, jobs):
            if any(j.get('checkpoint', {}).get('offset', 0) > 0 for j in jobs):
                raise StateError('Synthetic checkpoint save failure.')
            return original(store, jobs)
        with patch.object(StateStore, 'save_jobs', fail_synced_update):
            self.start()
            held = self.wait(lambda s: not s['active'] and s['paused'] and s['jobs'][0]['status'] == 'pending')
        job = held['jobs'][0]
        self.assertEqual(job['checkpoint']['offset'], 0)
        self.assertEqual(len(Client.calls), 1)
        path = self.folder / 'videos' / ('.tera-' + job['checkpoint']['token'] + '.part')
        self.assertGreaterEqual(path.stat().st_size, 1024 * 1024)
        Client.gate.set()
        self.manager.request('start')
        done = self.wait(lambda s: s['jobs'][0]['status'] == 'completed')
        self.assertEqual(Path(done['jobs'][0]['path']).read_bytes(), BODY)
