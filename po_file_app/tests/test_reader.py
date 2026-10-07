import sys
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from experimental.sld_reader import recover_zlib, archive_names


class ReaderTests(unittest.TestCase):
    def test_valid_streams_and_truncated_stream(self):
        payload = b'PS\x00\x00' + b'schema-only' * 10
        compressed = zlib.compress(payload)
        streams = recover_zlib(b'header' + compressed + b'trailer')
        self.assertEqual(len(streams), 1)
        self.assertEqual(streams[0]['data'], payload)
        self.assertEqual(streams[0]['kind'], 'parasolid_binary')
        self.assertEqual(streams[0]['compressed_bytes'], len(compressed))
        self.assertEqual(recover_zlib(compressed[:-3]), [])

    def test_decompression_size_limit(self):
        with patch('experimental.sld_reader.MAX_STREAM', 32):
            with self.assertRaises(ValueError): recover_zlib(zlib.compress(b'A' * 1000))

    def test_archive_name_inventory(self):
        import struct
        name = b'Contents/Config-0'
        encoded = bytes((b >> 4) | ((b & 15) << 4) for b in name)
        data = struct.pack('<HHHHHIIIHH', 20, 6, 8, 0, 0, 0, 10, 20, len(name), 0) + encoded
        self.assertEqual(archive_names(data), [{'header_offset': 0, 'name': name.decode()}])
        self.assertEqual(archive_names(data[:-5]), [])
