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

    def test_removed_vendor_bundle_has_actionable_error_and_keeps_cached_modules(self):
        import json
        from urllib.error import HTTPError
        with tempfile.TemporaryDirectory() as temp:
            app=Path(temp)
            modules=app/'.converter'/'modules';modules.mkdir(parents=True)
            existing=modules/'verified.js';existing.write_bytes(b'verified')
            manifest=app/'manifest.json'
            manifest.write_text(json.dumps({'files':[
                {'name':'verified.js','url':'https://example.invalid/verified.js',
                 'sha256':hashlib.sha256(b'verified').hexdigest()},
                {'name':'removed.js','url':'https://example.invalid/removed.js','sha256':'0'*64}]}))
            with patch.object(setup,'APP',app),patch.object(setup,'MANIFEST',manifest),patch.object(setup,'ensure_node',return_value='node'),patch.object(setup,'fetch',side_effect=HTTPError('url',404,'Not Found',{},None)):
                with self.assertRaisesRegex(RuntimeError,'latest app from GitHub'):setup.setup()
            self.assertEqual(existing.read_bytes(),b'verified')
            self.assertFalse((modules/'removed.js').exists())
