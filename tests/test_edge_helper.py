"""Offline browser-handoff boundaries. Never starts a browser or real provider."""
import threading
import unittest
from unittest.mock import Mock, patch

from terabox import Cancelled, DownloadError
from stream_smoke import PLAYER, SHARE
from edge_helper import OwnedEdge, allowed_request, captured_source, browser_command, resolve_shares


class BrowserHandoffTests(unittest.TestCase):
    def test_only_supported_player_sources_can_enter_queue(self):
        self.assertEqual(captured_source(PLAYER), PLAYER)
        for value in ('https://evil.test/player?url=secret',
                      'https://teradownloader.com/download?l=secret',
                      PLAYER.replace('play.terafile.workers.dev', 'evil.test'),
                      'file:///private', 12, None):
            self.assertIsNone(captured_source(value))

    def test_network_is_limited_and_never_fetches_the_captured_media(self):
        self.assertTrue(allowed_request('https://teradownloader.com/api/generate?data=x', 'XHR'))
        self.assertTrue(allowed_request('https://challenges.cloudflare.com/turnstile/v0/api.js', 'Script'))
        for value in ('https://teradownloader.com.evil.test/',
                      'https://teradownloader.com@evil.test/',
                      'http://teradownloader.com/', 'https://teradownloader.com:444/',
                      'http://127.0.0.1/private', PLAYER,
                      'https://play.terafile.workers.dev/part.ts'):
            self.assertFalse(allowed_request(value, 'Document'))
        self.assertFalse(allowed_request('https://teradownloader.com/video.mp4', 'Media'))

    def test_browser_uses_own_profile_no_share_in_command_no_existing_session(self):
        from pathlib import Path
        args = browser_command(Path('owned-edge.exe'), Path('owned-profile'))
        self.assertIn('--new-window', args)
        self.assertIn('about:blank', args)
        self.assertIn('--user-data-dir=owned-profile', args)
        self.assertIn('--remote-debugging-port=0', args)
        self.assertNotIn(SHARE, ' '.join(args))
        self.assertFalse(any('headless' in arg for arg in args))

    def test_resolves_each_share_once_and_cleans_up_before_result(self):
        browser = Mock()
        browser.__enter__ = Mock(return_value=browser)
        browser.__exit__ = Mock(return_value=False)
        browser.resolve.return_value = [PLAYER]
        with patch('edge_helper.OwnedEdge', return_value=browser):
            result = resolve_shares([SHARE, SHARE], threading.Event(), Mock())
        self.assertEqual(result, [PLAYER])
        browser.resolve.assert_called_once_with(SHARE, unittest.mock.ANY, unittest.mock.ANY)
        browser.__exit__.assert_called_once()

    def test_cancel_never_opens_browser_and_failure_does_not_fall_back(self):
        cancel = threading.Event(); cancel.set()
        with patch('edge_helper.OwnedEdge') as browser:
            with self.assertRaises(Cancelled):
                resolve_shares([SHARE], cancel, Mock())
            browser.assert_not_called()
        browser = Mock()
        browser.__enter__ = Mock(return_value=browser)
        browser.__exit__ = Mock(return_value=False)
        browser.resolve.side_effect = OSError('private-url-cookie')
        with patch('edge_helper.OwnedEdge', return_value=browser):
            with self.assertRaises(DownloadError) as error:
                resolve_shares([SHARE], threading.Event(), Mock())
        self.assertNotIn('private-url-cookie', str(error.exception))
        browser.__exit__.assert_called_once()

    def test_captured_navigation_is_blocked_and_releases_pending_button(self):
        browser = OwnedEdge(); browser.cdp = Mock(); browser.session = 'owned-session'; browser.found = []
        browser._event({'method':'Fetch.requestPaused', 'sessionId':'owned-session',
                        'params':{'requestId':'owned-request','resourceType':'Document','request':{'url':PLAYER}}})
        self.assertEqual(browser.found, [PLAYER])
        calls = browser.cdp.send.call_args_list
        self.assertEqual(calls[-1].args[0], 'Fetch.failRequest')
        self.assertEqual(calls[-1].args[1]['errorReason'], 'Aborted')
        self.assertEqual(calls[0].args[0], 'Runtime.evaluate')
        browser.found = [str(i) for i in range(100)]
        with self.assertRaises(DownloadError): browser.remember(PLAYER)

    def test_cancelled_existing_helper_never_navigates(self):
        browser = OwnedEdge(); browser.cdp = Mock()
        cancel = threading.Event(); cancel.set()
        with self.assertRaises(Cancelled):
            browser.resolve(SHARE, cancel, Mock())
        browser.cdp.send.assert_not_called(); browser.cdp.call.assert_not_called()


if __name__ == '__main__':
    unittest.main()
