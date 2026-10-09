"""Authored DWG bridge fixtures; no customer drawings or external tools."""
import io
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ezdxf
from pypdf import PdfReader
from native_drawing.dwg_input import vector_pdf, export_dwg
from native_drawing.exports import NOTICE,write_pdf,write_dxf
from drawings import convert_upload


def authored_doc():
    doc=ezdxf.new('R2000');doc.units=4
    m=doc.modelspace()
    m.add_line((-10,-5),(30,10))
    m.add_circle((0,0),3)
    m.add_lwpolyline([(0,0),(10,0),(10,10)])
    m.add_text('Authored drawing',dxfattribs={'height':2,'insert':(0,12)})
    block=doc.blocks.new('Authored block');block.add_line((0,0),(1,1))
    m.add_blockref('Authored block',(5,5))
    return doc


class DwgInputTests(unittest.TestCase):
    def test_pdf_keeps_vector_curves_text_and_block_geometry(self):
        with tempfile.TemporaryDirectory() as temp:
            output=Path(temp)/'draft.pdf'
            result=vector_pdf(authored_doc(),output)
            pdf=PdfReader(output);page=pdf.pages[0]
            self.assertEqual(len(pdf.pages),1)
            self.assertEqual(len(page.images),0)
            self.assertIn(NOTICE,page.extract_text())
            self.assertIn(b' c',page.get_contents().get_data())
            self.assertEqual(result['entity_types']['INSERT'],1)
            self.assertTrue(result['fitted_to_page'])
            self.assertAlmostEqual(float(page.mediabox.width),420*72/25.4,places=3)

    def test_empty_or_unsupported_drawing_is_not_published(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError,'No visible'):
                vector_pdf(ezdxf.new(),Path(temp)/'empty.pdf')
            doc=authored_doc();image=doc.add_image_def('unavailable-private-image.png',(2,2))
            doc.blocks.get('Authored block').add_image(image,(0,0),(1,1))
            # Even a nested image must be rejected before external file paths
            # can be read or replaced with a missing-image placeholder.
            with self.assertRaisesRegex(ValueError,'Raster or external'):
                vector_pdf(doc,Path(temp)/'raster.pdf')

    def test_tool_bridge_packages_only_verified_outputs_and_keeps_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'Authored.dwg';source.write_bytes(b'AC1015 authored header')
            def run(command,**kwargs):
                if '--version' in command:return subprocess.CompletedProcess(command,0,'dwg2dxf 0.14','')
                authored_doc().saveas(command[command.index('-o')+1])
                return subprocess.CompletedProcess(command,0,'','Authored decoder warning')
            value=io.BytesIO(source.read_bytes());value.name=source.name;value.size=len(value.getvalue())
            with patch('native_drawing.dwg_input.find_tools',return_value={'dwg2dxf':'test-dwg2dxf'}),patch('native_drawing.dwg_input.subprocess.run',side_effect=run):
                result=convert_upload(value,converter=lambda s,o,**kwargs:export_dwg(s,o))
            self.assertEqual(source.read_bytes(),value.getvalue())
            with zipfile.ZipFile(io.BytesIO(result['zip'])) as archive:
                self.assertEqual(set(archive.namelist()),{'Authored-EXPERIMENTAL.pdf','Authored-EXPERIMENTAL.dxf','drawing-report.json'})
                report=json.loads(archive.read('drawing-report.json'))
                self.assertEqual(report['implementation'],'local-libredwg-input')
                self.assertIn('Authored decoder warning',report['decoder_warnings'])
            with self.assertRaisesRegex(ValueError,'without a matching part'):
                convert_upload(value,dwg=True)

    def test_missing_dwg_or_invalid_decode_leaves_no_output_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'Authored.dwg';source.write_bytes(b'AC1015 authored')
            output=root/'output'
            with patch('native_drawing.dwg_input.find_tools',return_value={'dwg2dxf':'test-dwg2dxf'}),patch('native_drawing.dwg_input.subprocess.run',return_value=subprocess.CompletedProcess([],1,'','failed')):
                with self.assertRaisesRegex(ValueError,'LibreDWG'):export_dwg(source,output)
            self.assertFalse(output.exists())

    def test_native_txt_font_is_substituted_visibly_and_dxf_retains_font_reference(self):
        scene={'size_m':[.4318,.2794],'primitives':[{'kind':'text','style':'CONTINUOUS',
                'origin':[.05,.05,0],'angle':0,'text':'TXT','advances':[.003,.003,0],
                'font':{'family':'TXT','em_points':10,'width':1,'flags':128}}]}
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            result=write_pdf(scene,[],root/'text.pdf');write_dxf(scene,[],root/'text.dxf')
            self.assertTrue(any('Courier' in warning for warning in result['warnings']))
            self.assertEqual(ezdxf.readfile(root/'text.dxf').styles.get('DrawingTxt').dxf.font,'txt.shx')
            self.assertIn('T',PdfReader(root/'text.pdf').pages[0].extract_text())


if __name__=='__main__':unittest.main()
