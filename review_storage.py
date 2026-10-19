"""Review identities and destination checks; never inspect unrelated directories."""
import hashlib
import os
from pathlib import Path
import shutil
import tempfile
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from terabox import DownloadError, safe_name, share_id


class StorageError(DownloadError):
    pass


def input_key(link):
    share_id(link)
    parsed = urlsplit(link.strip())
    normalized = urlunsplit(('https', parsed.hostname.lower(), parsed.path,
                             urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True))), ''))
    return hashlib.sha256(normalized.encode()).hexdigest()


def share_key(link, metadata):
    identifier = str(metadata.get('shareid', ''))
    return 'provider:' + identifier if identifier.isascii() and identifier.isdigit() else 'source:' + input_key(link)


def share_folder(base, link, identity):
    share_id(link)
    suffix = hashlib.sha256(identity.encode()).hexdigest()[:12]
    return Path(base).resolve() / safe_name(f'Share-{suffix}')


def available_space(folder):
    return shutil.disk_usage(existing_parent(folder))[2]


def existing_parent(folder):
    path = Path(folder).resolve()
    while not path.exists() and path != path.parent:
        path = path.parent
    return path


def required_space(folder, pending):
    device = existing_parent(folder).stat().st_dev
    return sum(size for destination, size in pending if existing_parent(destination).stat().st_dev == device)


def target_paths(folder, name, fid):
    target = Path(folder) / safe_name(name)
    return target, target.with_name(target.name + '.' + safe_name(fid) + '.part')


def preflight(folder, needed, name=None, fid=None):
    try:
        folder = Path(folder).resolve()
        if available_space(folder) < needed:
            raise StorageError('Not enough free space. Choose another folder or free space, then Resume.')
        folder.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=folder) as probe:
            probe.write(b'\0')
            probe.flush()
        if name is not None:
            if any(os.path.lexists(path) for path in target_paths(folder, name, fid)):
                raise StorageError('A file or partial with this name exists. Rename, choose another folder, or Skip.')
    except OSError:
        raise StorageError('The destination is not writable. Choose another folder, then Resume.') from None


def prior_download(path, receipt, expected):
    if not path or not receipt:
        return False
    try:
        info = Path(path).stat()
        return (Path(path).is_file() and info.st_size == expected == receipt.get('size')
                and info.st_mtime_ns == receipt.get('mtime_ns'))
    except OSError:
        return False
