import io
import json
import struct
import sys
import tempfile
import unittest
import zipfile
import zlib
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from native_part.partition import recover_blocks, parasolid_header
from native_part.__main__ import inspect


def xb(kind='partition'):
    description=f': TRANSMIT FILE ({kind}) created by modeller version 3501210'.encode()
    schema=b'SCH_3501210_35102_13006'
    return b'PS\x00\x00'+struct.pack('>H',len(description))+description+struct.pack('>I',len(schema))+schema+b'opaque entities'


def block(payload):
    encoded=zlib.compress(payload)
    return struct.pack('<II',len(payload),len(encoded))+encoded


class NativePartTests(unittest.TestCase):
    def test_recovers_base_and_delta_without_merging_them(self):
        base,delta=xb(),xb('deltas')
        stream=b'prefix'.ljust(20,b'\0')+block(base)+b'opaque gap'+block(delta)
        result=recover_blocks(stream)
        self.assertEqual([b['data'] for b in result['blocks']],[base,delta])
        self.assertEqual(result['opaque_gaps'][0]['bytes'],len(b'opaque gap'))
        self.assertEqual(result['unparsed_tail_bytes'],0)
        self.assertEqual(parasolid_header(base)['kind'],'partition')
        self.assertEqual(parasolid_header(delta)['kind'],'deltas')

    def test_short_corrupt_and_size_mismatched_blocks_not_accepted(self):
        self.assertEqual(recover_blocks(b'short')['blocks'],[])
        framed=bytearray(block(xb()))
        framed[-1]^=1
        self.assertEqual(recover_blocks(b'0'*20+framed)['blocks'],[])
        framed=bytearray(block(xb()))
        struct.pack_into('<I',framed,0,1)
        self.assertEqual(recover_blocks(b'0'*20+framed)['blocks'],[])
        self.assertEqual(recover_blocks(b'0'*20+block(xb())[:-1])['blocks'],[])

    def test_header_requires_complete_valid_string_lengths(self):
        self.assertIsNone(parasolid_header(b'PS\x00\x00\xff\xffshort'))
        self.assertIsNone(parasolid_header(xb()[:20]))
        self.assertIsNone(parasolid_header(b'not parasolid'))

    def test_extracts_configuration_identity_without_claiming_step_support(self):
        with tempfile.TemporaryDirectory() as temp:
            source=Path(temp)/'sample.sldprt'
            out=Path(temp)/'result'
            payload=b'0'*20+block(xb())+block(xb('deltas'))
            with zipfile.ZipFile(source,'w',compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr('Contents/Config-2-Partition',payload)
            original=source.read_bytes()
            report=inspect(source,out)
            self.assertFalse(report['step_conversion_supported'])
            self.assertFalse(report['current_body_reconstructed'])
            self.assertEqual(report['partitions'][0]['configuration_archive_id'],'2')
            self.assertEqual((out/'config-2-block-000.x_b').read_bytes(),xb())
            self.assertEqual((out/'config-2-block-001.x_b').read_bytes(),xb('deltas'))
            self.assertFalse(list(out.glob('*.step')))
            self.assertEqual(source.read_bytes(),original)
            self.assertEqual(json.loads((out/'inspection.json').read_text())['step_conversion_supported'],False)
            with self.assertRaises(FileExistsError):inspect(source,out)

    def test_missing_geometry_leaves_no_output_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            source=Path(temp)/'sample.sldprt'
            out=Path(temp)/'result'
            with zipfile.ZipFile(source,'w') as archive:
                archive.writestr('Contents/Definition',b'metadata')
            with self.assertRaisesRegex(ValueError,'No supported'):inspect(source,out)
            self.assertFalse(out.exists())
