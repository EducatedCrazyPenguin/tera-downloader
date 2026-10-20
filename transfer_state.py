"""Owned durable bytes and conservative HTTP continuation; no credentials or URLs."""
from copy import deepcopy
import hashlib
import http.client
import os
from pathlib import Path
import re
import stat
import time
import uuid

from terabox import Cancelled, DownloadError, safe_name


class RestartRequired(DownloadError):
    def __init__(self, message='Resume cannot be verified. Choose Restart from zero explicitly.'):
        super().__init__(message, kind='restart')


def strong_etag(value):
    return value if isinstance(value, str) and re.fullmatch(r'"[\x21\x23-\x7e\x80-\xff]{0,254}"', value) else ''


def fresh_checkpoint(binding):
    return {'version': 1, 'token': uuid.uuid4().hex, 'binding': binding, 'offset': 0,
            'etag': '', 'digest': hashlib.sha256(b'').hexdigest(), 'file_id': [], 'phase': 'partial'}


class Checkpoint:
    def __init__(self, record, folder, name, size, binding, commit, discard, *, verification=None):
        self.record = deepcopy(record)
        self.size, self.commit, self.discard = size, commit, discard
        self.folder = Path(folder).resolve()
        self.target = self.folder / safe_name(name)
        expected = {'version', 'token', 'binding', 'offset', 'etag', 'digest', 'file_id', 'phase'}
        if (not isinstance(record, dict) or set(record) != expected or record['version'] != 1
                or not isinstance(record['token'], str) or not re.fullmatch('[a-f0-9]{32}', record['token'])
                or record['binding'] != binding or type(record['offset']) is not int
                or not 0 <= record['offset'] <= size or record['phase'] not in {'partial', 'ready', 'invalid'}
                or not isinstance(record['digest'], str) or not re.fullmatch('[a-f0-9]{64}', record['digest'])
                or record['etag'] != '' and not strong_etag(record['etag'])
                or not isinstance(record['file_id'], list) or len(record['file_id']) not in (0, 2)
                or any(type(n) is not int or n < 0 for n in record['file_id'])
                or (record['offset'] > 0 or record['phase'] == 'ready') and len(record['file_id']) != 2
                or record['phase'] == 'ready' and record['offset'] != size):
            raise RestartRequired('Saved checkpoint is invalid or belongs to another file. Restart is required.')
        self.path = self.folder / ('.tera-' + record['token'] + '.part')
        self.hasher = hashlib.sha256()
        self.check = lambda: None
        self.verification = verification or (lambda done, total: None)

    def _owned(self):
        try:
            info = self.path.lstat()
            return (stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                    and [info.st_dev, info.st_ino] == self.record['file_id'])
        except OSError:
            return False

    def discard_owned(self):
        if self._owned():
            self.path.unlink()

    def open_partial(self):
        if self.record['phase'] == 'invalid':
            raise RestartRequired('The saved transfer failed verification. Restart is required.')
        if not self.record['file_id']:
            if self.record['offset'] or os.path.lexists(self.path):
                raise RestartRequired('The partial file has no ownership record. It was left untouched.')
            self.folder.mkdir(parents=True, exist_ok=True)
            output = self.path.open('x+b')
            info = os.fstat(output.fileno())
            self.record['file_id'] = [info.st_dev, info.st_ino]
            try:
                self.sync(output, self.hasher, 0, '')
                return output
            except BaseException:
                output.close()
                self.discard_owned()  # This attempt created the still-empty file; no bytes were committed.
                raise
        if not self._owned():
            raise RestartRequired('The owned partial is missing or was replaced. It was left untouched.')
        output = self.path.open('r+b')
        try:
            info = os.fstat(output.fileno())
            if (not self._owned() or info.st_nlink != 1 or [info.st_dev, info.st_ino] != self.record['file_id']
                    or info.st_size < self.record['offset']):
                raise RestartRequired('The partial is shorter than its durable checkpoint. Restart is required.')
            remaining = self.record['offset']
            self.hasher = hashlib.sha256()
            self.verification(0, remaining)
            while remaining:
                self.check()
                chunk = output.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise RestartRequired()
                self.hasher.update(chunk)
                remaining -= len(chunk)
                self.verification(self.record['offset'] - remaining, self.record['offset'])
            if self.hasher.hexdigest() != self.record['digest']:
                raise RestartRequired('The saved bytes changed. They were not appended or finalized.')
            if info.st_size != self.record['offset']:
                output.truncate(self.record['offset'])
                output.flush()
                os.fsync(output.fileno())
            output.seek(self.record['offset'])
            return output
        except BaseException:
            output.close()
            raise

    def sync(self, output, hasher, offset, etag, phase='partial'):
        output.flush()
        os.fsync(output.fileno())
        value = {**self.record, 'offset': offset, 'digest': hasher.hexdigest(), 'etag': etag, 'phase': phase}
        if self.commit(deepcopy(value)) is False:
            raise Cancelled('The transfer was stopped.')
        self.record = value

    def reconcile(self):
        if self.record['phase'] == 'invalid':
            raise RestartRequired()
        if self.record['phase'] != 'ready' or os.path.lexists(self.path):
            return None
        try:
            info = self.target.lstat()
            if (not stat.S_ISREG(info.st_mode) or info.st_size != self.size or info.st_nlink != 1
                    or [info.st_dev, info.st_ino] != self.record['file_id']):
                raise RestartRequired()
            with self.target.open('rb') as saved:
                opened = os.fstat(saved.fileno())
                if [opened.st_dev, opened.st_ino] != self.record['file_id']:
                    raise RestartRequired()
                hasher = hashlib.sha256()
                checked = 0
                self.verification(0, self.size)
                while True:
                    self.check()
                    chunk = saved.read(1024 * 1024)
                    if not chunk:
                        break
                    hasher.update(chunk)
                    checked += len(chunk)
                    self.verification(checked, self.size)
                digest = hasher.hexdigest()
            if digest != self.record['digest']:
                raise RestartRequired('A different final file exists. It was left untouched.')
            return self.target
        except OSError:
            raise RestartRequired('Finalization was interrupted and its output cannot be verified.') from None

    def finalize(self):
        if not self._owned() or os.path.lexists(self.target):
            raise DownloadError('A final file exists or the owned partial changed. Choose another destination.', kind='storage')
        if os.name == 'nt':
            self.path.rename(self.target)  # Windows rename never replaces an existing target.
        else:
            os.link(self.path, self.target)
            self.path.unlink()
        return self.target


def validate_response(response, offset, size, etag):
    headers = response.headers
    mime = headers.get('Content-Type', '').lower()
    invalid = (any(value in mime for value in ('text/', 'json', 'mpegurl', 'multipart/'))
               or headers.get('Content-Encoding', 'identity').lower() != 'identity')
    if offset:
        expected_range = f'bytes {offset}-{size - 1}/{size}'
        if (invalid or response.status != 206 or headers.get('Content-Range') != expected_range
                or headers.get('ETag') != etag or headers.get('Content-Length') != str(size - offset)):
            raise RestartRequired('The server did not confirm the exact saved representation/range. Restart is required.')
    elif (invalid or response.status != 200 or headers.get('Content-Range')
          or headers.get('Content-Length') not in (None, str(size))):
        raise DownloadError('The response is not the complete original representation.', kind='integrity')
    return strong_etag(headers.get('ETag', ''))


def download(client, video, folder, progress, state, policy=None):
    state.check = client.check_cancel
    output = None
    received = state.record['offset']
    etag = state.record['etag']
    try:
        client.check_cancel()
        result = state.reconcile()
        if result:
            return result
        if state.record['phase'] == 'ready':
            with state.open_partial():
                pass
            client.check_cancel()
            return state.finalize()
        if received and (not etag or received >= video.size):
            raise RestartRequired('No strong validator is available for this partial. Restart is required.')
        output = state.open_partial()
        progress(received, video.size)
        url = client.download_url(video)
        headers = {'Range': f'bytes={received}-', 'If-Range': etag} if received else None
        try:
            response = client.open(url, headers=headers)
        except DownloadError as error:
            if received and error.kind == 'restart':
                raise RestartRequired() from None
            if error.kind == 'login':
                raise DownloadError('The media URL expired. Refreshing through the selected source may help.', kind='expired', retry_after=error.retry_after) from None
            raise
        with response:
            etag = validate_response(response, received, video.size, etag)
            last_sync, last_time = received, time.monotonic()
            def check():
                if client.pause is not None and client.pause.is_set() and received != state.record['offset']:
                    state.sync(output, state.hasher, received, etag)
                client.check_cancel()
            while True:
                check()
                read_size = policy.before_read(client, check) if policy else 256 * 1024
                try:
                    chunk = response.read(read_size)
                except (http.client.HTTPException, TimeoutError, OSError):
                    raise DownloadError('The connection was interrupted; verified partial bytes were kept.', kind='transient') from None
                if not chunk:
                    break
                if policy:
                    policy.received(len(chunk))
                if received + len(chunk) > video.size:
                    raise DownloadError('The response exceeded the expected size.', kind='integrity')
                output.write(chunk)
                state.hasher.update(chunk)
                received += len(chunk)
                progress(received, video.size)
                now = time.monotonic()
                if received - last_sync >= 1024 * 1024 or now - last_time >= 2:
                    state.sync(output, state.hasher, received, etag)
                    last_sync, last_time = received, now
        if received != video.size:
            raise DownloadError('The connection ended before the complete file arrived.', kind='transient')
        state.sync(output, state.hasher, received, etag, phase='ready')
        output.close()
        output = None
        client.check_cancel()
        return state.finalize()
    except (Cancelled, DownloadError) as error:
        if output is not None and not state.discard.is_set():
            if isinstance(error, Cancelled) or error.kind in {'transient', 'expired'}:
                state.sync(output, state.hasher, received, etag)
            elif error.kind == 'integrity':
                state.sync(output, state.hasher, received, etag, phase='invalid')
        raise
    finally:
        if output is not None:
            output.close()
        if state.discard.is_set():
            state.discard_owned()
