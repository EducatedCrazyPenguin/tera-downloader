"""Small Windows boundaries shared by the source and packaged GUI."""
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
from pathlib import Path
import uuid

MUTEX = 'Local\\Tera.Downloader.Application'


def downloads_directory():
    shell = ctypes.WinDLL('shell32', use_last_error=True)
    ole = ctypes.WinDLL('ole32', use_last_error=True)
    folder = (ctypes.c_byte * 16).from_buffer_copy(uuid.UUID('374de290-123f-4565-9164-39c4925e467b').bytes_le)
    output = ctypes.c_void_p()
    shell.SHGetKnownFolderPath.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.HANDLE, ctypes.POINTER(ctypes.c_void_p)]
    shell.SHGetKnownFolderPath.restype = ctypes.c_long
    ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    try:
        if shell.SHGetKnownFolderPath(ctypes.byref(folder), 0, None, ctypes.byref(output)) < 0 or not output.value:
            return None
        return Path(ctypes.wstring_at(output)) / 'Tera'
    finally:
        ole.CoTaskMemFree(output)


@contextmanager
def application_mutex():
    library = ctypes.WinDLL('kernel32', use_last_error=True)
    library.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    library.CreateMutexW.restype = wintypes.HANDLE
    library.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = library.CreateMutexW(None, False, MUTEX)
    if not handle:
        raise OSError('The application installation guard could not be opened.')
    try:
        yield
    finally:
        library.CloseHandle(handle)
