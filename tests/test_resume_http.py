"""Bounded loopback HTTP fixture. Never connects outside its owned server."""
from copy import deepcopy
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

from terabox import DownloadError, TeraBox, Video
from transfer_state import Checkpoint, RestartRequired, fresh_checkpoint


BODY = b'0123456789' * 100


class HTTPResumeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.folder = Path(self.directory.name)
        self.requests = []
        self.mode = 'valid'
        fixture = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                fixture.requests.append((self.headers.get('Range'), self.headers.get('If-Range')))
                offset = 400 if self.headers.get('Range') else 0
                if fixture.mode == 'rate':
                    self.send_response(429)
                    self.send_header('Retry-After', '2')
                    self.end_headers()
                    return
                if fixture.mode == '416':
                    self.send_response(416)
                    self.end_headers()
                    return
                status = 206 if offset and fixture.mode != 'ignored' else 200
                body = BODY[offset:] if status == 206 else BODY
                self.send_response(status)
                self.send_header('Content-Type', 'application/octet-stream')
                self.send_header('Content-Length', str(len(body)))
                self.send_header('ETag', '"changed"' if fixture.mode == 'changed' else '"version1"')
                if status == 206:
                    start = 401 if fixture.mode == 'bad_range' else offset
                    self.send_header('Content-Range', f'bytes {start}-999/1000')
                self.end_headers()
                self.wfile.write(body)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.server_thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        self.server_thread.start()
        self.addCleanup(self.close_server)
        host, port = self.server.server_address
        self.assertEqual(host, '127.0.0.1')
        self.origin = f'http://{host}:{port}'
        def validate_local(url, *args):
            parsed = urlsplit(url)
            if parsed.scheme != 'http' or parsed.hostname != host or parsed.port != port or parsed.username or parsed.password:
                raise AssertionError('Fixture attempted an external connection')
            return url
        validation = patch('terabox.validate_url', side_effect=validate_local)
        validation.start()
        self.addCleanup(validation.stop)
        class LocalClient(TeraBox):
            def download_url(self, video): return fixture.origin + '/owned-fixture'
        self.client = LocalClient()
        self.saved = fresh_checkpoint('binding')

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.server_thread.join(1)
        self.assertFalse(self.server_thread.is_alive())

    def commit(self, value):
        self.saved = deepcopy(value)
        return True

    def state(self):
        return Checkpoint(self.saved, self.folder, 'movie.mp4', len(BODY), 'binding', self.commit, threading.Event())

    def partial(self):
        state = self.state()
        with state.open_partial() as output:
            output.write(BODY[:400])
            state.sync(output, hashlib.sha256(BODY[:400]), 400, '"version1"')
        return state.path

    def test_real_http_valid_range_saves_exact_file(self):
        self.partial()
        result = self.client.download(Video('movie.mp4', len(BODY), '1'), self.folder, checkpoint=self.state())
        self.assertEqual(result.read_bytes(), BODY)
        self.assertEqual(self.requests, [('bytes=400-', '"version1"')])

    def test_real_http_ignored_changed_bad_range_and_416_never_append(self):
        path = self.partial()
        for mode in ('ignored', 'changed', 'bad_range', '416'):
            self.mode = mode
            with self.subTest(mode=mode), self.assertRaises(RestartRequired):
                self.client.download(Video('movie.mp4', len(BODY), '1'), self.folder, checkpoint=self.state())
            self.assertEqual(path.read_bytes(), BODY[:400])
            self.assertFalse((self.folder / 'movie.mp4').exists())

    def test_real_http_retry_after_is_classified_without_logging_urls(self):
        self.mode = 'rate'
        with self.assertRaises(DownloadError) as caught:
            self.client.open(self.origin + '/owned-fixture')
        self.assertEqual(caught.exception.kind, 'transient')
        self.assertEqual(caught.exception.retry_after, 2)
        self.assertNotIn(self.origin, str(caught.exception))
