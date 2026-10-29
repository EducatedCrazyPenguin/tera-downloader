"""Local run boundaries and responsive byte pacing. Queue state has one owner."""
from copy import deepcopy
from datetime import datetime
import math
import re
import threading
import time
import uuid


DEFAULTS = {'speed_bps': 0, 'schedule_enabled': False, 'start': '00:00', 'end': '00:00',
            'deadline_minutes': 0, 'byte_budget': 0}


def local_now():
    return datetime.now().astimezone()


def validate_options(changes):
    if not isinstance(changes, dict) or not set(changes) <= DEFAULTS.keys():
        raise ValueError('Unsupported run setting.')
    result = {**DEFAULTS, **changes}
    for name in ('speed_bps', 'deadline_minutes', 'byte_budget'):
        if type(result[name]) is not int or not 0 <= result[name] <= 2 ** 63 - 1:
            raise ValueError('Speed, time and byte limits must be non-negative numbers; zero means unlimited.')
    if type(result['schedule_enabled']) is not bool:
        raise ValueError('Choose whether to enable the daily window.')
    for name in ('start', 'end'):
        if not isinstance(result[name], str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', result[name]):
            raise ValueError('Use HH:MM in 24-hour local time for the daily window.')
    if result['schedule_enabled'] and result['start'] == result['end']:
        raise ValueError('The window start and end must differ. Disable the window for all-day downloading.')
    try:
        datetime.fromtimestamp(time.time() + result['deadline_minutes'] * 60)
    except (OSError, OverflowError, ValueError):
        raise ValueError('The run duration exceeds the supported calendar range.') from None
    return result


def in_window(options, local):
    if not options['schedule_enabled']:
        return True
    current = f'{local.hour:02d}:{local.minute:02d}'
    start, end = options['start'], options['end']
    return start <= current < end if start < end else current >= start or current < end


class RunPolicy:
    def __init__(self, options=None, record=None):
        self.options = validate_options({} if options is None else options)
        self.record = deepcopy(record) if record is not None else {'id': '', 'started': 0, 'bytes': 0, 'limit_hold': '', 'open': False}
        saved = self.record
        if (not isinstance(saved, dict) or set(saved) != {'id', 'started', 'bytes', 'limit_hold', 'open'}
                or not isinstance(saved['id'], str) or saved['id'] and not re.fullmatch('[a-f0-9]{32}', saved['id'])
                or type(saved['started']) not in (int, float) or not math.isfinite(saved['started']) or saved['started'] < 0
                or type(saved['bytes']) is not int or saved['bytes'] < 0 or type(saved['open']) is not bool
                or saved['limit_hold'] not in {'', 'bytes', 'deadline', 'recovery'} or saved['open'] and not saved['id']):
            raise ValueError('Saved run limits are invalid. The original settings were left unchanged.')
        try:
            datetime.fromtimestamp(saved['started'] + self.options['deadline_minutes'] * 60)
        except (OSError, OverflowError, ValueError):
            raise ValueError('Saved run start time is outside the supported calendar.') from None

    def begin(self, now=None):
        self.record = {'id': uuid.uuid4().hex, 'started': time.time() if now is None else now,
                       'bytes': 0, 'limit_hold': '', 'open': True}

    def finish(self):
        self.record['open'] = False
        self.record['limit_hold'] = ''

    def add_bytes(self, amount):
        self.record['bytes'] += amount

    def reason(self, now=None, local=None):
        if not self.record['open']:
            return ''
        now = time.time() if now is None else now
        if not self.record['limit_hold']:
            budget, minutes = self.options['byte_budget'], self.options['deadline_minutes']
            if budget and self.record['bytes'] >= budget:
                self.record['limit_hold'] = 'bytes'
            elif minutes and now >= self.record['started'] + minutes * 60:
                self.record['limit_hold'] = 'deadline'
        return self.record['limit_hold'] or ('' if in_window(self.options, local or local_now()) else 'schedule')


class BandwidthLimiter:
    def __init__(self, rate=0, clock=None):
        self.clock = clock or time.monotonic
        self.lock = threading.Lock()
        self.set_rate(rate)

    def set_rate(self, rate):
        if type(rate) is not int or rate < 0:
            raise ValueError('The bandwidth limit must be non-negative bytes per second.')
        with self.lock:
            self.rate = rate
            self.due = self.clock()

    def read_size(self):
        with self.lock:
            return min(256 * 1024, max(1, self.rate // 10)) if self.rate else 256 * 1024

    def received(self, amount):
        with self.lock:
            self.due = max(self.due, self.clock()) + amount / self.rate if self.rate else self.clock()

    def wait(self, check, cancel):
        while True:
            check()
            with self.lock:
                remaining = self.due - self.clock() if self.rate else 0
            if remaining <= 0:
                return
            cancel.wait(min(remaining, .05))


class TransferPolicy:
    def __init__(self, limiter, account):
        self.limiter, self.account = limiter, account

    def before_read(self, client, check=None):
        self.limiter.wait(check or client.check_cancel, client.cancel)
        return self.limiter.read_size()

    def received(self, amount):
        self.limiter.received(amount)
        self.account(amount)
