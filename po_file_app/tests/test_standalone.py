"""Standalone conversion preserves filenames, validates solids and isolates PO state."""
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from test_native_conversion import sample_part
from test_native_geometry import two_cubes
from native_part.backend import convert_part_native
from standalone import convert_batch,prepare_uploads


def upload(name,data):
    return SimpleNamespace(name=name,size=len(data),getvalue=lambda:data)


class StandaloneTests(unittest.TestCase):
    def test_batch_keeps_success_and_reports_failed_part(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'two.sldprt'
            sample_part(path,records=two_cubes())
            data=path.read_bytes()
            inputs=prepare_uploads([upload('C04045-001.SLDPRT',data),upload('bad.sldprt',b'not-a-part')])
            updates=[]
            result=convert_batch(inputs,convert_part_native,lambda *args:updates.append(args))
            self.assertEqual(set(result['outputs']),{'C04045-001.step'})
            self.assertEqual(updates[-1][:2],(2,2))
            self.assertEqual(path.read_bytes(),data)
            with zipfile.ZipFile(io.BytesIO(result['zip'])) as archive:
                self.assertEqual(set(archive.namelist()),{'C04045-001.step','report.json'})
                self.assertEqual(archive.read('C04045-001.step'),result['outputs']['C04045-001.step'])
                report=json.loads(archive.read('report.json'))
                self.assertEqual(report['results'][0]['validation']['solid_count'],2)
                self.assertEqual(report['results'][1]['status'],'Failed')
                self.assertIn('error',report['results'][1])
            self.assertEqual(list(Path(temp).iterdir()),[path])

    def test_collisions_unsafe_names_and_oversized_uploads_are_rejected(self):
        for name in ('../part.sldprt','..\\part.sldprt','C:\\part.sldprt','part.pdf','part?.sldprt'):
            with self.assertRaises(ValueError):prepare_uploads([upload(name,b'')])
        with self.assertRaisesRegex(ValueError,'same STEP filename'):
            prepare_uploads([upload('Part.sldprt',b'a'),upload('part.SLDPRT',b'b')])
        oversized=SimpleNamespace(name='large.sldprt',size=65*1024*1024,getvalue=lambda:self.fail('Read oversized upload'))
        with self.assertRaisesRegex(ValueError,'64 MiB'):prepare_uploads([oversized])

    def test_part_tab_runs_without_po_or_folder_settings_and_hides_stale_results(self):
        from streamlit.testing.v1 import AppTest
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'cube.sldprt';sample_part(path)
            current=[upload('uploaded-cube.sldprt',path.read_bytes())]
            def uploader(label,*args,**kwargs):
                return current if label=='SolidWorks part files' else None
            with patch('streamlit.file_uploader',side_effect=uploader), patch('core.find_files',side_effect=AssertionError('Searched network drive')):
                app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'),default_timeout=20).run()
                self.assertFalse(app.exception)
                self.assertEqual([tab.label for tab in app.tabs],['Purchase orders','Part to STEP'])
                self.assertEqual(app.sidebar.text_input[1].value,'')
                app.session_state['completed_job']={'sentinel':'unchanged PO'}
                button=next(b for b in app.button if b.label=='Convert uploaded parts to STEP')
                self.assertFalse(button.disabled)
                button.click().run()
                self.assertFalse(app.exception)
                result=app.session_state['standalone_result']
                self.assertEqual(set(result['outputs']),{'uploaded-cube.step'})
                self.assertEqual(app.session_state['completed_job'],{'sentinel':'unchanged PO'})
                self.assertTrue(any(b.label=='Download STEP files ZIP' for b in app.get('download_button')))
                # Replacing the selected upload must hide the old STEP downloads.
                current[:]=[upload('changed.sldprt',b'other-input')]
                app.run()
                self.assertFalse(app.exception)
                self.assertNotIn('standalone_result',app.session_state)
                self.assertFalse(any(b.label=='Download STEP files ZIP' for b in app.get('download_button')))


if __name__=='__main__':unittest.main()
