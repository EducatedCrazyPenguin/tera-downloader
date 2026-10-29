# Tera

A personal Windows desktop downloader for TeraBox share links, with a saved
queue, verified restart recovery and explicit direct or website-assisted routes.

## Use Tera

Open the installed **Tera** shortcut, paste a share link and choose **Download now**.
Use **Choose videos** for selection. Website mode uses an isolated browser and
saves a streaming copy as `.ts`; the direct route uses your selected Firefox login.

- Completed website segments survive exit and are verified before reuse.
- Select several pending rows to move/remove them, or choose **Move next**.
- Search and status filters change the queue view, not execution order.
- Pause, schedules, speed limits and saved destinations remain available.

The latest locally verified release is **0.9.0**. The optional Camoufox runtime is
installed separately from Tera. See the [user guide](docs/usage.md) for setup,
browser requirements, recovery, privacy, backups and Windows packaging.

## Repository layout

| Folder | Contents |
| --- | --- |
| [src/](src/) | Application code and browser worker |
| [tests/](tests/) | Offline tests, isolated smoke checks and synthetic fixtures |
| [scripts/](scripts/) | Test runner, Windows builder and optional runtime installer |
| [packaging/](packaging/) | PyInstaller and Inno Setup configuration |
| [requirements/](requirements/) | Pinned desktop and build dependencies |
| [docs/](docs/) | User guide, design notes and development history |
| [third_party/](third_party/) | Dependency notices, licences and recorded hashes |

The root launchers remain available for source use. Local browser profiles,
downloads, credentials, research, build output and installers are excluded from Git.

## Development

The checked environment is Python 3.12.10 with Tkinter on Windows. From the repository root:

```powershell
python scripts/test.py -v
python scripts/test.py -p test_queue_bulk.py
python src/terabox.py --help
```

Double-click **Start Tera.pyw** to launch without a console. It uses the existing
`.venv-desktop` environment when present. **Start Tera.cmd** is the explicit
console launcher. These launchers open the app; the offline test runner does not
open browsers or make provider requests.

Windows build commands and required local build assets are described in the
[build guide](docs/usage.md#building-and-checking-the-windows-package). The build
entrypoint is `scripts/build_windows.py` and does not install or launch Tera.

See the [changelog](CHANGELOG.md), [design](docs/DESIGN.md) and
[development checklist](docs/development/todo.md) for implementation evidence.

**Evidence: 3/3 for the recorded synthetic queue and local release checks.
Complete live-provider transfer and playback remain separately unverified.**
