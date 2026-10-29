import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

import quiet_launcher


class LauncherTests(unittest.TestCase):
    def test_source_gui_keeps_legacy_settings_at_repository_root(self):
        from contextlib import nullcontext
        import tera_gui
        with patch('tera_gui.application_mutex',return_value=nullcontext()), patch('tera_gui.tk.Tk'), \
             patch('tera_gui.data_override',return_value=None), patch('tera_gui.default_data_dir',return_value=Path('synthetic-state')), \
             patch('tera_gui.QueueManager') as manager, patch('tera_gui.TeraApp'):
            tera_gui.gui()
        self.assertEqual(manager.call_args.kwargs['legacy_settings'],Path(__file__).resolve().parents[1]/'.tera-settings.json')


    def test_self_test_failure_records_location_without_exception_values(self):
        with tempfile.TemporaryDirectory() as folder, patch('smoke_terabox_gui.main', side_effect=RuntimeError('private-url-token')):
            self.assertEqual(quiet_launcher.main(['--data-dir', folder, '--self-test', 'app']), 1)
            text = (Path(folder) / 'self-test.log').read_text()
            self.assertIn('self_test_failed', text)
            self.assertNotIn('private', text)

    def test_launch_uses_isolated_data_and_no_cli_or_browser_action(self):
        with tempfile.TemporaryDirectory() as folder, patch('tera_gui.gui') as gui:
            self.assertEqual(quiet_launcher.main(['--data-dir', folder], prefer_environment=False), 0)
            gui.assert_called_once_with(Path(folder))
            text = (Path(folder) / 'launcher.log').read_text()
            self.assertIn('started', text)
            self.assertIn('exited', text)

    def test_exception_and_callback_diagnostics_exclude_private_text(self):
        with tempfile.TemporaryDirectory() as folder, patch('tera_gui.gui', side_effect=RuntimeError('private-url-token')):
            self.assertEqual(quiet_launcher.main(['--data-dir', folder], prefer_environment=False), 1)
            text = (Path(folder) / 'launcher.log').read_text()
            self.assertIn('startup_failed', text)
            self.assertNotIn('private', text)
        original = tk.Tk.report_callback_exception
        def callback_failure(directory):
            tk.Tk.report_callback_exception(None, RuntimeError, RuntimeError('private-url-token'), None)
        with tempfile.TemporaryDirectory() as folder, patch('tera_gui.gui', side_effect=callback_failure):
            self.assertEqual(quiet_launcher.main(['--data-dir', folder], prefer_environment=False), 0)
            text = (Path(folder) / 'launcher.log').read_text()
            self.assertIn('callback_failed', text)
            self.assertNotIn('private', text)
            self.assertNotIn('Traceback', text)
        self.assertIs(tk.Tk.report_callback_exception, original)

    def test_project_pythonw_handoff_is_hidden_and_does_not_open_state(self):
        with tempfile.TemporaryDirectory() as folder, patch('quiet_launcher.project_pythonw', return_value=Path('fake-pythonw.exe')), \
                patch('quiet_launcher.subprocess.Popen') as launch, patch('tera_gui.gui') as gui:
            self.assertEqual(quiet_launcher.main(['--data-dir', folder]), 0)
            gui.assert_not_called()
            args, options = launch.call_args
            self.assertEqual(args[0][0], 'fake-pythonw.exe')
            self.assertEqual(args[0][-2:], ['--data-dir', folder])
            self.assertTrue(options['creationflags'])
            self.assertEqual(options['stdout'], quiet_launcher.subprocess.DEVNULL)

    def test_project_interpreter_does_not_handoff_to_itself(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            exe = root / '.venv-desktop' / 'Scripts' / 'pythonw.exe'
            exe.parent.mkdir(parents=True)
            exe.touch()
            with patch('quiet_launcher.ROOT', root), patch('quiet_launcher.sys.prefix', str(root / '.venv-desktop')):
                self.assertIsNone(quiet_launcher.project_pythonw())

    def test_handoff_failure_is_safe_and_log_is_bounded(self):
        with tempfile.TemporaryDirectory() as folder, patch('quiet_launcher.project_pythonw', return_value=Path('missing.exe')), \
                patch('quiet_launcher.subprocess.Popen', side_effect=OSError('private')):
            self.assertEqual(quiet_launcher.main(['--data-dir', folder]), 1)
            self.assertIn('startup_failed', (Path(folder) / 'launcher.log').read_text())
            (Path(folder) / 'launcher.log').write_text('x' * 70000)
            quiet_launcher.record(Path(folder), 'started')
            self.assertLess((Path(folder) / 'launcher.log').stat().st_size, 1000)
            self.assertEqual((Path(folder) / 'launcher.previous.log').stat().st_size, 70000)
