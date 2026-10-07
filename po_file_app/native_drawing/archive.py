"""Independent reader for ZIP-shaped SolidWorks archives observed in sample files.

Recognizes structure rather than using a vendor signature table. Every entry is
bounded, decompressed with an output limit, and checked against its ZIP CRC.
Legacy compound-file drawings and encrypted archives are unsupported.
"""
import struct
import zlib
from pathlib import Path

MAX_FILE = 64 * 1024 * 1024
MAX_ENTRY = 16 * 1024 * 1024
MAX_TOTAL = 64 * 1024 * 1024
CENTRAL = struct.Struct('<4s6H3I5H2I')
END = struct.Struct('<4s4H2IH')


def unswap(raw):
    return bytes((byte >> 4) | ((byte & 15) << 4) for byte in raw)


def read_archive(path):
    path = Path(path)
    if path.stat().st_size > MAX_FILE:
        raise ValueError('Drawing exceeds the 64 MiB native-reader limit.')
    return decode_archive(path.read_bytes())


def decode_archive(data):
    if len(data) > MAX_FILE or len(data) < END.size:
        raise ValueError('Drawing archive size is unsupported.')
    candidates = []
    for pos in range(max(0, len(data) - 65558), len(data) - END.size + 1):
        _, disk, central_disk, count_disk, count, size, offset, comment = END.unpack_from(data, pos)
        if (disk == central_disk == 0 and count == count_disk and 0 < count <= 4096
                and count * CENTRAL.size <= size <= pos and offset + size <= pos
                and pos + END.size + comment <= len(data)):
            candidates.append((pos, count, size, offset))
    results = []
    for candidate in candidates:
        try:
            results.append(_read_directory(data, *candidate))
        except (ValueError, UnicodeError, struct.error, zlib.error):
            continue
    if len(results) != 1:
        raise ValueError('No unique, CRC-valid supported drawing archive was found.')
    return results[0]


def _read_directory(data, end, count, size, offset):
    base = end - size - offset
    cursor = end - size
    signature = data[cursor:cursor + 4]
    local_signature = None
    entries = {}
    ranges = []
    total = 0
    for _ in range(count):
        if cursor + CENTRAL.size > end:
            raise ValueError('Truncated central directory.')
        (sig, made, version, flags, method, mtime, mdate, crc, compressed, expanded,
         name_size, extra_size, comment_size, disk, internal, external, local_offset) = CENTRAL.unpack_from(data, cursor)
        if (sig != signature or version > 20 or disk or flags & 1 or method not in (0, 8)
                or expanded > MAX_ENTRY or not 0 < name_size <= 512):
            raise ValueError('Unsupported archive entry.')
        following = cursor + CENTRAL.size + name_size + extra_size + comment_size
        if following > end:
            raise ValueError('Central entry exceeds directory bounds.')
        raw_name = data[cursor + CENTRAL.size:cursor + CENTRAL.size + name_size]
        # Normal ZIP archives have ordinary UTF-8 names. SolidWorks variants
        # observed here store names with the high and low nibbles exchanged.
        name = (raw_name if signature == b'PK\x01\x02' else unswap(raw_name)).decode('utf-8')
        if name in entries or '\x00' in name:
            raise ValueError('Duplicate or invalid archive name.')
        local = local_offset + base
        if local < base or local + 30 > end - size:
            raise ValueError('Local header outside archive data.')
        current_sig = data[local:local + 4]
        local_signature = local_signature or current_sig
        if current_sig != local_signature:
            raise ValueError('Inconsistent local archive signatures.')
        local_flags, local_method = struct.unpack_from('<HH', data, local + 6)
        local_name_size, local_extra_size = struct.unpack_from('<HH', data, local + 26)
        if local_flags != flags or local_method != method or local_name_size != name_size:
            raise ValueError('Local and central entry descriptions disagree.')
        if data[local + 30:local + 30 + name_size] != raw_name:
            raise ValueError('Local and central filenames disagree.')
        begin = local + 30 + local_name_size + local_extra_size
        finish = begin + compressed
        if finish > end - size or begin < local:
            raise ValueError('Compressed entry outside archive data.')
        if any(local < prior_end and prior_start < finish for prior_start, prior_end in ranges):
            raise ValueError('Archive entries overlap.')
        ranges.append((local, finish))
        total += expanded
        if total > MAX_TOTAL:
            raise ValueError('Expanded archive exceeds its resource limit.')
        payload = data[begin:finish]
        if method == 8:
            decoder = zlib.decompressobj(-15)
            payload = decoder.decompress(payload, expanded + 1)
            if not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
                raise ValueError('Incomplete or oversized deflate stream.')
        if len(payload) != expanded or zlib.crc32(payload) != crc:
            raise ValueError('Archive size or CRC verification failed.')
        entries[name] = payload
        cursor = following
    # The observed SolidWorks variant includes an opaque suffix in the
    # declared directory span. This suffix is not interpreted.
    if cursor > end:
        raise ValueError('Central directory size mismatch.')
    return entries
