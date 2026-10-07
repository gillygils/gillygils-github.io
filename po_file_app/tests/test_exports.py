import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import add_converted_exports


def upload(name, data):
    value = io.BytesIO(data)
    value.name = name
    return value


class ExportTests(unittest.TestCase):
    def prepare(self, root):
        job = root / 'PO 1530 Parts'; job.mkdir()
        (job / 'C15999.sldprt').write_bytes(b'native')
        report = {'po': '1530', 'items': [{'part': 'C15999'}], 'results': []}
        (job / 'report.json').write_text(json.dumps(report))
        archive = root / 'package.zip'; archive.write_bytes(b'previous-zip')
        return {'folder': str(job), 'archive': str(archive), 'report': report}

    def test_exports_added_to_flat_zip_and_report(self):
        with tempfile.TemporaryDirectory() as temp:
            completed = self.prepare(Path(temp))
            files = [upload('C15999.step', b'ISO-10303-21;\nDATA;\nENDSEC;\nEND-ISO-10303-21;'), upload('C15999.pdf', b'%PDF-1.7\nexample')]
            updated = add_converted_exports(completed, files)
            with ZipFile(updated['archive']) as archive:
                self.assertEqual(set(archive.namelist()), {'C15999.sldprt', 'C15999.step', 'C15999.pdf', 'report.json'})
                self.assertEqual(archive.read('C15999.pdf'), files[1].getvalue())
                self.assertEqual(len(json.loads(archive.read('report.json'))['results']), 2)
            self.assertEqual(completed['report']['results'], [])
            with self.assertRaises(ValueError): add_converted_exports(updated, files)

    def test_bad_filenames_and_headers_leave_package_unchanged(self):
        with tempfile.TemporaryDirectory() as temp:
            completed = self.prepare(Path(temp))
            for name, data in [('C15998.pdf', b'%PDF-1.7'), ('../C15999.pdf', b'%PDF-1.7'), ('C15999.step', b'native file'), ('C15999.pdf', b'not pdf')]:
                with self.assertRaises(ValueError): add_converted_exports(completed, [upload(name, data)])
            self.assertEqual(Path(completed['archive']).read_bytes(), b'previous-zip')
            self.assertEqual(len(list(Path(completed['folder']).iterdir())), 2)

    def test_zip_failure_rolls_back_added_exports_and_report(self):
        with tempfile.TemporaryDirectory() as temp:
            completed = self.prepare(Path(temp))
            original = (Path(completed['folder']) / 'report.json').read_bytes()
            with patch('shutil.make_archive', side_effect=OSError('disk full')):
                with self.assertRaises(OSError): add_converted_exports(completed, [upload('C15999.pdf', b'%PDF-1.7')])
            self.assertFalse((Path(completed['folder']) / 'C15999.pdf').exists())
            self.assertEqual((Path(completed['folder']) / 'report.json').read_bytes(), original)
            self.assertEqual(Path(completed['archive']).read_bytes(), b'previous-zip')
