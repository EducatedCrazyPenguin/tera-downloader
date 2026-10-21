"""Build only: no application launch, installer execution, network or user data."""
import argparse
import hashlib
import importlib.metadata
import os
from pathlib import Path
import shutil
import subprocess
import sys

from app_version import VERSION


def run(command, log):
    with log.open('w', encoding='utf-8') as output:
        child = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
        print(f'Build process {child.pid}; log {log.name}', flush=True)
        try:
            result = child.wait(timeout=180)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()
            raise
        if result:
            raise RuntimeError(f'Build failed ({result}); see {log.name}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--iscc', type=Path, default=Path('.tools/InnoSetup/ISCC.exe'))
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    os.chdir(root)
    build = root / 'build'
    build.mkdir(exist_ok=True)
    os.environ.update(TEMP=str(build), TMP=str(build), PYINSTALLER_CONFIG_DIR=str(build / 'pyinstaller-cache'))
    from PIL import Image, ImageDraw
    image = Image.new('RGB', (256, 256), '#175c67')
    draw = ImageDraw.Draw(image)
    draw.rectangle((48, 48, 207, 95), fill='white')
    draw.rectangle((104, 80, 151, 211), fill='white')
    image.save(build / 'Tera.ico', sizes=[(16,16), (32,32), (48,48), (64,64), (128,128), (256,256)])
    from PyInstaller.utils.win32.versioninfo import VSVersionInfo, FixedFileInfo, StringFileInfo, StringTable, StringStruct, VarFileInfo, VarStruct
    numbers = tuple(map(int, VERSION.split('.'))) + (0,)
    info = VSVersionInfo(ffi=FixedFileInfo(filevers=numbers, prodvers=numbers, fileType=1),
                        kids=[StringFileInfo([StringTable('040904B0', [StringStruct(k, v) for k, v in
                              {'FileDescription': 'Tera video downloader', 'FileVersion': VERSION, 'ProductName': 'Tera',
                               'ProductVersion': VERSION, 'OriginalFilename': 'Tera.exe'}.items()])]),
                              VarFileInfo([VarStruct('Translation', [1033, 1200])])])
    (build / 'version.txt').write_text(str(info), encoding='utf-8')
    notices = build / 'licenses'
    notices.mkdir(exist_ok=True)
    for package in ('pystray', 'Pillow', 'six', 'PyInstaller'):
        dist = importlib.metadata.distribution(package)
        for entry in dist.files or []:
            if any(word in entry.name.lower() for word in ('license', 'copying')):
                source = Path(dist.locate_file(entry))
                if source.is_file():
                    target = notices / package / Path(*entry.parts)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
    shutil.copy2(Path(sys.base_prefix) / 'LICENSE.txt', notices / 'Python-LICENSE.txt')
    import tkinter
    if tkinter.Tcl().call('info', 'patchlevel') != '8.6.15':
        raise RuntimeError('Update the pinned Tcl license for this runtime before packaging.')
    shutil.copy2(root / 'third_party' / 'Tcl-8.6.15-license.terms', notices / 'Tcl-license.terms')
    shutil.copy2(Path(sys.base_prefix) / 'tcl' / 'tk8.6' / 'license.terms', notices / 'Tk-license.terms')
    (notices / 'README.txt').write_text('Bundled third-party notices. Dependencies are unmodified.\n'
        'Source versions: see requirements-desktop.txt in the Tera source repository.\n'
        'https://github.com/EducatedCrazyPenguin/tera-downloader\n'
        'https://pypi.org/project/pystray/0.19.5/ (LGPLv3)\n'
        'https://pypi.org/project/Pillow/13.0.0/ (MIT-CMU)\n'
        'https://pypi.org/project/six/1.17.0/ (MIT)\n', encoding='utf-8')
    run([sys.executable, '-m', 'PyInstaller', '--noconfirm', 'Tera.spec'], build / 'pyinstaller.log')
    run([str(args.iscc.resolve()), '/Qp', f'/DAppVersion={VERSION}', 'tera-installer.iss'], build / 'installer-build.log')
    installer = root / 'dist' / f'Tera-{VERSION}-Setup.exe'
    digest = hashlib.sha256(installer.read_bytes()).hexdigest()
    installer.with_suffix('.sha256').write_text(f'{digest}  {installer.name}\n', encoding='ascii')
    print(f'Built {installer.name}; SHA256 {digest}', flush=True)


if __name__ == '__main__':
    main()
