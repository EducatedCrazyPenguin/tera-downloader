from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from app_state import StateStore
from firefox_session import FirefoxProfile
from queue_manager import QueueManager
from stream_smoke import make_segment,run_copy,MANIFEST,PLAYER,SHARE
from tera_gui import TeraApp
from website_dialog import WEBSITE_ROUTE, DIRECT_ROUTE
from website_stream import WebsiteStream,validate_media


class WebsiteQueueTests(unittest.TestCase):
    def test_real_loopback_stream_copy_saved_bytes_and_held_restore(self):
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        import threading,urllib.request
        from urllib.parse import urlsplit
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory)
            body,data=make_segment(base/'fixture')
            hits=[]
            class Handler(BaseHTTPRequestHandler):
                def log_message(self,*_):pass
                def do_GET(self):
                    hits.append(self.path)
                    payload=MANIFEST if self.path.endswith('.vdo') else body
                    self.send_response(200);self.send_header('Content-Length',str(len(payload)))
                    self.send_header('Content-Type','application/octet-stream');self.end_headers();self.wfile.write(payload)
            server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
            server.daemon_threads=True
            thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.01},daemon=True);thread.start()
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            class Local(WebsiteStream):
                def open(self,url):
                    self.check_cancel();validate_media(url)
                    return opener.open(f'http://127.0.0.1:{server.server_address[1]}'+urlsplit(url).path,timeout=3)
            manager=QueueManager(base/'state',Local)
            def close():
                manager.post('close');self.assertTrue(manager.closed.wait(5))
            def wait(predicate):
                end=time.monotonic()+10
                while time.monotonic()<end:
                    s=manager.request('snapshot')
                    if predicate(s):return s
                    time.sleep(.01)
                self.fail('Website queue timed out')
            try:
                self.assertTrue(manager.ready.wait(3))
                manager.request('preferences',changes={'connection_mode':'website','proxy_url':'http://unused:secret@localhost:1'})
                manager.request('review',links=[PLAYER],folder=str(base/'videos'),profile=FirefoxProfile('Synthetic',base/'private-profile'))
                reviewed=wait(lambda s:s['jobs'] and not s['review_busy'])
                self.assertIsNone(reviewed['jobs'][0]['profile'])
                self.assertEqual(reviewed['jobs'][0]['video']['size'],0)
                close();before=len(hits)
                manager=QueueManager(base/'state',Local);self.assertTrue(manager.ready.wait(3))
                restored=manager.request('snapshot')
                self.assertEqual(len(hits),before)
                self.assertFalse(restored['running'])
                self.assertEqual(restored['preferences']['connection_mode'],'website')
                manager.request('select',job_ids=[restored['jobs'][0]['id']]);manager.request('start')
                done=wait(lambda s:s['jobs'][0]['status']=='completed')
                output=Path(done['jobs'][0]['path'])
                self.assertEqual(done['jobs'][0]['received'],output.stat().st_size)
                run_copy(['-i',str(output),'-map','0:d','-c','copy','-f','data','recovered.bin'],base/'fixture','recover.log')
                self.assertEqual((base/'fixture'/'recovered.bin').read_bytes(),data*2)
                self.assertEqual(hits.count('/one.ts'),1);self.assertEqual(hits.count('/two.ts'),1)
                self.assertFalse(any((base/'videos').glob('.tera-stream-*')))
                self.assertNotIn(b'synthetic.vdo',(base/'state'/'queue.sqlite').read_bytes())
            finally:
                if not manager.closed.is_set():close()
                server.shutdown();server.server_close();thread.join(2)

    def view(self,route,text):
        v=Mock();v.pending_add=None;v.initialized=True;v.closing=False
        v.connection_route.get.return_value=route
        v.helper_browser.get.return_value='Firefox';v.manager.directory=Path('synthetic-state')
        v.links_box.get.return_value=text;v.destination.get.return_value='synthetic-folder'
        v.profile_options={'Firefox':Mock()};v.source.get.return_value='Firefox'
        v.per_share.get.return_value=False
        return v

    def test_no_vpn_share_opens_handoff_instead_of_direct_request(self):
        view=self.view(WEBSITE_ROUTE,SHARE)
        with patch('tera_gui.WebsiteDialog',return_value=Mock(result=[PLAYER])) as dialog:
            TeraApp.add_links(view,quick=True)
        dialog.assert_called_once()
        self.assertEqual(view.send.call_args.kwargs['links'],[PLAYER])
        self.assertIsNone(view.send.call_args.kwargs['profile'])

    def test_cancelled_handoff_keeps_input_and_starts_nothing(self):
        view=self.view(WEBSITE_ROUTE,SHARE)
        with patch('tera_gui.WebsiteDialog',return_value=Mock(result=None)):
            TeraApp.add_links(view,quick=True)
        view.send.assert_not_called();view.links_box.delete.assert_not_called()

    def test_direct_mode_does_not_silently_send_player_links(self):
        view=self.view(DIRECT_ROUTE,PLAYER)
        TeraApp.add_links(view,quick=True)
        view.send.assert_not_called()
        self.assertIn('No VPN',view.status.set.call_args.args[0])


if __name__=='__main__':unittest.main()
