"""Explicit website-assisted, finite MPEG-TS streams. No browser-cookie access."""
from contextlib import nullcontext
import json
import hashlib
import http.client
import math
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request
import uuid

from terabox import Cancelled, DownloadError, TeraBox, Video, safe_name

PLAYER_HOST = 'teradownloader.com'
MEDIA_HOST = 'play.terafile.workers.dev'
MAX_PLAYLIST = 2 * 1024 * 1024


def is_website_source(link):
    try:
        return urllib.parse.urlsplit(link).hostname in {PLAYER_HOST, MEDIA_HOST}
    except ValueError:
        return False


def _https(parsed, host):
    return (parsed.scheme == 'https' and parsed.hostname == host and parsed.username is None
            and parsed.password is None and parsed.port in (None, 443) and not parsed.fragment)


def validate_media(url):
    try:
        if not _https(urllib.parse.urlsplit(url), MEDIA_HOST):
            raise ValueError
    except ValueError:
        raise DownloadError('The website stream must use its supported HTTPS relay.') from None
    return url


def parse_source(link):
    try:
        if not isinstance(link, str) or len(link) > 32768 or any(ord(c) < 32 for c in link):
            raise ValueError
        parsed = urllib.parse.urlsplit(link.strip())
        name = 'stream'
        if parsed.hostname == PLAYER_HOST:
            if not _https(parsed, PLAYER_HOST) or parsed.path != '/player':
                raise ValueError
            query = urllib.parse.parse_qs(parsed.query)
            if len(query.get('url', [])) != 1 or len(query.get('filename', [])) > 1:
                raise ValueError
            url = urllib.parse.unquote(query['url'][0])
            name = urllib.parse.unquote(query.get('filename', ['stream'])[0])
        else:
            url = link.strip()
        validate_media(url)
        return url, safe_name(Path(safe_name(name)).stem + '.ts')
    except (ValueError, TypeError):
        raise DownloadError('Paste the generated website player link or its supported relay link.') from None


class RelayRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_media(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class WebsiteStream(TeraBox):
    def __init__(self, cancel=None, status=lambda text: None, firefox_profile=None, pause=None, **unused):
        # The selected Firefox account and direct-route proxy never cross this boundary.
        super().__init__(cancel, status, pause=pause)
        self.http = urllib.request.build_opener(urllib.request.ProxyHandler({}), RelayRedirect())
        self.parts = []
        self.duration = 0

    def open(self, url):
        self.check_cancel()
        validate_media(url)
        request = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/156.0.0.0 Safari/537.36',
            'Referer': 'https://teradownloader.com/', 'Accept-Encoding': 'identity'})
        try:
            return self.http.open(request, timeout=25)
        except urllib.error.HTTPError as error:
            transient = error.code in {429, 500, 502, 503, 504}
            from recovery import retry_delay
            delay = retry_delay(error.headers.get('Retry-After')) if error.headers else 5
            error.close()
            raise DownloadError('The website stream is unavailable. Generate a fresh player link on the website.',
                                kind='expired' if error.code in (401,403,410) else 'transient' if transient else 'access', retry_after=delay) from None
        except (urllib.error.URLError, OSError):
            raise DownloadError('Could not connect to the website relay. No direct TeraBox fallback was used.', kind='transient') from None

    def find_videos(self, link):
        source, name = parse_source(link)
        self.status('Reading the website stream playlistâ€¦')
        try:
            with self.open(source) as response:
                raw = response.read(MAX_PLAYLIST + 1)
            if len(raw) > MAX_PLAYLIST:
                raise DownloadError('The website playlist exceeds the supported size.')
            text = raw.decode('utf-8-sig')
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            if (not lines or lines[0] != '#EXTM3U' or '#EXT-X-ENDLIST' not in lines
                    or '#EXT-X-GAP' in lines or '#EXT-X-I-FRAMES-ONLY' in lines):
                raise DownloadError('A finite, complete website playlist is required. Live or incomplete playlists are not downloaded.')
            unsupported = ('#EXT-X-STREAM-INF:', '#EXT-X-MEDIA:', '#EXT-X-MAP:', '#EXT-X-BYTERANGE:')
            if (any(line.startswith(unsupported) for line in lines)
                    or any(line.startswith('#EXT-X-KEY:') and line != '#EXT-X-KEY:METHOD=NONE' for line in lines)):
                raise DownloadError('This stream format needs additional handling. Use a finite, unencrypted MPEG-TS player link.')
            self.parts = [validate_media(urllib.parse.urljoin(source, line)) for line in lines if not line.startswith('#')]
            durations = [float(line.split(':', 1)[1].split(',', 1)[0]) for line in lines if line.startswith('#EXTINF:')]
            if (not 0 < len(self.parts) <= 10000 or len(durations) != len(self.parts)
                    or not all(math.isfinite(value) and value > 0 for value in durations)):
                raise DownloadError('The website playlist does not describe a complete supported video.')
            self.manifest = hashlib.sha256(json.dumps([self.parts, durations, [line for line in lines if line.startswith('#')]],sort_keys=True).encode()).hexdigest()
            self.durations = durations
            self.duration = sum(durations)
            identity = hashlib.sha256((source + repr(durations)).encode()).hexdigest()[:24]
            self.video = Video(name, 0, 'stream-' + identity)
            return [self.video]
        except (UnicodeError, ValueError):
            raise DownloadError('The website returned an invalid stream playlist.') from None
        except (OSError, http.client.HTTPException):
            raise DownloadError('The website playlist was interrupted. Generate a fresh link and retry.', kind='transient') from None

    def download(self, video, folder, progress=lambda *_: None, *, checkpoint=None, policy=None):
        from review_storage import available_space, preflight
        self.check_cancel()
        if not self.parts or video.fid != self.video.fid or Path(video.name).suffix.lower() != '.ts':
            raise DownloadError('Review this website stream first and keep its .ts streaming-copy extension.')
        folder = Path(folder).resolve()
        preflight(folder, 0, video.name, video.fid)
        target = folder / safe_name(video.name)
        state = checkpoint
        if state:
            state.prepare(self.manifest)
            state.verify(self.check_cancel,self.status)
        received = expected = state.record['offset'] if state else 0
        progress(received,0)
        workspace = nullcontext(str(state.path)) if state else tempfile.TemporaryDirectory(prefix='.tera-stream-',dir=folder)
        with workspace as directory:
            work = Path(directory).resolve()
            if work.parent != folder:
                raise DownloadError('The stream workspace is not inside its destination.')
            parts = []
            try:
                for index, url in enumerate(self.parts):
                    self.check_cancel()
                    self.status(f'Downloading website stream: segment {index + 1} of {len(self.parts)}â€¦')
                    part = work / f'part{index:05d}.ts'
                    parts.append(part)
                    if state and index < len(state.record['segments']):
                        continue
                    self.status(f'Downloading segments: {index} / {len(self.parts)} verified; {received} saved bytes')
                    incomplete = work / 'incomplete'
                    for leftover in (incomplete,part):
                        if leftover.exists():
                            from stream_checkpoint import identity
                            identity(leftover);leftover.unlink()
                    with self.open(url) as response, incomplete.open('xb') as output:
                        mime = response.headers.get('Content-Type', '').lower()
                        length = response.headers.get('Content-Length', '')
                        if (response.status not in (200, 206) or any(value in mime for value in ('text/', 'json', 'mpegurl'))
                                or not str(length).isdigit() or int(length) <= 0):
                            raise DownloadError('The website did not provide a verifiable media segment. No incomplete video was kept.')
                        length = int(length)
                        if response.status == 206:
                            span = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+|\*)', response.headers.get('Content-Range', ''))
                            if (not span or int(span[2]) - int(span[1]) + 1 != length
                                    or span[3] != '*' and int(span[2]) >= int(span[3])):
                                raise DownloadError('The website returned an invalid media range.')
                        if length % 188:
                            raise DownloadError('The website returned an unsupported media segment.')
                        if available_space(folder) < length:
                            raise DownloadError('Not enough space for the stream. Choose another folder.', kind='storage')
                        expected += length
                        part_received = 0
                        while True:
                            self.check_cancel()
                            try:
                                chunk = response.read(min(64 * 1024, policy.before_read(self) if policy else 64 * 1024))
                            except (OSError, http.client.HTTPException):
                                raise DownloadError('A media segment was interrupted. No incomplete video was kept.', kind='transient') from None
                            if not chunk:
                                break
                            if part_received + len(chunk) > length:
                                raise DownloadError('A media segment exceeded its expected size.')
                            start = (-part_received) % 188
                            if any(chunk[offset] != 0x47 for offset in range(start, len(chunk), 188)):
                                raise DownloadError('The website returned unsupported media data.')
                            output.write(chunk)
                            part_received += len(chunk)
                            received += len(chunk)
                            if policy:
                                policy.received(len(chunk))
                            progress(received, 0)
                        if part_received != length:
                            raise DownloadError('A media segment ended early. Verified segments were kept.', kind='transient')
                        output.flush();os.fsync(output.fileno())
                    incomplete.rename(part)
                    if state:state.segment(index,part)
                if received != expected:
                    raise DownloadError('The stream byte count could not be verified.')
                needed = expected + max(64 * 1024 * 1024, expected // 10)
                if available_space(folder) < needed:
                    raise DownloadError('More free space is needed to join the stream. Choose another folder.', kind='storage')
                joined = work / 'joined.ts'
                for leftover in (joined,work/'join.ffconcat',work/'assembly.log'):
                    if leftover.exists():
                        from stream_checkpoint import identity
                        identity(leftover);leftover.unlink()
                assemble(parts, self.durations, joined, self)
                self.check_cancel()
                if not joined.is_file() or joined.stat().st_size <= 0 or joined.stat().st_size % 188:
                    raise DownloadError('The streaming copy could not be validated. No completed file was kept.')
                if os.name != 'nt':
                    raise DownloadError('Transactional stream completion is supported on Windows.')
                with joined.open('r+b') as output:os.fsync(output.fileno())
                if state:state.ready(joined)
                joined.rename(target)
                if state:state.discard_owned()
                progress(received, received)
                return target
            except OSError:
                raise DownloadError('The stream could not be saved. Check free space and the destination.', kind='storage') from None
            finally:
                incomplete=work/'incomplete'
                if incomplete.exists():
                    from stream_checkpoint import identity
                    identity(incomplete);incomplete.unlink()


def ffmpeg_path():
    root = Path(__file__).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[1]
    executable = root / ('tools' if getattr(sys, 'frozen', False) else '.tools') / 'stream-ffmpeg.exe'
    if not executable.is_file():
        raise DownloadError('The bundled stream assembly tool is missing. Reinstall Tera.')
    return executable


def assemble(parts, durations, target, client):
    work = target.parent.resolve()
    if len(parts) != len(durations) or not parts or any(part.parent.resolve() != work or not re.fullmatch(r'part[0-9]{5}\.ts', part.name) for part in parts):
        raise DownloadError('Invalid local stream assembly inputs.')
    playlist = work / 'join.ffconcat'
    with playlist.open('x', encoding='utf-8') as output:
        output.write('ffconcat version 1.0\n')
        for part, duration in zip(parts, durations):
            if not math.isfinite(duration) or duration <= 0:
                raise DownloadError('Invalid stream timing.')
            output.write(f"file '{part.name}'\nduration {duration:.9f}\n")
    client.check_cancel()
    client.status('Joining the website streaming copyâ€¦')
    with (work / 'assembly.log').open('x', encoding='utf-8') as log:
        child = subprocess.Popen([str(ffmpeg_path()), '-hide_banner', '-loglevel', 'error', '-nostdin', '-n',
            '-protocol_whitelist', 'file', '-f', 'concat', '-safe', '1', '-i', playlist.name,
            '-map', '0', '-c', 'copy', '-f', 'mpegts', target.name], cwd=work,
            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW)
        log.write(f'owned_ffmpeg_pid={child.pid} local_stream_copy\n')
        log.flush()
        expires = time.monotonic() + 120
        try:
            while child.poll() is None:
                client.check_cancel()
                if time.monotonic() >= expires:
                    raise DownloadError('Local stream assembly exceeded its time limit.')
                client.cancel.wait(.05)
            client.check_cancel()
            if child.returncode:
                raise DownloadError('The downloaded segments could not be joined. No completed video was kept.')
        finally:
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=3)
