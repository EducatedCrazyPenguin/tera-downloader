"""Bounded local-only stream fixtures/checks. Copy operations, no encoding."""
import io
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import patch

from website_stream import WebsiteStream, ffmpeg_path

PLAYER = 'https://teradownloader.com/player?url=https%3A%2F%2Fplay.terafile.workers.dev%2Fsynthetic.vdo&filename=sample.mp4'
SHARE = 'https://terabox.com/s/1synthetic'
MANIFEST = b'#EXTM3U\n#EXT-X-TARGETDURATION:1\n#EXTINF:1,\n/one.ts\n#EXT-X-DISCONTINUITY\n#EXTINF:1,\n/two.ts\n#EXT-X-ENDLIST\n'


def run_copy(command, work, log_name):
    with (work/log_name).open('w',encoding='utf-8') as log:
        child=subprocess.Popen([str(ffmpeg_path()),'-hide_banner','-loglevel','error','-nostdin',*command],
            cwd=work,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
        print('Owned local copy fixture PID',child.pid,flush=True)
        try:
            result=child.wait(timeout=10)
        finally:
            if child.poll() is None:
                child.terminate();child.wait(timeout=3)
        assert result==0,'Local stream-copy fixture failed'


def make_segment(work):
    work.mkdir(parents=True,exist_ok=True)
    data=b'synthetic-data-only-copy-fixture' * 80
    (work/'input.bin').write_bytes(data)
    run_copy(['-f','data','-i','input.bin','-map','0','-c','copy','-f','mpegts','segment.ts'],work,'make.log')
    return (work/'segment.ts').read_bytes(),data


class SyntheticWebsite(WebsiteStream):
    body=b''
    def open(self,url):
        from urllib.parse import urlsplit
        from website_stream import validate_media
        self.check_cancel()
        validate_media(url)
        body=MANIFEST if urlsplit(url).path.endswith('.vdo') else self.body
        response=io.BytesIO(body)
        response.status=response.code=200
        response.headers={'Content-Type':'application/octet-stream','Content-Length':str(len(body))}
        return response


def check_website_mode(base):
    import tkinter as tk
    from app_state import StateStore
    from queue_manager import QueueManager
    from tera_gui import TeraApp
    from website_dialog import WEBSITE_ROUTE, WebsiteDialog
    import website_dialog
    body,data=make_segment(base/'fixture')
    SyntheticWebsite.body=body
    root=tk.Tk();root.withdraw()
    manager=QueueManager(base/'state',SyntheticWebsite)
    app=TeraApp(root,manager,SyntheticWebsite,available_profiles=[])
    errors=[]
    original_hook=sys.unraisablehook
    sys.unraisablehook=lambda _:errors.append('unraisable_error')
    root.report_callback_exception=lambda *_:errors.append('callback_failed')
    def wait(predicate):
        end=time.monotonic()+10
        while time.monotonic()<end:
            if predicate():
                assert not errors,errors
                return
            if not app.destroyed:root.update()
            time.sleep(.01)
        raise AssertionError('Website native flow timed out')
    try:
        wait(lambda:app.initialized)
        app.connection_route.set(WEBSITE_ROUTE);app.route_changed()
        wait(lambda:app.snapshot['preferences'].get('connection_mode')=='website')
        app.helper_browser.set('Firefox');app.browser_changed()
        wait(lambda:app.snapshot['preferences'].get('website_browser')=='firefox')
        def configure_helper(browser, profile_dir, stop, status):
            assert browser=='firefox' and profile_dir==base/'state'/'browser-profiles'/'firefox'
            status('Synthetic helper setup complete')
        with patch.object(website_dialog, 'configure_browser', side_effect=configure_helper) as configure:
            app.helper_setup_button.invoke()
            configure.assert_called_once()
        app.helper_browser.set('Camoufox');app.browser_changed()
        wait(lambda:app.snapshot['preferences'].get('website_browser')=='camoufox')
        assert app.helper_setup_button.instate(['disabled'])
        assert 'uBlock included' in app.helper_hint.cget('text')
        app.destination.set(str(base/'videos'))
        app.links_box.insert('1.0',SHARE)
        # The real modal starts a worker and queues the captured player without a paste.
        with patch.object(website_dialog, 'resolve_shares', return_value=[PLAYER]) as resolver:
            app.download_button.invoke()
            resolver.assert_called_once()
        from browser_smoke import check_browser_helper
        check_browser_helper(base / 'browser-edge', 'edge')
        check_browser_helper(base / 'browser-firefox', 'firefox')
        from camoufox_helper import runtime_directory
        if runtime_directory().is_dir():
            check_browser_helper(base / 'browser-camoufox', 'camoufox')
        else:
            print('SKIP: optional Camoufox runtime is not installed')
        wait(lambda:app.snapshot['jobs'] and app.snapshot['jobs'][0]['status']=='completed')
        job=app.snapshot['jobs'][0]
        assert job['profile'] is None and job['path'].endswith('.ts')
        assert job['video']['size']==Path(job['path']).stat().st_size>0
        copy=Path(job['path'])
        run_copy(['-i',str(copy),'-map','0:d','-c','copy','-f','data','recovered.bin'],base/'fixture','recover.log')
        assert (base/'fixture'/'recovered.bin').read_bytes()==data*2
        # Closing Tera while a handoff is active waits for its worker cleanup.
        import threading
        from terabox import Cancelled
        started=threading.Event();stopped=threading.Event()
        def waiting_helper(shares, stop, status, **options):
            started.set()
            assert stop.wait(3), 'Close did not cancel the helper'
            stopped.set()
            raise Cancelled('Cancelled synthetic helper')
        def close_during_handoff():
            if not started.is_set():
                root.after(10,close_during_handoff);return
            app.close()
        app.links_box.insert('1.0',SHARE)
        root.after(20,close_during_handoff)
        with patch.object(website_dialog, 'resolve_shares', side_effect=waiting_helper):
            app.download_button.invoke()
        wait(lambda:app.destroyed)
        assert stopped.is_set(), 'Tera exited before helper cleanup'
        with StateStore(base/'state') as store:
            assert store.load_preferences()['connection_mode']=='website'
            assert store.load_preferences()['website_browser']=='camoufox'
            assert store.load_jobs()[0]['status']=='completed'
        print('PASS: native No-VPN choice, automatic modal/worker handoff and close-during-handoff cancellation, every synthetic segment, local FFmpeg copy, exact recovered bytes and saved completion')
    finally:
        if not app.destroyed:
            app.close();wait(lambda:app.destroyed)
        sys.unraisablehook=original_hook
        assert manager.closed.is_set()
