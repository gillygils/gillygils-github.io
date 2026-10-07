import hashlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZipFile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import converter.setup as setup


class ConverterSetupTests(unittest.TestCase):
    def archive(self):
        data=io.BytesIO()
        with ZipFile(data,'w') as archive:
            archive.writestr('node-v24.21.0-win-x64/node.exe',b'fake-node-runtime')
            archive.writestr('node-v24.21.0-win-x64/LICENSE',b'runtime-license')
        return data.getvalue()

    def test_portable_node_verified_and_license_retained(self):
        archive=self.archive()
        manifest=(hashlib.sha256(archive).hexdigest()+'  node-v24.21.0-win-x64.zip\n').encode()
        with tempfile.TemporaryDirectory() as temp, patch.object(setup,'APP',Path(temp)), patch.object(setup,'os',SimpleNamespace(name='nt')), patch.object(setup,'node_executable',return_value=None), patch.object(setup.platform,'machine',return_value='AMD64'), patch.object(setup,'fetch',side_effect=[manifest,archive]):
            executable=Path(setup.ensure_node())
            self.assertEqual(executable.read_bytes(),b'fake-node-runtime')
            self.assertEqual((executable.parent/'LICENSE').read_bytes(),b'runtime-license')

    def test_node_checksum_failure_prevents_installation(self):
        manifest=('0'*64+'  node-v24.21.0-win-x64.zip\n').encode()
        with tempfile.TemporaryDirectory() as temp, patch.object(setup,'APP',Path(temp)), patch.object(setup,'os',SimpleNamespace(name='nt')), patch.object(setup,'node_executable',return_value=None), patch.object(setup.platform,'machine',return_value='AMD64'), patch.object(setup,'fetch',side_effect=[manifest,self.archive()]):
            with self.assertRaisesRegex(RuntimeError,'checksum mismatch'):setup.ensure_node()
            self.assertFalse((Path(temp)/'.converter'/'runtime'/'node.exe').exists())
