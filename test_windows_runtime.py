import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app_state import data_override
import quiet_launcher
from windows_runtime import application_mutex, downloads_directory, MUTEX


class WindowsRuntimeTests(unittest.TestCase):
    def test_data_override_precedence_and_resolved_environment(self):
        with patch.dict(os.environ, {'TERA_DATA_DIR': 'synthetic-env'}):
            self.assertEqual(data_override(), Path('synthetic-env').resolve())
            self.assertEqual(data_override('explicit'), Path('explicit').resolve())
        with patch.dict(os.environ, {'TERA_DATA_DIR': ''}):
            self.assertIsNone(data_override())

    def test_frozen_launcher_never_uses_development_environment(self):
        with patch.object(quiet_launcher.sys, 'frozen', True, create=True), patch.object(Path, 'is_file', return_value=True):
            self.assertIsNone(quiet_launcher.project_pythonw())

    def test_environment_override_reaches_gui_without_default_profile_import(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'TERA_DATA_DIR': folder}), patch('tera_gui.gui') as gui:
            self.assertEqual(quiet_launcher.main([], prefer_environment=False), 0)
            gui.assert_called_once_with(Path(folder).resolve())

    def test_windows_downloads_known_folder_and_mutex_lifetime(self):
        folder = downloads_directory()
        self.assertTrue(folder is None or folder.is_absolute() and folder.name == 'Tera')
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
        kernel.OpenMutexW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        with application_mutex():
            handle = kernel.OpenMutexW(0x100000, False, MUTEX)
            self.assertTrue(handle)
            kernel.CloseHandle(handle)

    def test_environment_data_selection_disables_legacy_import_in_real_gui_entry(self):
        import tera_gui
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'TERA_DATA_DIR': folder}), \
                patch('tera_gui.tk.Tk'), patch('tera_gui.TeraApp'), patch('tera_gui.QueueManager') as manager:
            tera_gui.gui()
            manager.assert_called_once_with(Path(folder).resolve(), legacy_settings=None)

    def test_self_test_requires_explicit_disposable_directory(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'TERA_DATA_DIR': folder}), patch('tera_gui.gui') as gui:
            self.assertEqual(quiet_launcher.main(['--self-test', 'app']), 1)
            gui.assert_not_called()
