import json
from contextlib import closing
import sqlite3
import subprocess
import sys
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app_state import StateError, StateStore, protect, unprotect


class StateTests(unittest.TestCase):
    def test_transient_windows_replace_denial_retries_once_and_persistent_failure_preserves_settings(self):
        with tempfile.TemporaryDirectory() as folder, StateStore(folder) as store:
            store.save_preferences({'last_destination': 'before'})
            replace = os.replace
            denied = PermissionError('Synthetic Windows sharing denial')
            denied.winerror = 5
            calls = []
            def briefly_busy(source, target):
                calls.append(1)
                if len(calls) == 1:
                    self.assertEqual(store.load_preferences()['last_destination'], 'before')
                    raise denied
                return replace(source, target)
            with patch('app_state.os.replace', side_effect=briefly_busy):
                store.save_preferences({'last_destination': 'after'})
            self.assertEqual(len(calls), 2)
            with patch('app_state.os.replace', side_effect=denied) as failed:
                with self.assertRaises(StateError):
                    store.save_preferences({'last_destination': 'lost'})
                self.assertEqual(failed.call_count, 2)
            self.assertEqual(store.load_preferences()['last_destination'], 'after')
            self.assertEqual(list(Path(folder).glob('*.tmp')), [])

    def test_dpapi_round_trip_and_no_plaintext_source_on_disk(self):
        source = 'https://terabox.com/s/1synthetic?pwd=private-test-code'
        self.assertEqual(unprotect(protect(source.encode())), source.encode())
        with tempfile.TemporaryDirectory() as folder:
            with StateStore(folder) as store:
                store.save_jobs([{'id': 'job', 'link': source, 'status': 'pending', 'folder': 'destination'}])
                self.assertEqual(store.load_jobs()[0]['link'], source)
            self.assertNotIn(source.encode(), (Path(folder) / 'queue.sqlite').read_bytes())
            self.assertNotIn(b'private-test-code', (Path(folder) / 'queue.sqlite').read_bytes())

    def test_preferences_import_is_non_destructive_and_preserves_unknown_values(self):
        with tempfile.TemporaryDirectory() as folder:
            legacy = Path(folder) / 'legacy.json'
            original = json.dumps({'firefox_profile': 'synthetic-profile'})
            legacy.write_text(original, encoding='utf-8')
            data = Path(folder) / 'state'
            with StateStore(data, legacy) as store:
                preferences = store.load_preferences()
                self.assertEqual(preferences['firefox_profile'], 'synthetic-profile')
                store.save_preferences({'last_destination': 'videos', 'future_option': 7})
                store.save_preferences({'favorites': [{'name': 'Movies', 'path': 'videos'}]})
                self.assertEqual(store.load_preferences()['future_option'], 7)
            with StateStore(data, legacy) as reopened:
                self.assertEqual(reopened.load_preferences()['last_destination'], 'videos')
                self.assertEqual(len(reopened.load_preferences()['favorites']), 1)
            self.assertEqual(legacy.read_text(encoding='utf-8'), original)

    def test_failed_protection_does_not_replace_saved_queue(self):
        with tempfile.TemporaryDirectory() as folder:
            with StateStore(folder) as store:
                original = {'id': 'old', 'link': 'https://terabox.com/s/1synthetic', 'status': 'pending'}
                store.save_jobs([original])
                with patch('app_state.protect', side_effect=StateError('Protection unavailable')):
                    with self.assertRaises(StateError):
                        store.save_jobs([{'id': 'new', 'link': 'https://terabox.com/s/1otherxx'}])
                self.assertEqual(store.load_jobs(), [original])

    def test_single_owner_and_lock_released_on_close(self):
        with tempfile.TemporaryDirectory() as folder:
            with StateStore(folder):
                with self.assertRaisesRegex(StateError, 'already'):
                    StateStore(folder)
            with StateStore(folder):
                pass

    def test_data_directory_lock_blocks_a_separate_hidden_process(self):
        script = "from app_state import StateStore, StateError; import sys\ntry:\n StateStore(sys.argv[1])\nexcept StateError as error:\n print('blocked' if 'already' in str(error) else 'unexpected error')\n"
        with tempfile.TemporaryDirectory() as folder:
            with StateStore(folder):
                result = subprocess.run([sys.executable, '-c', script, folder],
                    cwd=Path(__file__).resolve().parents[1] / "src", capture_output=True, text=True, timeout=5,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), 'blocked')

    def test_corrupt_and_newer_databases_are_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'queue.sqlite'
            path.write_bytes(b'not a sqlite database')
            original = path.read_bytes()
            with self.assertRaises(StateError):
                StateStore(folder)
            self.assertEqual(path.read_bytes(), original)
            path.unlink()
            with closing(sqlite3.connect(path)) as connection:
                connection.execute('PRAGMA user_version = 999')
            original = path.read_bytes()
            with self.assertRaises(StateError):
                StateStore(folder)
            self.assertEqual(path.read_bytes(), original)

    def test_backup_round_trip_and_failed_settings_write_preserves_old(self):
        with tempfile.TemporaryDirectory() as folder:
            with StateStore(folder) as store:
                record = {'id': 'job', 'link': 'https://terabox.com/s/1synthetic'}
                store.save_jobs([record])
                store.save_preferences({'last_destination': 'keep'})
                store.backup(Path(folder) / 'backup.sqlite')
                with patch('app_state.os.replace', side_effect=OSError('synthetic write failure')):
                    with self.assertRaises(StateError):
                        store.save_preferences({'last_destination': 'lost'})
                self.assertEqual(store.load_preferences()['last_destination'], 'keep')
            with StateStore(Path(folder) / 'restored') as other:
                with closing(sqlite3.connect(Path(folder) / 'backup.sqlite')) as backup:
                    backup.backup(other.db)
                self.assertEqual(other.load_jobs(), [record])

    def test_corrupt_preferences_are_not_replaced_with_defaults(self):
        with tempfile.TemporaryDirectory() as folder:
            with StateStore(folder):
                pass
            path = Path(folder) / 'settings.json'
            for contents in ('broken json', '{"favorites": "invalid"}', '{"firefox_profile": 5}'):
                path.write_text(contents, encoding='utf-8')
                with self.assertRaises(StateError):
                    StateStore(folder)
                self.assertEqual(path.read_text(encoding='utf-8'), contents)


if __name__ == '__main__':
    unittest.main()
