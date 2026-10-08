"""Install optional, checksum-verified LibreDWG 0.14 Windows tools once."""
import hashlib
import io
import json
import os
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from .dwg import DEFAULT_TOOLS

URL = 'https://github.com/LibreDWG/libredwg/releases/download/0.14/libredwg-0.14-win64.zip'
SHA256 = '1ad7e15344d20b3426c3435b078d82fb84b35062815946b2cca9c5fc9810fea8'
SOURCE_URL = 'https://github.com/LibreDWG/libredwg/releases/tag/0.14'
REQUIRED = {'dxf2dwg.exe', 'dwg2dxf.exe', 'libredwg-0.dll', 'libiconv-2.dll',
            'libpcre2-16-0.dll', 'libpcre2-8-0.dll', 'README.txt'}


def verified_files(data):
    if hashlib.sha256(data).hexdigest() != SHA256:
        raise ValueError('LibreDWG download checksum failed; no tools were installed.')
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        files = {}
        for name in REQUIRED:
            info = archive.getinfo(name)
            if info.file_size > 64*1024*1024:
                raise ValueError('LibreDWG component exceeds its size limit.')
            files[name] = archive.read(info)
    return files


def installed(folder):
    try:
        manifest = json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
        hashes = manifest['files']
        return (manifest['archive_sha256'] == SHA256 and REQUIRED <= hashes.keys()
                and all(hashlib.sha256((folder/name).read_bytes()).hexdigest() == hashes[name]
                        for name in REQUIRED))
    except (OSError, ValueError, KeyError, TypeError):
        return False


def setup(folder=DEFAULT_TOOLS):
    if os.name != 'nt':
        raise RuntimeError('This installer is for 64-bit Windows. Other platforms can build LibreDWG 0.14 and set PO_DWG_TOOLS.')
    folder = Path(folder)
    if installed(folder):
        print('Local DWG tools already installed and checksums verified.')
        return
    if folder.exists():
        raise RuntimeError('Existing .dwg-tools installation is incomplete or modified. Rename that folder, then run this installer again.')
    print('Downloading optional LibreDWG 0.14 tools (about 12 MB)…')
    request = urllib.request.Request(URL, headers={'User-Agent': 'PO-File-Packager'})
    with urllib.request.urlopen(request, timeout=90) as response:
        data = response.read(32*1024*1024+1)
    if len(data) > 32*1024*1024:
        raise ValueError('LibreDWG archive exceeds its size limit.')
    files = verified_files(data)
    folder.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='dwg-install-', dir=folder.parent) as temp:
        prepared = Path(temp)/'tools'
        prepared.mkdir()
        for name, content in files.items():
            (prepared/name).write_bytes(content)
        license_path = Path(__file__).parent/'licenses'/'LibreDWG-COPYING'
        shutil.copyfile(license_path, prepared/'COPYING')
        manifest = {'version': '0.14', 'source_url': SOURCE_URL, 'archive_sha256': SHA256,
                    'files': {name: hashlib.sha256(content).hexdigest() for name, content in files.items()}}
        (prepared/'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        prepared.rename(folder)
    print('Local DWG tools installed. Drawing conversion needs no internet connection.')


if __name__ == '__main__':
    try:
        setup()
    except Exception as exc:
        raise SystemExit('DWG tool installation failed: '+str(exc))
