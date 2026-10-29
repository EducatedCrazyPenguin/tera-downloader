"""Offline browser-choice/profile boundaries; never launches a browser."""
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from edge_helper import OwnedEdge, resolve_shares
from stream_smoke import PLAYER, SHARE
from terabox import DownloadError


class BrowserChoiceTests(unittest.TestCase):
    def test_firefox_choice_dispatches_without_opening_edge(self):
        browser = Mock()
        browser.__enter__ = Mock(return_value=browser)
        browser.__exit__ = Mock(return_value=False)
        browser.resolve.return_value = [PLAYER]
        with patch('firefox_helper.OwnedFirefox', return_value=browser) as firefox, patch('edge_helper.OwnedEdge') as edge:
            result = resolve_shares([SHARE], threading.Event(), Mock(), browser='firefox', profile_dir=Path('owned-profile'))
        self.assertEqual(result, [PLAYER]); firefox.assert_called_once(); edge.assert_not_called()

    def test_browser_choice_never_silently_falls_back(self):
        with patch('edge_helper.OwnedEdge') as edge:
            with self.assertRaises(DownloadError):
                resolve_shares([SHARE], threading.Event(), Mock(), browser='unsupported')
            edge.assert_not_called()

    def test_persistent_profile_is_owned_and_customizations_survive_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'helper'
            browser = OwnedEdge(profile_dir=target)
            browser.prepare_profile()
            (target / 'user.js').write_text('// synthetic user customization', encoding='utf-8')
            browser.__exit__(None, None, None)
            self.assertEqual((target / 'user.js').read_text(encoding='utf-8'), '// synthetic user customization')
            again = OwnedEdge(profile_dir=target); again.prepare_profile(); again.__exit__(None,None,None)

    def test_an_existing_unmarked_profile_is_never_modified(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            sentinel = target / 'cookies.sqlite'; sentinel.write_bytes(b'synthetic sentinel')
            browser = OwnedEdge(profile_dir=target)
            with self.assertRaises(DownloadError): browser.prepare_profile()
            self.assertEqual(sorted(p.name for p in target.iterdir()), ['cookies.sqlite'])
            self.assertEqual(sentinel.read_bytes(), b'synthetic sentinel')


    def test_wait_does_not_abort_a_page_still_loading_after_twenty_seconds(self):
        browser = OwnedEdge(); browser.navigate = Mock()
        browser.evaluate = Mock(side_effect=[{'ready':False}, {'ready':True,'links':[PLAYER],'remaining':0,'pending':False}])
        cancel = Mock();cancel.is_set.return_value=False;cancel.wait.return_value=False
        with patch('edge_helper.time.monotonic', side_effect=[0,0,30,30,40,40,41]):
            self.assertEqual(browser.resolve(SHARE,cancel,Mock()),[PLAYER])

    def test_browser_preference_is_validated_and_saved(self):
        from queue_manager import QueueManager
        from app_state import StateStore, StateError
        with tempfile.TemporaryDirectory() as directory:
            manager=QueueManager(Path(directory))
            try:
                manager.request('preferences',changes={'website_browser':'firefox'})
                with self.assertRaises(StateError):
                    manager.request('preferences',changes={'website_browser':'unknown'})
            finally:
                manager.post('close');self.assertTrue(manager.closed.wait(5))
            with StateStore(Path(directory)) as store:
                self.assertEqual(store.load_preferences()['website_browser'],'firefox')

    def test_firefox_reports_only_a_formatted_turnstile_error_code(self):
        from firefox_helper import OwnedFirefox
        browser=OwnedFirefox();browser.challenge_error=None
        browser._event({'method':'log.entryAdded','params':{'text':'URL https://challenges.cloudflare.com/example/701823'}})
        self.assertIsNone(browser.challenge_error)
        browser._event({'method':'log.entryAdded','params':{'text':'[Cloudflare Turnstile] Error: 600010. private detail'}})
        self.assertEqual(browser.challenge_error,'600010')

    def test_edge_no_longer_disables_user_installed_helper_extensions(self):
        from edge_helper import browser_command
        self.assertNotIn('--disable-extensions',browser_command(Path('edge.exe'),Path('owned')))


if __name__ == '__main__': unittest.main()
