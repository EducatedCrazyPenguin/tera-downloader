# Personal desktop release 0.1.0

Approved 20 October 2026. Extend the completed A–E roadmap below in four sequential slices: saved-byte verification/recovery feedback; filtered and sorted batch controls with atomic destination edits; private bounded diagnostics and About/Help; a self-contained per-user Windows installation. Track acceptance and verification in the P01–P06 checklist in todo.md. Keep the earlier live-provider gate pending.

Use optional checkpoint verification callbacks and transient attempt-tagged queue snapshot fields, without a database migration. Search/sort Review and History only; Select/Deselect visible preserves hidden choices. Batch destination changes validate every selected job before a single save and preserve all jobs on failure.

Diagnostics use allowlisted codes/times/counts only, two 128 KiB files, no private strings or automatic upload. Package Python/Tk/tray with PyInstaller and a quiet per-user Inno Setup installer under LocalAppData/Programs/Tera, preserving separate state and downloads. Version 0.1.0; no autostart, forced close, reboot or post-install launch. A mutex protects running instances from installer changes. CLI --data-dir overrides TERA_DATA_DIR, which overrides default state; isolated state disables legacy import. Saved destinations take priority over Windows Downloads/Tera.

Verify focused tests, full offline suite, isolated synthetic native UI, packaged startup without system Python, synthetic upgrade retention, and actual installed shortcut startup with isolated state. Preserve user data and untracked AGENTS.md; commit/push completed slices. Existing historical roadmap follows unchanged. Evidence: 2/3 — Current code and approved plan establish scope; new runtime and installation checks are pending. No live download or authentication is authorized by this release plan.

# Tera product roadmap and incorporation plan

Date: 19 October 2026; updated 20 October 2026. Status: approved roadmap; Deliveries A-E implemented locally. Live-provider verification remains pending.

## Outcome and scope

Turn the current Windows/Tkinter downloader into a dependable tool for heavy download use, incorporating both feature lists from this conversation. Favor recoverable jobs, clear progress, and quiet operation over a framework rewrite or more simultaneous connections.

The capability map and build order below are the reviewable design proposal. They are not claims that these features already exist. Implementation tasks and acceptance checks live only in [todo.md](todo.md); do not create duplicate feature plans or a separate specification for each small preference.

**Evidence: 2/3 — All five local deliveries have offline/native evidence, recorded below: 128 offline tests and the queue/recovery/limits and Windows tray/quiet-launcher checks pass on Python 3.12.10. Live TeraBox range/validator behavior, large real transfers and real notification delivery remain unverified. The capability map below records the approved design; delivery records establish what was implemented and tested.**

> 🧠 **From Hindsight memory (Pause and resume active Tera downloads)** — Existing Pause/Resume preserves the current stream, partial bytes, and queue position only while Tera stays open. Restart recovery and automatic reconnection were excluded from that earlier feature. Current source confirms these boundaries; this roadmap deliberately proposes extending them.

### Coverage of the requested features

| ID | Capability | Proposed behavior | Delivery |
|---|---|---|---|
| F01 | Remembered and favorite folders | Remember the last destination, allow named favorites, optionally create a separate folder per share. | A |
| F02 | Restore unfinished work | Save pending links, selected videos, destination, order, and job status; reopening restores them without automatically starting network work. | A |
| F03 | Editable queue | Add reviewed jobs during a run, move pending jobs up/down or next, remove pending jobs, and skip the active video. | A |
| F04 | Local history and retry failed | Show completed/failed jobs, filter history, retry selected failures, reveal a saved file's folder, and clear history without deleting downloads. | A |
| F05 | Progress dashboard | Show current speed, file/queue progress, estimated remaining time, and waiting/paused reasons. | A |
| F06 | Review and selection | Before adding a batch, show discovered videos, selection, total known size, destination, and free space. | B |
| F07 | Duplicate detection | Flag exact repeated links early and matching provider file identities after discovery; use completion records to recognize prior downloads. | B |
| F08 | Storage safeguards | Check the destination, available space, safe filenames, and filename conflicts; never overwrite existing files. | B |
| F09 | Finish current file, then pause | Keep Pause now; add a distinct boundary-pause action that does not interrupt the current video. | B |
| F10 | Resume partial files after restart/disconnect | Retain owned checkpoints and resume only when file identity and HTTP response validation make appending safe. Otherwise offer an explicit restart. | C, provider-gated |
| F11 | Recovery and useful failure actions | Classify failures, perform bounded transient recovery, refresh expired URLs through the selected login, and offer Retry, Check login, Change folder, or Restart as appropriate. | C |
| F12 | Bandwidth cap | Apply an optional adjustable file-transfer speed cap without blocking the UI. | D |
| F13 | Scheduling | Support a daily download window, including overnight windows, using the displayed Windows local timezone; operate only while Tera is running, including in the tray. | D |
| F14 | Time and size limits | Stop after the current file when a chosen deadline or file-transfer byte budget is reached; show the boundary behavior clearly. | D |
| F15 | Quiet operation and optional notifications | Use inline statuses and recovery actions; no surprise applications, sounds, file opens, or notification popups by default. | A/D/E |
| F16 | Tray/background operation | Explicitly minimize Tera to the tray; restore it or control the queue through its menu; optionally notify once on completion or a new action-required condition. | E |

## Baseline app and proposed component boundaries

Verified integration points at the starting commit `96d766b` (line numbers below describe that baseline):

- `terabox.py:104` owns the client/session setup; `:168` opens allowlisted requests; `:204` discovers videos; `:275` performs exclusive temporary-file creation, streaming, size checks, and completion.
- `terabox.py:343` processes a fixed list sequentially. UI queue rows and progress use list indexes, which must become stable job identities before reordering is safe.
- `terabox.py:389` stores only the selected profile in a project-local JSON file. `:421` builds Tkinter widgets; `:507` disables almost all editing during work; `:660` closes by cancelling.
- `firefox_session.py` remains the read-only, TeraBox-only cookie boundary. `--check`, URL validation, safe filenames, and the existing offline/native harnesses should be reused.

### Proposed capability map

These are responsibility boundaries, not seven mandatory new Python packages. Add a small module only where the corresponding work needs one.

| Module ID | Responsibility | Depends on |
|---|---|---|
| local-state | Settings migration, queue/history records, protected source links, checkpoint records, and single-instance ownership per data directory. | Existing standard library and Windows data protection |
| run-policy | Cancellation-aware rate limits, schedule eligibility, manual holds, and finish-current/time/size rules. | local-state |
| transfer-recovery | Existing TeraBox transport plus validated checkpoints, partial-file recovery, and classified transport failures. | local-state, run-policy |
| review-storage | Share discovery, video selection, destinations, disk checks, and duplicate/conflict decisions. | Existing TeraBox discovery, local-state |
| queue-engine | Stable jobs, ordering, commands, lifecycle transitions, retries, history updates, and progress snapshots. | local-state, transfer-recovery, review-storage, run-policy |
| activity-ui | Tkinter Review, Queue, and History views, dashboard, settings, and inline recovery actions. | queue-engine, review-storage, run-policy |
| desktop-integration | Explicit tray mode, optional notifications, quiet launcher, and clean shutdown. | activity-ui commands and queue snapshots |

Build order: stable queue identities -> local-state -> editable queue/history/dashboard -> review/storage/boundary pause -> validated recovery -> run policies -> desktop integration. Build a default/no-limit policy first; add its advanced rules later. Keep transfer and policy code independent of Tkinter.

## How the features fit together

### A. Persistent queue and everyday workflow

- Retain Python/Tkinter, the direct TeraBox client, and one active file transfer. Replace the fixed-list UI loop with a queue coordinator using plain `queue.Queue`, stable job IDs, and operation IDs on worker events. Late events from an old attempt must not change a reordered, skipped, or retried job.
- The coordinator owns queue transitions and serializes state writes. A transfer worker performs the active download; at most one metadata worker discovers/reviews additional shares. Workers own their clients and database connections; no cookie jar, SQLite connection, or Tk widget is shared across threads.
- Reuse `TeraBox.download`, `download_queue`, existing positional arguments, and `--check` through small adapters as needed. Add optional keyword inputs for transfer checkpoints/policies and typed job snapshots; keep existing default behavior and CLI output compatible until a documented UI-only change requires otherwise.
- A job records its stable ID, order, source reference, selected profile reference, provider file identity, name, expected size, destination, current attempt, lifecycle status, and checkpoint reference. Authentication tokens and signed URLs are never part of a stored job.
- Queue commands cover add, move, remove pending, skip current, retry failed, pause now, pause after current, resume, cancel, and save/exit. Pending edits do not interrupt the active file. Skip/cancel delete only the active attempt's owned partial and preserve completed files; save/exit is a distinct action.
- Introduce a versioned SQLite queue/history store and atomic JSON preferences under `%LOCALAPPDATA%\Tera`. Allow a test data-directory override. Import the legacy profile preference once without changing or deleting `.tera-settings.json`; preserve unknown settings during subsequent writes. Keep the current downloads folder as the initial default until the user chooses another.
- Protect persisted source links and any share access codes with Windows current-user DPAPI. File names, destinations, and history remain local user data, with a clear-history control and documentation. No cookies, account identifiers, page tokens, or signed media URLs are persisted. If protection or persistence fails, show the failure and do not silently save sensitive fields in plaintext or claim the queue is saved.
- Use SQLite transactions and the backup API before schema migrations. Recover corrupt/incompatible state without overwriting it. Acquire a data-directory lock before queue writes so another Tera instance cannot adopt the same jobs/partials. Tests use disposable directories and never attach to the daily-use instance.
- Reopening restores incomplete work in a held state and requires a user start/resume action. Phase A restores jobs; unfinished files still restart from zero until Phase C safely enables partial-byte reuse. Make that limitation explicit in the UI.

### B. Review, storage, and job controls

- Add a compact Review view, a Queue table, and a History view using existing ttk widgets. Keep the login source visible and fixed for an active job. Put less frequent limits/notification settings in one settings panel rather than adding many main-window buttons.
- Review performs real discovery only after the user submits links. It lists videos with selected-by-default checkboxes, file sizes, destination, and aggregate selected size; Download selected starts a new run or appends to the current run. User exclusions persist with the batch. Unreviewed inputs can be saved, but never start automatically.
- Deduplicate exact normalized source inputs before discovery. After discovery, use authoritative share/file identity and expected size; do not assume different aliases or filenames mean identical content. A prior completion is reusable only when its recorded file still exists with matching recorded size/metadata. Label that as a prior download, not a cryptographic integrity proof.
- Existing unrelated files remain protected. Offer skip, another destination, or a user-approved unused name; do not adopt arbitrary `.part` files or silently replace anything. Clear history also forgets its duplicate markers, and never deletes files or unfinished jobs.
- Validate the destination and selected byte total before starting; recheck free space before each file. Running out of space holds the affected job with a Change folder action. Do not scan unrelated directories. Per-share folders use safe names and a share identifier to avoid collisions.
- Changing a pending job's destination is immediate. Changing an active/partial job's destination requires stopping it and explicitly restarting in the new location; v1 does not move a large partial file in the background.
- Pause now keeps the current in-memory pause semantics. Finish current, then pause prevents the next file from starting and remains held until explicit Resume. If there is no active file it pauses immediately. Cancel/skip/save-exit have distinct, tested cleanup rules.

### C. Durable transfer recovery and actionable errors

- Use a per-job owned partial path and a recorded checkpoint containing file identity, expected size, durable offset, and a strong HTTP validator when available. Commit checkpoints only after flushing/syncing the corresponding bytes. Checkpoint periodically and at orderly holds/exit, not on every progress repaint.
- On recovery, validate ownership, path containment, file length, current share metadata, and the selected profile. Truncate only an owned partial's uncommitted tail; a shorter/missing partial requires restart. Never append based only on filename, length, or an `Accept-Ranges` advertisement.
- For append, send `Range` and strong `If-Range`; require a consistent `206`, exact starting offset/total, and matching representation validator. A `200`, `416`, changed/missing strong validator, malformed range, or wrong content becomes Restart required, never appended data. Re-resolve URLs instead of persisting signed ones. This conservative protocol follows [RFC 9110](https://www.rfc-editor.org/rfc/rfc9110.html#section-14.2).
- Graceful save/exit closes the response and records a suspended job; explicit Cancel still removes its owned partial. Preserve valid resumable partials on recoverable transport failures, with an explicit discard/restart action. Integrity failures are quarantined from resume and cannot be finalized. Reconcile crashes around final rename without overwriting an existing target or claiming an unverified file is complete.
- Add machine-readable error categories to `DownloadError` while preserving safe human messages. Distinguish transient connection/server/rate-limit failures, login required, unavailable/restricted share, storage failure, response/integrity failure, and restart required. Never infer anonymous fallback from a login failure.
- Allow at most two automatic attempts per recovery cycle, including the first attempt. Honor `Retry-After`; otherwise use a visible, cancellable five-second delay before the retry. Persist consumed attempts so restarting does not create an infinite loop. Then require Retry or another corrective action. Do not retry access denial, disk failure, malformed content, or unknown API codes automatically.
- A partial transfer resumes automatically only if validated resume is available. Otherwise preserve its pending job and ask for an explicit full restart; do not silently redownload a large file. Refresh an expired media URL through the selected session once within the same attempt budget; if auth still fails, hold for Check login.
- **Provider gate:** implement protocol tests with synthetic responses first. A small, explicitly authorized live check must establish actual TeraBox response/validator behavior before advertising true resume. If unsupported, ship queue restoration and an honest Restart required fallback; keep full partial-byte resume marked pending. This planning task does not authorize reading live cookies or downloading a sample.

### D. Progress, bandwidth, schedules, and limits

- Display current speed from a rolling five-second monotonic sample, current/overall bytes, file counts, and ETA where totals and rate are known. Show unknown totals honestly while discovery is incomplete; reset samples on resume/retry and show no ETA while held. Distinguish actual bytes transferred from progress already present in a resumed file.
- Add an unlimited-by-default file-transfer speed cap, adjustable during a run. Use cancellation-aware chunk pacing; throttle waits must still respond to pause, skip, and exit. Avoid large reads that make a low cap unusably bursty.
- Add an optional daily start/end window, including crossing midnight, evaluated in Windows local time. This machine currently uses India Standard Time (UTC+05:30); display the timezone beside the schedule. Reevaluate after sleep, clock/timezone changes, and restart. Per the confirmed user preference, scheduling operates only while Tera is running, including in the tray. Do not install a Windows task, automatically launch Tera, wake the machine, or change power/network settings.
- Manual Pause, finish-current holds, exceeded budgets, and needs-attention states take precedence over a schedule reopening. A schedule can resume only its own schedule hold. Ending the window finishes the active file, then holds; the UI must state this is a boundary rule, not a hard network cutoff.
- Optional per-run deadline and file-transfer byte budget also finish the current file, then hold. The byte budget counts file-body bytes received during that run, including retransfers; an existing resumed prefix is not charged again. A finish-current budget can overrun by the remaining active file, which must be disclosed before starting. New explicit runs reset the run budget; pause/resume does not.

### E. Quiet desktop integration

- Quiet mode is the default: inline validation/errors; no sounds, automatic Explorer/video launches, Firefox launches, global keystrokes, clipboard monitoring, or attention-stealing completion dialogs. Login in Firefox and Reveal folder remain explicit user actions.
- Per the confirmed user preference, window X means Save queue and exit. Minimize to tray is a separate explicit action; do not hide the window unless a working tray icon exists. Tray commands feed the same queue command channel as Tkinter. Exit from the tray uses the same orderly save/exit path.
- Use a narrow optional Windows tray integration based on `pystray`/Pillow instead of hand-maintaining a Win32 message loop. Delivery E pins them in `requirements-desktop.txt` and verifies a project-local `.venv-desktop`; the base interpreter remains dependency-free. Ordinary downloading still works without the optional integration.
- Tray notifications are opt-in and contain generic completion/action-needed summaries, not private share URLs or filenames. Deduplicate repeated failures; queue/schedule polls never produce repeated popups. A missing tray backend disables the tray action visibly and keeps the window accessible.
- Add a quiet `pythonw`/`.pyw` launch path with safe local diagnostic logging. Keep `Start Tera.cmd` as the explicit diagnostic fallback. No Windows login autostart, automatic app launch, or persistent service is included by default.

## Delivery sequence and review checkpoints

| Delivery | Complete user-visible slice | Depends on | Exit check |
|---|---|---|---|
| A | Stable/persistent queue, saved folders, editable pending jobs, local history, and dashboard. | Current app | Restart restores queue without network activity; mutations and retry-failed target the right jobs. |
| B | Review/selection, deduplication, storage checks, finish-current pause, and clear corrective actions. | A | Synthetic review-to-download flow and all no-overwrite/cancel checks pass. |
| C | Owned checkpoints, safe restart recovery, bounded retries, URL refresh, and partial-resume capability reporting. | A/B | Crash/append/rename tests pass; provider support is either evidenced or explicitly pending. |
| D | Adjustable speed cap, daily windows, deadlines, and byte budgets. | A/B/C control interfaces | Fake-clock tests prove hold precedence, responsive waits, and correct accounting. |
| E | Tray mode, opt-in notifications, quiet launcher, and final UX/documentation integration. | A-D | Isolated Windows lifecycle checks prove restore/exit, no hidden orphan, and no surprise launches. |

Review the capability boundaries before implementation and review each completed delivery before expanding it. Each slice must leave the original flow usable. No speculative parallel file downloading, segmented acceleration, proxy resolution, cloud service, telemetry, account system, themes, or framework replacement is part of this roadmap.

## Verification, migration, and remaining uncertainties

- Start with focused `unittest` coverage, then `python -m unittest -v`. If the sandbox's default temporary location fails, reuse the already verified workspace-temporary-directory runner; do not weaken assertions or touch real data.
- Extend `smoke_terabox_gui.py` for Review -> selected queue -> reorder/add -> pause/boundary pause -> resume -> history/retry -> save/restore. Use synthetic profiles, mocked network, and disposable settings/download directories. Inspect each extended harness before running it.
- Add a loopback HTTP fixture for complete/ranged/ignored/invalid responses, expired URLs, truncated streams, and retry responses. It must be explicitly loopback-only and bounded, with no browser or external provider connection.
- Add crash/restart checks for persisted job transitions, partial checkpoints, completion-before-rename and rename-before-history-update. Test corrupt state, failed writes, changed/missing source metadata, data-protection failure, concurrent instances, missing files, and existing target conflicts.
- Use fake clocks for speed samples, throttle waits, retry delays, overnight schedules, sleep/clock changes, and budgets. Check that cancellation/exit wins promptly over every wait.
- Verify tray, notifications, and the quiet launcher in a bounded isolated Windows instance. Native visible testing, if necessary, needs advance notice and the existing standing conditions; never attach to the user's app or profile. Do not test real Firefox login/downloads without an explicit request.
- Before any migration, use SQLite backup or an atomic JSON backup as appropriate and prove restore. Keep old preference data and existing downloads intact. Rollback must refuse unknown new state safely rather than erase it.
- No dedicated installer/build pipeline was found in this source project. Validate the source launchers; if packaging or an existing daily-use shortcut becomes part of a later release, follow the desktop release agreement and distinguish source, native, and installed verification.
- Main unknowns: provider support for strong validated range resume; stable validators across refreshed URLs; real Windows notification delivery, Explorer restart and sleep/resume. The isolated Windows tray/quiet-launcher lifecycle is now verified as described in Delivery E below; it is not an installed-package or live-provider check.

## Confirmed preferences and remaining defaults

Confirmed by the user on 19 October 2026: clicking X saves the queue and exits; scheduled downloads operate only while Tera is running, including in the tray, without Windows automatically launching it. These decisions are requirements, not unanswered preferences. Other defaults: quiet mode on, notifications off, one active file, review before adding a batch, explicit start after restoration, unlimited speed/time/bytes until configured, and local-only persisted history until cleared.

## Supporting sources

- Current repository at `96d766b`: `README.md`, `terabox.py`, `firefox_session.py`, `test_terabox.py`, `test_firefox_session.py`, `smoke_terabox_gui.py`, `Start Tera.cmd`, `.gitignore`, and the working agreements. Files were inspected without reading real settings, cookies, or downloads.
- [Python SQLite documentation](https://docs.python.org/3.10/library/sqlite3.html): standard-library local transactions, connection ownership, and backup support.
- [Microsoft CryptProtectData](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata): current-user data protection is the proposed protection for saved source links/access codes; it does not protect against code running as that user or guarantee recovery after account changes.
- [RFC 9110](https://www.rfc-editor.org/rfc/rfc9110.html#section-14.2): safe partial-response handling; it does not prove TeraBox supports resume.
- [pystray integration guidance](https://pystray.readthedocs.io/en/latest/faq.html) and [usage](https://pystray.readthedocs.io/en/latest/usage.html): a Windows tray loop can coexist with the Tkinter main loop; native lifecycle behavior still requires testing.

## Delivery A implementation record — 19 October 2026

Implemented `app_state.py` (current-user DPAPI links, transactional SQLite state, atomic preferences, legacy import and data-directory locking), `queue_manager.py` (stable jobs/attempts, queue commands, history and progress), and `tera_gui.py` (queue/history views, destinations/favorites, controls and dashboard). `terabox.py` retains the direct transfer/legacy queue interfaces and routes GUI startup through the new view, with `--data-dir` for isolation. No dependency was added.

Closing now saves pending jobs and exits after the owned transfer stops; interrupted files still restart from zero. Restoration starts no authentication or network work. Disconnect also blocks queued authenticated jobs until an explicit re-add, preventing silent cookie reuse or anonymous fallback. Source input stays in the textbox until a successful queue save is acknowledged.

**Delivery A evidence: 3/3 — 47 offline tests passed; the withdrawn native Tkinter smoke verified the integrated flow, exact synthetic files, save/exit and restart, and the real isolated CLI entry point on Python 3.12.10 / Tk 8.6 / SQLite 3.49.1. No live Firefox login or TeraBox download was used.**

The initial UI still adds share links directly and discovers files when started. Review/selection and per-share folders belong to Delivery B; durable partial bytes, provider resume, and recovery policies belong to C. Rate/schedule/budget controls and tray/notification integration remain in D/E. The complete roadmap is not yet implemented.

## Delivery B implementation record — 19 October 2026

The UI now reviews submitted shares before Download selected, with persistent checkbox exclusions, known size totals and destinations. The existing coordinator owns those records and at most one additional metadata worker; clients and login sources remain isolated from the active transfer. Exact normalized sources and authoritative share/file/size identities prevent duplicate work. Prior-download receipts require a matching existing size and modification time, without claiming cryptographic verification.

`review_storage.py` supplies shared helpers for identity, hashed per-share folders, writable destination/free-space preflight and existing target/partial protection. Remaining selected bytes on the same filesystem are counted before each file. Storage conflicts/failures hold the queue for explicit Rename, Change folder, Skip or Resume. Active destinations are immutable until stopped and explicitly restarted. Finish current, then pause completes the active file and requires Resume before starting another; Pause now retains its original cancellable stream hold.

The earlier Delivery A workflow description above records that delivery's initial state. Review and storage are now implemented, not pending. No schema migration, transport dependency, signed URL persistence or byte-level recovery was added. C-E remain pending.

**Delivery B evidence: 3/3 for the checked local scope — 65 offline tests and the integrated withdrawn native Tkinter/isolated real-entry-point smoke passed on Python 3.12.10 / Tk 8.6 / SQLite 3.49.1. This includes synthetic exact files, saved review/exclusions, duplicate handling, storage correction, boundary pause, Cancel/reset and clean save/restore. Whole-product evidence remains 2/3: no live authentication/download, large-file, provider resume or installed-package check was run.**

## Delivery C implementation record — 20 October 2026

Implemented owned partial checkpoints and strict conditional continuation in `transfer_state.py`, plus error categories and bounded retry policy in `recovery.py`. The queue persists only metadata/validators and commits offsets after file flush/fsync. Save/exit keeps verified prefixes; explicit discard actions delete only owned partials. Recovery verifies the recorded file identity/hash, safely trims uncommitted tails, and checks both sides of final rename. The optional transport checkpoint parameter leaves the legacy default API behavior intact. Existing A/B records load with defaults; no schema migration was needed.

Continuation requires fresh matching selected metadata, a strong ETag and exact If-Range/206 Content-Range/length. Unsafe replies hold for explicit Restart rather than appending or silently redownloading. A new explicit Retry cycle allows at most two attempts; Retry-After/default delay and consumed attempts are persisted. Pause/Cancel/exit remain responsive during the wait. Login and storage failures provide inline corrective actions; held login actions target that job's saved profile and cannot silently switch source.

**Delivery C evidence: 3/3 for the checked local scope — 91 offline tests, the bounded real loopback HTTP fixture, three hidden forced-crash stages and the withdrawn native recovery/Restart flow passed on Python 3.12.10 / Tk 8.6 / SQLite 3.49.1. Whole-product evidence remains 2/3: the live TeraBox provider gate, large real files, power loss, installed packaging and D/E remain pending. No real authentication/download or additional dependency was used.**

## Delivery D implementation record — 20 October 2026

Implemented the runtime limits in `run_policy.py`, with the existing coordinator retaining ownership of run transitions and byte accounting. A shared limiter paces file-body reads and responds to cap changes, pause and cancellation. Daily windows use Windows local time, include overnight intervals, reevaluate without OS scheduling tasks and release only their own holds. Manual/boundary/error pauses remain separate. Time and byte limits finish the active file and latch until an explicit new run; their possible overrun is disclosed in the UI before starting.

Run options and identity/start/counters persist through existing preferences and job payloads. Actual body reads count even when retransferred; existing resumed bytes do not. Resume, Apply limits and clear-history preserve the open run's budget. The deadline includes pauses, waiting and time after exit. Abrupt interruption of a byte-limited transfer conservatively holds uncertain accounting for an explicit new run while retaining the verified partial. Settings, timezone, current counter/deadline/hold and explicit Start new run are available in the native Run limits tab. No dependency or schema migration was needed.

**Delivery D evidence: 3/3 for the checked local scope — 111 offline tests and the withdrawn native combined cap/window/boundary/retry/budget/save-restore scenario passed on Python 3.12.10 / Tk 8.6 / SQLite 3.49.1. Whole-product evidence remains 2/3: E, live TeraBox compatibility, large real transfers, power loss and installed packaging remain pending. No real authentication/download, Windows autolaunch or power-setting change was used.**

## Delivery E implementation record — 20 October 2026

`desktop_integration.py` adds a lazy optional Windows tray backend. Tk is hidden only after checked Windows registration; missing/startup-failed support leaves it available, and a failed backend loop restores a hidden window. Show, Pause, Resume/Start, Cancel and Save/exit callbacks enqueue UI actions and use existing controls. X retains save/exit behavior. Startup and shutdown races are cancellation-aware; Tk keeps polling until the tray loop stops. Generic notifications default off, persist through existing preferences, and deduplicate download action-needed outcomes, completion and run limits without replaying restored history or schedule polls.

`Start Tera.pyw` / `quiet_launcher.py` provide a console-free GUI entry point, preferring the project-local desktop environment and handing off before opening state. Safe, bounded local diagnostics record fixed events/PIDs only, including callback failures. `Start Tera.cmd` stays the diagnostic fallback. `requirements-desktop.txt` pins reviewed binary-wheel packages pystray 0.19.5, Pillow 13.0.0 and six 1.17.0; these extras require Python 3.11+, while base source syntax remains compatible with 3.10. The pinned pystray Windows message hook is narrowly overridden to detect rejected icon registration; recheck it when upgrading. No schema change, OS autostart/service, installer or shortcut was added. No existing Tera desktop shortcut was found.

**Delivery E evidence: 3/3 for the checked local scope — 128 offline tests, dependency consistency, the withdrawn A-D native smoke, and the isolated Windows tray/real `.pyw`→`pythonw` lifecycle check passed on Python 3.12.10 / Tk 8.6 / SQLite 3.49.1. The native tray check covered restore, pause/resume, Cancel/reset, exact files, orderly exit, rejected registration and one intercepted generic notification; the launcher held the state lock and saved/exited on its owned WM_CLOSE. Later tray-close race and callback-log regressions passed offline. Whole-product evidence remains 2/3: real TeraBox resume/large files, long live pauses, real notification delivery, Explorer restart, sleep/resume, power loss and installed packaging are unverified.**

All local roadmap deliveries are complete. The sandbox denied the native tray message-filter API; the successful tray check used the explicitly approved context outside it. Initial native startup-ordering and selection-fixture failures were diagnosed and corrected. No provider keys, real Firefox sessions, live downloads or notification banners were used; test profiles, state and files were synthetic. All final owned processes/windows closed, and task-owned temporary folders were removed. The live-provider gate remains explicitly pending.
