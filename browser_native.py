"""Windows-only, loopback DevTools socket and a job owning one browser tree."""
import ctypes as c
from ctypes import wintypes as w
import json
import re
import time
from urllib.parse import urlsplit


class BrowserJob:
    def __init__(self):
        class Basic(c.Structure):
            _fields_ = [('times', c.c_longlong * 2), ('flags', w.DWORD),
                        ('min_ws', c.c_size_t), ('max_ws', c.c_size_t),
                        ('active', w.DWORD), ('affinity', c.c_size_t),
                        ('priority', w.DWORD), ('scheduling', w.DWORD)]
        class Limits(c.Structure):
            _fields_ = [('basic', Basic), ('io', c.c_ulonglong * 6),
                        ('memory', c.c_size_t * 4)]
        self.api = c.WinDLL('kernel32', use_last_error=True)
        self.api.CreateJobObjectW.argtypes = [c.c_void_p, w.LPCWSTR]
        self.api.CreateJobObjectW.restype = w.HANDLE
        self.api.SetInformationJobObject.argtypes = [w.HANDLE, c.c_int, c.c_void_p, w.DWORD]
        self.api.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        self.api.CloseHandle.argtypes = [w.HANDLE]
        self.handle = self.api.CreateJobObjectW(None, None)
        if not self.handle:
            raise OSError('Cannot create isolated browser ownership.')
        limits = Limits(); limits.basic.flags = 0x2000  # KILL_ON_JOB_CLOSE
        if not self.api.SetInformationJobObject(self.handle, 9, c.byref(limits), c.sizeof(limits)):
            self.close()
            raise OSError('Cannot configure isolated browser ownership.')

    def assign(self, child):
        if not self.api.AssignProcessToJobObject(self.handle, int(child._handle)):
            raise OSError('Cannot own the isolated browser process.')

    def alive(self):
        class Accounting(c.Structure):
            _fields_ = [('times', c.c_longlong * 4), ('faults', w.DWORD),
                        ('total', w.DWORD), ('active', w.DWORD), ('terminated', w.DWORD)]
        query = self.api.QueryInformationJobObject
        query.argtypes = [w.HANDLE, c.c_int, c.c_void_p, w.DWORD, c.c_void_p]
        query.restype = w.BOOL
        record = Accounting()
        if not query(self.handle, 1, c.byref(record), c.sizeof(record), None):
            raise OSError('Could not check the owned browser process tree.')
        return bool(record.active)

    def close(self):
        if self.handle:
            self.api.CloseHandle(self.handle)
            self.handle = None


class DevTools:
    """WinHTTP handles WebSocket framing; no proxy, credentials or third-party package."""
    def __init__(self, endpoint, port, *, protocol='cdp'):
        parsed = urlsplit(endpoint)
        if (parsed.scheme != 'ws' or parsed.hostname not in ('127.0.0.1', 'localhost')
                or parsed.port != port or parsed.username or parsed.password
                or parsed.query or parsed.fragment
                or not (protocol == 'cdp' and re.fullmatch(r'/devtools/browser/[A-Za-z0-9-]+', parsed.path)
                        or protocol == 'bidi' and parsed.path == '/session')):
            raise OSError('Unrecognized owned-browser endpoint.')
        self.api = api = c.WinDLL('winhttp', use_last_error=True)
        signatures = {
            'WinHttpOpen': ([w.LPCWSTR, w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD], w.HANDLE),
            'WinHttpConnect': ([w.HANDLE, w.LPCWSTR, w.WORD, w.DWORD], w.HANDLE),
            'WinHttpOpenRequest': ([w.HANDLE, w.LPCWSTR, w.LPCWSTR, w.LPCWSTR, w.LPCWSTR, c.c_void_p, w.DWORD], w.HANDLE),
            'WinHttpSetTimeouts': ([w.HANDLE, c.c_int, c.c_int, c.c_int, c.c_int], w.BOOL),
            'WinHttpSetOption': ([w.HANDLE, w.DWORD, c.c_void_p, w.DWORD], w.BOOL),
            'WinHttpSendRequest': ([w.HANDLE, w.LPCWSTR, w.DWORD, c.c_void_p, w.DWORD, w.DWORD, c.c_size_t], w.BOOL),
            'WinHttpReceiveResponse': ([w.HANDLE, c.c_void_p], w.BOOL),
            'WinHttpQueryHeaders': ([w.HANDLE, w.DWORD, w.LPCWSTR, c.c_void_p, c.POINTER(w.DWORD), c.c_void_p], w.BOOL),
            'WinHttpWebSocketCompleteUpgrade': ([w.HANDLE, c.c_size_t], w.HANDLE),
            'WinHttpWebSocketSend': ([w.HANDLE, c.c_int, c.c_void_p, w.DWORD], w.DWORD),
            'WinHttpWebSocketReceive': ([w.HANDLE, c.c_void_p, w.DWORD, c.POINTER(w.DWORD), c.POINTER(c.c_int)], w.DWORD),
            'WinHttpCloseHandle': ([w.HANDLE], w.BOOL),
        }
        for name, (args, result) in signatures.items():
            function = getattr(api, name); function.argtypes = args; function.restype = result
        self.handles = []; self.serial = 0; self.on_event = lambda message: None
        try:
            session = self._handle(api.WinHttpOpen('Tera browser helper', 1, None, None, 0))
            self._ok(api.WinHttpSetTimeouts(session, 3000, 3000, 3000, 3000))
            connection = self._handle(api.WinHttpConnect(session, '127.0.0.1', port, 0))
            request = self._handle(api.WinHttpOpenRequest(connection, 'GET', parsed.path, None, None, None, 0))
            self._ok(api.WinHttpSetOption(request, 114, None, 0))  # UPGRADE_TO_WEB_SOCKET
            self._ok(api.WinHttpSendRequest(request, None, 0, None, 0, 0, 0))
            self._ok(api.WinHttpReceiveResponse(request, None))
            status = w.DWORD(); size = w.DWORD(c.sizeof(status))
            self._ok(api.WinHttpQueryHeaders(request, 19 | 0x20000000, None, c.byref(status), c.byref(size), None))
            if status.value != 101:
                raise OSError('Owned-browser WebSocket upgrade failed.')
            self.socket = self._handle(api.WinHttpWebSocketCompleteUpgrade(request, 0))
        except BaseException:
            self.close()
            raise

    @staticmethod
    def _ok(result):
        if not result:
            raise OSError('Owned-browser control request failed.')

    def _handle(self, handle):
        self._ok(handle); self.handles.append(handle); return handle

    def send(self, method, params=None, session=None):
        self.serial += 1
        payload = {'id': self.serial, 'method': method, 'params': params or {}}
        if session:
            payload['sessionId'] = session
        data = json.dumps(payload).encode('utf-8')
        if self.api.WinHttpWebSocketSend(self.socket, 2, data, len(data)):
            raise OSError('Owned-browser control send failed.')
        return self.serial

    def receive(self):
        parts = []; total = 0
        while True:
            buffer = c.create_string_buffer(65536); count = w.DWORD(); kind = c.c_int()
            if self.api.WinHttpWebSocketReceive(self.socket, buffer, len(buffer), c.byref(count), c.byref(kind)):
                raise OSError('Owned-browser control timed out or closed.')
            total += count.value
            if kind.value not in (2, 3) or total > 2 * 1024 * 1024:
                raise OSError('Invalid owned-browser control response.')
            parts.append(buffer.raw[:count.value])
            if kind.value == 2:
                return json.loads(b''.join(parts))

    def call(self, method, params=None, session=None):
        serial = self.send(method, params, session)
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            message = self.receive()
            if message.get('id') == serial:
                if 'error' in message:
                    raise OSError('Owned-browser command was rejected.')
                return message.get('result', {})
            self.on_event(message)
        raise OSError('Owned-browser command exceeded its time bound.')

    def close(self):
        for handle in reversed(self.handles):
            self.api.WinHttpCloseHandle(handle)
        self.handles.clear()
