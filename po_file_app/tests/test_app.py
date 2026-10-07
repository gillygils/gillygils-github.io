"""Exercise packaging and the download-triggered reset through Streamlit callbacks."""
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import streamlit as st
from streamlit.testing.v1 import AppTest
from core import Item


class AppTests(unittest.TestCase):
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
            upload = io.BytesIO(b'test-po-document')
            upload.getvalue = lambda: b'test-po-document'

            def uploader(*args, **kwargs):
                return upload if st.session_state.get('upload_generation', 0) == 0 else None

            def download(label, data, file_name, **kwargs):
                downloads[label] = file_name
                # AppTest cannot click native download widgets. A button exercises
                # the same registered callback through Streamlit's event handling.
                return st.button(label, on_click=kwargs['on_click'] if callable(kwargs['on_click']) else None)

            with patch('streamlit.file_uploader', side_effect=uploader), patch('core.parse_po', return_value=('1530', [Item(1, '50', 'PC', 'C13030')])), patch('streamlit.download_button', side_effect=download):
                app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py')).run()
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
