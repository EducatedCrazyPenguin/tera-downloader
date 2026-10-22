import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import terabox
from tera_gui import TeraApp, duration_text, size_text, visible_jobs, transfer_message


class EntryTests(unittest.TestCase):
    def test_quick_start_uses_same_validated_input_and_keeps_text_until_saved(self):
        view = Mock()
        view.pending_add = None
        view.initialized = True
        view.closing = False
        view.links_box.get.return_value = 'https://terabox.com/s/1synthetic'
        view.destination.get.return_value = 'synthetic-folder'
        view.source.get.return_value = 'No login'
        view.profile_options = {'No login': None}
        view.per_share.get.return_value = True
        TeraApp.add_links(view, quick=True)
        self.assertEqual(view.send.call_args.args, ('download_now',))
        self.assertTrue(view.send.call_args.kwargs['per_share'])
        view.notebook.select.assert_called_once_with(view.queue_page)
        view.links_box.delete.assert_not_called()
        self.assertEqual(view.pending_add, view.links_box.get.return_value)

    def test_filename_filter_and_numeric_sort_leave_source_order_unchanged(self):
        jobs = [{'id': 'b', 'video': {'name': 'B.MP4', 'size': 20}, 'finished': 20},
                {'id': 'a', 'video': {'name': 'a.mp4', 'size': 100}, 'finished': 10}]
        self.assertEqual([j['id'] for j in visible_jobs(jobs, 'mp4', 'name', False)], ['a', 'b'])
        self.assertEqual([j['id'] for j in visible_jobs(jobs, '', 'size', False)], ['b', 'a'])
        self.assertEqual([j['id'] for j in visible_jobs(jobs, '', 'finished', True)], ['b', 'a'])
        self.assertEqual([j['id'] for j in visible_jobs(jobs, 'A.MP4', 'name', False)], ['a'])
        self.assertEqual([j['id'] for j in jobs], ['b', 'a'])

    def test_pause_and_close_override_verification_message(self):
        snapshot = {'verification': {'done': 1024, 'total': 2048}, 'message': 'Paused', 'paused': True}
        self.assertEqual(transfer_message(snapshot), 'Paused')
        snapshot['paused'] = False
        self.assertIn('1.0 KB of 2.0 KB', transfer_message(snapshot))
        snapshot['closing'] = True
        self.assertEqual(transfer_message(snapshot), 'Paused')

    def test_cli_routes_isolated_data_directory_to_gui(self):
        with patch('sys.argv', ['terabox.py', '--data-dir', 'synthetic-state']), patch('tera_gui.gui') as launch:
            terabox.main()
            launch.assert_called_once_with(Path('synthetic-state'))

    def test_readable_dashboard_units_and_unknown_eta(self):
        self.assertEqual(size_text(1024 ** 3), '1.0 GB')
        self.assertEqual(duration_text(None), '—')
        self.assertEqual(duration_text(3661), '1h 01m')

    def test_held_login_action_uses_that_jobs_profile(self):
        view = Mock()
        view.selected_queue_job.return_value = 'held'
        view.snapshot = {'jobs': [{'id': 'held', 'status': 'login', 'profile': {'name': 'Saved source', 'path': 'synthetic-profile'}}]}
        view.profile_options = {'Other': None}
        view.source.get.return_value = 'Other'
        profile = TeraApp.login_profile(view)
        self.assertEqual(profile.name, 'Saved source')
        self.assertEqual(profile.path, Path('synthetic-profile'))
        view.snapshot['jobs'][0]['profile'] = None
        self.assertIsNone(TeraApp.login_profile(view))

    def test_run_limit_fields_convert_units_and_reject_invalid_input(self):
        view = Mock()
        view.limit_speed.get.return_value = '1.5'
        view.limit_bytes.get.return_value = '2.25'
        view.limit_minutes.get.return_value = '30'
        view.window_start.get.return_value = '22:00'
        view.window_end.get.return_value = '06:00'
        view.window_enabled.get.return_value = True
        TeraApp.apply_limits(view)
        options = view.send.call_args.kwargs['options']
        self.assertEqual(options['speed_bps'], 1536)
        self.assertEqual(options['byte_budget'], 2359296)
        self.assertEqual(options['deadline_minutes'], 30)
        self.assertTrue(options['schedule_enabled'])
        for speed in ('-1', 'inf', 'nan'):
            view.send.reset_mock()
            view.limit_speed.get.return_value = speed
            TeraApp.apply_limits(view)
            view.send.assert_not_called()


if __name__ == '__main__':
    unittest.main()
