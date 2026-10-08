"""Install a checksum-verified private copy of the permitted local reader."""
import argparse
import hashlib
import io
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from urllib.request import urlopen
from urllib.error import HTTPError

APP = Path(__file__).resolve().parents[1]
MANIFEST = Path(__file__).with_name('manifest.json')


def fetch(url):
    with urlopen(url, timeout=90) as response:
        return response.read()


def node_executable():
    private = APP / '.converter' / 'runtime' / 'node.exe'
    return str(private) if private.is_file() else shutil.which('node')


def ensure_node(offline=False):
    executable = node_executable()
    if executable:
        version = subprocess.check_output([executable, '--version'], text=True).strip()
        if int(version.lstrip('v').split('.')[0]) >= 20:
            return executable
    if offline:
        raise RuntimeError('Offline startup requires an installed Node.js 20+ runtime. Run the normal installer once while connected.')
    if os.name != 'nt':
        raise RuntimeError('Install Node.js 20 or newer to run local part conversion.')
    machine = platform.machine().lower()
    if machine not in {'amd64', 'x86_64', 'arm64', 'aarch64'}:
        raise RuntimeError('Portable Node setup supports 64-bit Windows only.')
    arch = 'arm64' if machine in {'arm64', 'aarch64'} else 'x64'
    base = 'https://nodejs.org/dist/latest-v24.x/'
    sums = fetch(base + 'SHASUMS256.txt').decode('ascii')
    match = re.search(r'^([0-9a-f]{64})\s+(node-v[0-9.]+-win-' + arch + r'\.zip)$', sums, re.M)
    if not match:
        raise RuntimeError('Official Node checksum manifest did not list a compatible Windows archive.')
    archive = fetch(base + match[2])
    if hashlib.sha256(archive).hexdigest() != match[1]:
        raise RuntimeError('Node download checksum mismatch.')
    member = match[2][:-4] + '/node.exe'
    with zipfile.ZipFile(io.BytesIO(archive)) as package:
        executable_bytes = package.read(member)
        license_bytes = package.read(match[2][:-4] + '/LICENSE')
    runtime = APP / '.converter' / 'runtime'
    runtime.mkdir(parents=True, exist_ok=True)
    (runtime / 'LICENSE').write_bytes(license_bytes)
    (runtime / 'node.exe').write_bytes(executable_bytes)
    return str(runtime / 'node.exe')


def setup(offline=False):
    print('Preparing local part converter…', flush=True)
    executable = ensure_node(offline=offline)
    manifest = json.loads(MANIFEST.read_text())
    destination = APP / '.converter' / 'modules'
    destination.mkdir(parents=True, exist_ok=True)
    for file in manifest['files']:
        target = destination / file['name']
        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == file['sha256']:
            continue
        if offline:
            raise RuntimeError('Offline converter component is missing or fails its checksum: ' + file['name']
                               + '. Run run_windows.bat once while connected to install this app version.')
        print('Downloading converter component ' + file['name'], flush=True)
        try:
            data = fetch(file['url'])
        except HTTPError as exc:
            if exc.code == 404:
                raise RuntimeError('The pinned converter download is no longer published: '
                                   + file['name'] + '. Download the latest app from GitHub '
                                   'and rerun run_windows.bat. Verified cached components are retained.') from exc
            raise
        if hashlib.sha256(data).hexdigest() != file['sha256']:
            raise RuntimeError('Converter checksum mismatch: ' + file['name'])
        with tempfile.NamedTemporaryFile(dir=destination, delete=False) as temp:
            temp.write(data)
            temporary = Path(temp.name)
        try:
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
    print('Local converter installed. CAD files remain on this PC. Node: ' + executable, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--offline', action='store_true', help='Verify the installed runtime and modules without downloading anything.')
    args = parser.parse_args()
    try:
        setup(offline=args.offline)
    except Exception as exc:
        print('Local STEP converter setup failed: ' + str(exc), file=sys.stderr, flush=True)
        sys.exit(1)
