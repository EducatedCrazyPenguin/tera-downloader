# Tera roadmap implementation checklist

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
