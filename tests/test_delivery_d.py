from datetime import datetime
import threading
from unittest.mock import patch

from app_state import StateError
from app_state import StateStore
from test_delivery_c import BODY, Body, Client, LINK, QueueFixture
from terabox import DownloadError, Video


class DeliveryDTests(QueueFixture):
    def configure(self, **options):
        current = self.manager.request('snapshot')['run_options']
        self.manager.request('configure_run', options={**current, **options})

    def two_files(self):
        original = Client.find_videos
        def find(client, link):
            videos = original(client, link)
            return videos + [Video('second.mp4', len(BODY), '2', 'https://terabox.com/synthetic')]
        change = patch.object(Client, 'find_videos', find)
        change.start()
        self.addCleanup(change.stop)
        self.manager.request('review', links=[LINK], folder=str(self.folder / 'videos'), profile=None)
        return self.wait(lambda s: not s['review_busy'])

    def test_byte_budget_finishes_current_and_requires_explicit_new_run(self):
        self.configure(byte_budget=1)
        reviewed = self.two_files()
        Client.gate.set()
        self.manager.request('select', job_ids=[j['id'] for j in reviewed['jobs']])
        held = self.wait(lambda s: s['policy_hold'] == 'bytes' and not s['active'])
        self.assertEqual([j['status'] for j in held['jobs']], ['completed', 'pending'])
        self.assertEqual(held['run_state']['bytes'], len(BODY))
        with self.assertRaises(StateError): self.manager.request('start')
        self.manager.request('start', new_run=True)
        done = self.wait(lambda s: all(j['status'] == 'completed' for j in s['jobs']))
        self.assertEqual(done['run_state']['bytes'], len(BODY))

    def test_closed_schedule_arms_without_requests_and_manual_pause_wins(self):
        self.configure(schedule_enabled=True, start='09:00', end='10:00')
        with patch('run_policy.local_now', return_value=datetime(2026, 10, 20, 8)) as local:
            self.start()
            armed = self.manager.request('snapshot')
            self.assertEqual(armed['policy_hold'], 'schedule')
            self.assertTrue(armed['running'])
            self.assertEqual(Client.calls, [])
            self.manager.request('pause')
            local.return_value = datetime(2026, 10, 20, 9)
            self.assertTrue(self.manager.request('snapshot')['manual_paused'])
            self.assertEqual(Client.calls, [])
            Client.gate.set()
            self.manager.request('start')
            done = self.wait(lambda s: s['jobs'][0]['status'] == 'completed')
            self.assertEqual(done['run_state']['bytes'], len(BODY))

    def test_window_closure_finishes_file_then_only_its_hold_auto_resumes(self):
        self.configure(schedule_enabled=True, start='09:00', end='10:00')
        reviewed = self.two_files()
        with patch('run_policy.local_now', return_value=datetime(2026, 10, 20, 9)) as local:
            self.manager.request('select', job_ids=[j['id'] for j in reviewed['jobs']])
            self.assertTrue(Client.started.wait(3))
            local.return_value = datetime(2026, 10, 20, 10)
            self.manager.request('snapshot')
            Client.gate.set()
            held = self.wait(lambda s: s['policy_hold'] == 'schedule' and not s['active'])
            self.assertEqual([j['status'] for j in held['jobs']], ['completed', 'pending'])
            local.return_value = datetime(2026, 10, 21, 9)
            self.manager.request('snapshot')
            self.wait(lambda s: all(j['status'] == 'completed' for j in s['jobs']))

    def test_deadline_counts_pause_and_budget_survives_save_restore(self):
        self.configure(deadline_minutes=1)
        with patch('run_policy.time.time', return_value=100) as wall:
            self.start()
            self.assertTrue(Client.started.wait(3))
            self.manager.request('pause')
            wall.return_value = 161
            held = self.manager.request('snapshot')
            self.assertEqual(held['policy_hold'], 'deadline')
            self.stop(self.manager)
            before = len(Client.calls)
            self.manager = self.make_manager()
            restored = self.manager.request('snapshot')
            self.assertFalse(restored['running'])
            self.assertGreater(restored['run_state']['bytes'], 0)
            self.assertEqual(len(Client.calls), before)
            with self.assertRaises(StateError): self.manager.request('start')
            Client.gate.set()
            self.manager.request('start', new_run=True)
            finished = self.wait(lambda s: s['jobs'][0]['status'] == 'completed')
            self.assertEqual(finished['run_state']['bytes'], len(BODY) - restored['jobs'][0]['received'])

    def test_low_cap_wait_can_pause_change_rate_cancel_and_reset_controls(self):
        self.configure(speed_bps=1)
        self.start()
        self.wait(lambda s: s['run_state']['bytes'] == 1)
        self.manager.request('pause')
        paused = self.wait(lambda s: s['pause_acknowledged'])
        self.assertEqual(paused['jobs'][0]['checkpoint']['offset'], 1)
        self.configure(speed_bps=0)
        self.assertTrue(self.manager.request('snapshot')['manual_paused'])
        self.manager.request('cancel')
        done = self.wait(lambda s: not s['active'])
        self.assertEqual(done['jobs'][0]['status'], 'cancelled')
        self.assertFalse(done['run_state']['open'])
        self.assertFalse(list((self.folder / 'videos').glob('.tera-*.part')))

    def test_retransfers_count_but_explicit_new_run_resets_only_new_traffic(self):
        response = Body()
        response.headers.pop('ETag')
        read = response.read
        def interrupted(size):
            if response.tell() >= 256 * 1024:
                raise DownloadError('Synthetic interruption.', kind='transient')
            return read(size)
        response.read = interrupted
        with patch.object(Client, 'open', return_value=response):
            self.start()
            held = self.wait(lambda s: s['jobs'][0]['status'] == 'restart')
        self.assertEqual(held['run_state']['bytes'], 256 * 1024)
        self.manager.request('restart', job_id=held['jobs'][0]['id'])
        Client.gate.set()
        self.manager.request('start')
        finished = self.wait(lambda s: s['jobs'][0]['status'] == 'completed')
        self.assertEqual(finished['run_state']['bytes'], len(BODY) + 256 * 1024)

    def test_failed_hot_settings_save_keeps_prior_limits_and_stops_worker(self):
        self.start()
        self.assertTrue(Client.started.wait(3))
        original = StateStore.save_preferences
        def failed(store, changes):
            if 'run_options' in changes: raise StateError('Synthetic settings failure.')
            return original(store, changes)
        with patch.object(StateStore, 'save_preferences', failed):
            with self.assertRaises(StateError): self.configure(speed_bps=1)
            held = self.wait(lambda s: not s['active'] and s['paused'])
        self.assertEqual(held['run_options']['speed_bps'], 0)
        self.assertFalse(held['running'])
        Client.gate.set()
        self.manager.request('start')
        self.wait(lambda s: s['jobs'][0]['status'] == 'completed')

    def test_skip_during_throttle_preserves_manual_pause_and_queue(self):
        self.configure(speed_bps=1)
        reviewed = self.two_files()
        self.manager.request('select', job_ids=[j['id'] for j in reviewed['jobs']])
        self.wait(lambda s: s['run_state']['bytes'] == 1)
        self.manager.request('pause')
        self.wait(lambda s: s['pause_acknowledged'])
        self.manager.request('skip')
        held = self.wait(lambda s: not s['active'])
        self.assertTrue(held['manual_paused'])
        self.assertEqual([j['status'] for j in held['jobs']], ['skipped', 'pending'])
        self.configure(speed_bps=0)
        Client.gate.set()
        self.manager.request('start')
        self.wait(lambda s: s['jobs'][1]['status'] == 'completed')

    def test_clearing_history_cannot_reset_an_open_runs_byte_counter(self):
        self.configure(byte_budget=1)
        reviewed = self.two_files()
        Client.gate.set()
        self.manager.request('select', job_ids=[j['id'] for j in reviewed['jobs']])
        self.wait(lambda s: s['policy_hold'] == 'bytes' and not s['active'])
        self.stop(self.manager)
        self.manager = self.make_manager()
        self.manager.request('clear_history')
        held = self.manager.request('snapshot')
        self.assertEqual(held['run_state']['bytes'], len(BODY))
        self.assertEqual(len(held['jobs']), 1)
        with self.assertRaises(StateError): self.manager.request('start')

    def test_pause_reports_checkpoint_bytes_when_progress_was_coalesced(self):
        original = self.manager.post
        def coalesced(action, **data):
            if action != '_progress': original(action, **data)
        with patch.object(self.manager, 'post', side_effect=coalesced):
            self.configure(speed_bps=1)
            self.start()
            self.wait(lambda s: s['run_state']['bytes'] == 1)
            self.manager.request('pause')
            held = self.wait(lambda s: s['pause_acknowledged'])
        self.assertEqual(held['jobs'][0]['received'], 1)
        self.assertEqual(held['jobs'][0]['checkpoint']['offset'], 1)
