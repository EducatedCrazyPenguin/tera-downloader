# Changelog

## Unreleased — repository maintenance

- Organise source, tests, tooling, packaging, requirements and documentation into dedicated folders.
- Keep the root launchers, preserve legacy settings lookup, and add a canonical test runner.
- Shorten the GitHub landing README; move the full manual into docs/usage.md.
- No new installed-app release or data migration.


## 0.9.0 — 30 October 2026

- Move/remove multiple eligible queue selections with active-item protection.
- Add Move next for pending selections, preserving their relative order.
- Add filename and status filters without changing execution order; keep three visible filename rows at the checked minimum layouts.
- Preserve existing transfer recovery, profiles and state schema 2.

Evidence: 3/3 for named synthetic ordering/filter tests; provider delivery is a separate verification boundary.


## 0.8.0 — 29 October 2026

- Checkpoint verified website segments for restart recovery and preserve them on recoverable errors.
- Refresh rejected links once through retained, protected share provenance; reject changed playlists.
- Validate saved segment hashes, recover interrupted final publication, and retain bounded retries.
- Migrate state to version 2 with a consistent SQLite/settings backup; keep .ts output.

Evidence: 2/3 — synthetic recovery checks cover named cases; full live-provider delivery remains untested.


## 0.7.0 — 29 October 2026

- Add background Camoufox resolution for No-VPN shares, using normal website
  controls and a private local Playwright worker. Retain Firefox/Edge choices.
- Include uBlock in the optional pinned browser runtime. Keep profiles separate,
  media blocked during capture, cancellation bounded and queue sources validated.
- Resolve rows sequentially so changing labels/popups do not skip or reorder
  files. Save Camoufox as a supported browser preference.

Live automatic resolution of the supplied share succeeded and Tera accepted its
615-segment text playlist. No full real video was downloaded. Full transfer,
playback/audio/quality and future Cloudflare acceptance remain unverified.

**Evidence: 3/3 for the named live resolution/playlist observation; 2/3 for
complete provider delivery. Runtime/install gates are recorded in docs/development/todo.md.**

## 0.6.0 — 29 October 2026

- Choose Firefox or Edge for No-VPN website downloads; remember the choice and
  default to Firefox. Use separate persistent helper profiles for cookies and
  extensions, with a Set up browser button for managing them.
- Use Firefox WebDriver BiDi without adding a driver/runtime dependency. Retain
  origin restrictions, validated player capture and owned-process cancellation.
- Allow three minutes per share and a minute for initial load. Handle Firefox's
  Windows launcher handoff and wait for graceful browser shutdown before cleanup.
- On this machine, install the user-requested official uBlock Origin 1.75.0 into
  Tera's Firefox profile and verify permanent activation after restart.

Verified with 187 offline tests, real Edge/Firefox local-site capture and cookie
restart checks, native selector/setup/queue checks, clean packaged checks and the
actual installed Desktop shortcut. Installed 0.6.0; queue/settings and the requested
uBlock package were preserved. Browser controls are in Settings → Connection.

**Evidence: 2/3 — Named local/packaged/installed checks pass. Live Cloudflare
verification failed (observed 600010); unattended provider delivery is unresolved.**

## 0.5.0 — 29 October 2026

- Start a small isolated Edge window automatically for No-VPN shares; use normal
  Watch Online buttons and return supported player links without a manual paste.
- Keep human verification in the normal website flow and retain manual fallback.
  Network/site failures and changed controls still stop automatic resolution.
- Bound browser work, block media during capture, isolate browser state and
  close only the owned process tree. Cancel/app exit wait for helper cleanup.

Verified with 179 offline tests, real headless Edge/local-site capture,
automatic native dialog/queue/cancel checks, clean packaged checks and the
actual installed Desktop shortcut. Installed 0.5.0; queue/settings were unchanged.

**Evidence: 2/3 — Local, packaged and installed checks passed. Live website
capture did not complete in the bounded probe; unattended provider resolution
and complete real-video delivery remain unverified.**

## 0.4.0 — 28 October 2026

- Choose VPN available / Direct or No VPN / Website at the top, with a remembered
  choice for new links. No VPN control or automatic detection is performed.
- Resolve original shares through an explicit browser handoff, then paste the
  generated player link to save a finite streaming copy (.ts).
- Verify every segment and join timestamp discontinuities using the pinned
  existing FFmpeg tool with local inputs and stream copy only.
- Keep website credentials isolated, protect saved player links with Windows
  DPAPI and preserve original-file downloads. Stream transfers restart after exit.

Verified with 172 offline tests, real loopback HTTP/local FFmpeg copy checks,
clean isolated native and packaged flows, and actual installed Desktop shortcut
startup/save/exit. Installed 0.4.0; existing queue/settings checksums were unchanged.
The assembly fixture carries synthetic data packets, not real movie/audio.

**Evidence: 2/3 — Local, packaged and installed behavior checked; full real-video
delivery, playback/audio/quality and expiring-source recovery remain untested.**

## 0.3.0 — 28 October 2026

- Add an optional app-only HTTP CONNECT proxy in Settings → Connection for desktop
  login checks, share review and downloads. Direct access remains the default.
- Protect saved proxy credentials with Windows DPAPI and keep TLS validation,
  domain restrictions and fail-without-direct-fallback behavior.
- A proxy is not provided. VPN-free TeraBox access requires a working endpoint
  and remains provider-unverified.

Verified with 161 offline tests, a byte-exact local HTTPS CONNECT transfer,
native settings save/restart, packaged synthetic flows and the actual installed
Desktop shortcut using disposable state. Installed 0.3.0; saved queue/settings
checksums were unchanged by the quiet upgrade.

**Evidence: 2/3 — Local and installed behavior checked. External proxy/TeraBox
access and complete real downloads remain unverified.**

## 0.1.0 — 21 October 2026

- See progress while Tera verifies saved bytes, with clearer recovery and waiting messages.
- Search and sort Review/History, select matching videos, and change selected destinations together.
- Find recovery guidance and save private diagnostics from Help / About.
- Install a self-contained Windows app with Desktop/Start-menu shortcuts and safe upgrade protection.
- Preserve saved destinations; use Windows Downloads/Tera for new users.
- Retry one brief Windows settings-replacement denial while preserving previous settings on persistent failure.

Verified with 146 offline tests, synthetic native/packaged/installed flows and a
disposable installer upgrade/uninstall. See docs/development/todo.md for the exact scope.

**Evidence: 2/3 — Checked local and installed behavior; live TeraBox resume and
large-file reliability remain unverified. Personal installer is unsigned.**
