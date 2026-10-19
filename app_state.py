"""Local queue storage. Source links are protected with current-user Windows DPAPI."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import uuid


class StateError(Exception):
    pass


class _Blob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]


def _crypt(data, decrypt=False):
    if os.name != 'nt':
        raise StateError('Saving private source links requires Windows data protection.')
    source = ctypes.create_string_buffer(data)
    incoming = _Blob(len(data), ctypes.cast(source, ctypes.POINTER(ctypes.c_ubyte)))
    outgoing = _Blob()
    library = ctypes.WinDLL('crypt32', use_last_error=True)
    function = library.CryptUnprotectData if decrypt else library.CryptProtectData
    function.argtypes = [ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob)]
    function.restype = wintypes.BOOL
    # UI_FORBIDDEN; do not use machine-wide protection or show credential prompts.
    if not function(ctypes.byref(incoming), None, None, None, None, 1, ctypes.byref(outgoing)):
        raise StateError('Windows could not protect or unlock saved links. No plaintext fallback was used.')
    try:
        return ctypes.string_at(outgoing.data, outgoing.size)
    finally:
        free = ctypes.WinDLL('kernel32', use_last_error=True).LocalFree
        free.argtypes = [ctypes.c_void_p]
        free.restype = ctypes.c_void_p
        free(outgoing.data)


def protect(data):
    return _crypt(data)


def unprotect(data):
    return _crypt(data, True)


def default_data_dir():
    location = os.environ.get('LOCALAPPDATA')
    if not location:
        raise StateError('The Windows local application-data folder is unavailable.')
    return Path(location) / 'Tera'


class StateStore:
    def __init__(self, directory, legacy_settings=None):
        self.directory = Path(directory).resolve()
        self.db = None
        self.lock = None
        self._sources = {}
        self._rows = None
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            self.lock = (self.directory / 'instance.lock').open('a+b')
            self.lock.seek(0, os.SEEK_END)
            if self.lock.tell() == 0:
                self.lock.write(b'\0')
                self.lock.flush()
            self.lock.seek(0)
            try:
                self._file_lock(False)
            except OSError:
                self.lock.close()
                self.lock = None
                raise StateError('Tera is already using this data folder. Open the existing instance.') from None
            self.db = sqlite3.connect(self.directory / 'queue.sqlite', timeout=2)
            version = self.db.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0, 1):
                raise StateError('This queue belongs to a newer Tera version. Its data was left unchanged.')
            if version == 0:
                if self.db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchone():
                    raise StateError('The queue database has an unknown format. Its data was left unchanged.')
                with self.db:
                    self.db.execute('CREATE TABLE jobs (id TEXT PRIMARY KEY, position INTEGER NOT NULL, source BLOB NOT NULL, payload TEXT NOT NULL)')
                    self.db.execute('PRAGMA user_version = 1')
            if not (self.directory / 'settings.json').exists():
                preferences = {}
                if legacy_settings and Path(legacy_settings).exists():
                    legacy = json.loads(Path(legacy_settings).read_text(encoding='utf-8'))
                    if isinstance(legacy, dict) and 'firefox_profile' in legacy:
                        preferences['firefox_profile'] = legacy['firefox_profile']
                self.save_preferences(preferences)
            self.load_preferences()
        except (OSError, sqlite3.Error, ValueError, StateError) as error:
            self.close()
            if isinstance(error, StateError):
                raise
            raise StateError('Local state could not be opened. Existing data was left in place; check the data folder and retry.') from None

    def _file_lock(self, unlock):
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(self.lock.fileno(), msvcrt.LK_UNLCK if unlock else msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(self.lock.fileno(), fcntl.LOCK_UN if unlock else fcntl.LOCK_EX | fcntl.LOCK_NB)

    def load_jobs(self):
        result = []
        rows = {}
        try:
            for identifier, position, source, payload in self.db.execute('SELECT id, position, source, payload FROM jobs ORDER BY position'):
                record = json.loads(payload)
                if not isinstance(record, dict):
                    raise ValueError('Invalid job')
                link = unprotect(bytes(source)).decode('utf-8')
                record.update(id=identifier, link=link)
                self._sources[identifier] = (link, bytes(source))
                rows[identifier] = (identifier, position, bytes(source), payload)
                result.append(record)
            self._rows = rows
            return result
        except (sqlite3.Error, ValueError, UnicodeError):
            raise StateError('Saved queue data could not be read. It was not reset or overwritten.') from None

    def save_jobs(self, jobs):
        if self._rows is None:
            self.load_jobs()
        rows, sources = [], {}
        # Encrypt before the transaction so any protection failure preserves the old queue.
        for position, job in enumerate(jobs):
            record = dict(job)
            identifier, link = record.pop('id'), record.pop('link')
            cached = self._sources.get(identifier)
            encrypted = cached[1] if cached and cached[0] == link else protect(link.encode('utf-8'))
            sources[identifier] = (link, encrypted)
            rows.append((identifier, position, encrypted, json.dumps(record, ensure_ascii=False)))
        try:
            current = {row[0]: row for row in rows}
            changed = [row for row in rows if self._rows.get(row[0]) != row]
            with self.db:
                self.db.executemany('DELETE FROM jobs WHERE id = ?', [(identifier,) for identifier in self._rows.keys() - current.keys()])
                self.db.executemany('INSERT INTO jobs VALUES (?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET position=excluded.position, source=excluded.source, payload=excluded.payload', changed)
            self._sources = sources
            self._rows = current
        except sqlite3.Error:
            raise StateError('The queue could not be saved. Check the data folder before continuing.') from None

    def load_preferences(self):
        try:
            result = json.loads((self.directory / 'settings.json').read_text(encoding='utf-8'))
            if not isinstance(result, dict):
                raise ValueError('Invalid preferences')
            if 'firefox_profile' in result and result['firefox_profile'] is not None and not isinstance(result['firefox_profile'], str):
                raise ValueError('Invalid profile preference')
            if 'last_destination' in result and not isinstance(result['last_destination'], str):
                raise ValueError('Invalid destination preference')
            if 'favorites' in result and (not isinstance(result['favorites'], list) or not all(
                    isinstance(item, dict) and set(item) == {'name', 'path'}
                    and all(isinstance(value, str) and value.strip() for value in item.values()) for item in result['favorites'])):
                raise ValueError('Invalid favorites')
            return result
        except (OSError, ValueError):
            raise StateError('Saved preferences could not be read. The original file was left unchanged.') from None

    def save_preferences(self, changes):
        path = self.directory / 'settings.json'
        temporary = self.directory / (uuid.uuid4().hex + '.tmp')
        try:
            preferences = self.load_preferences() if path.exists() else {}
            preferences.update(changes)
            with temporary.open('x', encoding='utf-8') as output:
                json.dump(preferences, output, ensure_ascii=False, indent=2)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
            return preferences
        except (OSError, ValueError) as error:
            raise StateError('Preferences could not be saved. The previous settings were kept.') from error
        finally:
            temporary.unlink(missing_ok=True)

    def backup(self, destination):
        path = Path(destination)
        if path.exists():
            raise StateError('The backup destination already exists.')
        try:
            with closing(sqlite3.connect(path)) as destination_db:
                self.db.backup(destination_db)
        except sqlite3.Error:
            raise StateError('The queue backup could not be created.') from None

    def close(self):
        if self.db is not None:
            self.db.close()
            self.db = None
        if self.lock is not None:
            self.lock.seek(0)
            try:
                self._file_lock(True)
            finally:
                self.lock.close()
                self.lock = None
        self._sources.clear()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
