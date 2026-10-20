import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import terabox
from tera_gui import TeraApp, duration_text, size_text


class EntryTests(unittest.TestCase):
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
