import struct
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from native_part.entities import Cursor, DecodeError, read_schema, decode_prefix


class NativeEntityTests(unittest.TestCase):
    def test_compact_and_extended_reference_identifiers(self):
        cursor=Cursor(struct.pack('>hhhh',1,5,-4,2))
        self.assertEqual(cursor.pointer(),0)
        self.assertEqual(cursor.pointer(),4)
        self.assertEqual(cursor.pointer(),65537)
        with self.assertRaises(DecodeError):cursor.pointer()

    def test_scalars_reject_nonfinite_and_truncated_values(self):
        with self.assertRaises(DecodeError):Cursor(b'\0').value('d')
        with self.assertRaises(DecodeError):Cursor(struct.pack('>d',float('nan'))).value('f')
        with self.assertRaises(DecodeError):Cursor(b'').value('unknown')

    def test_schema_patches_are_counted_and_bounded(self):
        schema=[('body','p',1),('flag','u',1)]
        self.assertEqual(read_schema(Cursor(b'\xff'),schema),schema)
        self.assertEqual(read_schema(Cursor(b'\x01CDZ'),schema),schema[:1])
        with self.assertRaises(DecodeError):read_schema(Cursor(b'\x02CZ'),schema)
        with self.assertRaises(DecodeError):read_schema(Cursor(b'\x03CCCZ'),schema)
        with self.assertRaises(DecodeError):read_schema(Cursor(b'\x01C'),schema)

    def test_unknown_schema_does_not_claim_geometry_or_completion(self):
        report=decode_prefix(b'not Parasolid')
        self.assertFalse(report['complete'])
        self.assertFalse(report['geometry_reconstructed'])
        self.assertIn('Unsupported',report['stopped_reason'])
