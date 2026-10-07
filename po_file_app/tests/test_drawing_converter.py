import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject
from drawing_converter.backend import validate_pdf, convert_drawing


def make_pdf(path, pages=1, content=True):
    writer=PdfWriter()
    for _ in range(pages):
        page=writer.add_blank_page(width=792,height=612)
        if content:
            stream=DecodedStreamObject();stream.set_data(b'q 0 0 m 1 1 l S Q')
            page[NameObject('/Contents')]=writer._add_object(stream)
    with Path(path).open('wb') as file:writer.write(file)


class DrawingTests(unittest.TestCase):
    def test_pdf_must_have_matching_pages_and_content(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'drawing.pdf'
            make_pdf(path,2)
            self.assertEqual(validate_pdf(path,2),2)
            with self.assertRaises(RuntimeError):validate_pdf(path,1)
            make_pdf(path,1,False)
            with self.assertRaisesRegex(RuntimeError,'empty page'):validate_pdf(path,1)
            with self.assertRaises(RuntimeError):validate_pdf(path,True)

    def test_successful_worker_output_published_only_after_validation(self):
        with tempfile.TemporaryDirectory() as temp:
            source=Path(temp)/'C15999.slddrw';source.write_bytes(b'native')
            output=Path(temp)/'C15999.pdf'
            def worker(command,**kwargs):
                self.assertEqual(Path(command[2]),source)
                make_pdf(command[3],2)
                return subprocess.CompletedProcess(command,0,json.dumps({'success':True,'sheets':2}),'')
            with patch('drawing_converter.backend.drawing_capability',return_value=('{control}','available')),patch('drawing_converter.backend.subprocess.run',side_effect=worker):
                report=convert_drawing(source,output)
            self.assertEqual(report['pages'],2)
            self.assertEqual(validate_pdf(output,2),2)
            self.assertEqual(source.read_bytes(),b'native')
            with self.assertRaises(FileExistsError):convert_drawing(source,output)

    def test_worker_page_mismatch_not_published(self):
        with tempfile.TemporaryDirectory() as temp:
            source=Path(temp)/'C15999.slddrw';source.write_bytes(b'native')
            output=Path(temp)/'C15999.pdf'
            def worker(command,**kwargs):
                make_pdf(command[3],1)
                return subprocess.CompletedProcess(command,0,json.dumps({'success':True,'sheets':2}),'')
            with patch('drawing_converter.backend.drawing_capability',return_value=('{control}','available')),patch('drawing_converter.backend.subprocess.run',side_effect=worker):
                with self.assertRaisesRegex(RuntimeError,'page count'):convert_drawing(source,output)
            self.assertEqual(set(Path(temp).iterdir()),{source})

    def test_timeout_leaves_no_pdf(self):
        with tempfile.TemporaryDirectory() as temp:
            source=Path(temp)/'C15999.slddrw';source.write_bytes(b'native')
            output=Path(temp)/'C15999.pdf'
            with patch('drawing_converter.backend.drawing_capability',return_value=('{control}','available')),patch('drawing_converter.backend.subprocess.run',side_effect=subprocess.TimeoutExpired('worker',150)):
                with self.assertRaisesRegex(RuntimeError,'timed out'):convert_drawing(source,output)
            self.assertEqual(set(Path(temp).iterdir()),{source})

    def test_app_packages_pdf_from_simulated_print_worker(self):
        from streamlit.testing.v1 import AppTest
        from core import Item
        from zipfile import ZipFile
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'source';folder=root/'IDT C15000';folder.mkdir(parents=True)
            source=folder/'C15999.slddrw';source.write_bytes(b'native')
            upload=io.BytesIO(b'PO')
            def uploader(*args,**kwargs):return [] if kwargs.get('accept_multiple_files') else upload
            def worker(command,**kwargs):
                self.assertEqual(Path(command[2]),source)
                make_pdf(command[3],2)
                return subprocess.CompletedProcess(command,0,json.dumps({'success':True,'sheets':2}),'')
            with patch('streamlit.file_uploader',side_effect=uploader),patch('core.parse_po',return_value=('1530',[Item(1,'1','PC','C15999')])),patch('drawing_converter.backend.drawing_capability',return_value=('{control}','available')),patch('drawing_converter.backend.subprocess.run',side_effect=worker):
                app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py')).run()
                app.sidebar.text_input[0].set_value(str(root));app.sidebar.text_input[1].set_value(str(Path(temp)/'output'))
                next(c for c in app.checkbox if c.label=='Automatically print drawings to PDF (experimental)').check()
                next(b for b in app.button if b.label=='Search source folder').click().run()
                next(c for c in app.checkbox if c.label.startswith('I checked')).check().run()
                next(b for b in app.button if b.label=='Create PO folder and process files').click().run()
                self.assertFalse(app.exception)
                self.assertFalse(app.error)
                result=app.session_state['completed_job']
                self.assertTrue(any(r['status']=='Printed PDF' for r in result['report']['results']))
                with ZipFile(result['archive']) as archive:
                    self.assertIn('C15999.pdf',archive.namelist())
                    self.assertIn('C15999.slddrw',archive.namelist())

    def test_app_stops_repeating_failed_printing_and_keeps_originals(self):
        from streamlit.testing.v1 import AppTest
        from core import Item
        from zipfile import ZipFile
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'source';folder=root/'IDT C15000';folder.mkdir(parents=True)
            source=folder/'C15999.slddrw';source.write_bytes(b'native')
            (folder/'C15998.slddrw').write_bytes(b'native2')
            calls=[]
            upload=io.BytesIO(b'PO')
            def uploader(*args,**kwargs):return [] if kwargs.get('accept_multiple_files') else upload
            def worker(command,**kwargs):
                calls.append(command)
                raise subprocess.TimeoutExpired('worker',55)
            with patch('streamlit.file_uploader',side_effect=uploader),patch('core.parse_po',return_value=('1530',[Item(1,'1','PC','C15999'),Item(2,'1','PC','C15998')])),patch('drawing_converter.backend.drawing_capability',return_value=('{control}','available')),patch('drawing_converter.backend.subprocess.run',side_effect=worker):
                app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py')).run()
                app.sidebar.text_input[0].set_value(str(root));app.sidebar.text_input[1].set_value(str(Path(temp)/'output'))
                next(c for c in app.checkbox if c.label=='Automatically print drawings to PDF (experimental)').check()
                next(b for b in app.button if b.label=='Search source folder').click().run()
                next(c for c in app.checkbox if c.label.startswith('I checked')).check().run()
                next(b for b in app.button if b.label=='Create PO folder and process files').click().run()
                self.assertFalse(app.exception)
                self.assertEqual(len(calls),1)
                result=app.session_state['completed_job']
                statuses=[r['status'] for r in result['report']['results']]
                self.assertTrue(any(s.startswith('PDF printing failed') for s in statuses))
                self.assertTrue(any(s.startswith('PDF printing skipped') for s in statuses))
                with ZipFile(result['archive']) as archive:
                    self.assertIn('C15999.slddrw',archive.namelist())
                    self.assertIn('C15998.slddrw',archive.namelist())
                    self.assertNotIn('C15999.pdf',archive.namelist())
                    self.assertNotIn('C15998.pdf',archive.namelist())
                    self.assertIn('purchase-order.pdf',archive.namelist())
