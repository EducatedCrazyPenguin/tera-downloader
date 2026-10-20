"""Local TeraBox downloader with optional Firefox session reuse. Standard library only."""
from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import re
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from firefox_session import SessionError, load_session, profiles

SHARE_DOMAINS = (
    'terabox.com', 'terabox.app', 'teraboxapp.com', '1024terabox.com',
    '1024tera.com', 'freeterabox.com', 'terasharelink.com', 'teraboxlink.com',
    'terasharefile.com', 'terafileshare.com', 'teraboxshare.com',
    'nephobox.com', '4funbox.com', 'mirrobox.com',
)
MEDIA_DOMAINS = SHARE_DOMAINS + ('teraboxcdn.com',)
VIDEO_EXTENSIONS = {'.mp4', '.mkv', '.avi', '.mov', '.webm', '.m4v', '.ts', '.flv'}


class DownloadError(Exception):
    def __init__(self, message, *, kind='unknown', retry_after=5):
        super().__init__(message)
        self.kind = kind
        self.retry_after = retry_after


class Cancelled(DownloadError):
    pass


PAUSED_STATUS = 'Paused. Click Resume to continue.'


def _wait_for_download(cancel, pause=None, status=lambda text: None):
    if cancel.is_set():
        raise Cancelled('Cancelled. Completed downloads were kept.')
    if pause is not None and pause.is_set():
        while pause.is_set():
            # A quick Resume/Pause can happen entirely between worker checks.
            status(PAUSED_STATUS)
            if cancel.wait(.1):
                raise Cancelled('Cancelled. Completed downloads were kept.')
        if cancel.is_set():
            raise Cancelled('Cancelled. Completed downloads were kept.')
        status('Resuming…')


def validate_url(url: str, domains=MEDIA_DOMAINS) -> str:
    parsed = urllib.parse.urlsplit(url)
    host = (parsed.hostname or '').lower()
    if (parsed.scheme != 'https' or parsed.username or parsed.password
            or parsed.port not in (None, 443)
            or not any(host == d or host.endswith('.' + d) for d in domains)):
        raise DownloadError('Only HTTPS connections to supported TeraBox domains are allowed.')
    return url


def share_id(url: str) -> str:
    validate_url(url, SHARE_DOMAINS)
    parsed = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qs(parsed.query)
    if query.get('surl'):
        value = query['surl'][0]
    elif parsed.path.startswith('/s/1'):
        value = parsed.path[4:].rstrip('/')
    else:
        raise DownloadError('Paste a TeraBox /s/1… or sharing/link?surl=… link.')
    if not re.fullmatch(r'[A-Za-z0-9_-]{5,160}', value):
        raise DownloadError('The share identifier is not valid.')
    return value


def safe_name(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).strip(' .')[:170].rstrip(' .')
    if not name:
        name = 'video'
    if name.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}:
        name = '_' + name
    return name


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


@dataclass
class Video:
    name: str
    size: int
    fid: str
    direct: str = ''


class TeraBox:
    def __init__(self, cancel=None, status=lambda text: None, firefox_profile=None, pause=None):
        self.cancel = cancel or threading.Event()
        self.pause = pause
        self.status = status
        self.cookies = http.cookiejar.CookieJar()
        self.firefox_profile = firefox_profile
        self.session_origin = ''
        self.authenticated = False
        self.bdstoken = ''
        if firefox_profile:
            try:
                session = load_session(firefox_profile)
            except SessionError as error:
                raise DownloadError(str(error)) from None
            self.cookies = session.cookies
            self.session_origin = session.origin
        # Do not inherit HTTP proxy settings. System VPN routing still applies.
        self.http = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), SafeRedirect(),
            urllib.request.HTTPCookieProcessor(self.cookies))
        self.origin = ''
        self.token = ''
        self.pcf = ''
        self.surl = ''
        self.metadata = {}

    def bootstrap(self, url):
        with self.open(url) as response:
            final = urllib.parse.urlsplit(response.url)
            validate_url(response.url, SHARE_DOMAINS)
            self.origin = f'https://{final.hostname}'
            page = response.read(4 * 1024 * 1024).decode('utf-8', errors='replace')
        match = re.search(r'fn%28%22(.*?)%22%29', page)
        if not match:
            raise DownloadError('TeraBox changed its page format or returned a challenge. Open the share in Firefox and retry.')
        self.token = match.group(1)
        template = re.search(r'var\s+templateData\s*=\s*(\{.*?\})\s*;</script>', page, re.S)
        try:
            values = json.loads(template.group(1)) if template else {}
        except ValueError:
            values = {}
        self.pcf = str(values.get('pcftoken', ''))
        self.bdstoken = str(values.get('bdstoken', ''))
        return bool(values.get('uk'))

    def verify_login(self):
        if not self.firefox_profile:
            return False
        self.status('Checking your Firefox TeraBox session…')
        self.bootstrap(self.session_origin + '/main')
        try:
            quota = self.api('/api/quota', {'checkfree': 1, 'checkexpire': 1, 'bdstoken': self.bdstoken})
        except Cancelled:
            raise
        except DownloadError:
            raise DownloadError('TeraBox did not accept the saved Firefox session. Open TeraBox in that profile, sign in again if asked, then close Firefox and retry.', kind='login') from None
        if 'total' not in quota or 'used' not in quota:
            raise DownloadError('TeraBox did not confirm account access. Refresh your login in Firefox.', kind='login')
        self.authenticated = True
        return True

    def check_cancel(self):
        _wait_for_download(self.cancel, self.pause, self.status)

    def open(self, url, data=None, headers=None):
        self.check_cancel()
        validate_url(url)
        defaults = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/135.0.0.0 Safari/537.36', 'Accept-Encoding': 'identity'}
        if self.origin:
            defaults['Referer'] = self.origin + '/'
        defaults.update(headers or {})
        request = urllib.request.Request(url, data=data, headers=defaults)
        try:
            return self.http.open(request, timeout=25)
        except urllib.error.HTTPError as error:
            from recovery import retry_delay
            kind = ('transient' if error.code in (429, 500, 502, 503, 504) else
                    'login' if error.code in (401, 403) else 'restart' if error.code == 416 else 'access')
            delay = retry_delay(error.headers.get('Retry-After'))
            error.close()
            raise DownloadError(f'TeraBox returned HTTP {error.code}. No external fallback was used.', kind=kind, retry_after=delay) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise DownloadError('Could not connect to TeraBox directly. If Firefox also cannot open the share, your network is blocking or interrupting TeraBox; this app does not route around that restriction.', kind='transient') from None

    def api(self, endpoint, params=None, body=None):
        query = {'app_id': 250528, 'web': 1, 'channel': 'dubox', 'clienttype': 0,
                 'jsToken': self.token, 'pcftoken': self.pcf}
        query.update(params or {})
        url = self.origin + endpoint + '?' + urllib.parse.urlencode(query)
        data = urllib.parse.urlencode(body).encode() if body is not None else None
        with self.open(url, data) as response:
            raw = response.read(4 * 1024 * 1024 + 1)
        if len(raw) > 4 * 1024 * 1024:
            raise DownloadError('TeraBox returned an unexpectedly large API response.')
        try:
            result = json.loads(raw)
        except (ValueError, UnicodeError):
            raise DownloadError('TeraBox returned a page instead of file information. Retry later.') from None
        if not isinstance(result, dict):
            raise DownloadError('Unexpected TeraBox response.')
        if result.get('errno') != 0:
            code = result.get('errno', 'unknown')
            raise DownloadError(f'TeraBox rejected {endpoint} (code {code}).')
        return result

    def find_videos(self, link):
        self.surl = share_id(link.strip())
        if self.firefox_profile:
            self.verify_login()
            self.status('Opening the share with your Firefox login…')
            share_url = self.origin + '/sharing/link?' + urllib.parse.urlencode({'surl': self.surl})
        else:
            self.status('Opening an anonymous TeraBox session…')
            share_url = link.strip()
        self.bootstrap(share_url)
        password = urllib.parse.parse_qs(urllib.parse.urlsplit(link).query).get('pwd', [''])[0]
        if password:
            self.api('/share/verify', {'surl': self.surl}, {'pwd': password})
        self.metadata = self.api('/api/shorturlinfo', {'shorturl': '1' + self.surl, 'root': 1, 'page': 1, 'num': 20})
        self.status('Reading shared folders…')
        pending = [None]
        visited = set()
        videos = []
        while pending:
            directory = pending.pop()
            if directory in visited:
                continue
            visited.add(directory)
            if len(visited) > 100:
                raise DownloadError('This share has more than 100 folders. Use a smaller share.')
            for page_number in range(1, 101):
                self.check_cancel()
                params = {'shorturl': self.surl, 'root': 1 if directory is None else 0, 'page': page_number, 'num': 100, 'by': 'name', 'order': 'asc'}
                if directory is not None:
                    params['dir'] = directory
                entries = self.api('/share/list', params).get('list', [])
                if not isinstance(entries, list):
                    raise DownloadError('TeraBox returned an invalid file list.')
                for entry in entries:
                    if str(entry.get('isdir')) == '1':
                        pending.append(entry['path'])
                    elif Path(entry.get('server_filename', '')).suffix.lower() in VIDEO_EXTENSIONS:
                        videos.append(Video(entry['server_filename'], int(entry.get('size', 0)), str(entry['fs_id']), entry.get('dlink') or ''))
                if len(entries) < 100:
                    break
            else:
                raise DownloadError('This folder is too large to list completely.')
        if not videos:
            raise DownloadError('No supported video files were found in this share.')
        return videos

    def download_url(self, video):
        if video.direct:
            return validate_url(video.direct)
        self.status('Requesting the original video…')
        meta = self.metadata
        try:
            result = self.api('/share/download', {
                'shareid': meta['shareid'], 'sign': meta['sign'], 'timestamp': meta['timestamp'],
                'type': 'dlink', 'need_speed': 0, 'scene': '', 'bdstoken': self.bdstoken}, {
                'product': 'share', 'uk': meta.get('uk_str') or meta['uk'],
                'fid_list': json.dumps([int(video.fid)]), 'primaryid': meta['shareid']})
        except Cancelled:
            raise
        except DownloadError as error:
            mode = 'with your Firefox session' if self.firefox_profile else 'without login'
            raise DownloadError(f'The video is visible, but TeraBox did not provide a full-download link {mode}.\n\n' + str(error) + '\n\nNo preview or partial movie was saved.', kind=error.kind, retry_after=error.retry_after) from None
        direct = result.get('dlink')
        if isinstance(direct, list):
            direct = direct[0].get('dlink') if direct else None
        if not direct and isinstance(result.get('list'), list):
            direct = next((entry.get('dlink') for entry in result['list'] if str(entry.get('fs_id')) == video.fid), None)
        if not isinstance(direct, str) or not direct:
            raise DownloadError('TeraBox returned no original-file URL. No preview was saved.')
        return validate_url(direct)

    def download(self, video, folder, progress=lambda received, total: None, *, checkpoint=None):
        if checkpoint is not None:
            from transfer_state import download
            return download(self, video, folder, progress, checkpoint)
        self.check_cancel()
        if video.size <= 0:
            raise DownloadError('TeraBox did not report a file size, so completeness cannot be verified.')
        url = self.download_url(video)
        folder = Path(folder).resolve()
        folder.mkdir(parents=True, exist_ok=True)
        name = safe_name(video.name)
        target = folder / name
        if os.path.lexists(target):
            raise DownloadError('A file with this name already exists. Choose another folder or rename it.')
        temporary = folder / (name + '.' + safe_name(video.fid) + '.part')
        received = 0
        self.status('Downloading the original video…')
        try:
            # Exclusive create prevents accidental reuse or overwrite of another partial file.
            with temporary.open('xb') as output:
                with self.open(url) as response:
                    if response.status != 200:
                        raise DownloadError('TeraBox returned an unexpected download status.')
                    mime = response.headers.get('Content-Type', '').lower()
                    if any(value in mime for value in ('text/', 'json', 'mpegurl')):
                        raise DownloadError('TeraBox returned a page or playlist instead of the original video.')
                    length = response.headers.get('Content-Length')
                    if length and int(length) != video.size:
                        raise DownloadError('The download size differs from the original file. Download stopped.')
                    while True:
                        self.check_cancel()
                        chunk = response.read(1024 * 256)
                        if not chunk:
                            break
                        received += len(chunk)
                        if received > video.size:
                            raise DownloadError('The response exceeded the expected file size.')
                        output.write(chunk)
                        progress(received, video.size)
            if received != video.size:
                raise DownloadError('The connection ended before the complete video arrived.')
            self.check_cancel()
            # Windows rename fails if target already exists; never replace an existing video.
            if os.path.lexists(target):
                raise DownloadError('A file with this name appeared during the download.')
            temporary.rename(target)
            return target
        except FileExistsError:
            raise DownloadError('A partial file with this name already exists. Choose another folder.') from None
        except Exception:
            temporary.unlink(missing_ok=True)
            raise


def parse_links(text):
    links = []
    for number, line in enumerate(text.splitlines(), 1):
        for value in line.split(','):
            value = value.strip()
            if not value:
                continue
            try:
                share_id(value)
            except DownloadError as error:
                raise DownloadError(f'Invalid link on line {number}: {error}') from None
            links.append(value)
    if not links:
        raise DownloadError('Paste at least one TeraBox share link.')
    return links


def download_queue(links, folder, firefox_profile, cancel, event=lambda *args: None, client_factory=None, pause=None):
    """Download every video in each link, reporting progress through ``event``."""
    client_factory = client_factory or TeraBox
    completed, failures = [], []
    status = lambda text: event('status', text)
    for link_index, link in enumerate(links):
        status = lambda text: event('status', (link_index, text))
        _wait_for_download(cancel, pause, status)
        event('queue', (link_index, 'Opening share…'))
        try:
            client = client_factory(cancel, status, firefox_profile, **({'pause': pause} if pause is not None else {}))
            videos = client.find_videos(link)
        except Cancelled:
            raise
        except DownloadError as error:
            failures.append(f'Link {link_index + 1}: {error}')
            event('queue', (link_index, 'Failed'))
            continue
        link_failed = False
        for video_index, video in enumerate(videos):
            _wait_for_download(cancel, pause, status)
            event('queue', (link_index, f'Downloading {video_index + 1}/{len(videos)}: {video.name}'))
            last = [0.0]
            def update(received, total):
                now = time.monotonic()
                if now - last[0] > .15 or received == total:
                    event('progress', (link_index, received, total))
                    last[0] = now
            try:
                path = client.download(video, folder, update)
            except Cancelled:
                raise
            except DownloadError as error:
                failures.append(f'Link {link_index + 1}, {video.name}: {error}')
                link_failed = True
            else:
                completed.append(str(path))
        event('queue', (link_index, 'Completed with errors' if link_failed else 'Completed'))
    _wait_for_download(cancel, pause, status)
    return completed, failures


def human_size(size):
    return f'{size / 1024 ** 3:.2f} GB' if size >= 1024 ** 3 else f'{size / 1024 ** 2:.1f} MB'


SETTINGS_PATH = Path(__file__).parent / '.tera-settings.json'


def load_settings():
    try:
        result = json.loads(SETTINGS_PATH.read_text(encoding='utf-8'))
        return result if isinstance(result, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(profile):
    # Deliberately contains no usernames, credentials, cookies, or share URLs.
    SETTINGS_PATH.write_text(json.dumps({'firefox_profile': str(profile.path) if profile else None}), encoding='utf-8')


def open_firefox(profile, link):
    if link:
        validate_url(link, SHARE_DOMAINS)
    else:
        link = 'https://www.terabox.com/'
    candidates = [Path(os.environ.get(root, '')) / 'Mozilla Firefox' / 'firefox.exe'
                  for root in ('ProgramFiles', 'ProgramFiles(x86)', 'LOCALAPPDATA')]
    executable = next((path for path in candidates if path.is_file()), None)
    if executable is None:
        raise DownloadError('Open Firefox manually, sign into TeraBox, then click Check login.')
    args = [str(executable)]
    if profile:
        args.extend(['-P', profile.name])
    subprocess.Popen(args + ['-new-tab', link])


def gui(data_dir=None):
    from tera_gui import gui as launch_gui
    launch_gui(data_dir)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, help='Use an isolated local queue/settings directory.')
    parser.add_argument('--check', metavar='URL', help='List videos and test original-file URL resolution without downloading.')
    parser.add_argument('--firefox', action='store_true', help='Use the default Firefox profile for the check.')
    parser.add_argument('--profile', help='Firefox profile name to use with --firefox.')
    args = parser.parse_args()
    if not args.check:
        gui(args.data_dir)
        return
    try:
        profile = None
        if args.firefox:
            available = profiles()
            profile = next((p for p in available if p.name == args.profile), None) if args.profile else next(iter(available), None)
            if not profile:
                raise DownloadError('Firefox profile not found. Open Firefox once or check --profile.')
        client = TeraBox(firefox_profile=profile)
        for video in client.find_videos(args.check):
            result = {'name': video.name, 'bytes': video.size}
            try:
                client.download_url(video)
                result['status'] = 'url_resolved_not_download_verified'
            except DownloadError as error:
                result.update(status='unavailable', reason=str(error))
            print(json.dumps(result))
    except (DownloadError, SessionError) as error:
        print(json.dumps({'status': 'failed', 'reason': str(error)}))
        raise SystemExit(1)


if __name__ == '__main__':
    main()
