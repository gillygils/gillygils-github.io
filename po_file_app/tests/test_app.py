"""Exercise packaging and the download-triggered reset through Streamlit callbacks."""
import io
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import streamlit as st
from streamlit.testing.v1 import AppTest
from core import Item


class AppTests(unittest.TestCase):
    def test_assembly_skip_is_reported_and_existing_step_is_retained(self):
        from test_sheetmetal_geometry import arched_box_records
        from test_native_conversion import sample_part
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'source';group=root/'IDT C16000';group.mkdir(parents=True)
            (group/'C16210.sldasm').write_bytes(b'assembly-with-external-references')
            (group/'C16211.sldasm').write_bytes(b'other-assembly')
            existing=b'ISO-10303-21;\nEND-ISO-10303-21;'
            (group/'C16211.step').write_bytes(existing)
            sample_part(group/'C16231.sldprt',records=arched_box_records())
            def uploader(*args,**kwargs):
                return [] if kwargs.get('accept_multiple_files') else io.BytesIO(b'po')
            with patch('streamlit.file_uploader',side_effect=uploader),patch('core.parse_po',return_value=('1926',[
                    Item(1,'1','PC','C16210'),Item(2,'1','PC','C16211'),Item(3,'1','PC','C16231')])):
                app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'),default_timeout=20).run()
                app.sidebar.text_input[0].set_value(str(root))
                app.sidebar.text_input[1].set_value(str(Path(temp)/'output'))
                next(b for b in app.button if b.label=='Search source folder').click().run()
                next(c for c in app.checkbox if c.label.startswith('I checked')).check().run()
                next(b for b in app.button if b.label=='Create PO folder and process files').click().run()
                self.assertFalse(app.exception)
                job=app.session_state['completed_job'];results=job['report']['results']
                skipped=[r for r in results if r['status']=='STEP conversion skipped: assembly unsupported']
                self.assertEqual([r['part'] for r in skipped],['C16210'])
                self.assertIn('referenced component files',skipped[0]['details'])
                self.assertTrue(any(r['part']=='C16231' and r['status']=='Converted STEP' for r in results))
                with ZipFile(job['archive']) as archive:
                    self.assertEqual(archive.read('C16210.sldasm'),b'assembly-with-external-references')
                    self.assertEqual(archive.read('C16211.step'),existing)
                    self.assertIn('C16231.step',archive.namelist())
                    self.assertNotIn('C16210.step',archive.namelist())

    def test_process_po_packages_c_and_m_files_using_real_parser(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'source'
            files={'IDT C16000/C16913.sldprt':b'part','IDT C16000/C16913.slddrw':b'drawing',
                   'IDT M16000/M16915_001.sldprt':b'suffixed-part'}
            for name,data in files.items():
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
            text='PO # 1926\n1 PC C16913 - Machine 1 $0.00 $0.00\n2 PC M16915_001 - Anodize Type II Class 2 3 $0.00 $0.00'
            def uploader(*args,**kwargs):
                return [] if kwargs.get('accept_multiple_files') else io.BytesIO(b'synthetic-process-po')
            with patch('streamlit.file_uploader',side_effect=uploader),patch('core.PdfReader') as reader:
                reader.return_value.pages=[SimpleNamespace(extract_text=lambda **kwargs:text)]
                app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'),default_timeout=15).run()
                next(c for c in app.checkbox if c.label=='Convert copied part files to STEP locally').uncheck()
                app.sidebar.text_input[0].set_value(str(root))
                app.sidebar.text_input[1].set_value(str(Path(temp)/'output'))
                next(b for b in app.button if b.label=='Search source folder').click().run()
                next(c for c in app.checkbox if c.label.startswith('I checked')).check().run()
                next(b for b in app.button if b.label=='Create PO folder and process files').click().run()
                self.assertFalse(app.exception)
                job=app.session_state['completed_job']
                self.assertEqual(job['report']['po'],'1926')
                self.assertEqual([(i['part'],i['quantity']) for i in job['report']['items']],
                                 [('C16913','1'),('M16915_001','3')])
                with ZipFile(job['archive']) as archive:
                    self.assertEqual(set(archive.namelist()),{Path(name).name for name in files}|{'purchase-order.pdf','report.json'})

    def test_zip_name_flat_contents_and_download_reset(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'source'
            group = root / 'IDT C13000'
            group.mkdir(parents=True)
            files = {'C13030.sldprt': b'part', 'C13030.slddrw': b'drawing'}
            for name, data in files.items():
                (group / name).write_bytes(data)
            output = Path(temp) / 'output'
            downloads = {}
            exports = []
            upload = io.BytesIO(b'test-po-document')
            upload.getvalue = lambda: b'test-po-document'

            def uploader(*args, **kwargs):
                if args and args[0]=='SolidWorks part files':
                    return []
                if kwargs.get('accept_multiple_files'):
                    return exports
                return upload if st.session_state.get('upload_generation', 0) == 0 else None

            def download(label, data, file_name, **kwargs):
                downloads[label] = file_name
                # AppTest cannot click native download widgets. A button exercises
                # the same registered callback through Streamlit's event handling.
                return st.button(label, on_click=kwargs['on_click'] if callable(kwargs['on_click']) else None)

            with patch('streamlit.file_uploader', side_effect=uploader), patch('core.parse_po', return_value=('1530', [Item(1, '50', 'PC', 'C13030')])), patch('streamlit.download_button', side_effect=download):
                app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py'), default_timeout=15).run()
                automatic = next(c for c in app.checkbox if c.label == 'Convert copied part files to STEP locally')
                if not automatic.disabled:
                    automatic.uncheck()
                app.sidebar.text_input[0].set_value(str(root))
                app.sidebar.text_input[1].set_value(str(output))
                next(b for b in app.button if b.label == 'Search source folder').click().run()
                next(c for c in app.checkbox if c.label.startswith('I checked')).check().run()
                next(b for b in app.button if b.label == 'Create PO folder and process files').click().run()
                self.assertFalse(app.exception)
                self.assertEqual(downloads['Download PO files ZIP'], 'PO 1530 Parts.zip')
                saved = app.session_state['completed_job']
                with ZipFile(saved['archive']) as archive:
                    self.assertEqual(set(archive.namelist()), set(files) | {'purchase-order.pdf', 'report.json'})
                    for name, data in files.items():
                        self.assertEqual(archive.read(name), data)
                for name, data in [('C13030.step', b'ISO-10303-21;\nEND-ISO-10303-21;'), ('C13030.pdf', b'%PDF-1.7\nexample')]:
                    value = io.BytesIO(data)
                    value.name = name
                    exports.append(value)
                app.run()
                next(b for b in app.button if b.label == 'Add exports and update ZIP').click().run()
                self.assertFalse(app.exception)
                self.assertFalse(app.error)
                saved = app.session_state['completed_job']
                with ZipFile(saved['archive']) as archive:
                    self.assertIn('C13030.step', archive.namelist())
                    self.assertIn('C13030.pdf', archive.namelist())
                self.assertEqual(sum(r['status'] == 'Added export' for r in saved['report']['results']), 2)
                next(b for b in app.button if b.label == 'Download PO files ZIP').click().run()
                self.assertFalse(app.exception)
                self.assertEqual(app.session_state['upload_generation'], 1)
                for key in ('matches', 'search_key', 'completed_job', 'review_ack'):
                    self.assertNotIn(key, app.session_state)
                self.assertEqual(app.sidebar.text_input[0].value, str(root))
                self.assertEqual(app.sidebar.text_input[1].value, str(output))
                self.assertEqual(downloads['Download last ZIP again'], 'PO 1530 Parts.zip')
                self.assertTrue(Path(saved['archive']).is_file())
                self.assertTrue(any('Ready for the next PO' in message.value for message in app.success))
                app.run()
                self.assertFalse(app.exception)
                self.assertEqual(app.session_state['upload_generation'], 1)


if __name__ == '__main__':
    unittest.main()
