"""Offline website transport tests; no real share, browser or provider."""
import io
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from terabox import Cancelled, DownloadError, parse_links
import website_stream as stream

PLAYER = 'https://teradownloader.com/player?url=https%3A%2F%2Fplay.terafile.workers.dev%2Fsynthetic.vdo&filename=sample.mp4'
SOURCE = 'https://play.terafile.workers.dev/synthetic.vdo'
PACKET = bytes([0x47, 0, 0, 0x10]) + bytes(184)
BODY = PACKET * 4
MANIFEST = b'#EXTM3U\n#EXT-X-TARGETDURATION:10\n#EXTINF:10,\n/first.ts\n#EXTINF:10,\n/second.ts\n#EXT-X-ENDLIST\n'


class Response(io.BytesIO):
    def __init__(self, body, mime='application/octet-stream', length=None):
        super().__init__(body)
        self.status = self.code = 200
        self.headers = {'Content-Type': mime, 'Content-Length': str(len(body) if length is None else length)}
        self.url = SOURCE


class WebsiteTests(unittest.TestCase):
    def client(self, bodies=None):
        client = stream.WebsiteStream()
        def copy_parts(parts, durations, target, client):
            target.write_bytes(b"".join(part.read_bytes() for part in parts))
        self.assembly = patch("website_stream.assemble", side_effect=copy_parts)
        self.assembly.start()
        self.addCleanup(self.assembly.stop)
        plans = bodies or {'/synthetic.vdo':MANIFEST,'/first.ts':BODY,'/second.ts':BODY}
        def opened(url):
            from urllib.parse import urlsplit
            stream.validate_media(url)
            body = plans[urlsplit(url).path]
            if isinstance(body, Exception): raise body
            return body if isinstance(body, Response) else Response(body)
        client.open = opened
        return client

    def test_player_url_validation_and_private_source_identity(self):
        url, name = stream.parse_source(PLAYER)
        self.assertEqual(url, SOURCE)
        self.assertEqual(name, 'sample.ts')
        self.assertEqual(parse_links(PLAYER), [PLAYER])
        for bad in ('https://teradownloader.com/download?l=secret',
                    PLAYER.replace('play.terafile.workers.dev','evil.invalid'),
                    PLAYER.replace('https%3A','http%3A'),
                    'https://play.terafile.workers.dev.evil.invalid/file.vdo',
                    'https://user:secret@play.terafile.workers.dev/file.vdo'):
            with self.subTest(case=bad.split('?')[0]):
                with self.assertRaises(DownloadError) as error:
                    stream.parse_source(bad)
                self.assertNotIn('secret',str(error.exception))

    def test_every_segment_is_saved_exactly_once_with_correct_extension(self):
        client=self.client()
        video=client.find_videos(PLAYER)[0]
        self.assertEqual(video.size,0)
        self.assertEqual(client.duration,20)
        with tempfile.TemporaryDirectory() as folder:
            progress=[]
            target=client.download(video,folder,lambda received,total:progress.append(received))
            self.assertEqual(target.name,'sample.ts')
            self.assertEqual(target.read_bytes(),BODY+BODY)
            self.assertEqual(progress[-1],len(BODY)*2)
            self.assertEqual(len(list(Path(folder).iterdir())),1)
            with self.assertRaises(DownloadError): client.download(video,folder)
            self.assertEqual(target.read_bytes(),BODY+BODY)

    def test_missing_or_short_segment_never_produces_completed_file(self):
        for second in (DownloadError('Synthetic unavailable.'),Response(BODY,length=len(BODY)+188),b'<html>not a video</html>'):
            with self.subTest(case=type(second).__name__),tempfile.TemporaryDirectory() as folder:
                client=self.client({'/synthetic.vdo':MANIFEST,'/first.ts':BODY,'/second.ts':second})
                video=client.find_videos(PLAYER)[0]
                with self.assertRaises(DownloadError): client.download(video,folder)
                self.assertEqual(list(Path(folder).iterdir()),[])

    def test_live_encrypted_and_foreign_host_playlists_are_rejected(self):
        for manifest in (MANIFEST.replace(b'#EXT-X-ENDLIST',b''),
                         MANIFEST.replace(b'#EXTINF:10,',b'#EXT-X-KEY:METHOD=AES-128,URI="secret"\n#EXTINF:10,',1),
                         MANIFEST.replace(b'/second.ts',b'https://evil.invalid/secret')):
            client=self.client({'/synthetic.vdo':manifest})
            with self.assertRaises(DownloadError) as error: client.find_videos(PLAYER)
            self.assertNotIn('secret',str(error.exception))

    def test_cancel_and_pause_keep_worker_control_and_cleanup(self):
        client=self.client()
        video=client.find_videos(PLAYER)[0]
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(Cancelled):
                client.download(video,folder,lambda *_:client.cancel.set())
            self.assertEqual(list(Path(folder).iterdir()),[])

    def test_pause_holds_network_bytes_until_resume(self):
        client=self.client({'/synthetic.vdo':MANIFEST,'/first.ts':BODY*256,'/second.ts':BODY})
        client.pause=threading.Event()
        paused=threading.Event();errors=[];progress=[]
        client.status=lambda text:paused.set() if text.startswith('Paused') else None
        video=client.find_videos(PLAYER)[0]
        with tempfile.TemporaryDirectory() as folder:
            def update(done,total):
                progress.append(done)
                if len(progress)==1:client.pause.set()
            def work():
                try:client.download(video,folder,update)
                except Exception as error:errors.append(error)
            worker=threading.Thread(target=work,daemon=True);worker.start()
            try:
                self.assertTrue(paused.wait(2));self.assertEqual(len(progress),1)
                client.pause.clear();worker.join(3)
                self.assertFalse(worker.is_alive());self.assertEqual(errors,[])
                self.assertEqual((Path(folder)/'sample.ts').read_bytes(),BODY*257)
            finally:
                client.cancel.set();client.pause.clear();worker.join(2)

    def test_website_session_never_loads_firefox_or_inherits_proxy(self):
        with patch('terabox.load_session',side_effect=AssertionError('Firefox forbidden')):
            client=stream.WebsiteStream(firefox_profile=Mock(),proxy_url='http://user:secret@localhost:8080')
        self.assertFalse(client.firefox_profile)
        self.assertFalse(client.proxy_url)
        self.assertFalse(any(type(handler).__name__=='HTTPCookieProcessor' for handler in client.http.handlers))


if __name__=='__main__': unittest.main()
