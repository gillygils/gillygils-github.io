"""Independent diagnostic reader; NOT a SolidWorks-to-STEP converter.

Finds standard zlib streams by signature, validates completed decompression,
and inventories archive-name records observed in supplied sample files.
No Convert3D implementation or decoding tables are used.
"""
import argparse
import hashlib
import json
import re
import struct
import zlib
from pathlib import Path

MAX_FILE = 64 * 1024 * 1024
MAX_STREAM = 8 * 1024 * 1024
MAX_TOTAL = 32 * 1024 * 1024
MAX_ATTEMPTS = 4096


def archive_names(data):
    """Inspect candidate local-record headers; names are diagnostic only.

    The samples have ZIP-like local headers without normal ZIP signatures.
    Name bytes have swapped high/low nibbles. Payload framing and size
    transformations remain unsupported; this does not extract those entries.
    """
    found = []
    header = struct.Struct('<HHHHHIIIHH')
    for match in re.finditer(b'\x14\x00\x06\x00\x08\x00', data):
        offset = match.start()
        if offset + header.size > len(data):
            continue
        fields = header.unpack_from(data, offset)
        name_length = fields[-2]
        if not 1 <= name_length <= 512:
            continue
        start = offset + header.size
        raw = data[start:start + name_length]
        if len(raw) != name_length:
            continue
        decoded = bytes((byte >> 4) | ((byte & 15) << 4) for byte in raw)
        if not all(32 <= byte < 127 for byte in decoded):
            continue
        found.append({'header_offset': offset, 'name': decoded.decode('ascii')})
    return found


def recover_zlib(data):
    recovered = []
    total = 0
    attempts = 0
    cursor = 0
    for match in re.finditer(b'\x78[\x01\x5e\x9c\xda]', data):
        offset = match.start()
        if offset < cursor:
            continue
        attempts += 1
        if attempts > MAX_ATTEMPTS:
            raise ValueError('Too many candidate streams; inspection limit reached.')
        decoder = zlib.decompressobj()
        try:
            payload = decoder.decompress(data[offset:], MAX_STREAM + 1)
        except zlib.error:
            continue
        if len(payload) > MAX_STREAM:
            raise ValueError('A decompressed stream exceeds the inspection size limit.')
        if not decoder.eof or not payload:
            continue
        consumed = len(data) - offset - len(decoder.unused_data)
        cursor = offset + consumed
        total += len(payload)
        if total > MAX_TOTAL:
            raise ValueError('Recovered data exceeds the total inspection size limit.')
        kind = 'parasolid_binary' if payload.startswith(b'PS\x00\x00') else 'unknown'
        if payload.startswith(b'\x89PNG\r\n\x1a\n'):
            kind = 'png_preview'
        if payload.startswith(b'%PDF-'):
            kind = 'pdf'
        recovered.append({'offset': offset, 'compressed_bytes': consumed,
                          'size': len(payload), 'kind': kind, 'data': payload})
    return recovered


def inspect_file(path):
    path = Path(path)
    if path.stat().st_size > MAX_FILE:
        raise ValueError('File exceeds the 64 MiB experimental inspection limit.')
    data = path.read_bytes()
    streams = recover_zlib(data)
    report = {'file': path.name, 'size': len(data),
              'sha256': hashlib.sha256(data).hexdigest(),
              'archive_names': archive_names(data),
              'recovered_streams': [{k: v for k, v in stream.items() if k != 'data'} for stream in streams],
              'step_conversion_supported': False,
              'limitations': ['Archive payload decoding is incomplete.',
                              'Recovered Parasolid streams may contain only metadata or empty partitions.',
                              'Geometry topology, units and configurations are not decoded or validated.',
                              'No STEP or drawing PDF is generated.']}
    return report, streams


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file', type=Path)
    parser.add_argument('--output', type=Path, required=True,
                        help='New output directory; an existing directory is never overwritten.')
    args = parser.parse_args()
    report, streams = inspect_file(args.file)
    args.output.mkdir(parents=True, exist_ok=False)
    for index, stream in enumerate(streams):
        extension = {'parasolid_binary': '.x_b', 'png_preview': '.png', 'pdf': '.pdf'}.get(stream['kind'], '.bin')
        (args.output / f'stream-{index:03d}{extension}').write_bytes(stream['data'])
    (args.output / 'inspection.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
