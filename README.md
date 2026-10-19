# Tera — local TeraBox downloader

## Use it

1. Double-click **Start Tera.cmd** on Windows (Python 3.10+ with Tkinter).
2. Select your usual **Firefox profile**. Use **Login in Firefox** to open your
   share and sign into TeraBox in a normal tab; **Check login** verifies it.
3. Paste share links one per line or separated by commas, choose a destination,
   then click **Add to queue**. Invalid links are reported inline. Your last
   destination is remembered; **Save favorite…** names folders you use often.
4. Click **Start queue**. Each share is discovered in order and all its supported
   videos are queued. Add more links while a transfer runs; select pending rows
   to **Move up**, **Move down**, or **Remove pending**. **Skip current** removes
   only that attempt's temporary file and continues to the next item.
5. **Pause** holds the active transfer and queue. **Pausing…** waits for an
   in-flight read; **Paused** confirms the worker has stopped reading. Click
   **Resume** to continue while Tera remains open. The dashboard shows overall
   known progress, speed and estimated time; undiscovered sizes are marked.
6. The **History** tab shows completed, failed, skipped and cancelled items.
   Select failures and click **Retry selected failures**, then **Start queue**.
   **Reveal folder** opens a saved destination only when clicked. **Clear history**
   is available while idle and never deletes files or unfinished jobs.
7. Clicking **X saves the queue and exits** after the current request stops.
   Reopening restores unfinished jobs and destinations without automatically
   checking login or starting downloads. **Interrupted files restart from zero
   in this version.** Cancel queue marks pending items cancelled; completed files
   are always kept. Tray mode and schedules are not implemented yet.

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

Delivery A verification passed **47 offline tests** and an isolated, withdrawn
native Tkinter smoke check on Python 3.12.10 / Tk 8.6 / SQLite 3.49.1. The checks
covered encrypted storage, failed saves, backup/restore, process locking, queue
edits, active-stream skip cleanup, history/retry, favorites, pause/rapid toggles,
byte-exact synthetic files, save/exit, held restoration and real isolated CLI
startup/exit. No real Firefox session or TeraBox download was used for this update.
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
records Delivery A's local verification. Review/selection, duplicate/storage
preflight, finish-current pause, durable partial resume, automatic retries,
bandwidth/schedule/budget controls and tray/notifications remain pending.
