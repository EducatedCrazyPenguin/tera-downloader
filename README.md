# Tera — local TeraBox downloader

## Use it

1. Double-click **Start Tera.cmd** on Windows (Python 3.10+ with Tkinter).
2. Leave your usual **Firefox profile** selected. Click **Login in Firefox**, open
   your share and sign into TeraBox in a normal tab.
3. Click **Check login** in Tera. Once verified, the profile choice is remembered.
4. Paste share links one per line or separated by commas and click **Download
   queue**. Tera downloads every video in the first share before moving to the
   next link. Blank lines are ignored; invalid links are reported before the
   queue starts.
5. Click **Pause** to hold the current download and remaining queue, then
   **Resume** to continue from the same position. Keep Tera open while paused.
   **Pausing…** means the current network read is still finishing; **Paused**
   confirms the worker has stopped reading. Cancel and closing Tera still cancel
   the queue and remove its current temporary file; completed videos are kept.

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
- Only the selected profile path is stored in `.tera-settings.json`, excluded from Git.
- **Disconnect Firefox** disables imports and drops retained operation metadata;
  it does not log you out of Firefox or delete Firefox data.
- Requests and redirects are limited to supported TeraBox domains. There are no
  external download proxies, link resolvers, telemetry or cookie uploads.
- A system VPN applies normally. A Firefox-only VPN extension does not route
  this app. Tera does not verify or enforce VPN connectivity. If Firefox itself
  cannot open a share without a VPN, the network is blocking or interrupting
  TeraBox; Tera uses direct connections only and cannot bypass that restriction.

## Verification and limits

Live verification covered a Firefox account check, original-file URL resolution,
and a small MKV sample whose response size matched the shared file metadata.
**A complete large-file transfer was not run as part of this verification.**
Some shares do not provide download URLs without an authenticated session.

Original files are kept temporary until the byte count matches the share size.
Previews and HLS playlists are rejected. Existing files are not overwritten;
cancelled or failed transfers remove only their own temporary file. A queue
continues after an individual link or video fails and shows the completed and
failed items at the end. Pause keeps the current connection and downloaded bytes
only while Tera stays open. A long pause can fail if the server closes the
connection; there is no automatic reconnection or recovery after closing Tera.
Cancelled or failed downloads restart from zero when started again. Rate
limits, expired links, account limits, share restrictions and future TeraBox
changes can still cause failures.

Pause/Resume verification uses synthetic streams and an isolated Tkinter smoke
check; it does not establish long-pause reliability against TeraBox.
**Evidence: 2/3 — Offline checks cover the pause controls and transfer logic;
live server behavior during long pauses remains unverified.**

The app does not silently retry anonymously when the selected Firefox session
fails validation. TeraBox's own download restrictions still apply.

## Diagnostic commands

```powershell
python terabox.py --check "YOUR_TERABOX_LINK" --firefox
python terabox.py --check "YOUR_TERABOX_LINK" --firefox --profile default-release
python -m unittest -v
python smoke_terabox_gui.py  # Withdrawn Tkinter window; synthetic downloads only.
```

Diagnostics do not print cookie values, account identifiers or signed download URLs.
