"""Install a pinned optional browser from local assets only; no downloads or launches."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import zipfile

from camoufox_helper import RUNTIME_MARKER, runtime_directory

BROWSER_SHA = '2d3e33207c2d5853e817e8317f0e33124ffb7054bd5102c8b84546e3d15a6447'
NODE_SHA = '6d75619e8720161bb0e8c5617bcf90384b48a920b9182ec6e9d52f11f83a8e84'
UBLOCK_SHA = '5b74415860456370644bd80f16125e865b0e6c356bb5dfcfb84069967eaa5287'


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def unpack(archive, destination):
    root=destination.resolve()
    with zipfile.ZipFile(archive) as package:
        for entry in package.infolist():
            target=(root/entry.filename).resolve()
            if not target.is_relative_to(root) or (entry.external_attr>>16)&0o170000==0o120000:
                raise ValueError('Unsafe archive path')
        package.extractall(root)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser-archive',type=Path,required=True)
    parser.add_argument('--ublock-xpi',type=Path,required=True)
    parser.add_argument('--node',type=Path,required=True)
    parser.add_argument('--node-license',type=Path,required=True)
    parser.add_argument('--playwright-core',type=Path,required=True)
    args=parser.parse_args()
    for source,expected in ((args.browser_archive,BROWSER_SHA),(args.ublock_xpi,UBLOCK_SHA),(args.node,NODE_SHA)):
        if digest(source)!=expected:
            raise ValueError('A local runtime asset does not match its pinned hash')
    if json.loads((args.playwright_core/'package.json').read_text(encoding='utf-8'))['version']!=RUNTIME_MARKER['playwright']:
        raise ValueError('Unexpected Playwright version')
    target=runtime_directory()
    target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists():
        raise ValueError('The runtime directory already exists; no existing runtime was replaced')
    temporary=Path(tempfile.mkdtemp(prefix='.tera-camoufox-install-',dir=target.parent)).resolve()
    try:
        unpack(args.browser_archive,temporary/'native')
        unpack(args.ublock_xpi,temporary/'addons'/'ublock')
        shutil.copy2(args.node,temporary/'node.exe')
        shutil.copytree(args.playwright_core,temporary/'playwright-core')
        shutil.copy2(args.node_license,temporary/'Node-LICENSE.txt')
        integrity={str(item.relative_to(temporary)).replace('\\','/'):digest(item)
                   for item in temporary.rglob('*') if item.is_file()}
        (temporary/'integrity.json').write_text(json.dumps(integrity,indent=2),encoding='utf-8')
        (temporary/'tera-runtime.json').write_text(json.dumps(RUNTIME_MARKER),encoding='utf-8')
        temporary.rename(target)
        print('Installed pinned Camoufox runtime; browser was not launched.',flush=True)
    finally:
        if temporary.exists() and temporary.parent==target.parent.resolve() and temporary.name.startswith('.tera-camoufox-install-'):
            shutil.rmtree(temporary)


if __name__=='__main__':
    main()
