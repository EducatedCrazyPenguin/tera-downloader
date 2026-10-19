import queue
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from app_state import StateError
from queue_manager import QueueManager
from review_storage import StorageError
from test_queue_manager import Client, LINK


class ReviewClient(Client):
    def find_videos(self, link):
        self.metadata = {'shareid': '123' if 'another' not in link else '456'}
        return super().find_videos(link)


class DeliveryBTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.folder = Path(self.directory.name)
        Client.calls, Client.fail, Client.release = [], set(), threading.Event()
        self.manager = self.make_manager()

    def make_manager(self, factory=ReviewClient):
        manager = QueueManager(self.folder / 'state', factory)
        self.addCleanup(self.stop, manager)
        self.assertTrue(manager.ready.wait(3))
        self.assertIsNone(manager.startup_error)
        return manager

    def stop(self, manager):
        if not manager.closed.is_set():
            manager.post('close')
            self.assertTrue(manager.closed.wait(3))
        manager.thread.join(1)

    def wait(self, predicate):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            snapshot = self.manager.request('snapshot')
            if predicate(snapshot):
                return snapshot
            try:
                self.manager.events.get(timeout=.02)
            except queue.Empty:
                pass
        self.fail('Queue did not reach expected state: ' + repr(snapshot))

    def review(self, links=None, folder=None, **data):
        self.manager.request('review', links=links or [LINK], folder=str(folder or self.folder / 'videos'), profile=None, **data)
        return self.wait(lambda s: not s['review_busy'])

    def test_review_dedup_selection_exclusion_and_restore(self):
        snapshot = self.review([LINK, LINK + '#view'])
        self.assertEqual(len(Client.calls), 1)
        self.assertEqual(len(snapshot['jobs']), 3)
        self.assertTrue(all(j['status'] == 'review' for j in snapshot['jobs']))
        self.manager.request('start')
        self.assertFalse(self.manager.request('snapshot')['running'])
        self.assertFalse(any(c[0] == 'download' for c in Client.calls))
        first = snapshot['jobs'][0]
        self.manager.request('select', job_ids=[first['id']], start=False)
        self.stop(self.manager)
        before = len(Client.calls)
        self.manager = self.make_manager()
        snapshot = self.manager.request('snapshot')
        self.assertEqual([j['status'] for j in snapshot['jobs']], ['pending', 'excluded', 'excluded'])
        self.assertEqual(len(Client.calls), before)
        Client.release.set()
        self.manager.request('start')
        done = self.wait(lambda s: not s['running'] and not s['active'])
        self.assertEqual(Path(done['jobs'][0]['path']).read_bytes(), b'movie')
        self.assertEqual([c[1] for c in Client.calls if c[0] == 'download'], ['first'])

    def test_authoritative_aliases_and_missing_receipt_are_rechecked(self):
        reviewed = self.review()
        self.manager.request('select', job_ids=[j['id'] for j in reviewed['jobs']], start=False)
        Client.release.set()
        self.manager.request('start')
        done = self.wait(lambda s: not s['running'] and not s['active'])
        self.review([LINK.replace('terabox.com', 'terasharelink.com')])
        current = self.manager.request('snapshot')
        review = [j for j in current['jobs'] if j['status'] in {'review', 'excluded'}]
        self.assertTrue(all('Prior download' in j['error'] for j in review))
        Path(done['jobs'][0]['path']).unlink()
        self.manager.request('select', job_ids=[j['id'] for j in review], start=False)
        current = self.manager.request('snapshot')
        self.assertEqual(sum(j['status'] == 'pending' for j in current['jobs']), 1)
        self.assertEqual(sum(j['status'] == 'excluded' for j in current['jobs']), 2)

    def test_aliases_in_review_are_unselected_and_changed_sizes_stay_distinct(self):
        self.review()
        snapshot = self.review([LINK.replace('terabox.com', 'terasharelink.com')])
        self.assertEqual(sum(j['status'] == 'review' for j in snapshot['jobs']), 3)
        self.assertEqual(sum(j['error'] == 'Already selected in Review.' for j in snapshot['jobs']), 3)
        from terabox import Video
        with patch.object(ReviewClient, 'find_videos', return_value=[Video('first.mp4', 6, 'first')]):
            snapshot = self.review([LINK.replace('terabox.com', 'terabox.app')])
        self.assertEqual(sum(j['status'] == 'review' for j in snapshot['jobs']), 4)

    def test_review_save_failure_leaves_no_worker_and_saved_review_restarts_explicitly(self):
        with patch('app_state.protect', side_effect=StateError('Synthetic protection failure')):
            with self.assertRaises(StateError):
                self.manager.request('review', links=[LINK], folder=str(self.folder), profile=None)
        self.assertEqual(Client.calls, [])
        self.assertFalse(self.manager.request('snapshot')['review_busy'])
        self.assertFalse(self.manager.request('snapshot')['jobs'])
        self.review()
        self.stop(self.manager)
        before = len(Client.calls)
        self.manager = self.make_manager()
        snapshot = self.manager.request('snapshot')
        self.assertTrue(all(j['status'] == 'review' for j in snapshot['jobs']))
        self.assertEqual(len(Client.calls), before)
        self.assertNotIn(b'https://terabox.com/synthetic', (self.folder / 'state' / 'queue.sqlite').read_bytes())
        self.assertNotIn(b'https://terabox.com/s/1synthetic', (self.folder / 'state' / 'queue.sqlite').read_bytes())

    def test_storage_hold_correction_skip_and_exact_contents(self):
        reviewed = self.review(per_share=True)
        ids = [j['id'] for j in reviewed['jobs']]
        self.assertNotEqual(Path(reviewed['jobs'][0]['folder']), self.folder / 'videos')
        target = Path(reviewed['jobs'][0]['folder']) / 'first.mp4'
        target.parent.mkdir(parents=True)
        target.write_bytes(b'keep')
        self.manager.request('select', job_ids=ids)
        held = self.wait(lambda s: s['paused'] and not s['active'])
        self.assertEqual(held['jobs'][0]['status'], 'attention')
        self.assertFalse(any(c[0] == 'download' for c in Client.calls))
        with self.assertRaises(StateError):
            self.manager.request('destination', job_id=ids[0], name='../unsafe.mp4')
        self.manager.request('destination', job_id=ids[0], name='approved.mp4')
        Client.release.set()
        self.manager.request('start')
        done = self.wait(lambda s: not s['running'] and not s['active'])
        self.assertEqual(target.read_bytes(), b'keep')
        self.assertTrue(all(Path(j['path']).read_bytes() == b'movie' for j in done['jobs']))

    def test_aggregate_space_and_between_file_recheck_hold_then_change_folder(self):
        reviewed = self.review()
        with patch('queue_manager.preflight', side_effect=StorageError('Not enough free space.')) as check:
            self.manager.request('select', job_ids=[j['id'] for j in reviewed['jobs']])
            self.wait(lambda s: s['paused'] and not s['active'])
            self.assertEqual(check.call_args.args[1], 15)
        snapshot = self.manager.request('snapshot')
        identifier = snapshot['jobs'][0]['id']
        self.manager.request('destination', job_id=identifier, folder=str(self.folder / 'changed'))
        Client.release.set()
        with patch('queue_manager.preflight', side_effect=[None, StorageError('Disk filled.')]):
            self.manager.request('start')
            held = self.wait(lambda s: s['paused'] and not s['active'])
        self.assertEqual([j['status'] for j in held['jobs']], ['completed', 'attention', 'pending'])
        self.manager.request('skip', job_id=held['jobs'][1]['id'])
        self.manager.request('start')
        done = self.wait(lambda s: not s['running'] and not s['active'])
        self.assertEqual([j['status'] for j in done['jobs']], ['completed', 'skipped', 'completed'])
        self.assertEqual(Path(done['jobs'][0]['path']).parent, self.folder / 'changed')

    def test_finish_current_pause_resume_and_cancel(self):
        reviewed = self.review()
        self.manager.request('select', job_ids=[j['id'] for j in reviewed['jobs']])
        self.wait(lambda s: any(c[0] == 'download' for c in Client.calls))
        self.manager.request('pause_after')
        self.manager.request('pause_after')
        self.assertFalse(self.manager.request('snapshot')['paused'])
        Client.release.set()
        held = self.wait(lambda s: s['paused'] and not s['active'])
        self.assertEqual([j['status'] for j in held['jobs']], ['completed', 'pending', 'pending'])
        self.assertEqual([c[1] for c in Client.calls if c[0] == 'download'], ['first'])
        self.manager.request('start')
        self.wait(lambda s: not s['running'] and not s['active'])
        self.assertEqual([c[1] for c in Client.calls if c[0] == 'download'], ['first', 'second', 'third'])
        self.manager.request('pause_after')
        self.assertFalse(self.manager.request('snapshot')['running'])

    def test_review_during_active_transfer_and_close_cancels_discovery(self):
        gate = threading.Event()
        class SlowReview(ReviewClient):
            def find_videos(self, link):
                if 'another' in link:
                    gate.set()
                    while not self.cancel.wait(.01):
                        self.check_cancel()
                    self.check_cancel()
                return super().find_videos(link)
        self.stop(self.manager)
        self.manager = self.make_manager(SlowReview)
        reviewed = self.review()
        self.manager.request('select', job_ids=[j['id'] for j in reviewed['jobs']])
        self.wait(lambda s: any(c[0] == 'download' for c in Client.calls))
        self.manager.request('review', links=[LINK.replace('synthetic', 'anotherx')], folder=str(self.folder), profile=None)
        self.assertTrue(gate.wait(2))
        self.manager.request('pause')
        self.stop(self.manager)
        self.manager = self.make_manager()
        restored = self.manager.request('snapshot')
        self.assertFalse(restored['review_busy'])
        self.assertTrue(any(j['status'] == 'unreviewed' for j in restored['jobs']))
        self.manager.request('review_saved')
        reviewed = self.wait(lambda s: not s['review_busy'])
        self.assertEqual(sum(j['status'] == 'review' for j in reviewed['jobs']), 3)
        self.assertFalse(reviewed['running'])

    def test_late_review_result_and_changed_metadata_never_start_wrong_file(self):
        reviewed = self.review()
        before = reviewed['jobs']
        self.manager.post('_review_result', job_id='old-review', outcome='discovered', value=('provider:999', []))
        self.assertEqual(self.manager.request('snapshot')['jobs'], before)
        with patch.object(ReviewClient, 'find_videos', return_value=[]):
            self.manager.request('select', job_ids=[before[0]['id']])
            failed = self.wait(lambda s: not s['running'] and not s['active'])
        self.assertEqual(failed['jobs'][0]['status'], 'failed')
        self.assertFalse(any(c[0] == 'download' for c in Client.calls))

    def test_append_reviewed_selection_does_not_resume_manual_pause(self):
        reviewed = self.review()
        self.manager.request('select', job_ids=[j['id'] for j in reviewed['jobs']])
        self.wait(lambda s: any(c[0] == 'download' for c in Client.calls))
        self.manager.request('pause')
        later = self.review([LINK.replace('synthetic', 'anotherx')], folder=self.folder / 'extra')
        selected = [j['id'] for j in later['jobs'] if j['status'] == 'review']
        self.manager.request('select', job_ids=selected)
        self.assertTrue(self.manager.request('snapshot')['paused'])
        self.manager.request('destination', job_id=selected[0], name='different.mp4')
        with self.assertRaises(StateError):
            self.manager.request('destination', job_id=reviewed['jobs'][0]['id'], folder=str(self.folder / 'wrong'))
        Client.release.set()
        self.manager.request('start')
        done = self.wait(lambda s: not s['running'] and not s['active'])
        self.assertEqual(sum(j['status'] == 'completed' for j in done['jobs']), 6)
        self.assertTrue((self.folder / 'extra' / 'different.mp4').exists())

    def test_boundary_at_finalization_skip_and_cancel_are_distinct(self):
        written = threading.Event()
        release = threading.Event()
        self.addCleanup(release.set)
        class FinalizeClient(ReviewClient):
            def download(self, video, folder, progress):
                from terabox import TeraBox
                def update(done, total):
                    progress(done, total)
                    if video.fid == 'first':
                        written.set()
                        while not release.wait(.01):
                            self.check_cancel()
                return TeraBox.download(self, video, folder, update)
        self.stop(self.manager)
        self.manager = self.make_manager(FinalizeClient)
        reviewed = self.review()
        self.manager.request('select', job_ids=[j['id'] for j in reviewed['jobs']])
        self.assertTrue(written.wait(2))
        self.assertFalse((self.folder / 'videos' / 'first.mp4').exists())
        self.manager.request('pause_after')
        release.set()
        held = self.wait(lambda s: s['paused'] and not s['active'])
        self.assertEqual([j['status'] for j in held['jobs']], ['completed', 'pending', 'pending'])
        self.manager.request('cancel')
        done = self.manager.request('snapshot')
        self.assertEqual([j['status'] for j in done['jobs']], ['completed', 'cancelled', 'cancelled'])
        self.assertEqual((self.folder / 'videos' / 'first.mp4').read_bytes(), b'movie')
        self.assertFalse(list((self.folder / 'videos').glob('*.part')))

    def test_boundary_during_legacy_discovery_pauses_before_any_file(self):
        discovery = threading.Event()
        release = threading.Event()
        self.addCleanup(release.set)
        class DiscoverClient(ReviewClient):
            def find_videos(self, link):
                discovery.set()
                while not release.wait(.01):
                    self.check_cancel()
                return super().find_videos(link)
        self.stop(self.manager)
        self.manager = self.make_manager(DiscoverClient)
        self.manager.request('add', links=[LINK], folder=str(self.folder / 'videos'), profile=None)
        self.manager.request('start')
        self.assertTrue(discovery.wait(2))
        self.manager.request('pause_after')
        release.set()
        held = self.wait(lambda s: s['paused'] and not s['active'])
        self.assertTrue(all(j['status'] == 'pending' for j in held['jobs']))
        self.assertTrue(held['pause_acknowledged'])
        self.assertFalse(any(c[0] == 'download' for c in Client.calls))

    def test_skip_during_boundary_request_holds_remaining_jobs(self):
        reviewed = self.review()
        self.manager.request('select', job_ids=[j['id'] for j in reviewed['jobs']])
        self.wait(lambda s: any(c[0] == 'download' for c in Client.calls))
        self.manager.request('pause_after')
        self.manager.request('skip')
        held = self.wait(lambda s: s['paused'] and not s['active'])
        self.assertEqual([j['status'] for j in held['jobs']], ['skipped', 'pending', 'pending'])
        self.assertEqual([c[1] for c in Client.calls if c[0] == 'download'], ['first'])

    def test_cancelled_file_can_be_reviewed_again_with_new_destination(self):
        reviewed = self.review()
        self.manager.request('select', job_ids=[reviewed['jobs'][0]['id']])
        self.wait(lambda s: bool(s['active']))
        self.manager.request('cancel')
        self.wait(lambda s: not s['active'])
        reviewed = self.review(folder=self.folder / 'restart')
        candidates = [j for j in reviewed['jobs'] if j['status'] == 'review']
        self.assertEqual(len(candidates), 3)
        self.assertTrue(all(j['folder'] == str(self.folder / 'restart') for j in candidates))
