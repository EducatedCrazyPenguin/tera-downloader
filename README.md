# Tera — local TeraBox downloader

## Use it

1. Double-click **Start Tera.cmd** on Windows (Python 3.10+ with Tkinter).
2. Leave your usual **Firefox profile** selected. Click **Login in Firefox**, open
   your share and sign into TeraBox in a normal tab.
3. Click **Check login** in Tera. Once verified, the profile choice is remembered.
4. Paste your link and click **Download**. A single video downloads automatically.
   For a folder, select a video from the list and click **Download** again.

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
  this app. Tera does not verify or enforce VPN connectivity.

## Verification and limits

Live verification covered a Firefox account check, original-file URL resolution,
and a small MKV sample whose response size matched the shared file metadata.
**A complete large-file transfer was not run as part of this verification.**
Some shares do not provide download URLs without an authenticated session.

Original files are kept temporary until the byte count matches the share size.
Previews and HLS playlists are rejected. Existing files are not overwritten;
cancelled or failed transfers remove only their own temporary file. Downloads
restart from zero after interruption. Rate limits, expired links, account limits,
share restrictions and future TeraBox changes can still cause failures.

The app does not silently retry anonymously when the selected Firefox session
fails validation. TeraBox's own download restrictions still apply.

## Diagnostic commands

```powershell
python terabox.py --check "YOUR_TERABOX_LINK" --firefox
python terabox.py --check "YOUR_TERABOX_LINK" --firefox --profile default-release
python -m unittest -v
```

Diagnostics do not print cookie values, account identifiers or signed download URLs.
