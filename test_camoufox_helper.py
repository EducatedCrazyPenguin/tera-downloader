"""Offline optional-runtime and private-pipe boundaries; never launches a browser."""
from pathlib import Path
import queue
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from camoufox_helper import OwnedCamoufox, checked_runtime
from edge_helper import browser_factory, resolve_shares
from stream_smoke import PLAYER, SHARE
from terabox import Cancelled, DownloadError


class CamoufoxTests(unittest.TestCase):
    def test_factory_and_default_background_mode(self):
        self.assertIs(browser_factory('camoufox'),OwnedCamoufox)
        self.assertTrue(OwnedCamoufox().headless)
        self.assertFalse(OwnedCamoufox(setup=True).headless)

    def test_camoufox_setup_is_explicitly_unavailable_before_launch(self):
        from edge_helper import configure_browser
        with patch('camoufox_helper.OwnedCamoufox') as browser:
            with self.assertRaisesRegex(DownloadError,'includes uBlock'):
                configure_browser('camoufox',Path('unused'),threading.Event(),Mock())
            browser.assert_not_called()

    def test_missing_runtime_is_actionable_and_never_uses_another_browser(self):
        with tempfile.TemporaryDirectory() as directory, patch('camoufox_helper.runtime_directory',return_value=Path(directory)), patch('camoufox_helper.subprocess.Popen') as launch:
            with self.assertRaisesRegex(DownloadError,'optional Camoufox'):
                with OwnedCamoufox():pass
            launch.assert_not_called()

    def test_cancelled_resolve_never_sends_share(self):
        browser=OwnedCamoufox();browser._call=Mock()
        stop=threading.Event();stop.set()
        with self.assertRaises(Cancelled):browser.resolve(SHARE,stop,Mock())
        browser._call.assert_not_called()

    def test_every_pipe_source_is_revalidated_before_queue(self):
        browser=OwnedCamoufox();browser._call=Mock(return_value=[PLAYER,PLAYER])
        self.assertEqual(browser.resolve(SHARE,threading.Event(),Mock()),[PLAYER])
        for result in ([],None,[PLAYER,'https://evil.test/private'],[PLAYER]*101):
            browser._call.return_value=result
            with self.assertRaises(DownloadError):browser.resolve(SHARE,threading.Event(),Mock())

    def test_pipe_errors_never_expose_private_browser_details(self):
        browser=OwnedCamoufox();browser._send=Mock(return_value=1)
        browser.messages.put({'id':1,'error':'https://private.test/signed?cookie=secret'})
        with self.assertRaises(DownloadError) as error:browser._call('resolve')
        self.assertNotIn('private',str(error.exception));self.assertNotIn('secret',str(error.exception))

    def test_closed_or_mismatched_pipe_is_a_failure(self):
        for value in (None,{'id':2,'result':[PLAYER]}):
            browser=OwnedCamoufox();browser._send=Mock(return_value=1);browser.messages.put(value)
            with self.assertRaises(DownloadError):browser._call('resolve')

    def test_camoufox_preference_survives_a_store_restart(self):
        from app_state import StateStore
        with tempfile.TemporaryDirectory() as directory:
            with StateStore(Path(directory)) as store:store.save_preferences({'website_browser':'camoufox'})
            with StateStore(Path(directory)) as store:self.assertEqual(store.load_preferences()['website_browser'],'camoufox')

    def test_installer_rejects_archive_traversal_without_extracting(self):
        import zipfile
        from install_camoufox_runtime import unpack
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);archive=root/'bad.zip'
            with zipfile.ZipFile(archive,'w') as package:package.writestr('../escape','synthetic')
            with self.assertRaises(ValueError):unpack(archive,root/'output')
            self.assertFalse((root/'escape').exists())


if __name__=='__main__':unittest.main()
