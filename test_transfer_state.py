import hashlib
import io
import tempfile
import threading
import unittest
from copy import deepcopy
from pathlib import Path

from terabox import Cancelled, DownloadError, TeraBox, Video
from transfer_state import Checkpoint, RestartRequired, fresh_checkpoint


BODY = b'0123456789' * 100


class Response(io.BytesIO):
    def __init__(self, body, status=200, **headers):
        super().__init__(body)
        self.status = status
        self.headers = {'Content-Type': 'application/octet-stream', 'Content-Length': str(len(body)), 'ETag': '"version-1"', **headers}


class Client(TeraBox):
    def __init__(self, response):
        super().__init__()
        self.response, self.requests = response, []

    def download_url(self, video):
        return 'https://terabox.com/private-signed-url'

    def open(self, url, data=None, headers=None):
        self.check_cancel()
        self.requests.append(headers or {})
        return self.response


class TransferStateTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.folder = Path(self.directory.name)
        self.video = Video('movie.mp4', len(BODY), '1')
        self.saved = fresh_checkpoint('binding')
        self.discard = threading.Event()

    def state(self):
        return Checkpoint(deepcopy(self.saved), self.folder, 'movie.mp4', len(BODY), 'binding', self.commit, self.discard)

    def commit(self, value):
        self.saved = deepcopy(value)
        return True

    def partial(self, etag='"version-1"'):
        state = self.state()
        with state.open_partial() as output:
            output.write(BODY[:400])
            state.sync(output, hashlib.sha256(BODY[:400]), 400, etag)
        return state.path

    def test_complete_file_and_resume_exact_content_with_headers(self):
        self.partial()
        response = Response(BODY[400:], 206, **{'Content-Range': 'bytes 400-999/1000'})
        client = Client(response)
        result = client.download(self.video, self.folder, checkpoint=self.state())
        self.assertEqual(result.read_bytes(), BODY)
        self.assertEqual(client.requests, [{'Range': 'bytes=400-', 'If-Range': '"version-1"'}])
        self.assertEqual(self.saved['phase'], 'ready')
        self.assertNotIn('signed', repr(self.saved))

    def test_invalid_ranges_validators_and_representations_never_append(self):
        cases = [Response(BODY), Response(b'', 416),
                 Response(BODY[400:], 206, **{'Content-Range': 'bytes 0-599/1000'}),
                 Response(BODY[400:], 206, **{'Content-Range': 'bytes 400-999/999'}),
                 Response(BODY[400:], 206, **{'Content-Range': 'bytes 400-999/1000', 'ETag': '"changed"'}),
                 Response(BODY[400:], 206, **{'Content-Range': 'bytes 400-999/1000', 'Content-Encoding': 'gzip'}),
                 Response(BODY[400:], 206, **{'Content-Range': 'bytes 400-999/1000', 'Content-Length': '599'})]
        path = self.partial()
        for response in cases:
            with self.subTest(status=response.status, headers=response.headers):
                with self.assertRaises(RestartRequired):
                    Client(response).download(self.video, self.folder, checkpoint=self.state())
                self.assertEqual(path.read_bytes(), BODY[:400])
                self.assertFalse((self.folder / 'movie.mp4').exists())

    def test_short_missing_changed_or_unowned_partial_is_not_modified(self):
        path = self.partial()
        for content in (BODY[:200], b'x' * 400):
            path.write_bytes(content)
            with self.assertRaises(RestartRequired):
                self.state().open_partial()
            self.assertEqual(path.read_bytes(), content)
        path.unlink()
        with self.assertRaises(RestartRequired):
            self.state().open_partial()
        path.write_bytes(BODY[:400])
        self.saved['file_id'] = [0, 0]
        with self.assertRaises(RestartRequired):
            self.state().open_partial()
        self.assertEqual(path.read_bytes(), BODY[:400])

    def test_owned_extra_tail_is_truncated_to_verified_synced_prefix(self):
        path = self.partial()
        with path.open('ab') as output:
            output.write(b'unsynced tail')
        with self.state().open_partial() as output:
            self.assertEqual(output.tell(), 400)
        self.assertEqual(path.read_bytes(), BODY[:400])

    def test_no_strong_validator_requires_restart_before_any_request(self):
        self.partial(etag='')
        client = Client(Response(BODY[400:], 206))
        with self.assertRaises(RestartRequired):
            client.download(self.video, self.folder, checkpoint=self.state())
        self.assertEqual(client.requests, [])

    def test_cancel_discards_only_owned_file_but_save_exit_preserves_prefix(self):
        path = self.partial()
        client = Client(Response(BODY[400:], 206))
        client.cancel.set()
        with self.assertRaises(Cancelled):
            client.download(self.video, self.folder, checkpoint=self.state())
        self.assertTrue(path.exists())
        self.discard.set()
        with self.assertRaises(Cancelled):
            client.download(self.video, self.folder, checkpoint=self.state())
        self.assertFalse(path.exists())
        unknown = self.state().path
        unknown.write_bytes(b'foreign')
        self.saved = {**fresh_checkpoint('binding'), 'token': self.saved['token']}
        self.state().discard_owned()
        self.assertEqual(unknown.read_bytes(), b'foreign')

    def test_ready_rename_crash_reconciles_only_matching_owned_completion(self):
        state = self.state()
        with state.open_partial() as output:
            output.write(BODY)
            state.sync(output, hashlib.sha256(BODY), len(BODY), '"version-1"', phase='ready')
        target = self.folder / 'movie.mp4'
        state.path.rename(target)
        self.assertEqual(self.state().reconcile(), target)
        target.write_bytes(b'x' * len(BODY))
        with self.assertRaises(RestartRequired):
            self.state().reconcile()
        target.rename(self.folder / 'old-owned-file')
        target.write_bytes(BODY)
        with self.assertRaises(RestartRequired):
            self.state().reconcile()

    def test_existing_final_file_is_never_overwritten_by_durable_transfer(self):
        target = self.folder / 'movie.mp4'
        target.write_bytes(b'foreign file')
        with self.assertRaises(DownloadError):
            Client(Response(BODY)).download(self.video, self.folder, checkpoint=self.state())
        self.assertEqual(target.read_bytes(), b'foreign file')

    def test_corrupt_binding_token_offset_and_failed_commit_preserve_files(self):
        original = deepcopy(self.saved)
        for key, value in [('token', '../escape'), ('binding', 'other'), ('offset', -1), ('offset', len(BODY) + 1), ('phase', 'other')]:
            self.saved = {**original, key: value}
            with self.assertRaises(RestartRequired):
                self.state()
        self.saved = original
        state = self.state()
        def fail(value):
            raise DownloadError('Synthetic save failure')
        with state.open_partial() as output:
            output.write(BODY[:400])
            state.commit = fail
            with self.assertRaises(DownloadError):
                state.sync(output, hashlib.sha256(BODY[:400]), 400, '"version-1"')
        self.assertEqual(self.saved['offset'], 0)
        self.assertEqual(state.path.read_bytes(), BODY[:400])
