import http.cookiejar
import sqlite3
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch

from firefox_session import FirefoxProfile, SessionError, load_session, profiles
from terabox import DownloadError, TeraBox


class FirefoxTests(unittest.TestCase):
    def create_database(self, directory):
        path = Path(directory) / 'cookies.sqlite'
        connection = sqlite3.connect(path)
        connection.execute('CREATE TABLE moz_cookies (host TEXT, path TEXT, isSecure INTEGER, expiry INTEGER, name TEXT, value TEXT, isHttpOnly INTEGER, lastAccessed INTEGER, originAttributes TEXT)')
        return connection

    def test_scoped_import_and_cookie_boundaries(self):
        with tempfile.TemporaryDirectory() as directory:
            database = self.create_database(directory)
            future = int(time.time()) + 3600
            rows = [
                ('.1024tera.com', '/', 1, future, 'ndus', 'test-session-only', 1, 3, ''),
                ('www.1024tera.com', '/sharing', 1, future, 'host_only', 'a', 0, 2, ''),
                ('.terasharefile.com', '/', 1, future, 'alias_cookie', 'alias-only', 1, 1, ''),
                ('.example.com', '/', 1, future, 'password', 'unrelated', 1, 4, ''),
                ('.terabox.com.evil.example', '/', 1, future, 'ndus', 'wrong-host', 1, 5, ''),
                ('.terabox.com', '/', 1, future, 'ndus', 'container-account', 1, 8, '^userContextId=1'),
                ('.terabox.com', '/', 1, 1, 'ndus', 'expired', 1, 9, ''),
            ]
            database.executemany('INSERT INTO moz_cookies VALUES (?,?,?,?,?,?,?,?,?)', rows)
            database.commit()
            database.close()
            session = load_session(FirefoxProfile('test', Path(directory)))
            cookies = list(session.cookies)
            self.assertEqual({cookie.name for cookie in cookies}, {'ndus', 'host_only', 'alias_cookie'})
            self.assertEqual(session.origin, 'https://www.1024tera.com')
            host_cookie = next(cookie for cookie in cookies if cookie.name == 'host_only')
            self.assertFalse(host_cookie.domain_specified)
            self.assertEqual(host_cookie.path, '/sharing')
            self.assertTrue(host_cookie.secure)
            request = urllib.request.Request('https://sub.www.1024tera.com/sharing/link')
            session.cookies.add_cookie_header(request)
            self.assertNotIn('host_only=', request.get_header('Cookie', ''))
            self.assertNotIn('test-session-only', repr(session))
            self.assertEqual(sorted(p.name for p in Path(directory).iterdir()), ['cookies.sqlite'])

    def test_missing_login_has_no_sensitive_error_content(self):
        with tempfile.TemporaryDirectory() as directory:
            self.create_database(directory).close()
            with self.assertRaisesRegex(SessionError, 'No saved TeraBox login'):
                load_session(FirefoxProfile('test', Path(directory)))

    def test_install_profile_is_preferred(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            for name in ('old', 'current'):
                (base / name).mkdir()
                (base / name / 'cookies.sqlite').touch()
            (base / 'profiles.ini').write_text('[InstallABC]\nDefault=current\n[Profile0]\nName=old\nPath=old\nIsRelative=1\nDefault=1\n[Profile1]\nName=current\nPath=current\nIsRelative=1\n')
            found = profiles(base)
            self.assertEqual(found[0].name, 'current')

    def test_account_check_requires_quota_response(self):
        client = TeraBox()
        client.firefox_profile = object()
        client.session_origin = 'https://www.terabox.com'
        with patch.object(client, 'bootstrap'), patch.object(client, 'api', return_value={'errno': 0}):
            with self.assertRaises(DownloadError):
                client.verify_login()
        with patch.object(client, 'bootstrap'), patch.object(client, 'api', return_value={'errno': 0, 'total': 10, 'used': 1}):
            self.assertTrue(client.verify_login())


if __name__ == '__main__':
    unittest.main()
