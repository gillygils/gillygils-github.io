"""Experimental observed-record recovery; incomplete, not a stream decoder."""
import math
import re
import struct
STRING = b'\xff\xfe\xff'


def read_string(data, offset):
    if data[offset:offset+3] != STRING or offset+4 > len(data):
        raise ValueError('Missing Unicode string framing.')
    count, start = data[offset+3], offset+4
    if count == 255:
        if start+2 > len(data):
            raise ValueError('Truncated string length.')
        count = struct.unpack_from('<H', data, start)[0]
        start += 2
    end = start+2*count
    if count > 4096 or end > len(data):
        raise ValueError('String exceeds stream bounds.')
    return data[start:end].decode('utf-16le'), end


def finite(values, limit=2):
    return all(math.isfinite(v) and abs(v) <= limit for v in values)


def read_display(data):
    lines, texts, strings = [], [], []
    for m in re.finditer(re.escape(STRING), data):
        try:
            text, end = read_string(data, m.start())
            strings.append({'offset': m.start(), 'text': text})
        except (ValueError, UnicodeError):
            continue
    fonts = [m.start() for m in re.finditer(re.escape(struct.pack('<II',126,10)),data)]
    for m in re.finditer(re.escape(struct.pack('<II',80,4)),data):
        p = m.start()
        if p+57 > len(data):
            continue
        coords = struct.unpack_from('<6d',data,p+8)
        if (not finite(coords) or abs(coords[2]) > 1e-6 or abs(coords[5]) > 1e-6
                or data[p+56] != 0 or coords[:3] == coords[3:]):
            continue
        lines.append({'offset':p,'start':list(coords[:3]),'end':list(coords[3:])})
    for m in re.finditer(re.escape(struct.pack('<I',18)),data):
        p = m.start()-4
        if p < 0 or p+52 > len(data) or data[p+48:p+51] != STRING:
            continue
        try:
            text,end = read_string(data,p+48)
            origin = struct.unpack_from('<3d',data,p+8)
            rotations = struct.unpack_from('<2d',data,p+32)
            if not text or not finite(origin) or end+6 > len(data):
                continue
            flags,count = struct.unpack_from('<HI',data,end)
            if flags != 1 or count != len(text) or end+6+4*count > len(data):
                continue
            advances = struct.unpack_from('<'+'f'*count,data,end+6)
            if not finite(advances,.1) or any(v < 0 for v in advances):
                continue
            font = next((f for f in reversed(fonts) if f < p),None)
            height = struct.unpack_from('<d',data,font+28)[0] if font is not None else None
            family = read_string(data,font+40)[0] if font is not None else None
            supported = (finite(rotations,1e-12) and abs(origin[2]) < 1e-6
                         and height is not None and math.isfinite(height) and .00002 <= height <= .02)
            texts.append({'offset':p,'text':text,'origin':list(origin),'height':height,
                          'font':family,'advances':list(advances),'renderable':supported})
        except (ValueError,UnicodeError,struct.error):
            continue
    return {'lines':lines,'texts':texts,'strings':strings,'stream_bytes':len(data),'complete':False}
