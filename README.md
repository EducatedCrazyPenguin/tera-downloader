# Tera — local TeraBox downloader

## Windows release 0.9.0

The personal Windows x64 package bundles Python, Tkinter and tray support. Run
`Tera-0.9.0-Setup.exe`, then use **Tera** on the Desktop or Start menu. Python
installation and `.pyw` associations are not needed for the packaged app.
Installation is per user under `%LOCALAPPDATA%\Programs\Tera`; saved state stays
under `%LOCALAPPDATA%\Tera`. No administrator access, autostart, browser launch,
automatic update, reboot or post-install app launch is configured.

Exit Tera before upgrading or uninstalling. A Windows mutex makes the installer
refuse while Tera is running; it does not close the app. Installation and
uninstall leave queue/settings, helper browser profiles, owned partial files and completed downloads in
their separate locations. This release migrates state to version 2. Keep the
previous installer and both pre-migration backups for rollback; older versions
reject version-2 state. These personal builds are unsigned.

For a new destination, Tera uses the Windows Downloads folder's **Tera** subfolder,
including redirected Downloads locations. Saved destinations take precedence.
If Windows cannot resolve Downloads, select a folder before reviewing links.

**Checking saved download: X of Y** shows verification of existing bytes before
continuation or recovery of an interrupted final rename. This local checking is
separate from network speed and run-byte accounting. Pause and Cancel remain
available. Login, storage, restart, retry and download-window waits have distinct
messages; checking does not imply the provider will support continuation.

Review and History have filename search and sorting. Review's **Select visible**
and **Deselect visible** affect only matching reviewed rows; hidden choices are
kept and the selected total includes them. Queue order is changed only through
Move up/down. **Change folder…** applies one picked folder to all highlighted
eligible rows. If any selected row is active or owns partial bytes, no destination
changes; stop the active file or explicitly Restart from zero first.

**Settings → Help / About** displays the version and recovery guidance. **Save diagnostics…**
creates a new JSON report containing version, allowlisted event/error codes,
times, attempt counts and byte counts only. Choose a new report filename;
existing files are never overwritten. `activity.log` and
`activity.previous.log` hold at most 128 KiB each in the state directory. Raw
exceptions, filenames, folders, links, account details and credentials are
excluded; exports revalidate log entries and nothing is uploaded. Logging
failure does not stop a download or replace the queue.

## Queue ordering and filters

Use Ctrl-click or Shift-click to select multiple queue rows, then **File actions**:
**Move up / Move down** moves selected pending jobs together while preserving
their queue order. **Move next** puts selected pending jobs ahead of other pending
work and waiting retries, without stopping the current transfer. **Remove pending**
removes the selected eligible jobs and their owned partial data; completed files
are preserved. Mixed selections containing active/ineligible jobs are rejected
before anything is changed. New order and removals survive restart.

**Find in queue** matches filenames without regard to case. The adjacent status
filter offers All, Pending, Active, Waiting and Needs attention. Filtering changes
only the view; hidden selections are cleared and cannot receive bulk actions.
Clear the search and choose All to see the full queue. Starting the queue still
uses the saved queue order, including rows hidden by filters. Search/filter
choices reset when reopening; actual job order remains saved.

Evidence: 3/3 for the named synthetic queue and native view checks; full real
provider transfer remains outside these queue checks.

## Website downloads without a VPN

The top **Route for new links** choice is explicit and remembered:

- **VPN available — Direct** uses the existing original-file TeraBox route and
  selected Firefox login. It does not start, stop or detect a VPN.
- **No VPN — Website** accepts original share links, generated TeraDownloader
  player links and its supported `play.terafile.workers.dev` relay links.
  **Settings → Connection → Website browser** chooses Camoufox, Firefox or Edge.
  With **Camoufox**, Download now resolves original shares in the background,
  uses the ordinary Watch Online controls, captures player links and continues
  into Tera's existing queue. No browser paste or click is normally needed.
  Firefox and Edge retain their separate visible helper windows and manual
  verification option. Existing saved browser choices are preserved.

Camoufox uses an optional, separately installed runtime: native browser
**158.0-beta.40**, Node **24.22.1**, Playwright Core **1.62.1**, and official uBlock
Origin **1.75.0**. It does not import the Camoufox Python SDK or load/download its
fingerprint model. The browser is isolated from everyday browser profiles. It is
an experimental custom browser; a successful verification today does not
guarantee future website acceptance. No paid solver or token replay service is
used. [Camoufox source and release](https://github.com/daijro/camoufox/releases/tag/v158.0-beta.40),
[Playwright persistent contexts](https://playwright.dev/docs/api/class-browsertype#browser-type-launch-persistent-context).

The optional runtime lives under `%LOCALAPPDATA%\Tera\browser-runtime\camoufox-158.0-beta.40`
and occupies roughly 2.6 GB. It is separate from the small Tera installer and
is not automatically downloaded or updated. `install_camoufox_runtime.py`
installs from local browser ZIP, signed uBlock XPI, Node executable/license and
Playwright Core directory. It validates pinned browser/Node/XPI SHA256 hashes,
checks Playwright's version, rejects unsafe archive paths and records extracted
file hashes. No existing runtime directory is overwritten. See
`third_party/Camoufox-NOTICE.txt` for provenance and the script's `--help` for
local asset arguments. A missing runtime produces an actionable error; Tera
does not silently select a different browser. The runtime remains after a Tera
uninstall, alongside retained app state.

Each browser has a separate Tera-owned profile under the app's data folder,
`browser-profiles/camoufox`, `browser-profiles/firefox` or `browser-profiles/edge`.
These retain website cookies, cache, extensions and settings between attempts.
Tera does not copy or control your everyday Firefox/Edge profile. **Set up
browser…** explicitly opens the Firefox or Edge helper for extension management; close
that window or click Done. Setup closes after ten minutes. Camoufox loads its
included uBlock on each launch; its extension-setup button is disabled because
native settings-page automation has not passed here. The separate Firefox helper on this machine
also has the previously requested official uBlock installed.
[Official uBlock Origin](https://addons.mozilla.org/en-US/firefox/addon/ublock-origin/).

Opening the website sends it the share. Camoufox uses a private local pipe with
Tera; share/player links are not command-line arguments or activity-log entries.
Cancellation closes only the owned Node/browser process tree. Browser capture
blocks media, player navigation and unrelated top-level navigation. Ordinary
HTTPS subresources are allowed so website scripts can work; uBlock provides
its own filtering. Safe Browsing, blocklist and signature-check preferences are
explicitly enabled, but full protection backend equivalence to stock Firefox
has not been verified. Use this isolated browser for the helper flow.

Resolution allows up to three minutes per share and up to one minute for initial
loading, ending sooner on an explicit navigation failure. A site outage,
uncompleted verification or changed website controls can still prevent capture.
There is no automatic retry or VPN switching. On failure, use **Retry small
browser**, or **Open in normal browser instead** / **Use pasted player links**.
Already-generated player links remain valid inputs in the main box.
If Firefox logs a Turnstile failure, Tera shows its numeric code while leaving
the bounded verification window available. This is an observed failure report,
not a bypass or an identification of the exact detection signal.
Cancel/app exit close only the owned helper process tree; profiles are retained.
Capture blocks media requests, and helper setup permits normal extension installs.
Temporary synthetic test profiles are separate from these saved profiles.

Website mode saves a **streaming copy (.ts)**, not the original MP4. It accepts
finite, unencrypted MPEG-TS playlists, including timestamp discontinuities.
Each listed segment must arrive with a matching positive Content-Length and
valid TS packet framing; one missing/short/unsupported segment fails the file.
The bundled, pinned FFmpeg executable joins local segments with stream copy;
it cannot fetch network inputs. A final file appears only after assembly and
validation, and existing files are never overwritten. Keep the .ts extension.

Stream totals are unknown until completion; the UI shows transferred bytes and
segment progress without inventing an original-file size. Extra temporary space
is needed for downloaded segments and the assembled copy, approximately twice
the stream size. Current source support does not cover encrypted, master,
fMP4 or byte-range playlists. Stream resolution/audio/quality may differ from
the original. File format support in your media player is separate.

Pause/cancel and run limits apply to the queue. Pause holds further network reads
and final publication; an already-running local assembly can finish while paused.
Completed, validated segments are flushed and checkpointed in an owned workspace
beside the destination. Exit and recoverable failures preserve them. Reopening
waits for Start, verifies local hashes and requests only missing segments. Explicit
Cancel, Skip and Restart discard that job's owned workspace. A changed playlist
or altered saved segment requires an explicit restart; files are not mixed.

The existing two-attempt budget applies. A rejected relay link can trigger one
Camoufox refresh on the second attempt when its original share was retained.
Only a single unambiguous refreshed source is accepted, and saved segments are
reused only when the complete playlist fingerprint matches. Pasted player links
without provenance need manual regeneration. New bytes alone count against run
limits. Progress reports verified segments, saved bytes and current stage.

State version 2 protects original shares with DPAPI. Upgrading a version-1 queue
creates queue.before-v2.sqlite using SQLite backup and settings.before-v2.json.
Older Tera versions reject version-2 state without modifying it. Restore both
pre-migration backups to roll back; do not copy only an active SQLite main file.

Saved user-supplied player URLs are protected with current-user Windows DPAPI;
they are not written to activity logs. Route selection applies to new jobs and
does not convert existing queued original-file jobs.

**Evidence: 3/3 for automatic player generation and accepted text-playlist
metadata in the named live Camoufox test; 2/3 for complete real-video delivery.
The user-provided share resolved with native Camoufox 158.0-beta.40 and returned
one supported video with 615 playlist segments. No real video was downloaded.
Playback, audio/quality, full transfer and future provider availability remain
unverified. Local synthetic browser/queue checks cover their stated boundaries.**

## Use it

1. Open the installed **Tera** shortcut. For source use, double-click
   **Start Tera.pyw** on Windows (Python 3.10+ with Tkinter and
   the normal Python `.pyw` association). This opens Tera without a command window.
   **Start Tera.cmd** remains the explicit console/diagnostic fallback.
2. In **Settings → Firefox login**, select your usual **Firefox profile**. Use **Login in Firefox** to open your
   share and sign into TeraBox in a normal tab; **Check login** verifies it.
3. Paste share links one per line or separated by commas, choose a destination,
   then click **Download now** to discover and queue all eligible videos. Invalid
   links are reported inline. Your last destination is remembered. **Add links**
   returns to Downloads; **Settings → General** holds favorites, separate-share
   folders, tray and notification options. Existing pauses and run limits remain
   in force. Restored queues still wait for Start; interrupted discovery needs
   an explicit **Review saved** rather than starting automatically.
4. For optional selection, click **Choose videos…** instead. In **Choose videos**,
   click a video's checkbox (or select it and press Space) to
   include/exclude it. The view shows file sizes, destinations and selected bytes.
   **Download selected** starts those files, or appends them to the running queue.
   It preserves an existing pause. Review and exclusions survive reopening;
   **Review saved** explicitly discovers an interrupted review.
5. Add more links while downloading. In **Downloads**, select a file, then use
   **File actions** to
   **Move up**, **Move down**, or **Remove pending**. **Change folder…** and
   **Rename…** work on reviewed, pending or held files. **Skip** stops the active
   file, or skips a selected held file when no transfer is active. It removes
   only that attempt's owned temporary file and preserves completed files.
6. **Pause now** holds the active transfer and queue. **Pausing…** waits for an
   in-flight read; **Paused** confirms the worker has stopped reading. Click
   **Resume** to continue while Tera remains open. **Pause after file**
   lets the active file finish and starts no next file until Resume. The dashboard
   shows overall known progress, speed and estimated time.
7. The **History** tab shows completed, failed, skipped and cancelled items.
   Select failures and click **Retry selected failures**, then **Start queue**.
   This starts a new recovery cycle. Transient connection/server errors get at
   most two attempts including the first, honoring Retry-After or waiting five
   seconds. Pause and Cancel interrupt the wait. Access, unknown API, storage and
   verification errors do not automatically retry. **Login required** holds the
   queue: select that row, use Check login/Login in Firefox for its saved source,
   then **Retry selected** and Resume. No anonymous fallback is used.
   A failed share review returns to **Review saved** instead of downloading
   unreviewed files. To restart a cancelled/skipped file, review its share again.
   **Reveal folder** opens a saved destination only when clicked. **Clear history**
   is available while idle, forgets completion duplicate markers, and keeps files
   and jobs that still own unfinished partial bytes.
8. Clicking **X saves the queue and exits** after the current request stops.
   Reopening restores unfinished jobs and destinations without automatically
   checking login or starting downloads. **Owned partial bytes can continue only
   after strict local and server validation.** If Tera shows **Restart required**,
   select the row and explicitly choose **Restart from zero**, then Start/Resume.
   Cancel queue deletes owned unfinished partials and marks pending items cancelled;
   completed files are kept. **Minimize to tray** is a separate action; daily
   windows also work while Tera stays running in the tray.

## Quiet desktop use

The base app needs no third-party packages. Optional tray support uses pinned
Windows packages in a project-local environment (Python **3.11+** for these extras):

```powershell
python -m venv .venv-desktop
.\.venv-desktop\Scripts\python.exe -m pip install --only-binary=:all: -r requirements-desktop.txt
```

**Start Tera.pyw** automatically uses that environment when it exists, handing
off before opening the queue store. Without the extras, Tera still opens and
downloads normally; tray and notification controls are disabled with an inline
explanation. A broken environment can be renamed or removed after exiting Tera;
this does not remove the separate queue/settings or downloaded files. To diagnose
with the optional packages, run `.\.venv-desktop\Scripts\python.exe terabox.py`.

- **Minimize to tray** hides Tera only after Windows accepts its icon. Use
  **Show Tera** (or the icon's default action) to restore it. Its menu offers
  Pause, Resume/Start, Cancel, and **Save queue and exit**, using the same controls
  as the window. Windows may place the icon in the notification-area overflow.
  A startup/backend-loop failure keeps/restores the window. X always saves and exits.
- **Notify on completion or action needed** defaults off. Enabling it also
  starts the tray icon while leaving the window visible. Notifications cover
  queue completion, download failures/required actions and reached run limits.
  They contain generic text only, without filenames, folders, source links or
  account details. Repeated polls do not repeat an outcome. Restored history,
  manual pauses and daily-window holds are quiet. Windows notification settings
  can suppress delivery; the app's status remains authoritative.
- Disabling notifications stops new messages; an already displayed Windows
  notification may remain. The icon stays available until exit. Nothing starts
  Tera at Windows login, wakes the computer or prevents sleep.
- Quiet-launch diagnostics are local: `launcher.log` beside the queue data
  (`%LOCALAPPDATA%\Tera`, or `--data-dir`). They record fixed startup/exit/error
  codes and process IDs, without exception text, tracebacks or source data. At
  64 KiB the next entry rotates one previous log. If no window appears, inspect
  that log or use the diagnostic launcher. A callback failure records
  `callback_failed`; restarting after save/exit is the recovery action.

The extras are [pystray 0.19.5](https://pypi.org/project/pystray/0.19.5/)
(LGPLv3), [Pillow 13.0.0](https://pillow.readthedocs.io/en/stable/releasenotes/13.0.0.html)
(MIT-CMU), and six 1.17.0 (MIT). They are optional and installed from wheels;
their license notices remain in the environment. The Windows threading/lifecycle
integration follows [pystray's usage guidance](https://pystray.readthedocs.io/en/latest/usage.html).

Repeated normalized inputs are discovered once while already in Review/Queue.
Aliases are considered duplicates only when the provider reports matching share
and file IDs and expected size. Without an authoritative share ID, detection stays
within the same normalized input. A **Prior download** is unselected only when its
recorded file still matches its size and modification time; this is not a content
hash or an integrity guarantee. Missing/changed files can be selected again.

Tera checks writable destinations and remaining known bytes on the same disk
before a file starts, then repeats the checks between files. A collision or disk
failure holds the queue with **Needs attention**. Select the row and use
**Rename…**, **Change folder…**, or **Skip**, then **Resume**. Existing files and
unrelated `.part` files are never adopted or overwritten. Free-space checks do
not reserve disk space against other apps. A mid-file storage failure keeps its
last committed prefix for validated continuation after correction. Changing an
owned partial's name/folder requires explicit Restart from zero first; partial
files are not moved. Per-share folder names use a short identity hash, not a raw share
code or password.

## Run limits

Use **Settings → Run limits** and click **Apply limits**. Defaults are unlimited
speed/time/bytes with scheduling off. Settings persist locally and can be changed
during a run.

- **Speed (KiB/s)** caps video data; zero removes the cap. Login/share requests
  are outside this cap. Changes apply at the next read; an in-flight read can
  finish first. Pause, Skip, Cancel and save/exit remain available while throttled.
- **Daily window** uses the displayed Windows local timezone and 24-hour HH:MM.
  Start is inclusive, end exclusive; overnight windows such as 22:00–06:00 work.
  Start and end must differ. Start the queue to arm it outside the window; it
  waits without transferring files. The window closing finishes the active file
  before holding. Tera must stay running: no Windows task, autostart, wake-up or
  power-setting change is installed. Reopening still requires an explicit Start.
- **Run for (minutes)** creates a deadline from the run's original start. Pauses,
  schedule waits and time while Tera is closed count toward it. The displayed
  deadline and daily window follow the current Windows clock/timezone.
- **Run budget (MiB)** counts newly received video bytes, including retransfers.
  An existing resumed prefix is not charged again. Counts and deadlines survive
  graceful save/exit; Resume and Apply limits do not reset them.
- Time and byte limits **finish the current file**, so they can exceed the limit
  by that file's remaining time/bytes. After a limit holds, choose **Start new
  run** explicitly to reset its counters/deadline. Enlarging/disabling a reached
  limit does not silently release it. New run keeps verified partial bytes;
  **Restart from zero** is the separate action that discards a selected partial.

Only a schedule hold releases automatically. Manual Pause, finish-current pause,
login/storage/restart holds and reached run limits take precedence. Pause while
waiting outside a window prevents automatic starting when it opens. An abrupt
process crash can leave the last received-byte total uncertain; a byte-limited
run then requires **Start new run** while retaining its verified partial bytes.

TeraBox aliases from `terasharelink.com`, `terasharefile.com`, and
`terafileshare.com` are accepted in both `/s/1…` and `sharing/link?surl=…`
formats. They use the same selected Firefox login and direct TeraBox download flow.

You do not log in for every movie. Tera rereads Firefox's TeraBox cookies and
refreshes its page tokens before every download. If the session expires, sign
into TeraBox in Firefox again. If a new login is not detected, close Firefox
normally so it saves its session, then click Check login.

Firefox private tabs and containers are not imported. Select the same normal
profile in which you signed in. The current in-app browser integration does not
expose cookie export, so signing in there alone does not connect this downloader.

## Privacy

- Reads only TeraBox cookies from the selected Firefox profile, using a read-only
  query. Does not read passwords, other sites' cookie values, history or bookmarks.
- Does not copy the cookie database or save another cookie file. Imported cookies
  stay in memory and retain Firefox's domain, path, expiry and security restrictions.
- Local settings and queue/history are stored under `%LOCALAPPDATA%\Tera`,
  outside the repository. Existing `.tera-settings.json` is imported once without
  changing or deleting it. `--data-dir` selects an isolated store and does not
  import the real legacy settings; a second instance cannot own the same store.
  `TERA_DATA_DIR` also selects isolated state; explicit `--data-dir` wins over
  that environment variable. Neither isolated form imports legacy settings.
- Saved source links and share access codes are encrypted with current-user
  Windows DPAPI. Filenames, destinations and history are local metadata and can
  be cleared. Cookies, account identifiers, page tokens and signed media URLs
  from the original-file route are never stored in the queue. Explicitly pasted
  website player URLs are protected source links. Protection/save failures are reported; there
  is no plaintext fallback. DPAPI is tied to the Windows account and does not
  protect against programs already running as that user.
- Partial paths use random owned `.tera-….part` names. The local queue also stores
  durable offsets, file identity, prefix hashes and representation validators.
  It never stores the media URL; each transfer attempt resolves it again through
  the same selected source. Recovery verifies ownership and the saved prefix,
  and truncates only an owned uncommitted tail. Missing, shorter, replaced or
  changed partials require explicit restart. Cancel, Skip, Remove pending and
  Restart delete only a verified owned partial, never a completed video.
- **Disconnect**, or selecting **No login**, disables future imports and blocks
  unfinished authenticated jobs. Re-add those shares with your chosen source;
  retry never silently switches them to anonymous access. Firefox login/data
  remain untouched. Each queued row displays its own login source.
- Direct requests and redirects are limited to supported TeraBox domains.
  The explicit website mode uses only its supported HTTPS relay; it does not
  inherit the direct-mode proxy or Firefox cookies. There is no telemetry.
- **Settings → Connection** accepts an optional trusted HTTP CONNECT proxy as
  `http://[user:password@]host:port`. Leave it blank and save to use direct access.
  The address is masked and stored using current-user Windows DPAPI. Change it
  while the queue, review and login checks are stopped. It applies to the desktop
  app's login checks, share review and downloads; an unavailable proxy fails
  without direct fallback. HTTPS certificate validation and supported-domain
  restrictions remain enabled. SOCKS and TLS connections to the proxy itself
  are not supported; the TeraBox connection uses HTTPS through the HTTP tunnel.
- Tera does not supply a proxy or guarantee that one can reach TeraBox. A working
  proxy may avoid needing a system VPN for Tera's requests. Firefox login still
  uses Firefox's own network settings. A system VPN applies normally; a
  Firefox-only VPN extension does not route Tera. Saving an address does not
  perform a live connection check.

**Proxy evidence: 2/3 — A synthetic local HTTPS CONNECT download and offline
checks cover routing, TLS validation, exact bytes, credentials and call paths.
Real TeraBox access through an external proxy remains unverified.**

## Verification and limits

Earlier documented live verification covered a Firefox account check,
original-file URL resolution, and a small MKV sample whose response size matched
the shared file metadata. The new queue/UI was checked with synthetic data.
**A complete large-file transfer was not run as part of this verification.**
Some shares do not provide download URLs without an authenticated session.

Original files are kept temporary until the byte count matches the share size.
The original-file route rejects previews and HLS playlists. Website streaming
copies use the separate validated path described above. Existing files are not overwritten;
explicit cancellation removes only the owned temporary file. A queue
continues after an individual link or video fails and shows the completed and
failed items at the end. Pause keeps the current connection and downloaded bytes
only while Tera stays open. A long pause can fail if the server closes the
connection. Recovery preserves committed bytes but never silently restarts a
partially downloaded file. It appends only with a strong ETag, If-Range and an
exact 206 Content-Range/length for the same selected file. A 200, 416, changed or
missing validator, changed metadata or malformed response requires an explicit
restart. The prefix is reread and hashed before continuation, which can take time
for large files. Checkpoints follow file flush/fsync, normally every 1 MiB or two
seconds and at pause/exit; finalization is also checkpointed and reconciled after
a crash. These rules follow [HTTP range semantics](https://www.rfc-editor.org/rfc/rfc9110.html#section-14.2).
**Live TeraBox range/validator support remains unverified:** a server may require
Restart from zero even though the synthetic protocol checks pass. Rate
limits, expired links, account limits, share restrictions and future TeraBox
changes can still cause failures.

Deliveries A-E verification passed **128 offline tests** and an isolated, withdrawn
native Tkinter smoke check on Python 3.12.10 / Tk 8.6 / SQLite 3.49.1. The checks
covered encrypted storage, failed saves, backup/restore, process locking, queue
edits, active-stream skip cleanup, history/retry, favorites, review/selection,
duplicates/exclusions, disk/conflict handling, pause/rapid toggles, finish-current
pause, byte-exact synthetic files, save/exit, held restoration and real isolated
CLI startup/exit. New checks cover real loopback HTTP responses, hidden subprocess
crashes during writing and before/after rename, verified continuation, corrupt
checkpoints, failed saves, bounded retries and explicit Restart controls.
The limits checks add fake-clock pacing/window/deadline boundaries, manual-hold
precedence, retransfers and resumed-prefix accounting, settings failures and a
crash with an uncertain byte total. A native combined scenario exercises cap
changes, throttled pause/save/restore, schedule and retry interaction, boundary
holds, byte-budget overrun, explicit New run and byte-exact files.
The native check uses mocked login, provider and shell access;
space exhaustion and write failures use deterministic offline fixtures. No real
Firefox session or TeraBox download was used for this update.
The sandbox blocks local sockets, so the loopback suite ran with the required
local-network permission. Forced process crashes were tested; power loss was not.
**Evidence: 2/3 — Local queue/UI behavior is directly tested; live-provider
compatibility and full large-file transfer remain unverified.**

Delivery E additionally checked a real Windows tray lifecycle with intercepted
notifications: registration before hiding, restore, pause/resume, Cancel/reset,
save/exit, byte-exact output, and rejected registration leaving the window
accessible. The actual `.pyw` launcher handed off to project-local `pythonw`,
held a single queue-data lock and saved/exited on its owned WM_CLOSE. All owned
windows/processes exited. Offline checks cover missing/startup-failed backends,
notification opt-in/deduplication, preferences, safe failure logs and log rotation.
The sandbox rejected a Windows tray message-filter call, so the native tray test
used the approved unsandboxed context. The original queue/recovery/run-limit
Tkinter smoke still passed with optional packages absent from its interpreter.
At that Delivery E checkpoint, real notification banners, Explorer restarts,
sleep/resume and installed shortcut launch were not exercised. That checkpoint
was a source-launcher release; the later 0.1.0 packaging work is recorded in
the personal-release checklist.

## Backup and rollback

Exit Tera before copying its **whole** data directory and any owned partial files
in download folders. Keep them with the same Windows account; DPAPI-protected
links are not a portable account backup. Never copy only an active SQLite main
file as a backup. The state module also offers SQLite's online backup API for
queue snapshots; a full recovery needs the preferences and partials as well.
Existing legacy settings and completed videos are not migrated or deleted.

These deliveries keep schema version 1. To roll back, preserve the current data
first and restore a matching code/data backup together. Older download code may
not understand newer checkpoint or run-limit payloads despite sharing the schema
version; do not run the pre-roadmap app against the current live store. Corrupt
or unsupported state is refused instead of silently reset. No rollback or
restore command runs automatically.

The app does not silently retry anonymously when the selected Firefox session
fails validation. TeraBox's own download restrictions still apply.

## Diagnostic commands

```powershell
python terabox.py --check "YOUR_TERABOX_LINK" --firefox
python terabox.py --check "YOUR_TERABOX_LINK" --firefox --profile default-release
python -m unittest -v
python smoke_terabox_gui.py  # Withdrawn Tkinter window; synthetic downloads only.
.\.venv-desktop\Scripts\python.exe smoke_desktop.py  # Explicit native check; may show its owned window.
python terabox.py --data-dir "C:\path\to\isolated-tera-state"
```

Diagnostics do not print cookie values, account identifiers or signed download URLs.

## Building and checking the Windows package

Use Windows x64, Python 3.12.10 / Tcl 8.6.15, and the pinned build requirements.
The source runtime remains independent of these build tools. Use Inno Setup
7.1.0 x64's command-line compiler (the official signed installer supports
portable mode); supply its path through `--iscc` if it is not in `.tools`.

```powershell
python -m venv .venv-build
.\.venv-build\Scripts\python.exe -m pip install --only-binary=:all: -r requirements-build.txt
.\.venv-build\Scripts\python.exe build_windows.py --iscc .tools\InnoSetup\ISCC.exe
```

The inspected build script creates `dist\Tera\Tera.exe`,
`dist\Tera-0.2.0-Setup.exe`, a SHA256 file and logs under `build`. It does not
launch Tera or install anything. Bundled third-party licenses are in
`_internal\licenses`. The committed Tcl notice comes from the
[8.6.15 upstream license](https://github.com/tcltk/tcl/blob/core-8-6-15/license.terms).
Packaging follows [PyInstaller's one-folder guidance](https://pyinstaller.org/en/stable/operating-mode.html)
and [Inno Setup's per-user installation](https://jrsoftware.org/ishelp/topic_setup_privilegesrequired.htm).

Explicit synthetic package checks are available with `--self-test app` or
`--self-test desktop` plus `--data-dir` pointing to a new disposable directory.
The app check uses withdrawn Tk windows; the desktop check may briefly show its
owned window/tray. Both mock provider/login access; notifications are intercepted.
They create `self-test.log` and record success in `launcher.log`, and do not
establish live provider compatibility. An existing self-test log is not replaced.

## Proposed product roadmap

The [incorporation plan](tasks/plan.md) combines the requested heavy-download and
personal-workflow improvements. Its [implementation checklist](tasks/todo.md)
records completed deliveries and their local verification. Review/selection, duplicate/storage
preflight and finish-current pause are implemented in Delivery B. Delivery C adds
owned checkpoints, conservative continuation and bounded retries, with live
provider resume still pending. Delivery D implements bandwidth caps, daily windows
and per-run time/byte limits. Delivery E adds the optional tray, generic opt-in
notifications and quiet launcher. All five local delivery checkpoints are
complete; live-provider and large-file verification remain separate gates.
