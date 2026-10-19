# Tera — local TeraBox downloader

## Use it

1. Double-click **Start Tera.cmd** on Windows (Python 3.10+ with Tkinter).
2. Select your usual **Firefox profile**. Use **Login in Firefox** to open your
   share and sign into TeraBox in a normal tab; **Check login** verifies it.
3. Paste share links one per line or separated by commas, choose a destination,
   then click **Review links**. Invalid links are reported inline. Your last
   destination is remembered; **Save favorite…** names folders you use often.
   Optionally enable **Use a separate folder for each share** before reviewing.
4. In **Review**, click a video's checkbox (or select it and press Space) to
   include/exclude it. The view shows file sizes, destinations and selected bytes.
   **Download selected** starts those files, or appends them to the running queue.
   It preserves an existing pause. Review and exclusions survive reopening;
   **Review saved shares** explicitly discovers an interrupted review.
5. Review more links while downloading. In **Queue**, select pending rows to
   **Move up**, **Move down**, or **Remove pending**. **Change folder…** and
   **Rename…** work on reviewed, pending or held files. **Skip** stops the active
   file, or skips a selected held file when no transfer is active. It removes
   only that attempt's owned temporary file and preserves completed files.
6. **Pause now** holds the active transfer and queue. **Pausing…** waits for an
   in-flight read; **Paused** confirms the worker has stopped reading. Click
   **Resume** to continue while Tera remains open. **Finish current, then pause**
   lets the active file finish and starts no next file until Resume. The dashboard
   shows overall known progress, speed and estimated time.
7. The **History** tab shows completed, failed, skipped and cancelled items.
   Select failures and click **Retry selected failures**, then **Start queue**.
   A failed share review returns to **Review saved shares** instead of downloading
   unreviewed files. To restart a cancelled/skipped file, review its share again.
   **Reveal folder** opens a saved destination only when clicked. **Clear history**
   is available while idle, forgets completion duplicate markers, and never deletes
   files or unfinished jobs.
8. Clicking **X saves the queue and exits** after the current request stops.
   Reopening restores unfinished jobs and destinations without automatically
   checking login or starting downloads. **Interrupted files restart from zero
   in this version.** Cancel queue marks pending items cancelled; completed files
   are always kept. Tray mode and schedules are not implemented yet.

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
not reserve disk space against other apps. A mid-file storage failure cleans up
the owned partial and restarts that file from zero after correction. Stop an
active file before reviewing/restarting it at a new destination; partial files
are not moved. Per-share folder names use a short identity hash, not a raw share
code or password.

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
- Saved source links and share access codes are encrypted with current-user
  Windows DPAPI. Filenames, destinations and history are local metadata and can
  be cleared. Cookies, account identifiers, page tokens and signed media URLs
  are never stored in the queue. Protection/save failures are reported; there
  is no plaintext fallback. DPAPI is tied to the Windows account and does not
  protect against programs already running as that user.
- **Disconnect**, or selecting **No login**, disables future imports and blocks
  unfinished authenticated jobs. Re-add those shares with your chosen source;
  retry never silently switches them to anonymous access. Firefox login/data
  remain untouched. Each queued row displays its own login source.
- Requests and redirects are limited to supported TeraBox domains. There are no
  external download proxies, link resolvers, telemetry or cookie uploads.
- A system VPN applies normally. A Firefox-only VPN extension does not route
  this app. Tera does not verify or enforce VPN connectivity. If Firefox itself
  cannot open a share without a VPN, the network is blocking or interrupting
  TeraBox; Tera uses direct connections only and cannot bypass that restriction.

## Verification and limits

Earlier documented live verification covered a Firefox account check,
original-file URL resolution, and a small MKV sample whose response size matched
the shared file metadata. The new queue/UI was checked with synthetic data.
**A complete large-file transfer was not run as part of this verification.**
Some shares do not provide download URLs without an authenticated session.

Original files are kept temporary until the byte count matches the share size.
Previews and HLS playlists are rejected. Existing files are not overwritten;
cancelled or failed transfers remove only their own temporary file. A queue
continues after an individual link or video fails and shows the completed and
failed items at the end. Pause keeps the current connection and downloaded bytes
only while Tera stays open. A long pause can fail if the server closes the
connection; there is no automatic reconnection or partial-byte recovery after
closing Tera. Pending jobs are restored, but interrupted, cancelled or failed
files restart from zero when started again. Rate
limits, expired links, account limits, share restrictions and future TeraBox
changes can still cause failures.

Deliveries A/B verification passed **65 offline tests** and an isolated, withdrawn
native Tkinter smoke check on Python 3.12.10 / Tk 8.6 / SQLite 3.49.1. The checks
covered encrypted storage, failed saves, backup/restore, process locking, queue
edits, active-stream skip cleanup, history/retry, favorites, review/selection,
duplicates/exclusions, disk/conflict handling, pause/rapid toggles, finish-current
pause, byte-exact synthetic files, save/exit, held restoration and real isolated
CLI startup/exit. The native check uses mocked login, provider and shell access;
space exhaustion and write failures use deterministic offline fixtures. No real
Firefox session or TeraBox download was used for this update.
**Evidence: 2/3 — Local queue/UI behavior is directly tested; live-provider
compatibility and full large-file transfer remain unverified.**

The app does not silently retry anonymously when the selected Firefox session
fails validation. TeraBox's own download restrictions still apply.

## Diagnostic commands

```powershell
python terabox.py --check "YOUR_TERABOX_LINK" --firefox
python terabox.py --check "YOUR_TERABOX_LINK" --firefox --profile default-release
python -m unittest -v
python smoke_terabox_gui.py  # Withdrawn Tkinter window; synthetic downloads only.
python terabox.py --data-dir "C:\path\to\isolated-tera-state"
```

Diagnostics do not print cookie values, account identifiers or signed download URLs.

## Proposed product roadmap

The [incorporation plan](tasks/plan.md) combines the requested heavy-download and
personal-workflow improvements. Its [implementation checklist](tasks/todo.md)
records completed deliveries and their local verification. Review/selection, duplicate/storage
preflight and finish-current pause are now implemented in Delivery B. Durable
partial resume, automatic retries, bandwidth/schedule/budget controls and
tray/notifications remain pending in Deliveries C-E.
