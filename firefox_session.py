"""Read only TeraBox cookies from a selected local Firefox profile.

No cookie database copies, cookie exports, or account passwords are saved.
Cookie values are intentionally excluded from repr and diagnostic messages.
"""
from __future__ import annotations

import configparser
import http.cookiejar
import os
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path


TERABOX_DOMAINS = (
    'terabox.com', 'terabox.app', 'teraboxapp.com', '1024terabox.com',
    '1024tera.com', 'freeterabox.com', 'terasharelink.com', 'teraboxlink.com',
    'teraboxshare.com', 'nephobox.com', '4funbox.com', 'mirrobox.com',
)


class SessionError(Exception):
    pass


@dataclass(frozen=True)
class FirefoxProfile:
    name: str
    path: Path
    default: bool = False


@dataclass(repr=False)
class FirefoxSession:
    cookies: http.cookiejar.CookieJar = field(repr=False)
    origin: str
    profile: FirefoxProfile

    def __repr__(self):
        return 'FirefoxSession(cookie_values_hidden=True)'


def profiles(base: Path | None = None) -> list[FirefoxProfile]:
    base = base or Path(os.environ.get('APPDATA', '')) / 'Mozilla' / 'Firefox'
    config = configparser.ConfigParser(interpolation=None)
    try:
        config.read(base / 'profiles.ini', encoding='utf-8-sig')
    except (OSError, configparser.Error):
        raise SessionError('Could not read Firefox profiles. Open Firefox once and try again.') from None
    installed = {config[s].get('Default') for s in config.sections() if s.startswith('Install')}
    result = []
    for section in config.sections():
        if not section.startswith('Profile'):
            continue
        record = config[section]
        location = record.get('Path')
        if not location:
            continue
        path = (base / location if record.get('IsRelative', '1') == '1' else Path(location)).resolve()
        if not (path / 'cookies.sqlite').is_file():
            continue
        preferred = location in installed if installed else record.get('Default') == '1'
        result.append(FirefoxProfile(record.get('Name', path.name), path, preferred))
    return sorted(result, key=lambda profile: (not profile.default, profile.name))


def load_session(profile: FirefoxProfile) -> FirefoxSession:
    database = profile.path / 'cookies.sqlite'
    # Query only TeraBox hostnames. Never copy the database or read other sites' values.
    conditions, parameters = [], []
    for domain in TERABOX_DOMAINS:
        conditions.append('(host = ? OR host = ? OR host LIKE ?)')
        parameters.extend((domain, '.' + domain, '%.' + domain))
    query = ('SELECT host, path, isSecure, expiry, name, value, isHttpOnly, lastAccessed '
             'FROM moz_cookies WHERE (' + ' OR '.join(conditions) + ') '
             "AND originAttributes = '' ORDER BY lastAccessed ASC")
    connection = None
    try:
        connection = sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=2)
        connection.execute('PRAGMA query_only = ON')
        records = connection.execute(query, parameters).fetchall()
    except sqlite3.Error:
        raise SessionError('Firefox cookies could not be read. Close Firefox normally and click Check login again.') from None
    finally:
        if connection is not None:
            connection.close()
    jar = http.cookiejar.CookieJar(http.cookiejar.DefaultCookiePolicy(
        strict_ns_domain=http.cookiejar.DefaultCookiePolicy.DomainStrictNonDomain))
    auth_host = None
    auth_is_domain_cookie = False
    now = int(time.time())
    for host, path, secure, expiry, name, value, http_only, last_accessed in records:
        # Retain the browser's domain/path restrictions; never spread cookies to other domains.
        if expiry and int(expiry) <= now:
            continue
        if not any(host.lstrip('.') == d or host.endswith('.' + d) for d in TERABOX_DOMAINS):
            continue
        if name == 'ndus' and value:
            auth_host = host.lstrip('.')
            auth_is_domain_cookie = host.startswith('.')
        jar.set_cookie(http.cookiejar.Cookie(
            version=0, name=name, value=value, port=None, port_specified=False,
            domain=host, domain_specified=host.startswith('.'), domain_initial_dot=host.startswith('.'),
            path=path or '/', path_specified=True, secure=bool(secure),
            expires=int(expiry) if expiry else None, discard=not bool(expiry),
            comment=None, comment_url=None, rest={'HttpOnly': None} if http_only else {}, rfc2109=False))
    if not auth_host:
        raise SessionError('No saved TeraBox login found in this Firefox profile. Sign in using a normal tab, then close Firefox normally and click Check login.')
    # A domain cookie also applies to www; host-only regional cookies keep their original host.
    hostname = 'www.' + auth_host if auth_is_domain_cookie and auth_host in TERABOX_DOMAINS else auth_host
    return FirefoxSession(jar, 'https://' + hostname, profile)
