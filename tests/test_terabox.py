import io
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from terabox import (Cancelled, DownloadError, SafeRedirect, TeraBox, Video,
                     download_queue, parse_links, safe_name, share_id, validate_url)


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


class QueueClient:
    plans = {}
    calls = []

    def __init__(self, cancel, status, profile, pause=None):
        self.cancel = cancel
        self.status = status
        self.pause = pause

    def find_videos(self, link):
        self.calls.append(('list', link))
        plan = self.plans[link]
        if isinstance(plan, Exception):
            raise plan
        return plan

    def download(self, video, folder, progress):
        self.calls.append(('download', video.name))
        if video.name == 'broken.mp4':
            raise DownloadError('unavailable')
        progress(video.size, video.size)
        return Path(folder) / video.name


class Tests(unittest.TestCase):
    def run_worker(self, work, cancel):
        result, errors = [], []
        def run():
            try:
                result.append(work())
            except Exception as error:
                errors.append(error)
        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        def cleanup():
            cancel.set()
            worker.join(2)
            self.assertFalse(worker.is_alive(), 'Download worker did not stop')
        self.addCleanup(cleanup)
        return worker, result, errors

    def test_pause_resume_keeps_bytes_and_repeats_without_reopening(self):
        with tempfile.TemporaryDirectory() as folder:
            body = b'a' * (256 * 1024) + b'b' * (256 * 1024) + b'end'
            client = FakeClient(Response(body, length=len(body)))
            client.pause = threading.Event()
            paused = threading.Event()
            client.status = lambda text: paused.set() if text.startswith('Paused') else None
            progress = []
            def update(received, total):
                progress.append(received)
                if received < total:
                    client.pause.set()
            with patch.object(client, 'open', wraps=client.open) as opened:
                worker, result, errors = self.run_worker(
                    lambda: client.download(Video('movie.mp4', len(body), '1'), folder, update), client.cancel)
                try:
                    for count in (1, 2):
                        self.assertTrue(paused.wait(2), 'Worker did not acknowledge pause')
                        self.assertEqual(len(progress), count)
                        self.assertEqual(client.response.tell(), count * 256 * 1024)
                        self.assertFalse(client.response.closed)
                        self.assertFalse((Path(folder) / 'movie.mp4').exists())
                        self.assertEqual((Path(folder) / 'movie.mp4.1.part').stat().st_size, progress[-1])
                        client.pause.clear()
                        paused.clear()
                    worker.join(2)
                    self.assertFalse(worker.is_alive())
                    self.assertEqual(errors, [])
                    self.assertEqual(result[0].read_bytes(), body)
                    self.assertEqual(opened.call_count, 1)
                    self.assertEqual(len(list(Path(folder).iterdir())), 1)
                finally:
                    client.cancel.set()
                    worker.join(2)

    def test_cancel_while_paused_removes_only_owned_partial(self):
        with tempfile.TemporaryDirectory() as folder:
            existing = Path(folder) / 'keep.mp4'
            existing.write_bytes(b'keep')
            client = FakeClient(Response(b'movie'))
            client.pause = threading.Event()
            paused = threading.Event()
            client.status = lambda text: paused.set() if text.startswith('Paused') else None
            worker, result, errors = self.run_worker(
                lambda: client.download(Video('movie.mp4', 5, '1'), folder,
                                        lambda done, total: client.pause.set()), client.cancel)
            try:
                self.assertTrue(paused.wait(2))
                client.cancel.set()
                worker.join(2)
                self.assertFalse(worker.is_alive())
                self.assertEqual(result, [])
                self.assertIsInstance(errors[0], Cancelled)
                self.assertEqual(list(Path(folder).iterdir()), [existing])
                self.assertEqual(existing.read_bytes(), b'keep')
            finally:
                client.cancel.set()
                worker.join(2)

    def test_queue_pause_blocks_next_video_and_share(self):
        links = ['https://terabox.com/s/1abcdef', 'https://terabox.com/s/1ghijkl']
        QueueClient.calls = []
        QueueClient.plans = {
            links[0]: [Video('first.mp4', 1, '1'), Video('second.mp4', 1, '2')],
            links[1]: [Video('last.mp4', 1, '3')],
        }
        pause, cancel, paused = threading.Event(), threading.Event(), threading.Event()
        def event(kind, data):
            if kind == 'progress' and data[0] == 0:
                pause.set()
            if kind == 'status' and data[1].startswith('Paused'):
                paused.set()
        worker, result, errors = self.run_worker(
            lambda: download_queue(links, '.', None, cancel, event, QueueClient, pause=pause), cancel)
        for expected in (2, 3):
            self.assertTrue(paused.wait(2))
            self.assertEqual(len(QueueClient.calls), expected)
            pause.clear()
            paused.clear()
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(result, [(['first.mp4', 'second.mp4', 'last.mp4'], [])])

    def test_pause_acknowledgement_survives_fast_resume_pause(self):
        pause, acknowledged = threading.Event(), threading.Event()
        pause.set()
        statuses = []
        def status(text):
            statuses.append(text)
            if len(statuses) == 1:
                pause.clear()
                pause.set()
            else:
                acknowledged.set()
        client = TeraBox(pause=pause, status=status)
        worker, result, errors = self.run_worker(client.check_cancel, client.cancel)
        self.assertTrue(acknowledged.wait(2), 'Rapid toggles left the UI waiting for acknowledgement')
        client.cancel.set()
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(result, [])
        self.assertIsInstance(errors[0], Cancelled)

    def test_pause_before_request_does_not_open_connection_until_resumed(self):
        pause, paused = threading.Event(), threading.Event()
        pause.set()
        client = TeraBox(pause=pause, status=lambda text: paused.set() if text.startswith('Paused') else None)
        with patch.object(client.http, 'open', return_value=Response(b'movie')) as opened:
            worker, result, errors = self.run_worker(lambda: client.open('https://terabox.com/file'), client.cancel)
            self.assertTrue(paused.wait(2))
            opened.assert_not_called()
            pause.clear()
            worker.join(2)
            self.assertFalse(worker.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(result[0].read(), b'movie')
            result[0].close()

    def test_cancel_from_paused_api_is_not_converted_to_download_failure(self):
        for operation in ('verify_login', 'download_url'):
            with self.subTest(operation=operation):
                client = TeraBox()
                client.firefox_profile = object()
                client.metadata = {'shareid': '1', 'sign': 'synthetic', 'timestamp': 1, 'uk': '1'}
                with patch.object(client, 'bootstrap'), patch.object(client, 'api', side_effect=Cancelled('Cancelled')):
                    with self.assertRaises(Cancelled):
                        if operation == 'verify_login':
                            client.verify_login()
                        else:
                            client.download_url(Video('movie.mp4', 5, '1'))

    def test_pause_before_final_rename_keeps_file_temporary(self):
        with tempfile.TemporaryDirectory() as folder:
            client = FakeClient(Response(b'movie'))
            client.pause = threading.Event()
            paused = threading.Event()
            client.status = lambda text: paused.set() if text.startswith('Paused') else None
            # Set pause at EOF, after the final read checkpoint but before finalization.
            original_read = client.response.read
            def read(size):
                chunk = original_read(size)
                if not chunk:
                    client.pause.set()
                return chunk
            with patch.object(client.response, 'read', side_effect=read):
                worker, result, errors = self.run_worker(
                    lambda: client.download(Video('movie.mp4', 5, '1'), folder), client.cancel)
                try:
                    self.assertTrue(paused.wait(2))
                    self.assertFalse((Path(folder) / 'movie.mp4').exists())
                    self.assertEqual((Path(folder) / 'movie.mp4.1.part').read_bytes(), b'movie')
                    client.pause.clear()
                    worker.join(2)
                    self.assertFalse(worker.is_alive())
                    self.assertEqual(errors, [])
                    self.assertEqual(result[0].read_bytes(), b'movie')
                finally:
                    client.cancel.set()
                    worker.join(2)

    def test_parse_links_ignores_blank_lines_and_rejects_invalid_entries(self):
        self.assertEqual(parse_links(' \nhttps://terabox.com/s/1abcdef\n\nhttps://1024tera.com/s/1ghijkl\n'),
                         ['https://terabox.com/s/1abcdef', 'https://1024tera.com/s/1ghijkl'])
        with self.assertRaisesRegex(DownloadError, 'line 2'):
            parse_links('https://terabox.com/s/1abcdef\nnot a link')

    def test_parse_links_accepts_comma_separated_pastes(self):
        self.assertEqual(
            parse_links('https://1024terabox.com/s/11MffawUKDmOPTHCOyg-NMw, https://1024terabox.com/s/1uPvQGjeZf6uX-ruF5fNLnQ'),
            ['https://1024terabox.com/s/11MffawUKDmOPTHCOyg-NMw',
             'https://1024terabox.com/s/1uPvQGjeZf6uX-ruF5fNLnQ'])

    def test_queue_downloads_links_and_videos_in_order_and_continues_after_errors(self):
        links = ['https://terabox.com/s/1abcdef', 'https://terabox.com/s/1ghijkl', 'https://terabox.com/s/1mnopqr']
        QueueClient.calls = []
        QueueClient.plans = {
            links[0]: [Video('first.mp4', 1, '1'), Video('broken.mp4', 1, '2'), Video('second.mp4', 1, '3')],
            links[1]: DownloadError('share unavailable'),
            links[2]: [Video('last.mp4', 1, '4')],
        }
        completed, failures = download_queue(links, '.', None, threading.Event(), lambda *event: None, QueueClient)
        self.assertEqual(completed, ['first.mp4', 'second.mp4', 'last.mp4'])
        self.assertEqual(len(failures), 2)
        self.assertEqual(QueueClient.calls, [
            ('list', links[0]), ('download', 'first.mp4'), ('download', 'broken.mp4'), ('download', 'second.mp4'),
            ('list', links[1]), ('list', links[2]), ('download', 'last.mp4'),
        ])

    def test_queue_cancel_stops_before_the_next_item(self):
        link = 'https://terabox.com/s/1abcdef'
        QueueClient.calls = []
        QueueClient.plans = {link: [Video('first.mp4', 1, '1')]}
        cancelled = threading.Event()
        cancelled.set()
        with self.assertRaises(Cancelled):
            download_queue([link], '.', None, cancelled, lambda *event: None, QueueClient)

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
