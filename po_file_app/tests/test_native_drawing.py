import io
import struct
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from native_drawing.archive import decode_archive
from native_drawing.display import read_display, read_string
from native_drawing.draft import write_draft
from pypdf import PdfReader


def archive(payload=b'example', transformed=False):
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr('Contents/DisplayLists',payload)
    data=bytearray(out.getvalue())
    if transformed:
        central=data.index(b'PK\x01\x02')
        for pos,length_offset in [(0,26),(central,28)]:
            count=struct.unpack_from('<H',data,pos+length_offset)[0]
            start=pos+(30 if pos==0 else 46)
            data[start:start+count]=bytes((b>>4)|((b&15)<<4) for b in data[start:start+count])
        data[:4]=b'ABCD'
        data[central:central+4]=b'EFGH'
        end=data.index(b'PK\x05\x06')
        data[end:end+4]=b'IJKL'
        data.extend(b'opaque sample suffix')
    return bytes(data)


class NativeDrawingTests(unittest.TestCase):
    def test_reads_crc_verified_zip_and_nibble_variant_with_suffix(self):
        for transformed in [False,True]:
            self.assertEqual(decode_archive(archive(transformed=transformed)),
                             {'Contents/DisplayLists':b'example'})

    def test_crc_corruption_and_truncation_are_rejected(self):
        data=bytearray(archive(transformed=True))
        central=data.index(b'EFGH')
        data[central+16]^=1
        with self.assertRaises(ValueError):decode_archive(data)
        with self.assertRaises(ValueError):decode_archive(archive()[:40])

    def test_declared_size_cannot_allow_deflate_to_expand_unbounded(self):
        data=bytearray(archive(b'X'*100000))
        central=data.index(b'PK\x01\x02')
        struct.pack_into('<I',data,central+24,1)
        with self.assertRaises(ValueError):decode_archive(data)

    def test_local_name_must_match_central_directory(self):
        data=bytearray(archive())
        data[30]^=1
        with self.assertRaises(ValueError):decode_archive(data)

    def test_extended_unicode_and_truncated_strings(self):
        text='dimension '*30
        data=b'\xff\xfe\xff\xff'+struct.pack('<H',len(text))+text.encode('utf-16le')
        self.assertEqual(read_string(data,0),(text,len(data)))
        with self.assertRaises(ValueError):read_string(data[:-1],0)

    def test_line_candidates_require_finite_planar_coordinates_and_bounds(self):
        line=lambda points:struct.pack('<II6dB',80,4,*points,0)
        good=line([0,0,0,.1,.2,0])
        bad=line([0,0,0,float('nan'),.2,0])+line([0,0,0,.1,.2,.1])
        display=read_display(good+bad+good[:25])
        self.assertEqual(len(display['lines']),1)
        self.assertFalse(display['complete'])

    def test_draft_has_visible_limitations_and_vector_paths_without_images(self):
        display=read_display(struct.pack('<II6dB',80,4,0,0,0,.1,.2,0,0))
        with tempfile.TemporaryDirectory() as temp:
            output=Path(temp)/'draft.pdf'
            write_draft(display,output)
            page=PdfReader(output).pages[0]
            self.assertIn('NOT FOR MANUFACTURING',page.extract_text())
            self.assertIn(b' l S',page.get_contents().get_data())
            self.assertNotIn('/XObject',page['/Resources'])
            with self.assertRaises(FileExistsError):write_draft(display,output)
