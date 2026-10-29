# Build with the pinned Windows build environment; never collect user settings.
from pathlib import Path
from PyInstaller.utils.hooks import copy_metadata

root = Path(SPECPATH)
data = [(str(root / 'build' / 'licenses'), 'licenses'), (str(root / 'README.md'), 'docs'),
        (str(root / 'camoufox_worker.cjs'), '.')]
for package in ('pystray', 'Pillow', 'six'):
    data += copy_metadata(package)
a = Analysis([str(root / 'Start Tera.pyw')], pathex=[str(root)], binaries=[(str(root / '.tools' / 'stream-ffmpeg.exe'), 'tools')], datas=data,
             hiddenimports=['pystray._win32'], hookspath=[], hooksconfig={}, runtime_hooks=[],
             excludes=['pytest'], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='Tera', debug=False,
          bootloader_ignore_signals=False, strip=False, upx=False, console=False,
          disable_windowed_traceback=True, icon=str(root / 'build' / 'Tera.ico'),
          version=str(root / 'build' / 'version.txt'))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='Tera')
