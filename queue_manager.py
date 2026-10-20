"""One owner for queue state; transport workers report by stable job/attempt IDs."""
from __future__ import annotations

from collections import deque
from copy import deepcopy
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
import hashlib
import json
import os
import queue
import threading
import time
import uuid

from app_state import StateError, StateStore
from firefox_session import FirefoxProfile
from review_storage import (StorageError, available_space, input_key, preflight, prior_download,
                            required_space, share_folder, share_key, target_paths)
from terabox import Cancelled, DownloadError, PAUSED_STATUS, TeraBox, parse_links, _wait_for_download
from terabox import safe_name
from recovery import can_retry
from transfer_state import Checkpoint, RestartRequired, fresh_checkpoint
from run_policy import BandwidthLimiter, RunPolicy, TransferPolicy, local_now, validate_options


TERMINAL = {'completed', 'failed', 'skipped', 'cancelled'}
REVIEW = {'unreviewed', 'reviewing', 'review', 'excluded'}
HOLDS = {'attention', 'restart', 'login'}


class SpeedMeter:
    def __init__(self):
        self.samples = deque()

    def reset(self, received=0, now=None):
        self.samples.clear()
        self.samples.append((time.monotonic() if now is None else now, received))

    def update(self, received, now=None):
        now = time.monotonic() if now is None else now
        self.samples.append((now, received))
        while len(self.samples) > 2 and self.samples[1][0] <= now - 5:
            self.samples.popleft()

    @property
    def rate(self):
        if len(self.samples) < 2:
            return 0.0
        first, last = self.samples[0], self.samples[-1]
        return max(0, last[1] - first[1]) / (last[0] - first[0]) if last[0] > first[0] else 0.0

    def rate_at(self, now):
        return self.rate if self.samples and now - self.samples[-1][0] <= 5 else 0.0


@dataclass
class Job:
    id: str
    link: str = field(repr=False)
    folder: str = ''
    profile: dict | None = None
    video: dict | None = None
    status: str = 'pending'
    attempt: int = 0
    received: int = 0
    path: str = ''
    error: str = ''
    finished: float = 0.0
    source_blocked: bool = False
    identity: str = ''
    output_name: str = ''
    receipt: dict = field(default_factory=dict)
    per_share: bool = False
    checkpoint: dict = field(default_factory=dict)
    cycle_attempts: int = 0
    retry_due: float = 0.0
    error_kind: str = ''
    run_id: str = ''
    run_bytes: int = 0


class QueueManager:
    def __init__(self, directory, client_factory=None, legacy_settings=None):
        self.directory = directory
        self.client_factory = client_factory or TeraBox
        self.legacy_settings = legacy_settings
        self.commands = queue.Queue()
        self.events = queue.Queue()
        self.pause = threading.Event()
        self.ready = threading.Event()
        self.closed = threading.Event()
        self.startup_error = None
        self.thread = threading.Thread(target=self._run, name='Tera queue', daemon=True)
        self.thread.start()

    def post(self, action, **data):
        self.commands.put((action, data, None))

    def request(self, action, **data):
        """Synchronous boundary for tests/CLI; Tkinter uses post() and events."""
        if not self.ready.wait(5):
            raise StateError('The queue is still opening.')
        if self.startup_error:
            raise self.startup_error
        if self.closed.is_set():
            raise StateError('The queue has closed.')
        reply = queue.Queue(maxsize=1)
        self.commands.put((action, data, reply))
        success, value = reply.get(timeout=5)
        if not success:
            raise value
        return value

    def _run(self):
        self.jobs = []
        self.active = None
        self.verification = None
        self.worker = None
        self.cancel = threading.Event()
        self.discard_current = threading.Event()
        self.running = False
        self.closing = False
        self.intent = ''
        self.acknowledged = False
        self.error_hold = False
        self.boundary = False
        self.review_active = None
        self.review_worker = None
        self.review_cancel = threading.Event()
        self.review_requested = set()
        self.review_space = {}
        self.message = 'Add links, then Start. Restored jobs wait for your instruction.'
        self.run_ids = set()
        self.meter = SpeedMeter()
        store = None
        try:
            store = self.store = StateStore(self.directory, self.legacy_settings)
            self.preferences = store.load_preferences()
            self.policy = RunPolicy(self.preferences.get('run_options'), self.preferences.get('run_state'))
            self.policy_saved = deepcopy(self.policy.record)
            self.policy_hold = ''
            self.limiter = BandwidthLimiter(self.policy.options['speed_bps'])
            try:
                for row in store.load_jobs():
                    job = Job(**row)
                    if (job.status == 'downloading' and self.policy.options['byte_budget'] and self.policy.record['open']
                            and job.run_id == self.policy.record['id'] and (not isinstance(job.checkpoint, dict) or job.checkpoint.get('phase') != 'ready')):
                        self.policy.record['limit_hold'] = 'recovery'
                    if type(job.run_bytes) is not int or job.run_bytes < 0:
                        raise ValueError('Invalid run byte count')
                    parse_links(job.link)
                    if job.status not in TERMINAL | REVIEW | HOLDS | {'pending', 'resolving', 'downloading', 'retry_wait'}:
                        raise ValueError('Invalid status')
                    if job.video and (set(job.video) != {'name', 'size', 'fid'} or int(job.video['size']) <= 0):
                        raise ValueError('Invalid metadata')
                    if job.status == 'reviewing':
                        job.status = 'unreviewed'
                    elif job.status not in TERMINAL | REVIEW | HOLDS:
                        job.status = 'pending'
                        job.received = job.checkpoint.get('offset', 0) if isinstance(job.checkpoint, dict) else 0
                    if job.checkpoint:
                        try:
                            self._checkpoint_state(job)
                        except RestartRequired:
                            job.status, job.error_kind, job.error = 'restart', 'restart', 'Saved checkpoint cannot be verified. Restart is required.'
                            job.received = 0
                    if type(job.cycle_attempts) is not int or not 0 <= job.cycle_attempts <= 2:
                        raise ValueError('Invalid retry budget')
                    self.jobs.append(job)
                self.policy.record['bytes'] = max(self.policy.record['bytes'], sum(j.run_bytes for j in self.jobs if j.run_id == self.policy.record['id']))
            except (TypeError, ValueError, DownloadError):
                raise StateError('Saved jobs are invalid. The queue was left unchanged.') from None
            self.saved_jobs = deepcopy(self.jobs)
            self.ready.set()
            self._publish()
            while True:
                try:
                    action, data, reply = self.commands.get(timeout=.5)
                except queue.Empty:
                    action, data, reply = '_tick', {}, None
                if action == '_status' and data['text'] == self.message:
                    continue
                try:
                    value = self._handle(action, data)
                    if action != 'snapshot':
                        self._advance_review()
                    self._advance()
                    if action == 'snapshot':
                        value = self._snapshot()
                    elif action != '_bytes':
                        self._publish()
                    if reply:
                        reply.put((True, value))
                except (StateError, DownloadError, OSError, ValueError) as error:
                    # Failed persistence must stop further transfers, not silently lose changes.
                    if isinstance(error, StateError):
                        self.running = False
                        self.pause.set()
                        self.error_hold = True
                        self.cancel.set()
                    message = str(error) if isinstance(error, (StateError, DownloadError)) else 'The operation could not finish. Check the selected folder and retry.'
                    self.message = message
                    self.events.put(('error', message))
                    if reply:
                        reply.put((False, StateError(message)))
                if self.closing and not self.active and not self.review_active:
                    self._save()
                    break
        except Exception as error:
            self.startup_error = error if isinstance(error, StateError) else StateError('The queue could not open. Existing data was left in place.')
            self.events.put(('error', str(self.startup_error)))
        finally:
            self.cancel.set()
            self.review_cancel.set()
            self.pause.clear()
            if self.worker:
                self.worker.join(26)
            if self.review_worker:
                self.review_worker.join(26)
            if store:
                store.close()
            self.ready.set()
            self.closed.set()
            self.events.put(('closed', None))

    def _save(self):
        # Transport URLs/cookies never enter Job or its serialized representation.
        try:
            self.store.save_jobs([asdict(job) for job in self.jobs])
            if self.policy.record != self.policy_saved:
                self.preferences = self.store.save_preferences({'run_state': self.policy.record})
                self.policy_saved = deepcopy(self.policy.record)
        except StateError:
            self.jobs = deepcopy(self.saved_jobs)
            self.running = False
            self.cancel.set()
            if self.worker is None:
                self.active = None
            raise
        self.saved_jobs = deepcopy(self.jobs)

    def _job(self, identifier):
        job = next((job for job in self.jobs if job.id == identifier), None)
        if job is None:
            raise DownloadError('That queue item is no longer available.')
        return job

    @staticmethod
    def _binding(job):
        value = [job.id, input_key(job.link), job.profile, job.folder, job.video, job.identity, job.output_name]
        return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()

    def _checkpoint_state(self, job, commit=lambda value: True, discard=None):
        if not job.video:
            raise RestartRequired('A checkpoint requires reviewed file metadata.')
        return Checkpoint(job.checkpoint, job.folder, job.output_name or job.video['name'], job.video['size'],
                          self._binding(job), commit, discard or threading.Event())

    def _discard(self, job):
        if job.checkpoint:
            try:
                if not isinstance(job.checkpoint, dict) or not job.video:
                    raise RestartRequired()
                # Disconnect can clear the login reference; ownership still requires the recorded file ID.
                Checkpoint(job.checkpoint, job.folder, job.output_name or job.video['name'], job.video['size'],
                           job.checkpoint.get('binding'), lambda value: True, threading.Event()).discard_owned()
            except RestartRequired:
                pass  # An invalid ownership record cannot authorize deleting a file.
            job.checkpoint = {}

    def _handle(self, action, data):
        if action == '_tick':
            return
        if action == 'snapshot':
            return self._snapshot()
        if action == 'configure_run':
            options = validate_options(data['options'])
            self.preferences = self.store.save_preferences({'run_options': options})
            previous_speed = self.policy.options['speed_bps']
            self.policy.options = options
            if previous_speed != options['speed_bps']:
                self.limiter.set_rate(options['speed_bps'])
            self.message = 'Run settings applied. Time and byte limits finish the current file before holding.'
            return
        if action == '_bytes':
            if self.active != data['job_id']:
                return False
            job = self._job(data['job_id'])
            if job.attempt != data['attempt']:
                return False
            amount = data['amount']
            if type(amount) is not int or amount < 0:
                raise DownloadError('Invalid transfer byte count.')
            job.run_bytes += amount
            self.policy.add_bytes(amount)
            return True
        if action == '_checkpoint':
            if self.active != data['job_id']:
                return False
            job = self._job(data['job_id'])
            if job.attempt != data['attempt'] or self.intent in {'skip', 'cancel'}:
                return False
            record = data['checkpoint']
            if record.get('token') != job.checkpoint.get('token') or record.get('offset', -1) < job.checkpoint.get('offset', 0):
                raise StateError('An invalid transfer checkpoint was rejected.')
            if job.checkpoint.get('file_id') and record.get('file_id') != job.checkpoint['file_id']:
                raise StateError('A changed partial ownership record was rejected.')
            self._checkpoint_state(replace(job, checkpoint=record))
            job.checkpoint = deepcopy(record)
            if record['offset'] > job.received:
                job.received = record['offset']
                self.meter.update(job.received)
            self._save()
            return True
        if action == 'restart':
            job = self._job(data['job_id'])
            if job.source_blocked:
                raise DownloadError('Firefox was disconnected. Review the share again with your chosen login source.')
            if job.id == self.active or job.status not in {'failed', 'pending'} | HOLDS:
                raise DownloadError('Stop this file before restarting it.')
            self._discard(job)
            job.status, job.received, job.error, job.error_kind = 'pending', 0, '', ''
            job.cycle_attempts, job.retry_due = 0, 0
            self._save()
            self.message = 'Restart from zero chosen. Click Resume or Start to download.'
            return
        if action == 'review_saved':
            self.review_requested.update(j.id for j in self.jobs if j.status == 'unreviewed' and not j.source_blocked)
            return
        if action == 'review_choice':
            job = self._job(data['job_id'])
            if job.status not in {'review', 'excluded'}:
                raise DownloadError('Wait for review to finish.')
            job.status = 'excluded' if job.status == 'review' else 'review'
            self._save()
            return
        if action == 'review_choices':
            selected = data['selected']
            if type(selected) is not bool:
                raise DownloadError('Choose Select visible or Deselect visible.')
            jobs = [self._job(identifier) for identifier in dict.fromkeys(data['job_ids'])]
            if any(j.status not in {'review', 'excluded'} for j in jobs):
                raise DownloadError('Wait for review to finish before selecting these files.')
            for job in jobs:
                job.status = 'review' if selected else 'excluded'
            self._save()
            return
        if action == 'review':
            links = parse_links('\n'.join(data['links']))
            folder = str(Path(data['folder']).resolve())
            profile = data.get('profile')
            reference = {'name': profile.name, 'path': str(profile.path)} if profile else None
            self.preferences = self.store.save_preferences({'last_destination': folder})
            existing = {input_key(j.link) for j in self.jobs
                        if j.status not in TERMINAL | {'unreviewed', 'excluded'} and not j.source_blocked}
            added = []
            for link in links:
                key = input_key(link)
                if key in existing:
                    continue
                existing.add(key)
                old = next((j for j in self.jobs if j.status == 'unreviewed' and input_key(j.link) == key), None)
                if old:
                    added.append(old)
                else:
                    job = Job(uuid.uuid4().hex, link, folder, reference, status='unreviewed', per_share=bool(data.get('per_share')))
                    self.jobs.append(job)
                    added.append(job)
            self._save()
            self.review_requested.update(j.id for j in added)
            if self.error_hold and not self.active:
                self.error_hold = False
                self.pause.clear()
                self.acknowledged = False
            self.message = 'Reading shares for review…' if added else 'These shares are already in Review or Queue.'
            self.events.put(('added', [job.id for job in added]))
            return [job.id for job in added]
        if action == 'select':
            selected = set(data['job_ids'])
            for job in self.jobs:
                if job.status not in {'review', 'excluded'}:
                    continue
                duplicate = self._duplicate(job)
                job.status = 'pending' if job.id in selected and not duplicate and not job.source_blocked else 'excluded'
                job.error = duplicate
                if job.status == 'pending' and self.running:
                    self.run_ids.add(job.id)
            self._save()
            if data.get('start', True) and not self.running and not self.pause.is_set():
                self._handle('start', {})
            self.message = 'Selected files queued.' if not self.pause.is_set() else 'Selected files queued. Resume when ready.'
            return
        if action in {'destination', 'destinations'}:
            identifiers = data['job_ids'] if action == 'destinations' else [data['job_id']]
            jobs = [self._job(identifier) for identifier in dict.fromkeys(identifiers)]
            if not jobs:
                return
            if any(j.id == self.active or j.status not in {'pending', 'attention', 'review', 'excluded'} for j in jobs):
                raise DownloadError('Stop the active file before changing its destination; it must restart from zero.')
            if any(j.checkpoint.get('file_id') for j in jobs):
                raise RestartRequired('Choose Restart from zero before changing the saved partial destination or name.')
            if 'name' in data:
                name = data['name']
                if action == 'destinations' or not name or name != safe_name(name):
                    raise DownloadError('Use a plain, safe file name without folders or reserved characters.')
                if not jobs[0].video:
                    raise DownloadError('Review the share before choosing a file name.')
            if 'folder' in data:
                if not data['folder'].strip():
                    raise DownloadError('Choose a destination folder.')
                folder = str(Path(data['folder']).resolve())
            for job in jobs:
                if 'name' in data:
                    job.output_name = name
                if 'folder' in data:
                    job.folder = folder
                if job.status == 'attention':
                    job.status = 'pending'
                job.error = ''
                job.checkpoint, job.cycle_attempts = {}, 0
            self._save()
            for folder in {j.folder for j in jobs}:
                try:
                    self.review_space[folder] = available_space(folder)
                except OSError:
                    self.review_space[folder] = None
            self.message = 'Destinations updated. Resume when ready.'
            return
        if action == '_review_result':
            if data['job_id'] != self.review_active:
                return
            job = self._job(data['job_id'])
            self.review_worker.join(1)
            self.review_worker, self.review_active = None, None
            if self.closing or self.review_cancel.is_set() or data['outcome'] == 'cancelled':
                job.status = 'unreviewed'
            elif data['outcome'] == 'discovered':
                identity, videos = data['value']
                folder = str(share_folder(job.folder, job.link, identity)) if job.per_share else job.folder
                position = self.jobs.index(job)
                reviewed = [replace(job, id=job.id if index == 0 else uuid.uuid4().hex,
                                    video=video, folder=folder, status='review', identity=identity, error='')
                            for index, video in enumerate(videos)]
                self.jobs[position:position + 1] = reviewed
                for item in reviewed:
                    item.error = self._duplicate(item, in_review=True)
                    if item.error:
                        item.status = 'excluded'
                try:
                    self.review_space[folder] = available_space(folder)
                except OSError:
                    self.review_space[folder] = None
                self.message = f'{len(videos)} video(s) ready for review. Choose files, then Download selected.' if not self.running else self.message
            else:
                job.status, job.error, job.finished = 'failed', data['value'], time.time()
            self._save()
            return
        if action == 'add':
            links = parse_links('\n'.join(data['links']))
            folder = str(Path(data['folder']).resolve())
            profile = data.get('profile')
            reference = {'name': profile.name, 'path': str(profile.path)} if profile else None
            added = [Job(uuid.uuid4().hex, link, folder, reference) for link in links]
            self.preferences = self.store.save_preferences({'last_destination': folder})
            self.jobs.extend(added)
            if self.running:
                self.run_ids.update(j.id for j in added)
            self._save()
            self.message = f'{len(added)} share(s) queued. Files are discovered when the queue runs.'
            self.events.put(('added', [job.id for job in added]))
            return [job.id for job in added]
        if action == 'preferences':
            changes = data['changes']
            if not set(changes) <= {'firefox_profile', 'last_destination', 'favorites', 'notifications'}:
                raise DownloadError('Unsupported preference.')
            if 'notifications' in changes and not isinstance(changes['notifications'], bool):
                raise DownloadError('Notifications must be on or off.')
            if 'firefox_profile' in changes and changes['firefox_profile'] is not None and not isinstance(changes['firefox_profile'], str):
                raise DownloadError('Select a valid Firefox profile.')
            if 'last_destination' in changes and not isinstance(changes['last_destination'], str):
                raise DownloadError('Choose a valid destination.')
            if 'favorites' in changes and (not isinstance(changes['favorites'], list) or not all(isinstance(f, dict) and set(f) == {'name', 'path'}
                                                 and all(isinstance(v, str) and v.strip() for v in f.values())
                                                 for f in changes['favorites'])):
                raise DownloadError('Each favorite needs a name and destination.')
            self.preferences = self.store.save_preferences(changes)
            return
        if action == 'disconnect':
            if self.running or self.active or self.review_active:
                raise DownloadError('Stop the queue before disconnecting Firefox.')
            self.preferences = self.store.save_preferences({'firefox_profile': None})
            for job in self.jobs:
                if job.profile:
                    job.profile = None
                    if job.status != 'completed':
                        job.source_blocked = True
                        job.status = 'failed'
                        job.finished = time.time()
                        job.error = 'Firefox was disconnected. Add this share again with your chosen login source.'
            self._save()
            self.message = 'Firefox disconnected. Affected unfinished jobs require an explicit re-add; no anonymous fallback was used.'
            return
        if action == 'start':
            if any(j.status in {'restart', 'login'} for j in self.jobs):
                raise DownloadError('Resolve Restart required or Login required using the selected job actions before resuming.')
            if self.error_hold:
                if self.active:
                    raise DownloadError('Wait for the current request to stop, then retry saving the queue.')
                self._save()
                self.error_hold = False
            if self.active and self.intent:
                raise DownloadError('Wait for the current stop operation to finish.')
            if data.get('new_run') and self.active:
                raise DownloadError('Finish or stop the current file before starting a new run.')
            if not data.get('new_run') and self.policy.reason() in {'bytes', 'deadline', 'recovery'}:
                raise DownloadError('This run reached its limit. Start new run explicitly to reset its time and byte budget.')
            for job in self.jobs:
                if job.status == 'attention':
                    job.status, job.error = 'pending', ''
                    job.cycle_attempts = 0
            if not self.running or data.get('new_run'):
                self.run_ids = {j.id for j in self.jobs if j.status == 'pending'}
                self.running = bool(self.run_ids or self.active)
            if self.running and (data.get('new_run') or not self.policy.record['open']):
                self.policy.begin()
                self._save()
            self.pause.clear()
            self.boundary = False
            self.acknowledged = False
            current = self._job(self.active).received if self.active else 0
            self.meter.reset(current)
            self.message = 'Resuming…' if self.active else 'Starting queue…'
            return
        if action == 'pause':
            if self.running:
                self.pause.set()
                self.boundary = False
                self.acknowledged = not bool(self.active)
                self.message = PAUSED_STATUS if self.acknowledged else 'Pausing… waiting for the current network request.'
            return
        if action == 'pause_after':
            if self.running:
                if self.active and self._job(self.active).video and not self.pause.is_set():
                    self.boundary = True
                    self.message = 'Finishing the current file, then pausing. Resume will be required.'
                else:
                    self._handle('pause', {})
            return
        if action == 'move':
            job = self._job(data['job_id'])
            if job.status != 'pending':
                raise DownloadError('Only pending jobs can be reordered.')
            indexes = [i for i, j in enumerate(self.jobs) if j.status == 'pending']
            position = indexes.index(self.jobs.index(job))
            target = max(0, min(len(indexes) - 1, position + int(data['direction'])))
            first, second = indexes[position], indexes[target]
            self.jobs[first], self.jobs[second] = self.jobs[second], self.jobs[first]
            self._save()
            return
        if action == 'remove':
            job = self._job(data['job_id'])
            if job.status not in {'pending', 'attention'} | REVIEW:
                raise DownloadError('Only pending jobs can be removed. Use Skip for the active file.')
            if job.id == self.review_active:
                raise DownloadError('Wait for this review to finish before removing it.')
            self._discard(job)
            self.jobs.remove(job)
            self.review_requested.discard(job.id)
            self._save()
            return
        if action == 'retry':
            selected = set(data['job_ids'])
            count = 0
            for job in self.jobs:
                if job.id in selected and job.status in {'failed', 'login'} and not job.source_blocked:
                    job.status, job.error, job.received, job.finished = ('pending' if job.video else 'unreviewed'), '', 0, 0
                    count += 1
                    job.cycle_attempts, job.retry_due = 0, 0
                    if self.running:
                        self.run_ids.add(job.id)
            self._save()
            self.message = (f'{count} failure(s) requeued.' + (' They will run after the active item.' if self.running else ' Click Start to retry.')) if count else 'No retryable failures selected. Disconnected jobs must be added again.'
            return
        if action == 'clear_history':
            if self.running or self.active:
                raise DownloadError('Finish or stop the queue before clearing history.')
            self.jobs = [j for j in self.jobs if j.status not in TERMINAL or j.checkpoint.get('file_id')]
            for job in self.jobs:
                if job.status in {'review', 'excluded'}:
                    job.error = self._duplicate(job, in_review=True)
            self._save()
            self.message = 'History cleared. Downloaded files and unfinished owned partials were kept.'
            return
        if action in ('skip', 'cancel', 'close'):
            if action == 'skip' and not self.active:
                job = self._job(data['job_id']) if data.get('job_id') else next((j for j in self.jobs if j.status in HOLDS | {'retry_wait'}), None)
                if job and (job.status in HOLDS | {'pending', 'retry_wait'} or job.status == 'failed' and job.checkpoint):
                    self._discard(job)
                    job.status, job.finished, job.error = 'skipped', time.time(), ''
                    self._save()
                return
            if action != 'skip':
                self.running = False
                self.boundary = False
                self.pause.clear()
                self.review_cancel.set()
                self.review_requested.clear()
                if action == 'cancel':
                    self.policy.finish()
                for job in self.jobs:
                    if job.id != self.active and job.status in HOLDS | {'pending', 'retry_wait'} and action == 'cancel':
                        self._discard(job)
                        job.status = 'cancelled'
                        job.finished = time.time()
            if action == 'close':
                self.closing = True
                self.message = 'Saving queue and exiting… waiting for the current network request.'
            elif action == 'cancel':
                self.message = 'Cancelling queue… completed files will be kept.'
            else:
                self.message = 'Skipping the current item…'
            if self.active:
                self.intent = action
                if action in {'skip', 'cancel'}:
                    self.discard_current.set()
                self.cancel.set()
            self._save()
            return
        if action.startswith('_'):
            job = next((j for j in self.jobs if j.id == data['job_id']), None)
            if not job or self.active != job.id or job.attempt != data['attempt']:
                return
            if action == '_status':
                if self.error_hold:
                    return
                if data['text'] == PAUSED_STATUS and self.pause.is_set() and not self.intent:
                    self.acknowledged = True
                    self.message = PAUSED_STATUS
                elif not self.pause.is_set() and not self.intent and not self.boundary and not self.policy_hold and data['text'] != PAUSED_STATUS:
                    self.message = data['text']
            elif action == '_progress':
                self.verification = None
                job.received = data['received']
                self.meter.update(job.received)
            elif action == '_verification':
                done, total = data['done'], data['total']
                if type(done) is int and type(total) is int and 0 <= done <= total:
                    self.verification = {'done': done, 'total': total}
            elif action == '_result':
                self.verification = None
                outcome, value = data['outcome'], data['value']
                if outcome == 'discovered' and not self.intent:
                    videos = value
                    job.video = videos[0]
                    job.status = 'pending'
                    job.cycle_attempts = 0
                    position = self.jobs.index(job) + 1
                    extras = [Job(uuid.uuid4().hex, job.link, job.folder, job.profile, video) for video in videos[1:]]
                    self.jobs[position:position] = extras
                    self.run_ids.update(j.id for j in extras)
                elif outcome == 'completed':
                    job.status, job.path = 'completed', value
                    job.received = job.video['size']
                    job.finished = time.time()
                    job.checkpoint, job.retry_due, job.error_kind = {}, 0, ''
                    try:
                        info = Path(value).stat()
                        job.receipt = {'size': info.st_size, 'mtime_ns': info.st_mtime_ns}
                    except OSError:
                        job.receipt = {}
                elif self.intent == 'close':
                    job.status, job.received = 'pending', job.checkpoint.get('offset', 0)
                elif self.error_hold:
                    job.status, job.received = 'pending', job.checkpoint.get('offset', 0)
                elif self.intent in ('skip', 'cancel'):
                    job.status = 'skipped' if self.intent == 'skip' else 'cancelled'
                    job.received, job.finished = 0, time.time()
                    job.checkpoint = {}
                elif outcome in {'storage', 'restart', 'login'}:
                    job.status, job.error, job.received = ('attention' if outcome == 'storage' else outcome), value, job.checkpoint.get('offset', 0)
                    job.error_kind = outcome
                    self.pause.set()
                    self.acknowledged = True
                    self.message = value
                else:
                    kind = data.get('kind', 'unknown')
                    job.error_kind, job.error = kind, value
                    job.received = job.checkpoint.get('offset', 0)
                    if can_retry(kind, job.cycle_attempts, job.checkpoint):
                        job.status, job.retry_due = 'retry_wait', time.time() + data.get('retry_after', 5)
                        self.message = 'Connection interrupted. One bounded retry is waiting; Pause or Cancel remains available.'
                    elif kind in {'transient', 'expired'} and job.received and not job.checkpoint.get('etag'):
                        job.status, job.error_kind = 'restart', 'restart'
                        job.error = 'Saved bytes have no strong server validator. Choose Restart from zero explicitly.'
                        self.pause.set()
                        self.acknowledged = True
                        self.message = job.error
                    else:
                        job.status, job.finished = 'failed', time.time()
                self.worker.join(1)
                self.worker = None
                self.active, self.intent = None, ''
                if self.boundary:
                    self.boundary = False
                    self.pause.set()
                    self.acknowledged = True
                    if job.status not in HOLDS:
                        self.message = 'Paused after the current file. Click Resume to continue.'
                elif self.pause.is_set() and not self.error_hold:
                    self.acknowledged = True
                    if job.status not in HOLDS:
                        self.message = PAUSED_STATUS
                self._save()
            return
        raise DownloadError('Unsupported queue action.')

    def _advance(self):
        self.policy_hold = self.policy.reason()
        if self.policy_hold and self.running and not self.pause.is_set() and not self.intent and not self.error_hold:
            reason = {'schedule': 'Outside the daily download window', 'bytes': 'Run byte budget reached', 'deadline': 'Run deadline reached', 'recovery': 'Interrupted run: the last received-byte total is uncertain'}[self.policy_hold]
            self.message = reason + ('. Finishing the current file, then holding.' if self.active else '. Waiting for the window.' if self.policy_hold == 'schedule' else '. Start new run to continue.')
        if self.closing or not self.running or self.active or self.pause.is_set():
            return
        job = next((j for j in self.jobs if j.status in {'pending', 'retry_wait'}), None)
        if not job:
            self.running = False
            self.policy.finish()
            self.policy_hold = ''
            self._save()
            completed = sum(j.id in self.run_ids and j.status == 'completed' for j in self.jobs)
            failed = sum(j.id in self.run_ids and j.status == 'failed' for j in self.jobs)
            self.message = f'Queue finished: {completed} saved, {failed} failed.'
            return
        if self.policy_hold:
            self._save()
            return
        if job.retry_due > time.time():
            job.status = 'retry_wait'
            self.message = f'Retry in {max(1, int(job.retry_due - time.time()))}s. Pause or Cancel remains available.'
            return
        if job.cycle_attempts >= 2:
            job.status, job.error = 'failed', 'The two-attempt recovery budget is exhausted. Select Retry to begin a new cycle.'
            self._save()
            self.running = False
            self.message = job.error
            return
        if job.source_blocked:
            job.status, job.error = 'failed', 'This job was disconnected. Review it with your chosen login source.'
            self._save()
            return
        self.active = job.id
        self.verification = None
        self.message = 'Reconnecting through the selected source…' if job.cycle_attempts else 'Preparing download…'
        if job.run_id != self.policy.record['id']:
            job.run_id, job.run_bytes = self.policy.record['id'], 0
        job.attempt += 1
        job.cycle_attempts += 1
        job.retry_due = 0
        if job.video and not job.checkpoint:
            job.checkpoint = fresh_checkpoint(self._binding(job))
        job.received = job.checkpoint.get('offset', 0)
        job.status = 'downloading' if job.video else 'resolving'
        self.cancel = threading.Event()
        self.discard_current = threading.Event()
        self.meter.reset(job.received)
        self._save()
        pending = [(j.folder, j.video['size'] - j.checkpoint.get('offset', 0)) for j in self.jobs if j.video and j.status in {'pending', 'downloading'}]
        self.worker = threading.Thread(target=self._transfer, args=(deepcopy(job), self.cancel, pending, self.discard_current),
                                       name='Tera transfer', daemon=True)
        self.worker.start()

    def _duplicate(self, job, in_review=False):
        if not job.video or not job.identity:
            return ''
        for other in self.jobs:
            if other.id == job.id or not other.video:
                continue
            if (other.identity, other.video['fid'], other.video['size']) != (job.identity, job.video['fid'], job.video['size']):
                continue
            if other.status in {'pending', 'downloading', 'resolving', 'attention'}:
                return 'Already queued.'
            if other.status == 'completed' and prior_download(other.path, other.receipt, job.video['size']):
                return 'Prior download: recorded size and modification time still match.'
            if in_review and other.status == 'review' and self.jobs.index(other) < self.jobs.index(job):
                return 'Already selected in Review.'
        return ''

    @staticmethod
    def _metadata(videos):
        if not videos or any(not isinstance(v.name, str) or not v.name or not isinstance(v.fid, str) or not v.fid
                             or not isinstance(v.size, int) or isinstance(v.size, bool) or v.size <= 0 for v in videos):
            raise DownloadError('TeraBox returned invalid file metadata. No file was downloaded.')
        result, seen = [], set()
        for video in videos:
            key = (video.fid, video.size)
            if key not in seen:
                seen.add(key)
                result.append({'name': video.name, 'size': video.size, 'fid': video.fid})
        return result

    def _advance_review(self):
        self.review_requested.intersection_update(j.id for j in self.jobs if j.status == 'unreviewed')
        if self.closing or self.error_hold or self.review_active:
            return
        job = next((j for j in self.jobs if j.id in self.review_requested and j.status == 'unreviewed'), None)
        if job is None:
            return
        self.review_requested.discard(job.id)
        job.status = 'reviewing'
        self._save()
        self.review_active = job.id
        self.review_cancel = threading.Event()
        self.review_worker = threading.Thread(target=self._review, args=(deepcopy(job), self.review_cancel), name='Tera review', daemon=True)
        self.review_worker.start()

    def _review(self, job, cancel):
        try:
            reference = job.profile
            profile = FirefoxProfile(reference['name'], Path(reference['path'])) if reference else None
            client = self.client_factory(cancel, lambda text: None, profile)
            videos = self._metadata(client.find_videos(job.link))
            value, outcome = (share_key(job.link, getattr(client, 'metadata', {})), videos), 'discovered'
        except Cancelled:
            value, outcome = '', 'cancelled'
        except DownloadError as error:
            value, outcome = str(error), 'failed'
        except Exception:
            value, outcome = 'The share could not be reviewed. Check the connection and try again.', 'failed'
        self.post('_review_result', job_id=job.id, outcome=outcome, value=value)

    def _transfer(self, job, cancel, pending, discard):
        def emit(action, **data):
            self.post(action, job_id=job.id, attempt=job.attempt, **data)
        try:
            state = None
            if job.video:
                def commit(record):
                    return self.request('_checkpoint', job_id=job.id, attempt=job.attempt, checkpoint=record)
                state = self._checkpoint_state(job, commit, discard)
                last_check = [0.0]
                def verification(done, total):
                    now = time.monotonic()
                    if done == 0 or done == total or now - last_check[0] >= .15:
                        emit('_verification', done=done, total=total)
                        last_check[0] = now
                state.verification = verification
                def check_stopped():
                    _wait_for_download(cancel, self.pause, lambda text: emit('_status', text=text))
                state.check = check_stopped
                completed = state.reconcile()
                if completed:
                    emit('_result', outcome='completed', value=str(completed))
                    return
                # Other chosen folders on the same disk also consume the available space.
                needed = required_space(job.folder, pending)
                preflight(job.folder, needed, job.output_name or job.video['name'], job.video['fid'])
            reference = job.profile
            profile = FirefoxProfile(reference['name'], Path(reference['path'])) if reference else None
            client = self.client_factory(cancel, lambda text: emit('_status', text=text), profile, pause=self.pause)
            videos = client.find_videos(job.link)
            if not videos:
                raise DownloadError('No supported videos were found.')
            if job.video is None:
                value = self._metadata(videos)
                outcome = 'discovered'
            else:
                video = next((v for v in videos if v.fid == job.video['fid']), None)
                if (video is None or video.size != job.video['size'] or video.name != job.video['name']
                        or job.identity and share_key(job.link, getattr(client, 'metadata', {})) != job.identity):
                    raise RestartRequired('The selected file changed or is no longer available. Review it again before restarting.')
                last = [0.0]
                def update(received, total):
                    now = time.monotonic()
                    if now - last[0] >= .15 or received == total:
                        emit('_progress', received=received, total=total)
                        last[0] = now
                if job.output_name:
                    video = replace(video, name=job.output_name)
                policy = TransferPolicy(self.limiter, lambda amount: self.request('_bytes', job_id=job.id, attempt=job.attempt, amount=amount))
                value = str(client.download(video, job.folder, update, checkpoint=state, policy=policy))
                outcome = 'completed'
        except Cancelled:
            outcome, value = 'cancelled', 'The operation was cancelled.'
        except RestartRequired as error:
            outcome, value = 'restart', str(error)
        except StorageError as error:
            outcome, value = 'storage', str(error)
        except OSError:
            outcome, value = 'storage', 'The file could not be saved. Check free space or choose another folder, then Resume.'
        except DownloadError as error:
            outcome, value = ('login' if error.kind == 'login' else 'storage' if error.kind == 'storage' else 'failed'), str(error)
            if job.video and any(os.path.lexists(path) for path in target_paths(job.folder, job.output_name or job.video['name'], job.video['fid'])):
                outcome, value = 'storage', 'A file or partial with this name exists. Rename, choose another folder, or Skip.'
            emit('_result', outcome=outcome, value=value, kind=error.kind, retry_after=error.retry_after)
            return
        except Exception:
            outcome, value = 'failed', 'The file could not be saved. Check the destination and connection, then retry.'
        finally:
            if discard.is_set() and state is not None:
                state.discard_owned()
        emit('_result', outcome=outcome, value=value)

    def _snapshot(self):
        current = self._job(self.active) if self.active else None
        members = [j for j in self.jobs if j.id in self.run_ids and j.status not in {'skipped', 'cancelled'}]
        total = sum(j.video['size'] for j in members if j.video)
        received = sum(j.received for j in members)
        unknown = any(not j.video for j in members)
        speed = self.meter.rate_at(time.monotonic()) if current and current.video and not self.pause.is_set() and not self.intent and self.verification is None else 0
        held = bool(self.policy_hold and not self.active and self.running)
        return deepcopy({'jobs': [asdict(j) for j in self.jobs], 'preferences': self.preferences,
                         'active': self.active, 'verification': self.verification, 'running': self.running, 'paused': self.pause.is_set() or held,
                         'manual_paused': self.pause.is_set(), 'policy_hold': self.policy_hold,
                         'run_options': self.policy.options, 'run_state': self.policy.record,
                         'timezone': local_now().strftime('%Z (UTC%z)'),
                         'stopping': bool(self.intent) or bool(self.error_hold and self.active),
                         'pause_acknowledged': self.acknowledged or held, 'closing': self.closing,
                         'pause_after': self.boundary, 'review_busy': bool(self.review_active or self.review_requested),
                         'review_space': self.review_space,
                         'message': self.message, 'speed': speed, 'received': received, 'total': total,
                         'unknown': unknown, 'eta': (total - received) / speed if speed and not unknown else None})

    def _publish(self):
        self.events.put(('snapshot', self._snapshot()))
