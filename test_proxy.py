"""Synthetic proxy checks. The owned CONNECT endpoint never forwards traffic."""
import base64
import io
import os
from pathlib import Path
import socket
import socketserver
import ssl
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
import urllib.request

import terabox
from app_state import StateError, StateStore
from queue_manager import QueueManager
from tera_gui import TeraApp


PROXY = 'http://synthetic-user:synthetic-password@127.0.0.1:8080'
BODY = b'synthetic proxy video\n' * 256
LINK = 'https://terabox.com/s/1synthetic'


class ProxyTests(unittest.TestCase):
    def test_proxy_validation_never_echoes_credentials(self):
        self.assertEqual(terabox.validate_proxy('  '), '')
        self.assertEqual(terabox.validate_proxy(PROXY), PROXY)
        for value in (None, 42, 'socks5://private:secret@localhost:8080',
                      'https://localhost:8080', 'http://localhost',
                      'http://localhost:0', 'http://localhost:65536',
                      'http://localhost:80/api', 'http://localhost:80?key=secret',
                      'http://localhost:80#fragment', 'http://local host:80',
                      'http://local\nhost:80', 'http://user@localhost:80'):
            with self.subTest(value=type(value).__name__):
                with self.assertRaises(terabox.DownloadError) as error:
                    terabox.validate_proxy(value)
                self.assertNotIn('secret', str(error.exception))

    def test_credentials_are_encrypted_and_failed_protection_keeps_settings(self):
        with tempfile.TemporaryDirectory() as folder, StateStore(folder) as store:
            store.save_preferences({'proxy_url': PROXY})
            settings = Path(folder) / 'settings.json'
            original = settings.read_bytes()
            self.assertNotIn(b'synthetic-password', original)
            self.assertNotIn(b'synthetic-user', original)
            self.assertEqual(store.load_preferences()['proxy_url'], PROXY)
            store.save_preferences({'notifications': False})
            original = settings.read_bytes()
            self.assertEqual(store.load_preferences()['proxy_url'], PROXY)
            with patch('app_state.protect', side_effect=StateError('Synthetic protection failure')):
                with self.assertRaises(StateError):
                    store.save_preferences({'proxy_url': 'http://other:secret@localhost:8080'})
            self.assertEqual(settings.read_bytes(), original)
            store.save_preferences({'proxy_url': ''})
            self.assertFalse(store.load_preferences().get('proxy_url'))

    def test_https_download_uses_connect_even_when_no_proxy_is_star(self):
        fixture = self
        connects, requests, errors = [], [], []
        cert = Path(__file__).with_name('testdata') / 'proxy-localhost.pem'
        tls_server = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls_server.load_cert_chain(cert)

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                self.connection.settimeout(3)
                line = self.rfile.readline().decode('ascii').strip()
                headers = self.read_headers(self.rfile)
                connects.append((line, headers))
                fixture.assertEqual(line, 'CONNECT terabox.com:443 HTTP/1.1')
                self.wfile.write(b'HTTP/1.1 200 Connection established\r\n\r\n')
                self.wfile.flush()
                try:
                    with tls_server.wrap_socket(self.connection, server_side=True) as encrypted:
                        with encrypted.makefile('rb') as source:
                            request = source.readline().decode('ascii').strip()
                            origin_headers = self.read_headers(source)
                            requests.append((request, origin_headers))
                            encrypted.sendall(b'HTTP/1.1 200 OK\r\nContent-Type: application/octet-stream\r\n'
                                              + f'Content-Length: {len(BODY)}\r\nConnection: close\r\n\r\n'.encode() + BODY)
                except ssl.SSLError:
                    pass  # The untrusted-certificate case must fail before any origin request.
                except Exception as error:
                    errors.append(type(error).__name__)

            @staticmethod
            def read_headers(source):
                result = {}
                while True:
                    line = source.readline()
                    if line in (b'\r\n', b'\n', b''):
                        return result
                    key, value = line.decode('ascii').split(':', 1)
                    result[key.lower()] = value.strip()

        server = socketserver.ThreadingTCPServer(('127.0.0.1', 0), Handler)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        thread.start()
        proxy = f'http://synthetic-user:synthetic-password@127.0.0.1:{server.server_address[1]}'
        real_lookup = socket.getaddrinfo
        def lookup(host, *args, **kwargs):
            if host != '127.0.0.1':
                raise AssertionError('Direct or external connection attempted')
            return real_lookup(host, *args, **kwargs)
        try:
            with patch.dict(os.environ, {'no_proxy': '*', 'NO_PROXY': '*'}), \
                 patch('socket.getaddrinfo', side_effect=lookup), tempfile.TemporaryDirectory() as folder:
                client = terabox.TeraBox(proxy_url=proxy)
                for handler in client.http.handlers:
                    if isinstance(handler, urllib.request.HTTPSHandler):
                        handler._context = ssl.create_default_context(cafile=str(cert))
                video = terabox.Video('movie.mp4', len(BODY), '1', 'https://terabox.com/owned-fixture')
                output = client.download(video, folder)
                self.assertEqual(output.read_bytes(), BODY)
                self.assertEqual(len(connects), 1)
                self.assertEqual(requests[0][0], 'GET /owned-fixture HTTP/1.1')
                expected = 'Basic ' + base64.b64encode(b'synthetic-user:synthetic-password').decode('ascii')
                self.assertEqual(connects[0][1]['proxy-authorization'], expected)
                self.assertNotIn('proxy-authorization', requests[0][1])
                with self.assertRaises(terabox.DownloadError):
                    client.open('https://unrelated.invalid/forbidden')
                self.assertEqual(len(connects), 1)
                untrusted = terabox.TeraBox(proxy_url=proxy)
                with self.assertRaises(terabox.DownloadError):
                    untrusted.open('https://terabox.com/owned-fixture')
                self.assertEqual(len(requests), 1)
                self.assertEqual(errors, [])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)
            self.assertFalse(thread.is_alive())

    def test_failed_proxy_never_falls_back_to_direct(self):
        client = terabox.TeraBox(proxy_url=PROXY)
        with patch('socket.create_connection', side_effect=OSError('synthetic-password')) as connect:
            with self.assertRaises(terabox.DownloadError) as error:
                client.open('https://terabox.com/owned-fixture')
        self.assertEqual(connect.call_count, 1)
        self.assertEqual(connect.call_args.args[0], ('127.0.0.1', 8080))
        self.assertIn('proxy', str(error.exception).lower())
        self.assertNotIn('synthetic-password', str(error.exception))

    def test_proxy_is_applied_to_review_and_transfer_and_restored(self):
        calls, release = [], threading.Event()
        class Client(terabox.TeraBox):
            def __init__(self, cancel, status, profile, pause=None, proxy_url=''):
                calls.append(proxy_url)
                super().__init__(cancel, status, pause=pause, proxy_url=proxy_url)
            def find_videos(self, link):
                return [terabox.Video('movie.mp4', len(BODY), '1', 'https://terabox.com/synthetic')]
            def open(self, *args, **kwargs):
                while not release.wait(.01):
                    self.check_cancel()
                response = io.BytesIO(BODY)
                response.status = 200
                response.headers = {'Content-Type': 'application/octet-stream', 'Content-Length': str(len(BODY))}
                return response
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            manager = QueueManager(base / 'state', Client)
            def wait(predicate):
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    snapshot = manager.request('snapshot')
                    if predicate(snapshot):
                        return snapshot
                    time.sleep(.01)
                self.fail('Synthetic queue timed out')
            try:
                self.assertTrue(manager.ready.wait(3))
                manager.request('preferences', changes={'proxy_url': PROXY})
                manager.request('review', links=[LINK], folder=str(base / 'videos'), profile=None)
                reviewed = wait(lambda s: s['jobs'] and not s['review_busy'])
                manager.request('select', job_ids=[reviewed['jobs'][0]['id']])
                manager.request('start')
                wait(lambda s: bool(s['active']))
                with self.assertRaises(StateError):
                    manager.request('preferences', changes={'proxy_url': ''})
                release.set()
                done = wait(lambda s: s['jobs'][0]['status'] == 'completed')
                self.assertEqual(Path(done['jobs'][0]['path']).read_bytes(), BODY)
                self.assertEqual(calls, [PROXY, PROXY])
            finally:
                release.set()
                manager.post('close')
                self.assertTrue(manager.closed.wait(3))
            with StateStore(base / 'state') as store:
                self.assertEqual(store.load_preferences()['proxy_url'], PROXY)

    def test_settings_validation_uses_saved_proxy_for_login(self):
        view = Mock()
        view.login_busy = False
        view.proxy_url.get.return_value = PROXY
        TeraApp.save_proxy(view)
        view.send.assert_called_once_with('preferences', changes={'proxy_url': PROXY})
        view.send.reset_mock()
        view.proxy_url.get.return_value = 'socks5://localhost:8080'
        TeraApp.save_proxy(view)
        view.send.assert_not_called()
        view.snapshot = {'preferences': {'proxy_url': PROXY}}
        view.ui_events = Mock()
        TeraApp.check_login(view)
        view.login_thread.join(2)
        self.assertFalse(view.login_thread.is_alive())
        self.assertEqual(view.client_factory.call_args.kwargs['proxy_url'], PROXY)


if __name__ == '__main__':
    unittest.main()
