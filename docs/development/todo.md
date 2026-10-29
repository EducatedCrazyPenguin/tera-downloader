# Tera roadmap implementation checklist

## Share metadata rejection investigation — 25 October 2026

User reported `TeraBox rejected /api/shorturlinfo (code -3)` in installed 0.2.0
and confirmed that Firefox lists the same share normally (user-reported).
No production fix or replacement installation has been made for this error yet.

With explicit permission, a read-only diagnostic used only the most recent saved
matching failure and its selected Firefox source. Session and share-page checks
completed; both the current request and a shorturl/root-only request returned -3
(owned PID 7640). The separately approved one-page /share/list probe stopped
without usable metadata (PID 16516). Its original privacy filter omitted the
failure code, so this is not evidence of a particular file-list rejection code.
Neither probe downloaded video, logged private values or wrote queue/browser data.

The ignored `.tools/diagnose_share.py` now has self-checked code-only failure
reporting and an optional browser-ID hypothesis check. It preserves an existing
matching browserid, supplies a temporary host-only in-memory value only if absent,
and performs no video request. Further live checks require explicit permission;
the earlier two diagnostic permissions are already consumed.

**Evidence: 3/3 for the reproduced shorturlinfo rejection and recorded probe
outcomes; root cause remains unknown. The browser-ID explanation is a hypothesis,
not a verified fix. Do not remove metadata/identity checks or ship a guessed fix.**

## Quick-start redesign 0.2.0 — 22 October 2026

- [x] User confirmed Download now for all videos, optional selection; selected Cinema programme.
- [x] Implement quick discovery/queue action, preserving optional review, manual holds, duplicate protection and save/restore.
- [x] Replace crowded configuration/toolbars with Settings and native File actions; keep transfer controls visible.
- [x] Check mapped layout at 1020×760 and 880×680, Tk scaling 4/3 and 2; require headings and three complete queue rows.
- [x] Fresh Impeccable reviewer scored all four fixes resolved; built tokens recorded in DESIGN.md and .impeccable/design.json.
- [x] Full offline suite: 155 tests on Python 3.12.10; workspace temporary folders and synthetic/owned-loopback fixtures only.
- [x] Final package and quiet installed upgrade/actual shortcut check.
- [x] Implementation, documentation and release checks ready for Git publication.

Source native smoke passed as PID 33780, including quick-start from a mapped button,
optional selection, menu commands, Pause/Resume/Cancel, exact bytes, save/exit,
held restoration and recovery/limits. A first packaged run failed without a step
location; self-test-only diagnostics now record allowlisted module/line codes,
without raw exception values. The harness now waits for fresh discovered rows,
not merely the earlier save acknowledgement. A later packaged app/tray run passed
(PIDs 38460/26148; owned quiet child 38804). Final payload verification follows.
One existing three-second queue test timed out while a package build was also
running; it passed alone in 0.267 seconds and the complete suite then passed
serially. No assertion or timeout was weakened.

**Evidence: 3/3 for recorded source/synthetic checks and reviewed captures; 2/3 for
the whole product — live TeraBox behavior remains unverified. Installed release
status is recorded below.**

Final 0.2.0 payload passed the full synthetic packaged app harness (PID 24240)
and native tray/quiet-launcher harness (PID 38516; owned child 23072), with Python
removed from PATH. Quietly upgraded the existing per-user installation (installer
PID 27112); installed ProductVersion/FileVersion are 0.2.0 and the executable
SHA256 matches the build. Existing Desktop/Start-menu shortcut target, working
directory, icon and empty arguments were checked. The actual Desktop shortcut
launched with isolated TERA_DATA_DIR/APPDATA/LOCALAPPDATA (PID 12988), held its
synthetic state lock, and saved/exited cleanly on its owned WM_CLOSE. No real
Firefox/profile/download data was used. No owned final test process remains.

Installer: `dist/Tera-0.2.0-Setup.exe`, SHA256
`cade7dd1211cc1c6a1fe0be2c4f22e02e50eed12f92065bd39f18a24e9926342`.
The 0.1.0 installer is retained for rollback. Installation keeps the same separate
state location and database schema; current real queue contents were not read or
used as fixtures. This UI release did not repeat the 0.1.0 synthetic uninstall
retention campaign or test a clean Windows machine without Python installed.

## Personal release 0.1.0 — approved 20 October 2026

- [x] P01 — Saved-byte verification progress and distinct recovery/wait messages; test cancellation, stale events and counters.
- [x] P02 — Review/History search and sorting, visible selection, atomic batch destinations; test persistence and failures.
- [x] P03 — Allowlisted rotating activity log, About/Help and diagnostics export; test privacy, rotation and write failures.
- [x] P04 — Packaged runtime, safe Downloads default, isolated data selection and installer mutex; test compatibility.
- [x] P05 — Build self-contained Windows 0.1.0 installer; verify synthetic packaged/upgrade/installed shortcut flows.
- [x] P06 — Full offline suite, documentation, review, commit and push. Live-provider gate remains separate.

21 October 2026: implementation, installation and release verification complete.
Implementation commits through `6788c55` were pushed to GitHub main; release
completion is recorded in the following documentation checkpoint and `v0.1.0` tag.
All **146 offline tests passed** on Python 3.12.10 / SQLite 3.49.1 / Tcl 8.6.15
(Tk 8.6). Focused regressions additionally proved cancellation after the first
hashed chunk and rejection of a mixed batch containing an owned saved partial.
The source native harness passed (PID 13156), then the bundled runtime and
installed executable passed the extended app and native tray harnesses with
synthetic downloads, mocked profile/network access and intercepted notifications.
The final installed app/tray PIDs were 27552/29472; both exited cleanly.

The synthetic installer 0.0.0-to-0.1.0 upgrade/uninstall preserved the saved queue,
preferences, schema version 1 and exact partial bytes. This fixture used the same
current application payload with different installer versions; it does not prove
migration from arbitrary older application data. Holding the actual application
mutex made installation refuse without altering the executable. No shortcuts
were created by the disposable installer fixture.

Installed version **0.1.0** at `%LOCALAPPDATA%\Programs\Tera`; verified the executable
hash against the build and checked Desktop/Start-menu target, working directory,
icon and empty arguments. Launched the actual Desktop shortcut (PID 28256) with
`TERA_DATA_DIR`, empty test APPDATA/LOCALAPPDATA and Python removed from PATH.
The installed app held its isolated state lock and saved/exited on its owned
WM_CLOSE. All task-owned final app/installer processes exited. No real Firefox
cookies, provider calls, downloads or notification banners were used.

Artifact: `dist/Tera-0.1.0-Setup.exe`, SHA256
`89c8df054040f4119fbd3b02048fc137b2ed6ab0b922a386dd3a4b3c1d07220b`.
The build used pinned PyInstaller 6.22.3 and signature-verified portable Inno Setup
7.1.0 x64. Upstream Inno installer SHA256:
`0362a383ed217d4c4239b5933866dd96d3eb2102737da92f80f6057a4b40df2f`.
The Tera installer itself is unsigned. Previous version-named installers are
retained in dist; this is the first packaged release.

**Evidence: 3/3 for the checked local/source/packaged/installed flows; whole-product
evidence remains 2/3 because live provider resume, large real transfers, long
server pauses, sleep/wake, Explorer recovery, real notifications and power loss
remain unverified. A clean Windows machine without Python installed was not
available; the bundled runtime was checked with Python absent from PATH.**

Status: Deliveries A-E implemented locally through 20 October 2026. T01-T17 and all local delivery checkpoints passed the checks recorded below. Delivery C's live-provider gate remains pending. The authoritative behavior, defaults, capability map, and evidence limitations are in [plan.md](plan.md).

**Evidence at the Delivery A checkpoint: 3/3 for that local scope — 47 offline tests and the isolated native Tkinter/real-entry-point smoke check passed on Python 3.12.10, Tk 8.6, and SQLite 3.49.1. B-E were then pending.**

**Evidence at the Delivery B checkpoint: 3/3 for the tested local/synthetic scope — 65 offline tests and the integrated withdrawn native smoke passed in the same environment. C-E were then pending; real provider transfers and long-pause reliability remained unverified.**

**Evidence at the Delivery C checkpoint: 3/3 for the checked local protocol/runtime scope — 91 offline tests, bounded loopback HTTP, forced process crash/recovery and the withdrawn native recovery flow passed. D/E were then pending; provider resume, power loss and large real files remained unverified.**

**Evidence: Delivery D 3/3 for the checked local scope — 111 offline tests and the combined withdrawn native limits/recovery scenario passed on Python 3.12.10 / Tk 8.6 / SQLite 3.49.1. Whole-product evidence remains 2/3; live provider compatibility, large real transfers, power loss and E remain unverified.**

**Current evidence: Delivery E 3/3 for the checked local scope — 128 offline tests and both native harnesses passed, including the real Windows tray/quiet-launcher lifecycle with synthetic data and intercepted notifications. Whole-product evidence remains 2/3; live provider, large files, actual notification delivery and installed packaging remain unverified. Earlier delivery summaries below describe their historical checkpoints.**

## Delivery A — Queue, persistence, and everyday use

- [x] T01 — Introduce stable queue jobs and a command coordinator.
  - Acceptance: one active file; stable job/attempt IDs; existing queue order, cancellation, and client APIs keep working through adapters.
  - Verify: focused queue state/late-event tests, then the existing offline suite and synthetic GUI flow.
  - Likely files: `queue_manager.py`, `terabox.py`, `test_queue_manager.py`, `test_terabox.py`, `smoke_terabox_gui.py`.
  - Dependencies: none. Scope: medium.

- [x] T02 — Persist pending work and migrate preferences safely.
  - Acceptance: local SQLite jobs/history plus atomic preferences; protected source links; legacy profile preference imported non-destructively; restore never starts network work.
  - Verify: restart, database lock, corruption, write/protection failure, and backup/restore tests with disposable directories.
  - Likely files: `app_state.py`, `test_app_state.py`, `queue_manager.py`, `terabox.py`, `.gitignore`.
  - Dependencies: T01. Scope: medium.

- [x] T03 — Add remembered and favorite destinations.
  - Acceptance: last-used folder survives restart; favorites can be added/removed; selecting a destination never launches Explorer.
  - Verify: isolated preferences round trip and GUI destination selection.
  - Likely files: `terabox.py`, `app_state.py`, `test_app_state.py`, `smoke_terabox_gui.py`.
  - Dependencies: T02. Scope: medium.

- [x] Checkpoint A1 — Existing download/pause/privacy checks still pass; queue/preferences restore safely and the old settings file is intact.

- [x] T04 — Enable pending queue edits and active-item skip.
  - Acceptance: add/reorder/remove pending jobs while downloading; skip only the current attempt; completion/progress events still update the correct row.
  - Verify: concurrent-command tests and synthetic queue edits during a transfer, pause, and retry.
  - Likely files: `queue_manager.py`, `terabox.py`, `test_queue_manager.py`, `test_terabox.py`, `smoke_terabox_gui.py`.
  - Dependencies: T01-T03. Scope: medium.

- [x] T05 — Add local history and retry-failed actions.
  - Acceptance: filter completed/failed records; retry only selected failures; reveal-folder is explicit; clearing history preserves files and pending jobs.
  - Verify: history/dedup-receipt state tests; mock shell opens; synthetic failure -> retry -> completion.
  - Likely files: `app_state.py`, `queue_manager.py`, `terabox.py`, `test_app_state.py`, `smoke_terabox_gui.py`.
  - Dependencies: T02/T04. Scope: medium.

- [x] T06 — Add the speed/ETA and overall-progress dashboard.
  - Acceptance: honest current/total progress; unknown totals shown clearly; paused speed and ETA do not use stale samples; resumed prefixes are separate from new transfer bytes.
  - Verify: fake-clock progress tests and native synthetic paused/resumed dashboard checks.
  - Likely files: `queue_manager.py`, `terabox.py`, `test_queue_manager.py`, `smoke_terabox_gui.py`.
  - Dependencies: T04. Scope: medium.

- [x] Checkpoint A2 — Demonstrate edit -> download -> history/retry -> save/exit -> restore with synthetic data and no new network requests on restore.

## Delivery B — Review, storage, and boundary pause

- [x] T07 — Add the review/selection step and duplicate detection.
  - Acceptance: list selected videos and aggregate known sizes; append selected jobs during a run; recognize exact repeated inputs and authoritative provider identities.
  - Verify: metadata-fake tests for aliases, repeats, changed entries, exclusions, and late discovery; native review-to-queue flow.
  - Likely files: `review_storage.py`, `test_review_storage.py`, `queue_manager.py`, `terabox.py`, `smoke_terabox_gui.py`.
  - Dependencies: T02/T04/T05. Scope: medium.

- [x] T08 — Add destination/storage preflight and safe conflict actions.
  - Acceptance: writable destination/free-space checks before starting and between files; per-share folders; skip/rename/choose-folder actions never overwrite or adopt unrelated partials.
  - Verify: temporary-disk fixtures for space exhaustion, collisions, missing prior downloads, safe names, and changed destinations; no real directory scans.
  - Likely files: `review_storage.py`, `test_review_storage.py`, `terabox.py`, `test_terabox.py`, `smoke_terabox_gui.py`.
  - Dependencies: T03/T07. Scope: medium.

- [x] T09 — Add finish-current-file pause and distinct stop reasons.
  - Acceptance: Pause now remains responsive; boundary pause waits for the current file and starts no next file; manual Resume is required; cancel/skip remain distinct.
  - Verify: tests at idle, discovery, mid-read, finalization, and between jobs; repeated toggles in the native smoke.
  - Likely files: `run_policy.py`, `test_run_policy.py`, `queue_manager.py`, `terabox.py`, `smoke_terabox_gui.py`.
  - Dependencies: T04/T07. Scope: medium.

- [x] Checkpoint B — Review, selection, duplicate/conflict handling, disk failure, Pause now, and finish-current pause work without changing authentication or no-overwrite boundaries.

## Delivery C — Recovery without corrupting files

- [x] T10 — Introduce owned durable checkpoints and save/exit recovery.
  - Acceptance: durable offsets never exceed synced bytes; only owned paths are recovered; save/exit retains work while explicit Cancel cleans up; interrupted finalization reconciles safely.
  - Verify: subprocess crash/restart tests, shorter/missing/extra-tail partials, existing targets, corrupted checkpoint data, and failed persistence.
  - Likely files: `app_state.py`, `terabox.py`, `queue_manager.py`, `test_app_state.py`, `test_terabox.py`.
  - Dependencies: T02/T08/T09. Scope: medium.

- [x] T11 — Implement strictly validated partial-response resume.
  - Acceptance: append only after identity/strong-validator/range checks; ignored/invalid/changed responses request explicit restart; signed URLs are refreshed rather than stored.
  - Verify: bounded loopback HTTP fixture for valid and invalid responses, byte-exact final output, and privacy assertions; preserve all existing completion checks.
  - Likely files: `terabox.py`, `queue_manager.py`, `test_terabox.py`, `test_resume_http.py`, `smoke_terabox_gui.py`.
  - Dependencies: T10. Scope: medium.

- [x] T12 — Add classified errors and bounded recovery actions.
  - Acceptance: maximum two automatic attempts per cycle; cancellable Retry-After/default delay; no automatic full restart or anonymous fallback; meaningful Retry/Login/Folder/Restart actions.
  - Verify: fake-clock transport/API/storage/integrity classification and retry-budget persistence; synthetic expired-URL and login-required flows.
  - Likely files: `terabox.py`, `queue_manager.py`, `test_terabox.py`, `test_queue_manager.py`, `smoke_terabox_gui.py`.
  - Dependencies: T05/T10/T11. Scope: medium.

- [ ] Provider gate — Only after a separate explicit live-check request, verify a small TeraBox sample's range/validator and refreshed-URL behavior. No full large-file transfer is implied.
- [x] Checkpoint C — Crash/restore and response-validation tests pass; report true resume as provider-verified or provider-pending, never assume synthetic success proves live support.

## Delivery D — Bandwidth, schedules, and run limits

- [x] T13 — Add an adjustable bandwidth cap.
  - Acceptance: unlimited by default; cap changes during a run; pacing remains responsive to pause/skip/cancel/save-exit and does not block Tkinter.
  - Verify: deterministic fake-clock byte pacing, low-cap chunk bounds, and native controls during throttle waits.
  - Likely files: `run_policy.py`, `test_run_policy.py`, `terabox.py`, `test_terabox.py`, `smoke_terabox_gui.py`.
  - Dependencies: T06/T09/T12. Scope: medium.

- [x] T14 — Add daily schedule windows.
  - Acceptance: visible local timezone, overnight support, safe reevaluation after sleep/clock changes; only schedule holds auto-resume; scheduling only while Tera is running, without Windows tasks or autostart.
  - Verify: fake-clock boundaries, overnight windows, manual-hold precedence, restored held jobs, and retry/schedule interaction.
  - Likely files: `run_policy.py`, `test_run_policy.py`, `queue_manager.py`, `terabox.py`, `smoke_terabox_gui.py`.
  - Dependencies: T09/T12/T13. Scope: medium.

- [x] T15 — Add per-run deadline and byte-budget boundary stops.
  - Acceptance: finish-current semantics are explicit; retransfers count, resumed prefixes do not; manual pause does not reset budgets; exceeded limits never silently resume on a schedule.
  - Verify: fake-clock/byte accounting at mid-file and job boundaries, overshoot disclosure, and precedence with manual holds/retries.
  - Likely files: `run_policy.py`, `test_run_policy.py`, `queue_manager.py`, `terabox.py`, `smoke_terabox_gui.py`.
  - Dependencies: T06/T09/T14. Scope: medium.

- [x] Checkpoint D — One synthetic scenario combines cap, schedule, boundary pause, retry, budget, and save/restore; all waits remain cancellable.

## Delivery E — Quiet desktop use and release checks

- [x] T16 — Add optional tray integration and notifications.
  - Acceptance: explicit tray action; safe restore/exit; X saves the queue and exits as confirmed by the user; generic opt-in notifications fire once per meaningful outcome; missing tray support keeps the window available.
  - Verify: reviewed optional dependencies in a project-local environment, mocked notification/shell effects, and bounded isolated native lifecycle testing after advance notice when needed.
  - Likely files: `desktop_integration.py`, `test_desktop_integration.py`, `terabox.py`, `requirements-desktop.txt`, `smoke_terabox_gui.py`.
  - Dependencies: T10/T12/T14/T15. Scope: medium.

- [x] T17 — Add the quiet launcher and complete product documentation.
  - Acceptance: pythonw launch records safe local diagnostics, no duplicate app state owner, no automatic browser/file opens, and readable setup/recovery/privacy/limit documentation.
  - Verify: supported isolated launcher startup/exit, safe missing-dependency handling, existing diagnostic launcher compatibility, and docs/source consistency.
  - Likely files: `Start Tera.pyw`, `terabox.py`, `smoke_terabox_gui.py`, `README.md`, `requirements-desktop.txt`.
  - Dependencies: T16. Scope: medium.

- [x] Final checkpoint — Full offline suite, loopback transfer fixture, crash/restart checks, isolated native smoke, existing state backup/restore and corrupt/newer-version refusal checks, and local privacy inspection pass. No schema migration or packaged installation was introduced; live-provider and installed-release gates remain separate.
- [x] Update plan/checklist status with actual evidence; review and commit only the completed slice. Do not mark provider-dependent or native checks complete based on mocks.

No automatic task below authorizes real Firefox cookie checks, live downloads, visible background consoles, unrelated process termination, or changes to power/VPN/system settings.

## Delivery A verification record — 19 October 2026

- 47 offline tests cover DPAPI round trips, ciphertext on disk, failed writes, database backup/restore, corrupt/newer state, a separate hidden-process lock check, queue edits and stale events, active-stream skip cleanup, selective retries, held restart, and Disconnect without anonymous fallback.
- `python smoke_terabox_gui.py` uses withdrawn task-owned windows and synthetic streams: verified login isolation, favorites, add/move/remove, pause/rapid toggles, byte-exact saved files, history/retry/clear, a stubbed Reveal folder action, save/exit, and restoration without network work. Its final stage exercises the real `terabox.py --data-dir` entry point and native startup/exit.
- At the A checkpoint, saved queue jobs restarted interrupted files from zero; review/storage, byte checkpoints, budgets/schedules, tray and notifications were still pending. The B record below supersedes the review/storage status.

## Delivery B verification record — 19 October 2026

- `review_storage.py` adds hashed normalized input keys, authoritative provider identities with conservative source fallback, private safe per-share folder names, recorded size/mtime receipt checks, destination write probes, collision checks and shared-disk byte totals. No dependency or database schema migration was added.
- `queue_manager.py` persists reviews and exclusions in the existing protected job store. One separate metadata worker can review additional shares during a transfer; restoration starts neither discovery nor downloads. Explicit selections queue only reviewed files and preserve manual holds. Late discovery results, cancellation/re-review, changed metadata and failed protection are covered.
- Storage failures hold the affected item. Rename/folder correction and Skip preserve foreign final/partial files. Active destinations cannot be changed; the user stops and reviews/restarts them explicitly. Finish-current pause is distinct from Pause now, Skip and Cancel, including discovery and finalization boundaries.
- All 65 offline tests passed with temporary directories rooted in the workspace on Python 3.12.10 / Tk 8.6 / SQLite 3.49.1. Inverting the free-space guard made its focused regression fail; the original source was restored afterward.
- The withdrawn native Tkinter smoke verified checkbox selection and totals, exact input/alias duplicates, persistent exclusions, per-share destinations, rename and folder conflict correction, append/reorder/remove, favorites, mocked login, failed-save recovery, rapid pause/resume, finish-current hold, Cancel/control reset, byte-exact files, history/retry/clear, a stubbed Reveal action, save/exit, held restore and isolated real CLI startup/exit. Owned instances exit cleanly without pending Tk callbacks.
- No real Firefox profile, provider traffic, shell window, installation or live download was used. Disk exhaustion/write failure uses offline injection; no real disk was filled. Source/native behavior is checked; provider resume, large files, installed packaging and Deliveries C-E remain pending. Interrupted files still restart from zero.

## Delivery C verification record — 20 October 2026

- `transfer_state.py` records generated partial ownership, immutable job binding, durable offset, prefix SHA-256, strong ETag and finalization phase. File flush/fsync precedes the coordinator's SQLite checkpoint commit. Recovery validates file identity and prefix, truncates only owned uncommitted tails, refuses short/missing/replaced/corrupt bytes and reconciles a ready final file only with matching recorded identity, size and hash. No schema migration or dependency was required; the original transport API still defaults to its previous cleanup behavior.
- The queue now distinguishes Save/exit from Cancel/Skip/Remove/Restart. Exit keeps committed partial bytes; explicit discard actions remove only verified owned partials. Destination changes with an owned partial require Restart first. Restored jobs remain held without authentication/network work. Failed persistence retains the last stored offset and stops the worker. Clear history retains jobs that still own unfinished bytes.
- Append requires the same selected metadata, a strong validator and exact 206 range/length. Ignored 200, 416, bad ranges, changed/missing validators and encoded/non-video responses never append or finalize. Media URLs are refreshed in memory, not saved. `recovery.py` bounds transient/expired-URL cycles to two attempts including the first, honors Retry-After/default five-second delay, persists the budget/due time and keeps manual holds above automatic retry. Login, storage, unknown API and integrity errors do not automatically restart or switch source.
- All 91 offline tests passed on Python 3.12.10 / Tk 8.6 / SQLite 3.49.1 with workspace temporary folders. The local socket restriction (`WinError 10013`) required an elevated test run for the owned 127.0.0.1 HTTP fixture. Hidden bounded subprocesses recorded their PIDs and exited at a synced body checkpoint and immediately before/after rename; all three restored exact synthetic files. This is process-crash evidence, not a power-loss test.
- The native withdrawn smoke verifies saved partial bytes, a real Range request through the synthetic client, bounded recovery, a rejected 200 response, disabled Resume until explicit Restart, exact completed output and clean teardown, alongside the A/B workflow. Login and shell actions remain mocked; no real profile or provider was used. A deliberate removal of the ETag guard was detected by its focused regression and the original source restored.
- The live-provider gate stays unchecked. No TeraBox Range/strong-validator stability, refreshed live URL, long real pause, full large-file transfer or installed package was verified. D/E remain pending. The A/B restart-from-zero statements above describe those historical checkpoints and are superseded by this conditional recovery behavior.

## Delivery D verification record — 20 October 2026

- `run_policy.py` adds validated persisted options, a monotonic file-body limiter, local daily/overnight windows and a persisted run identity/start/received-byte total/latched limit reason. Settings stay in the existing atomic preferences; per-job run-byte receipts use the existing SQLite payload. No schema migration or dependency was added.
- Transfer reads shrink with a low cap and throttle waits poll cancellation/pause. Actual body bytes are counted before writing, including retransfers; resumed prefixes are not charged. Paused checkpoints update displayed progress even if progress messages were coalesced. Storage errors in throttle/checkpoint checks remain storage failures, not transient network retries.
- Schedule and run holds remain separate from the manual pause event. Window closure and limits finish the active file; only schedule holds release automatically. Explicit Start new run resets limits, while Resume and Apply preserve counters and latched holds. The run clock includes pauses, window waits and exit time. Restored work never starts automatically; a byte-limited process crash conservatively requires a new run for uncertain byte accounting without discarding a verified prefix.
- 111 offline tests passed, including fake-clock exact budget/deadline and overnight/timezone boundaries, bounded pacing/read sizes, cap changes, manual hold precedence, retry and restart byte accounting, clear-history continuity, failed hot-settings saves, throttled Skip/Cancel, saved run restoration and a hidden byte-budget crash test. A mutation weakening the exact budget boundary was detected and the original source restored.
- The withdrawn native scenario combines a closed window, manual pause across opening, hot cap change, throttled pause and save/exit, restoration without requests, validated continuation, finish-current pause, window closure, a bounded retry held outside its window, manual retry hold, byte-budget overrun and explicit New run. All outputs were byte-exact, controls reset and owned instances closed cleanly; the original A-C/real-entry-point smoke still passes.
- Runtime checks used temporary synthetic data, mocked login/provider/shell access and no live downloads. The full offline suite's owned loopback fixture required the previously established local-socket permission. No Windows task, wake-up, system-setting change, background service, installation or optional desktop dependency was introduced. E and the live-provider gate remain pending.

## Delivery E verification record — 20 October 2026

- Added the optional registered-before-hide Windows tray and generic opt-in notifications. The base interpreter remains dependency-free; reviewed wheels pystray 0.19.5 / Pillow 13.0.0 / six 1.17.0 are installed only in ignored `.venv-desktop`, and `pip check` passes. Their metadata identifies LGPLv3 / MIT-CMU / MIT respectively. The integration uses the pinned backend's message hook to check Windows registration rather than assuming a visible flag proves success.
- Added `Start Tera.pyw` and safe local launcher diagnostics with rotation, failure/callback handling, isolated `--data-dir`, and project-environment handoff before opening the queue. The explicit diagnostic CMD launcher is unchanged. New boolean preferences validate at write/load boundaries. No schema migration, installed package, shortcut, system setting, persistent watcher or real-data change was needed.
- All 128 offline tests passed on Python 3.12.10 / Tk 8.6 / SQLite 3.49.1 with workspace temporary directories. New checks cover startup failure, cancel-before-ready, stop-during-registration, a tray-close wait without a false save error, opt-in/deduplication, restored history, quiet schedule/cancel/exit outcomes, preference persistence/invalid values, hidden handoff, callback/failure log privacy and rotation. Temporarily removing the opt-in guard made its focused regression fail; original bytes were restored before the passing final suite. Existing encrypted storage/backup/restore/corrupt-newer-state refusal, loopback HTTP and forced-crash recovery checks still pass.
- `smoke_desktop.py` passed as owned PID 18112: real tray registration/hide/restore, Pause/Resume, Cancel/reset, exact synthetic bytes, Save/exit, intercepted generic notification and rejected Windows registration with the window kept accessible. The actual `.pyw` path launched hidden parent PID 32692 and `pythonw` app PID 21608, used empty APPDATA/LOCALAPPDATA and an isolated state lock, then saved/exited on its owned WM_CLOSE. No global keystrokes, clipboard or unrelated window was used. These processes exited; no owned desktop smoke directory remains.
- The unchanged withdrawn `smoke_terabox_gui.py` passed as owned PID 24568 with the optional packages absent from its interpreter, preserving A-D native queue/recovery/run-limit flows and real isolated CLI startup/exit. Native tray execution required permission outside the sandbox because its Windows message-filter call was denied. After diagnosed startup-ordering and fixture-selection failures, the final corrected run passed under the user's explicit one-run approval.
- Source syntax parses with Python 3.10 grammar; runtime execution was Python 3.12.10. No existing Tera desktop shortcut or packaging pipeline was found, so there is no installed-version/shortcut claim. Real OS notification banners were intercepted, not delivered. Live TeraBox authentication/range/validator/large-file checks, Explorer restarts, sleep/resume and power loss remain unverified. See README for recovery/backup/rollback and desktop-extra setup.


## App-only proxy — 28 October 2026

- User authorized an app-only proxy and reported having no endpoint. Added an
  optional HTTP CONNECT transport, masked connection settings and DPAPI storage.
  Existing cookies stay local and travel only in certificate-validated HTTPS to
  supported TeraBox origins. No public resolver or automatic free-proxy routing.
- Public cookie-free HEAD requests from the unrestricted host timed out after
  four seconds for www.terabox.app and www.1024tera.com; GitHub returned HTTP 200.
  This establishes reachability failure in that check, not its precise cause.
- Synthetic CONNECT transfer, offline suite, native settings save/restart,
  packaging and installed checks: see the completion record below when run.
- A real trusted proxy endpoint and TeraBox transfer remain pending.

**Evidence: 2/3 — Source and synthetic routing checks; external provider and
installed behavior remain unverified at this checkpoint.**


### App-only proxy completion record — 28 October 2026

- **Verified fact:** 161 offline tests passed on project Python 3.12.10. The six
  new proxy tests cover input rejection, protected storage and failed-write
  preservation, explicit CONNECT despite `no_proxy=*`, exact saved video bytes,
  proxy credentials excluded from origin headers, TLS rejection of an untrusted
  certificate, no direct fallback, domain restrictions, queue review/transfer
  propagation, mid-transfer setting rejection and the login caller.
- **Verified fact:** The isolated native smoke passed, including masked settings,
  encrypted save, invalid-address rejection, restart, clear-to-direct and the
  existing queue/recovery flows. The packaged executable repeated those flows
  with an isolated profile and no development Python on PATH. No real browser
  session, provider authentication or TeraBox media was used.
- **Verified fact:** Built Tera-0.3.0-Setup.exe using the existing pinned build
  environment. Quietly upgraded the inactive local installation from 0.2.0 to
  0.3.0; the installed executable matched the package and saved settings/queue
  checksums were unchanged. Existing Desktop shortcut target, working directory
  and icon refer to the stable installed executable. Actual shortcut startup,
  state ownership and clean save/exit passed with disposable inherited state,
  empty browser-data locations and a restricted PATH. All test instances closed.
- **Verified fact:** At the user's request, the public Geonode JSON list was
  retrieved using a browser user-agent; 12 of the 20 returned entries had an HTTP
  or HTTPS label. Two selected candidates both timed out after about three
  seconds before CONNECT; no cookies, account details, private share URLs or
  video bodies were sent. Testing stopped after these two failed candidates.
- **Inference / proposal:** Automatic list retrieval is feasible, but those
  results do not establish usable TeraBox transfers. If implemented later,
  validate a bounded number of candidates and keep one endpoint for the full
  transfer. Random per-request routing is not implemented. Geonode itself warns
  of unknown operators, disconnections and no request-specific guarantee:
  https://geonode.com/free-proxy-list
- **Unknown / pending:** A working trusted external proxy, a real authenticated
  TeraBox transfer without a system VPN, live-provider resume and large real
  files. This release supplies configuration, not an endpoint or a verified
  VPN-free downloading service.

**Evidence: 3/3 for the named synthetic/native/installed checks; 2/3 for the
VPN-free proposal because a working external proxy and real transfer have not
been demonstrated.**


## No-VPN investigation follow-up — 28 October 2026

The user reports that 0.3.0's proxy setting did not solve the problem and that
both Firefox and Tera fail with the VPN off. Investigated current GitHub relay
implementations and then the user-named teradownloader.com. Its public pages
are reachable, but its shipped flow requires a Cloudflare verification token;
one bounded isolated headless Edge attempt did not reach the listing response.
No media was downloaded, real Firefox credentials were not accessed, and no
production source or installation was changed. The next needed evidence is
the site's normally generated media URL so its actual delivery path can be
checked privately. Do not add another unverified integration as a claimed fix.
See research/no-vpn-options-2026-10-28.md for sources and limitations.

**Evidence: 2/3 — Source architectures, service availability and isolated
browser outcome checked; generated media delivery and VPN-free downloading
remain unverified.**


### Relay probe result — 28 October 2026

The user supplied a generated player URL and then explicitly authorized a
bounded playlist/segment check. The play.terafile.workers.dev route returned
a finite HLS playlist (615 segments, declared 1:41:51) and a 53,392-byte first
segment response (HTTP 206, MPEG-TS sync byte), with no redirect to TeraBox.
No full video, Firefox cookie, signed-URL log or saved media was involved.
This supports a website-assisted HLS path. Tera 0.3.0 still rejects playlist
sources; no source change or new installation was performed. Full transfer,
all remaining segments, audio/quality and HLS integration remain pending.
See research/no-vpn-options-2026-10-28.md for exact scope and source references.

**Evidence: 2/3 for the proposed solution; the named bounded observations are
3/3. Full download and installed integration remain unverified.**


## Delivery: explicit direct / website choice — 28 October 2026

User requested a top-level VPN available / no-VPN choice. Implemented an
explicit remembered route for new jobs. No-VPN original shares open a normal
browser handoff; generated player/relay links use an isolated finite-HLS path
without Firefox cookies or the direct-route proxy. The real playlist's 26
discontinuities required local stream-copy assembly, so the existing personal
FFmpeg build is copied, hash-pinned and bundled with its notices. No model,
new dependency download, rendering or video encoding is needed. Website copies
are .ts, totals are unknown until completion, and stream attempts restart from
zero after exit. Existing direct-file checkpoint behavior is preserved.

Focused transport, no-VPN handoff/cancel, encrypted queue restore and real
loopback/local FFmpeg copy tests passed. The FFmpeg fixture carries synthetic
data packets; it is not a claim of real movie/audio playback verification.
Full regression/native/packaged/installed checks are recorded below when run.

**Evidence: 2/3 — New route and synthetic transfer checked; complete provider
delivery, real-video playback/quality and installed release remain pending.**


### 0.4.0 completion checks — 28 October 2026

- **Verified fact:** All 172 offline tests passed on Windows with Python 3.12.10.
  The focused queue integration fetched synthetic parts over loopback HTTP,
  assembled with the pinned local FFmpeg using stream copy and recovered the
  exact expected data. This fixture does not verify real video/audio playback.
- **Verified fact:** The real provider playlist was accepted by the new parser:
  615 segments, 6,111 seconds and 26 discontinuities. This parser check read
  metadata only (zero video bytes); the earlier authorized segment sample
  remained bounded to 53,392 bytes and was discarded.
- **Verified fact:** The first native check exposed two Tk variable cleanup
  warnings. WebsiteDialog now releases its Tcl variables on the UI thread;
  the subsequent isolated native smoke passed cleanly and detects unraisable
  cleanup errors. The packaged executable repeated the synthetic route,
  handoff and assembly flows with no development Python on PATH. Dependency
  consistency and normal git diff whitespace checks passed.
- **Verified fact:** Built Tera-0.4.0-Setup.exe, SHA256
  fa7f1b81128be70649295963ef6dc0716129c62cdf23ad6aa3d7f700b82e6da0.
  Quietly upgraded the inactive daily-use installation to 0.4.0; installed
  executable and bundled FFmpeg hashes matched the build. Existing settings
  and queue/WAL/SHM checksums were unchanged. Existing Desktop shortcut target,
  working directory and icon refer to the stable installed executable.
- **Verified fact:** Actual Desktop shortcut startup, isolated state ownership
  and clean save/exit passed with synthetic inherited state, empty browser-data
  locations and a restricted PATH. Test instance PID 10260 exited; no Tera.exe
  process remained at the final read-only process check. No everyday browser,
  Firefox cookie, full provider download or system/VPN setting was operated.
- **Unknown / pending:** A complete real-provider video transfer, availability
  of all segments, actual playback/audio/quality, expired-link recovery and
  long pauses. The top choice routes new jobs; existing failed direct jobs
  need the share re-added in Website mode. Normal website verification and
  manual generated-player-link handoff are required.

**Evidence: 3/3 for the named local/native/packaged/installed checks; 2/3 for
complete VPN-free real-video downloading because full delivery and playback
have not been demonstrated.**


## Automatic website handoff — 29 October 2026

User reports website downloads now work, but manual Firefox opening/copying is
unacceptable. Added an automatic, isolated Microsoft Edge helper to the existing
No-VPN modal. It navigates normally, clicks only the site's ordinary Watch Online
buttons, captures validated player URLs without loading media, closes its owned
browser and returns all sources to the queue. A static origin guard leaves
Cloudflare frames untouched; no verification token, normal browser cookie or
clipboard is inspected. Verification remains a human step when the site asks.

Windows WinHTTP provides the loopback DevTools socket; a Windows job owns the
helper process tree. No runtime dependency/browser download was added. Startup,
page load, commands and per-share work are bounded. Errors do not fall back to
TeraBox directly or retry automatically. Cancel/app exit wait for cleanup;
manual browser/player-link fallback is retained. Profiles are disposable and
removed on normal exit; forced loss or a reported cleanup failure can leave an
owned tera-browser-* folder in Windows Temp.

Verification so far: 178 offline tests passed before the final capture-limit
check, plus real headless Edge against a two-row local website, exact link
capture, no media navigation, bounded empty-list failure and process/profile
cleanup. The native Tk flow automatically queued a returned source without a
paste, assembled synthetic packets and verified app-close-during-handoff
cancellation. The existing tray mock needed its root children set to an empty
list; its behavior/checks were preserved. Final release gates are recorded below.

Live evidence: first native Edge app-mode startup produced no usable page;
changed to a small regular Edge window. One short live capture then returned no
player. After reporting/stopping retries, a focused diagnostic loaded the
provider (HTTP 200, injected handoff active) but no Watch Online button appeared
within 25 seconds. The exact cause (verification, service response or changed
site state) is unknown. Do not claim current unattended provider capture passed.
No real media download was performed. User confirmed the same authorized share
still works manually; no private share/player URL was saved in these notes.

**Evidence: 2/3 — Local browser/native automation works; unattended current
provider capture and a full real-video transfer remain unverified.**


### 0.5.0 release checks and installation — 29 October 2026

- **Verified fact:** Final regression suite: 179 offline tests passed on Windows,
  Python 3.12.10. The added navigation regression rejects a captured media request
  before fetching it, releases the pending ordinary button and caps result count.
  Existing dependency consistency and git whitespace checks passed.
- **Verified fact:** Native Tk checks passed automatic worker-to-modal-to-queue
  handoff, exact synthetic output, encrypted persistence and closing Tera during
  an active handoff. Real Edge 156.0.4314.50 ran against a local two-row website:
  both ordinary buttons clicked exactly once, both player URLs captured, no media
  navigation, cancellation before navigation, empty-list timeout and owned process/
  temporary-profile cleanup. Injected JavaScript had no runtime exceptions.
- **Verified fact:** Final packaged app repeated those synthetic flows without
  development Python on PATH. An earlier packaged run exposed a local HTTP idle-
  socket reset when closing the owned browser. The fixture now handles only
  ConnectionResetError/BrokenPipeError from that disconnect; all other checks
  remain intact. The final packaged log has no traceback, ignored exception or
  callback/self-test failure.
- **Verified fact:** Built Tera-0.5.0-Setup.exe, final SHA256
  be70851b6d7aefbce986562bbccf9d546e6bf48edebcc78f462db306c0196761.
  Quietly installed 0.5.0 over the inactive 0.4.0 daily-use installation. Installed
  executable matches the checked package; saved settings and queue/WAL/SHM
  checksums were unchanged. Existing shortcut target, working directory and icon
  point to the stable installed executable. Actual Desktop shortcut PID 21728
  passed isolated state ownership, startup, clean save/exit without a development
  PATH. It did not exercise a real provider download.
- **Unknown / pending:** Fully unattended live provider link generation. A bounded
  native Edge diagnostic loaded the actual site but received no Watch Online
  buttons/player URL. The user reports the same share works manually. No exact
  root cause was established, and no verification was solved/replayed or normal
  Firefox session accessed. User must complete verification if shown, or use the
  manual fallback if site resolution fails. No full real video was downloaded;
  actual playback/audio/quality and expiring-source behavior remain untested.

**Evidence: 3/3 for the named local/browser/native/packaged/shortcut observations;
2/3 for the automated live solution because current unattended provider capture
and full delivery have not been demonstrated.**


## Firefox/Edge choice and requested uBlock — 29 October 2026

User reports ordinary Firefox succeeds but Edge/helper fails, possibly because
of cookies/uBlock. Implemented a remembered Website browser selector (Firefox
by default / Edge), separate Tera-owned persistent profiles, and Set up browser
for managing extensions. Everyday profiles are not copied or automated. Profiles
retain cookies/cache/extensions between runs; Edge no longer disables extensions.
Firefox uses supported BiDi with the existing WinHTTP transport, no driver or
runtime dependency download. Marker/lock checks reject an existing unmarked
profile and concurrent helper use. Three minutes per share / one minute initial
load replace the short waits. Job-tree lifetime handles Firefox's Windows
launcher handoff, and graceful owned-browser shutdown permits profile writes.

At the user's explicit request, downloaded official Mozilla uBlock Origin 1.75.0,
4,650,100 bytes, verified ID uBlock0@raymondhill.net, manifest version, Mozilla
signature material and AMO SHA256
5b74415860456370644bd80f16125e865b0e6c356bb5dfcfb84069967eaa5287.
Installed permanently in LOCALAPPDATA/Tera/browser-profiles/firefox with signature
checks intact; BiDi extension metadata confirmed active/non-temporary before and
after a real Firefox restart. The XPI is not bundled in Tera's installer. No
extension/cookie data from everyday Firefox was copied. The requested extension
has normal all-sites/webRequest/privacy permissions within this separate profile.
Sources: https://addons.mozilla.org/en-US/firefox/addon/ublock-origin/
and https://addons.mozilla.org/api/v5/addons/addon/ublock-origin/.

Verification: 187 offline tests pass; native selector/setup worker, automatic
modal capture/queue, saved choice and cancellation pass. Real headless Edge
156.0.4314.50 and Firefox 159.0 click each of two synthetic rows once, capture
exact sources, reject media, stop on an empty listing, cancel before navigation,
clean up owned processes and retain a synthetic first-party cookie after restart.
Mapped native controls passed all 16 size/scaling/tab combinations. Dependency
consistency and whitespace checks pass. Packaged/installed gates follow below.

Live evidence remains limited: plain Firefox and Firefox with active uBlock did
not yield a player in short probes. A later explicitly requested five-minute
inspection window emitted Cloudflare console code 600010; user screenshots
confirm Verification failed and a blank page overlay. Numeric console extraction
also observed unrelated six-digit text, so only the documented 600010 observation
is used diagnostically. Cloudflare documents 600* as generic challenge failure /
bot behavior detected; the exact cause or detection signal is unknown. Firefox
now reports strictly formatted Turnstile error codes in Tera while keeping the
bounded window available for normal user verification. No challenge token was
fabricated, captured or replayed; no full media was downloaded.
https://developers.cloudflare.com/turnstile/troubleshooting/client-side-errors/error-codes/

At the user's request, inspected Camoufox and FlareSolverr primary project pages.
Their existence does not verify service compatibility here. FlareSolverr's README
warns its CAPTCHA solvers do not currently work; no spoofing tool was installed.
Cloudflare also documents potential extension interference, so uBlock alone is
not established as a fix. The normal-Firefox manual route remains user-reported
working behavior; current automated provider resolution is not verified.
https://github.com/daijro/camoufox
https://github.com/FlareSolverr/FlareSolverr

**Evidence: 3/3 for the named local/native browser checks and uBlock activation;
2/3 for the live automation proposal because Cloudflare verification failed and
complete provider delivery has not been demonstrated.**


### 0.6.0 completion gates and remaining provider failure — 29 October 2026

- Final offline suite: 187 tests passed. Native selector/setup, saved choice,
  queue/assembly and cancel checks passed. Real headless Edge and Firefox each
  retained a synthetic first-party cookie across a real browser restart.
- The first packaged attempt caught a finish-current fixture race. It now waits
  for an active transfer and asserts exactly one additional completion relative
  to the count at that boundary; final byte-exact/all-file assertions remain.
- A later packaged attempt caught an actual small-window layout regression.
  Focused measurement reproduced it at scale 2 / 880x680: tree height 132 versus
  third-row bottom 168 (36 pixels short). Moved browser choice/setup into existing
  Settings → Connection instead of consuming another main-window row. The same
  three-row requirement and all 16 size/scaling/tab checks passed after the fix;
  selector/setup visibility is checked within the Connection canvas viewport.
  No minimum window increase, removed row assertion or broad suppression was used.
- Final packaged self-test passed with no traceback, ignored exception, callback
  failure or clipping diagnostic. It ran real headless Edge/Firefox and local
  fixtures without development Python on PATH. No provider media was downloaded.
- Built final Tera-0.6.0-Setup.exe, SHA256
  137d94b3d864753e4c957ad5ecc7ba993f09d08599e944661c6760f6fb0c5203.
  Quietly upgraded the inactive daily-use installation from 0.5.0 to 0.6.0.
  Installed executable matches the checked build. Queue/settings/WAL/SHM and
  the requested uBlock XPI fingerprints were unchanged by installation.
- Verified installed version 0.6.0, existing Desktop shortcut target/working
  directory/icon, and actual shortcut startup/state ownership/save/exit using
  disposable state and restricted PATH (owned PID 15476). The requested uBlock
  XPI remains 4,650,100 bytes in Tera's Firefox profile. The earlier native BiDi
  check confirmed active, permanent installation after restart.
- The user-requested five-minute Firefox inspection window closed normally;
  everyday Firefox was not copied or operated. Screenshot and console evidence
  establish verification failure, not its exact fingerprint/extension cause.
  Cloudflare's documented 600* category reports generic challenge/bot behavior
  failure. No spoofing tool was installed. Full real-provider capture/download,
  playback/audio/quality and expiring-source behavior remain unverified.

**Evidence: 3/3 for the stated named runtime/install observations; 2/3 overall
because current unattended Cloudflare/provider resolution remains unresolved.**


### Camoufox automatic website route 0.7.0 — 29 October 2026

- [x] Inspect Camoufox/Pydoll primary sources and native launch behavior. The
  current Camoufox SDK can load fpgen; use the native browser directly through
  existing Playwright Core, without installing/importing the SDK or any model.
- [x] Verify official native 158.0-beta.40 ZIP SHA256
  2d3e33207c2d5853e817e8317f0e33124ffb7054bd5102c8b84546e3d15a6447.
  Install the optional, versioned runtime under LOCALAPPDATA/Tera/browser-runtime,
  with Node 24.22.1, Playwright Core 1.62.1 and official uBlock 1.75.0. Record
  local extracted file hashes and retain dependency notices. The small app
  installer does not contain or automatically download this browser runtime.
- [x] Add remembered Camoufox browser selection and a background private-pipe
  worker. Validate every returned source again in Python. Block media/player
  loads and unrelated top-level navigation, keep shared URLs off command lines
  and logs, and own the Node/browser tree with the existing Windows job wrapper.
- [x] Keep Firefox/Edge choice and extension setup. Camoufox native settings-page
  navigation did not pass headless checks; its new setup button is explicitly
  unavailable, with uBlock included automatically. No existing browser profile
  was copied, attached or modified by this work.
- [x] Resolve live user-provided share using native Camoufox and the final Tera
  controller. Repeated final checks returned one supported player; WebsiteStream
  accepted one finite playlist with 615 segments / 6111 seconds. No real media
  segment or full video was downloaded by these checks. Signed URLs and API
  bodies stayed in memory. Exact future Cloudflare acceptance is unknown.
- [x] Fix real multi-file bugs found by focused runtime checks: changing a row's
  button label must not skip another row; popup capture must precede cleanup;
  popup navigation has no guaranteed frame yet; resolve rows sequentially to
  preserve their order. The local fixture changes the first label and asserts
  both exact player addresses in order plus exactly two ordinary clicks.
- [x] Strict headless local fixtures passed for Edge, Firefox and Camoufox,
  including media blocking, cancellation, owned cleanup and first-party cookie
  persistence after a real restart. A deep Camoufox/uBlock test profile failed
  ordinary Windows cleanup (winerror 145); checked extended-path cleanup removed
  the exact owned fixture, and shorter OS-temp profiles passed strict cleanup.
- [x] Final offline suite: 196 tests passed. Native self-test
  release-checks/source-0.7-final passed, including saved Camoufox selection,
  synthetic modal/worker/queue/assembly, exact bytes, cancel/app exit and all 16
  mapped layout checks. Packaged PID 30320 passed the same checks with real
  headless browsers and no development Python on PATH; no runtime was skipped.
- [x] Build final Tera-0.7.0-Setup.exe SHA256
  2d55a869659ae160fdb2cfa2439686c784f4888df64769150d94fba5b6349c59.
  Quiet upgrade PID 29172 preserved fingerprints of queue/settings/WAL/SHM and
  the existing Firefox uBlock XPI. Installed executable and worker equal the
  checked build/source. Installed file/product versions both read 0.7.0.
- [x] Back up previous settings as settings.before-camoufox-0.7.0.json in Tera's
  state directory, then select connection_mode=website and website_browser=camoufox.
  Verify queue rows unchanged. Existing shortcut target/working directory/icon
  match the installed app. Actual shortcut PID 28772 passed isolated startup,
  Camoufox-preference preservation, state ownership and clean save/exit without
  a development server or Python PATH. The test instance was closed.

Remaining verification limits: no full real-provider transfer, playback, audio,
quality, long-run performance or expiry behavior was tested. The provider route
was live-tested in the source controller; packaged/installed checks used the
specified synthetic flows. Protection prefs were enabled explicitly, but full
stock-Firefox protection backend equivalence was not established. Native BiDi
startup did not work in two probes, so the verified Juggler/Playwright route is
used. No claim is made about the exact earlier Cloudflare detection signal.

**Evidence: 3/3 for the named resolution/playlist, local/native/packaged/install
observations; 2/3 for complete real-video delivery because no full transfer or
playback was performed.**


### Reliable website downloads 0.8.0 — 29 October 2026

- Implemented website-specific durable checkpoints beside the destination. Each
  complete validated TS segment is flushed/fsynced before an acknowledged queue
  checkpoint; incomplete segments are discarded. Records bind job/workspace
  ownership and store sizes/hashes, not signed playlist/segment URLs.
- Resume verifies local hashes and exact canonical playlist identity (ordered
  absolute segment URLs, durations and tags including sequence/discontinuities).
  Changed or missing data holds for explicit restart; existing targets are never
  overwritten. Ready-file ownership/hash records reconcile crashes after rename.
- Exit/recoverable errors retain completed segments; Cancel/Skip/Restart remove
  only the owned workspace. Orderly website shutdown does not consume the failed
  attempt budget. Original-file checkpoint behavior is retained.
- Resolver/dialog/queue now retain provenance for unambiguous shares. StateStore
  protects original shares inside the existing DPAPI source blob. The second
  attempt can refresh once with Camoufox; ambiguous results and missing provenance
  hold for user action. Refreshed playlists must match before saved parts are used.
- Reused the two-attempt policy, honoured Retry-After, clamped unknown-size space
  reservations, retained new-byte-only accounting and stage/segment/byte messages.
  Observed Turnstile verification failures have a distinct fixed error message.
- State version 2 migration uses SQLite backup API and settings backup before the
  version change. Actual daily migration preserved queue rows and settings and
  verified queue.before-v2.sqlite plus settings.before-v2.json. Older versions
  reject version-2 state; rollback requires restoring both pre-migration backups.
- Final offline suite: 204 passing tests. Focused tests exercised real queue
  shutdown/restore with no first-segment re-request, exact recovered output,
  new-byte accounting, hash/truncation failures, changed manifests, publication
  crash reconciliation, disk-full preservation, bounded retry, protected
  provenance/migration and one refresh versus ambiguous-source hold.
- Source native gate release-checks/source-0.8-final passed. Final packaged
  PID 3028 passed isolated native queue/assembly/layout/startup checks and real
  headless Edge/Firefox/Camoufox fixtures without development Python PATH.
- Final installer SHA256:
  8119f86ee79698320ed5e7f1afdeb117af1b88fcf82a8826961792c3b661b543.
  Quiet upgrade PID 26820 preserved queue/settings and existing Firefox uBlock
  fingerprints. Installed executable and browser worker match checked artifacts;
  file/product versions are 0.8.0. Existing shortcut target/directory/icon verified;
  actual-shortcut PID 24128 passed isolated startup, ownership and clean exit.

No full provider download/playback was run; an explicitly approved small sample
is still needed for that gate. Refresh tests use synthetic sources; live refreshed
playlist stability is unverified. Existing player-only jobs cannot gain original
share provenance retroactively. MP4 output, parallelism and runtime repair/update
remain deferred. No new dependency or browser/model download was introduced.

**Evidence: 3/3 for the named synthetic/native/package/install observations;
2/3 overall because full live-provider recovery and playback remain unverified.**


### Queue ordering and bulk controls 0.9.0 — 30 October 2026

- User selected ordering/bulk controls and view-only filters as the queue focus.
  Added multi-selection Move up/down, Move next, and Remove pending through the
  existing File actions menu. Relative selection order is preserved; Move next
  precedes pending jobs and waiting retries without stopping the active worker.
- The coordinator resolves and validates every selected ID before mutation.
  Mixed active/ineligible or missing-ID selections are rejected before changes.
  Removal retains existing owned-partial cleanup and completed-file protections.
- Added case-insensitive filename search and All/Pending/Active/Waiting/Needs
  attention filters. Hidden rows lose selection and actions immediately disable.
  Filters affect only the view, not saved order or Start queue membership. Filter
  state resets on reopening; actual ordering/removal persists. No schema change.
- Reused existing header space, with compact destination-row padding. Native and
  packaged checks preserve all three filename rows and verify filter widgets in
  all 16 tab/size/scaling combinations; no window minimum or gate was weakened.
- Final offline suite: 210 passing tests. Focused cases cover stable group moves,
  prioritisation ahead of retry waits, mixed/invalid selection rejection, selected
  cleanup only, filter non-mutation and real coordinator save/restart ordering.
- Source native gate release-checks/source-0.9-final passed. Packaged PID 25544
  passed native queue/filter/layout/assembly/startup checks and isolated headless
  Edge/Firefox/Camoufox fixtures without development Python PATH.
- Final installer SHA256:
  b5ea8d0c51aba02727d152031b6c200f19e5d5a0851f8b9baa8135b5e250508c.
  Quiet upgrade PID 29360 preserved queue/settings and Firefox uBlock file
  fingerprints. Installed executable equals the tested build; file/product
  versions are 0.9.0. Existing shortcut target, working directory and icon were
  verified; actual-shortcut PID 31584 passed isolated startup/state ownership and
  clean save/exit. Test instance closed; no everyday browser was operated.

No parallel downloading, per-share grouping, provider changes or new dependencies
were added. Checks used synthetic downloads; complete real-provider transfer and
playback remain separately unverified.

**Evidence: 3/3 for the stated queue tests and native/package/install observations;
this does not establish full live-provider transfer reliability.**


### Repository organisation — 30 October 2026

- Group application modules/browser worker under src/, tests and synthetic
  fixtures under tests/, developer entrypoints under scripts/, build definitions
  under packaging/ and pinned dependencies under requirements/. Move design,
  product and development history under docs/. Retain root launchers/changelog.
- Replace the long landing README with a compact overview and folder map; retain
  the complete manual in docs/usage.md. Validate all relative Markdown links and
  update current test/build/CLI commands. Historical records remain historical.
- Root Start Tera.pyw bootstraps src/; quiet launcher still finds the root venv.
  Explicit source self-tests locate tests/. Preserve root legacy source settings;
  a new regression demonstrated and corrected the accidental src/ legacy path.
  Preserve frozen legacy lookup. Update FFmpeg, crash/TLS fixture and smoke paths.
- scripts/test.py is the canonical unittest discovery entrypoint. Final suite:
  211 tests passed. Root launcher/help, moved runtime installer/help and source
  CLI/help passed. Isolated source native startup/queue/browser/layout gate
  release-checks/source-organized passed. Packaged layout gate PID 26524 passed
  before the final source-only legacy-lookup fix; final build also succeeded.
  That lookup fix is covered by its focused mocked GUI/state-boundary regression.
- PyInstaller and Inno Setup build from relocated configuration. No dependencies,
  transfer behaviour, state schema, version or daily-use installation were changed.
  No real provider transfer was run. Local research/profiles/artifacts remain
  ignored; local AGENTS.md stays untracked and its test command was updated.

Evidence: 3/3 for the stated file-layout, unit, source-runtime and build checks;
no new installed-app release or live-provider verification is claimed.
