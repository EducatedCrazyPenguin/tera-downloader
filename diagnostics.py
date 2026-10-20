"""Bounded local troubleshooting data. Only allowlisted codes and numbers leave here."""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import threading

from app_version import VERSION

LIMIT = 128 * 1024
EVENTS = {'opened', 'attempt', 'completed', 'failed', 'cancelled', 'skipped', 'pending',
          'attention', 'restart', 'login', 'retry_wait', 'pause', 'start', 'cancel', 'close', 'error'}
KINDS = {'', 'transient', 'expired', 'login', 'storage', 'integrity', 'restart', 'access', 'unknown'}
LOCK = threading.Lock()


def clean(value):
    if not isinstance(value, dict) or value.get('event') not in EVENTS:
        return None
    stamp = value.get('time')
    if not isinstance(stamp, str) or not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}\+00:00', stamp):
        return None
    return {'time': stamp, 'event': value['event'],
            'kind': value.get('kind') if value.get('kind') in KINDS else 'unknown',
            **{key: value.get(key) if type(value.get(key)) is int and 0 <= value[key] <= 2**63 - 1 else 0
               for key in ('attempt', 'bytes')}}


def record(directory, event, *, kind='', attempt=0, received=0):
    entry = clean({'time': datetime.now(timezone.utc).isoformat(timespec='microseconds'),
                   'event': event, 'kind': kind, 'attempt': attempt, 'bytes': received})
    if entry is None:
        return
    line = (json.dumps(entry, separators=(',', ':')) + '\n').encode('ascii')
    try:
        with LOCK:
            path = Path(directory) / 'activity.log'
            if path.exists() and path.stat().st_size + len(line) > LIMIT:
                if path.stat().st_size > LIMIT:
                    path.unlink()
                else:
                    path.replace(path.with_name('activity.previous.log'))
            with path.open('ab') as output:
                output.write(line)
    except OSError:
        pass  # Diagnostics failure must never stop a download or a saved queue.


def export(directory, destination):
    entries = []
    with LOCK:
        for name in ('activity.previous.log', 'activity.log'):
            try:
                with (Path(directory) / name).open('rb') as source:
                    content = source.read(LIMIT)
                for line in content.splitlines():
                    try:
                        entry = clean(json.loads(line))
                    except (ValueError, TypeError, UnicodeError):
                        entry = None
                    if entry:
                        entries.append(entry)
            except OSError:
                continue
    # Exclusive creation also prevents overwriting settings, queue data, or an earlier report.
    with Path(destination).open('x', encoding='utf-8') as output:
        json.dump({'application': 'Tera', 'version': VERSION, 'events': entries}, output, indent=2)
