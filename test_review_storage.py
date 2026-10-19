import tempfile
import stat
import unittest
from pathlib import Path
from unittest.mock import patch

from review_storage import StorageError, input_key, preflight, prior_download, required_space, share_key, share_folder


class ReviewStorageTests(unittest.TestCase):
    def test_normalization_keeps_aliases_and_passwords_distinct(self):
        link = 'https://terabox.com/s/1abcdef?pwd=secret&x=1'
        self.assertEqual(input_key(link), input_key('https://TERABOX.com:443/s/1abcdef?x=1&pwd=secret#view'))
        self.assertNotEqual(input_key(link), input_key(link.replace('terabox.com', 'terasharelink.com')))
        self.assertNotEqual(input_key(link), input_key(link.replace('secret', 'different')))
        self.assertNotIn('secret', input_key(link))
        self.assertEqual(share_key(link, {'shareid': 123}), share_key(link.replace('terabox.com', 'terasharelink.com'), {'shareid': '123'}))
        self.assertNotEqual(share_key(link, {}), share_key(link.replace('terabox.com', 'terasharelink.com'), {}))

    def test_safe_share_folders_are_contained_and_separate(self):
        base = Path('downloads').resolve()
        first = share_folder(base, 'https://terabox.com/s/1abcdef', 'provider:123')
        self.assertEqual(first.parent, base)
        self.assertNotIn('abcdef', str(first))
        self.assertNotEqual(first, share_folder(base, 'https://terabox.com/s/1abcdef', 'provider:456'))

    def test_preflight_space_collision_partial_and_writability(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory) / 'videos'
            with patch('review_storage.shutil.disk_usage', return_value=(100, 96, 4)):
                with self.assertRaises(StorageError):
                    preflight(folder, 5)
            preflight(folder, 5, 'movie.mp4', '1')
            partial = folder / 'movie.mp4.1.part'
            partial.write_bytes(b'other work')
            with self.assertRaises(StorageError):
                preflight(folder, 5, 'movie.mp4', '1')
            self.assertEqual(partial.read_bytes(), b'other work')
            partial.unlink()
            (folder / 'movie.mp4').write_bytes(b'old')
            with self.assertRaises(StorageError):
                preflight(folder, 5, 'movie.mp4', '1')
            preflight(folder, 5, 'approved.mp4', '1')
            self.assertEqual(required_space(folder, [(folder, 5), (folder.parent / 'other', 7)]), 12)
            with patch('review_storage.tempfile.TemporaryFile', side_effect=PermissionError):
                with self.assertRaises(StorageError):
                    preflight(folder, 5)
            self.assertEqual((folder / 'movie.mp4').read_bytes(), b'old')

    def test_receipt_checks_size_and_metadata_without_adopting_unknown_files(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'movie.mp4'
            path.write_bytes(b'movie')
            receipt = {'size': 5, 'mtime_ns': path.stat().st_mtime_ns}
            self.assertTrue(prior_download(str(path), receipt, 5))
            self.assertFalse(prior_download(str(path), {}, 5))
            self.assertFalse(prior_download(str(path), receipt, 6))
            path.write_bytes(b'other')
            path.touch()
            with patch.object(Path, 'stat', return_value=type('Stat', (), {'st_mode': stat.S_IFREG, 'st_size': 5, 'st_mtime_ns': receipt['mtime_ns'] + 1})()):
                self.assertFalse(prior_download(str(path), receipt, 5))
            path.unlink()
            self.assertFalse(prior_download(str(path), receipt, 5))
