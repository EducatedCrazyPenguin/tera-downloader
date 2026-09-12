import io
import tempfile
import threading
import unittest
from pathlib import Path

from terabox import Cancelled, DownloadError, SafeRedirect, TeraBox, Video, safe_name, share_id, validate_url


class Response(io.BytesIO):
    status = 200

    def __init__(self, body, mime='application/octet-stream', length=None):
        super().__init__(body)
        self.headers = {'Content-Type': mime}
        if length is not None:
            self.headers['Content-Length'] = str(length)


class FakeClient(TeraBox):
    def __init__(self, response):
        super().__init__()
        self.response = response

    def download_url(self, video):
        return 'https://d.terabox.com/file/example'

    def open(self, *args, **kwargs):
        return self.response


class Tests(unittest.TestCase):
    def test_public_link_parsing_preserves_query_identifier(self):
        self.assertEqual(share_id('https://1024terabox.com/s/1abcdef'), 'abcdef')
        self.assertEqual(share_id('https://terabox.com/sharing/link?surl=1abcdef'), '1abcdef')

    def test_terashare_alias_formats(self):
        aliases = ('terasharelink.com', 'terasharefile.com', 'terafileshare.com')
        for domain in aliases:
            with self.subTest(domain=domain, format='path'):
                self.assertEqual(share_id(f'https://{domain}/s/1abc_DEF-123?pwd=7x9q'), 'abc_DEF-123')
            with self.subTest(domain=domain, format='query'):
                self.assertEqual(share_id(f'https://www.{domain}/sharing/link?surl=abc_DEF-123&pwd=7x9q'), 'abc_DEF-123')

    def test_terashare_alias_security_boundaries(self):
        invalid = (
            'http://terasharelink.com/s/1abcdef',
            'https://terasharelink.com.evil.example/s/1abcdef',
            'https://user@terasharefile.com/s/1abcdef',
            'https://terafileshare.com:8443/s/1abcdef',
        )
        for url in invalid:
            with self.subTest(url=url), self.assertRaises(DownloadError):
                share_id(url)

    def test_network_allowlist(self):
        for url in ('https://terabox.com.evil.example/a', 'http://terabox.com/a', 'https://user@terabox.com/a', 'https://127.0.0.1/a', 'https://terabox.com:8443/a'):
            with self.assertRaises(DownloadError):
                validate_url(url)
        self.assertEqual(validate_url('https://v4.freeterabox.com/video/x'), 'https://v4.freeterabox.com/video/x')
        with self.assertRaises(DownloadError):
            SafeRedirect().redirect_request(None, None, 302, '', {}, 'https://external.example/file')

    def test_windows_names(self):
        self.assertEqual(safe_name('CON.mp4'), '_CON.mp4')
        self.assertNotIn('/', safe_name('../../movie.mp4'))
        self.assertNotIn('\\', safe_name('..\\movie.mp4'))

    def test_complete_transfer_is_finalized(self):
        with tempfile.TemporaryDirectory() as folder:
            client = FakeClient(Response(b'movie', length=5))
            result = client.download(Video('movie.mp4', 5, '1'), folder)
            self.assertEqual(result.read_bytes(), b'movie')
            self.assertEqual(len(list(Path(folder).iterdir())), 1)

    def test_incomplete_and_preview_responses_are_not_saved(self):
        for response in (Response(b'short'), Response(b'#EXTM3U', 'application/vnd.apple.mpegurl'), Response(b'x', length=1)):
            with self.subTest(response=response), tempfile.TemporaryDirectory() as folder:
                with self.assertRaises(DownloadError):
                    FakeClient(response).download(Video('movie.mp4', 20, '1'), folder)
                self.assertEqual(list(Path(folder).iterdir()), [])

    def test_existing_files_and_partial_files_are_preserved(self):
        for name in ('movie.mp4', 'movie.mp4.1.part'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as folder:
                existing = Path(folder) / name
                existing.write_bytes(b'keep')
                with self.assertRaises(DownloadError):
                    FakeClient(Response(b'movie')).download(Video('movie.mp4', 5, '1'), folder)
                self.assertEqual(existing.read_bytes(), b'keep')

    def test_cancel_removes_partial(self):
        with tempfile.TemporaryDirectory() as folder:
            client = FakeClient(Response(b'movie'))
            with self.assertRaises(Cancelled):
                client.download(Video('movie.mp4', 5, '1'), folder, lambda done, total: client.cancel.set())
            self.assertEqual(list(Path(folder).iterdir()), [])


if __name__ == '__main__':
    unittest.main()
