"""Independently recover bounded zlib blocks from saved part partitions.

Observed partitions have a 20-byte prefix and size-framed compression blocks.
Multiple Parasolid streams can include deltas: extracting them is not equivalent
to reconstructing the current body. Opaque gaps and unparsed tails are reported.
"""
import hashlib
import re
import struct
import zlib

MAX_BLOCK = 16 * 1024 * 1024
MAX_TOTAL = 64 * 1024 * 1024
MAX_CANDIDATES = 4096


def recover_blocks(data):
    cursor, total, attempts = 20, 0, 0
    blocks, gaps = [], []
    for match in re.finditer(b'\x78[\x01\x5e\x9c\xda]', data):
        start = match.start() - 8
        if start < cursor:
            continue
        attempts += 1
        if attempts > MAX_CANDIDATES:
            raise ValueError('Too many candidate partition blocks.')
        expected, compressed = struct.unpack_from('<II', data, start)
        if not 0 < expected <= MAX_BLOCK or not 0 < compressed <= len(data) - start - 8:
            continue
        encoded = data[start + 8:start + 8 + compressed]
        decoder = zlib.decompressobj()
        try:
            payload = decoder.decompress(encoded, expected + 1)
        except zlib.error:
            continue
        if (not decoder.eof or decoder.unused_data or decoder.unconsumed_tail
                or len(payload) != expected):
            continue
        if start > cursor:
            gaps.append({'offset': cursor, 'bytes': start - cursor})
        total += len(payload)
        if total > MAX_TOTAL:
            raise ValueError('Recovered partition exceeds the expansion limit.')
        blocks.append({'offset': start, 'compressed_bytes': compressed,
                       'expanded_bytes': len(payload), 'sha256': hashlib.sha256(payload).hexdigest(),
                       'data': payload})
        cursor = start + 8 + compressed
    return {'blocks': blocks, 'opaque_gaps': gaps, 'unparsed_tail_bytes': len(data) - min(cursor, len(data))}


def parasolid_header(data):
    if len(data) < 10 or data[:2] != b'PS' or data[2:4] != b'\x00\x00':
        return None
    text_length = struct.unpack_from('>H', data, 4)[0]
    end = 6 + text_length
    if end + 4 > len(data):
        return None
    schema_length = struct.unpack_from('>I', data, end)[0]
    if not 0 < schema_length <= 512 or end + 4 + schema_length > len(data):
        return None
    try:
        description = data[6:end].decode('ascii')
        schema = data[end + 4:end + 4 + schema_length].decode('ascii')
    except UnicodeError:
        return None
    if 'TRANSMIT FILE' not in description or not schema.startswith('SCH_'):
        return None
    return {'description': description, 'schema': schema,
            'kind': 'deltas' if '(deltas)' in description else
                    'partition' if '(partition)' in description else 'unknown',
            'header_bytes': end + 4 + schema_length}
