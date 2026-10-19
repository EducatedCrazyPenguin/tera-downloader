"""One owner for queue state; transport workers report by stable job/attempt IDs."""
from __future__ import annotations

from collections import deque
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from pathlib import Path
import queue
import threading
import time
import uuid

from app_state import StateError, StateStore
from firefox_session import FirefoxProfile
from terabox import Cancelled, DownloadError, PAUSED_STATUS, TeraBox, parse_links


TERMINAL = {'completed', 'failed', 'skipped', 'cancelled'}


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
        self.worker = None
        self.cancel = threading.Event()
        self.running = False
        self.closing = False
        self.intent = ''
        self.acknowledged = False
        self.error_hold = False
        self.message = 'Add links, then Start. Restored jobs wait for your instruction.'
        self.run_ids = set()
        self.meter = SpeedMeter()
        store = None
        try:
            store = self.store = StateStore(self.directory, self.legacy_settings)
            self.preferences = store.load_preferences()
            try:
                for row in store.load_jobs():
                    job = Job(**row)
                    parse_links(job.link)
                    if job.status not in TERMINAL | {'pending', 'resolving', 'downloading'}:
                        raise ValueError('Invalid status')
                    if job.video and (set(job.video) != {'name', 'size', 'fid'} or int(job.video['size']) <= 0):
                        raise ValueError('Invalid metadata')
                    if job.status not in TERMINAL:
                        job.status = 'pending'
                        job.received = 0
                    self.jobs.append(job)
            except (TypeError, ValueError, DownloadError):
                raise StateError('Saved jobs are invalid. The queue was left unchanged.') from None
            self.saved_jobs = deepcopy(self.jobs)
            self.ready.set()
            self._publish()
            while True:
                try:
                    action, data, reply = self.commands.get(timeout=.5)
                except queue.Empty:
                    if self.active:
                        self._publish()
                    continue
                if action == '_status' and data['text'] == self.message:
                    continue
                try:
                    value = self._handle(action, data)
                    if action != 'snapshot':
                        self._advance()
                        self._publish()
                    if reply:
                        reply.put((True, value))
                except (StateError, DownloadError, OSError, ValueError) as error:
                    # Failed persistence must stop further transfers, not silently lose changes.
                    if isinstance(error, StateError):
                        self.running = False
                        self.pause.set()
                        self.error_hold = True
                    message = str(error) if isinstance(error, (StateError, DownloadError)) else 'The operation could not finish. Check the selected folder and retry.'
                    self.message = message
                    self.events.put(('error', message))
                    if reply:
                        reply.put((False, StateError(message)))
                if self.closing and not self.active:
                    self._save()
                    break
        except Exception as error:
            self.startup_error = error if isinstance(error, StateError) else StateError('The queue could not open. Existing data was left in place.')
            self.events.put(('error', str(self.startup_error)))
        finally:
            self.cancel.set()
            self.pause.clear()
            if self.worker:
                self.worker.join(26)
            if store:
                store.close()
            self.ready.set()
            self.closed.set()
            self.events.put(('closed', None))

    def _save(self):
        # Transport URLs/cookies never enter Job or its serialized representation.
        try:
            self.store.save_jobs([asdict(job) for job in self.jobs])
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

    def _handle(self, action, data):
        if action == 'snapshot':
            return self._snapshot()
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
            if not set(changes) <= {'firefox_profile', 'last_destination', 'favorites'}:
                raise DownloadError('Unsupported preference.')
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
            if self.running or self.active:
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
            if self.error_hold:
                if self.active:
                    raise DownloadError('Wait for the current request to stop, then retry saving the queue.')
                self._save()
                self.error_hold = False
            if self.active and self.intent:
                raise DownloadError('Wait for the current stop operation to finish.')
            if not self.running:
                self.run_ids = {j.id for j in self.jobs if j.status == 'pending'}
                self.running = bool(self.run_ids or self.active)
            self.pause.clear()
            self.acknowledged = False
            current = self._job(self.active).received if self.active else 0
            self.meter.reset(current)
            self.message = 'Resuming…' if self.active else 'Starting queue…'
            return
        if action == 'pause':
            if self.running:
                self.pause.set()
                self.acknowledged = not bool(self.active)
                self.message = 'Pausing… waiting for the current network request.'
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
            if job.status != 'pending':
                raise DownloadError('Only pending jobs can be removed. Use Skip for the active file.')
            self.jobs.remove(job)
            self._save()
            return
        if action == 'retry':
            selected = set(data['job_ids'])
            count = 0
            for job in self.jobs:
                if job.id in selected and job.status == 'failed' and not job.source_blocked:
                    job.status, job.error, job.received, job.finished = 'pending', '', 0, 0
                    count += 1
                    if self.running:
                        self.run_ids.add(job.id)
            self._save()
            self.message = (f'{count} failure(s) requeued.' + (' They will run after the active item.' if self.running else ' Click Start to retry.')) if count else 'No retryable failures selected. Disconnected jobs must be added again.'
            return
        if action == 'clear_history':
            if self.running or self.active:
                raise DownloadError('Finish or stop the queue before clearing history.')
            self.jobs = [j for j in self.jobs if j.status not in TERMINAL]
            self._save()
            self.message = 'History cleared. Downloaded files were kept.'
            return
        if action in ('skip', 'cancel', 'close'):
            if action != 'skip':
                self.running = False
                self.pause.clear()
                for job in self.jobs:
                    if job.status == 'pending' and action == 'cancel':
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
                elif not self.pause.is_set() and not self.intent and data['text'] != PAUSED_STATUS:
                    self.message = data['text']
            elif action == '_progress':
                job.received = data['received']
                self.meter.update(job.received)
            elif action == '_result':
                outcome, value = data['outcome'], data['value']
                if outcome == 'discovered' and not self.intent:
                    videos = value
                    job.video = videos[0]
                    job.status = 'pending'
                    position = self.jobs.index(job) + 1
                    extras = [Job(uuid.uuid4().hex, job.link, job.folder, job.profile, video) for video in videos[1:]]
                    self.jobs[position:position] = extras
                    self.run_ids.update(j.id for j in extras)
                elif outcome == 'completed':
                    job.status, job.path = 'completed', value
                    job.received = job.video['size']
                    job.finished = time.time()
                elif self.intent == 'close':
                    job.status, job.received = 'pending', 0
                elif self.error_hold:
                    job.status, job.received = 'pending', 0
                elif self.intent in ('skip', 'cancel'):
                    job.status = 'skipped' if self.intent == 'skip' else 'cancelled'
                    job.received, job.finished = 0, time.time()
                else:
                    job.status, job.error, job.received, job.finished = 'failed', value, 0, time.time()
                self.worker.join(1)
                self.worker = None
                self.active, self.intent = None, ''
                self._save()
            return
        raise DownloadError('Unsupported queue action.')

    def _advance(self):
        if self.closing or not self.running or self.active or self.pause.is_set():
            return
        job = next((j for j in self.jobs if j.status == 'pending'), None)
        if not job:
            self.running = False
            completed = sum(j.id in self.run_ids and j.status == 'completed' for j in self.jobs)
            failed = sum(j.id in self.run_ids and j.status == 'failed' for j in self.jobs)
            self.message = f'Queue finished: {completed} saved, {failed} failed.'
            return
        self.active = job.id
        job.attempt += 1
        job.received = 0
        job.status = 'downloading' if job.video else 'resolving'
        self.cancel = threading.Event()
        self.meter.reset()
        self._save()
        self.worker = threading.Thread(target=self._transfer, args=(deepcopy(job), self.cancel),
                                       name='Tera transfer', daemon=True)
        self.worker.start()

    def _transfer(self, job, cancel):
        def emit(action, **data):
            self.post(action, job_id=job.id, attempt=job.attempt, **data)
        try:
            reference = job.profile
            profile = FirefoxProfile(reference['name'], Path(reference['path'])) if reference else None
            client = self.client_factory(cancel, lambda text: emit('_status', text=text), profile, pause=self.pause)
            videos = client.find_videos(job.link)
            if not videos:
                raise DownloadError('No supported videos were found.')
            if job.video is None:
                if any(not isinstance(v.name, str) or not v.name or not isinstance(v.fid, str) or not v.fid
                       or not isinstance(v.size, int) or v.size <= 0 for v in videos):
                    raise DownloadError('TeraBox returned invalid file metadata. No file was downloaded.')
                value = [{'name': v.name, 'size': v.size, 'fid': v.fid} for v in videos]
                outcome = 'discovered'
            else:
                video = next((v for v in videos if v.fid == job.video['fid']), None)
                if video is None or video.size != job.video['size']:
                    raise DownloadError('The selected file changed or is no longer available. Add the share again.')
                last = [0.0]
                def update(received, total):
                    now = time.monotonic()
                    if now - last[0] >= .15 or received == total:
                        emit('_progress', received=received, total=total)
                        last[0] = now
                value = str(client.download(video, job.folder, update))
                outcome = 'completed'
        except Cancelled:
            outcome, value = 'cancelled', 'The operation was cancelled.'
        except DownloadError as error:
            outcome, value = 'failed', str(error)
        except Exception:
            outcome, value = 'failed', 'The file could not be saved. Check the destination and connection, then retry.'
        emit('_result', outcome=outcome, value=value)

    def _snapshot(self):
        current = self._job(self.active) if self.active else None
        members = [j for j in self.jobs if j.id in self.run_ids and j.status not in {'skipped', 'cancelled'}]
        total = sum(j.video['size'] for j in members if j.video)
        received = sum(j.received for j in members)
        unknown = any(not j.video for j in members)
        speed = self.meter.rate_at(time.monotonic()) if current and current.video and not self.pause.is_set() and not self.intent else 0
        return deepcopy({'jobs': [asdict(j) for j in self.jobs], 'preferences': self.preferences,
                         'active': self.active, 'running': self.running, 'paused': self.pause.is_set(),
                         'stopping': bool(self.intent) or bool(self.error_hold and self.active),
                         'pause_acknowledged': self.acknowledged, 'closing': self.closing,
                         'message': self.message, 'speed': speed, 'received': received, 'total': total,
                         'unknown': unknown, 'eta': (total - received) / speed if speed and not unknown else None})

    def _publish(self):
        self.events.put(('snapshot', self._snapshot()))
