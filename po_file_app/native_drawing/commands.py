"""Sequential reading of the display command layouts observed in sample drawings.

Record sizes describe in-memory structures, not serialized byte lengths.
Unknown commands stop decoding rather than searching past a state change.
Document metadata remains experimental; decoding commands alone is not proof
of drawing fidelity.
"""
import math
import struct
from .display import read_string

MAX_COMMANDS = 20000


class Commands:
    def __init__(self, data):
        self.data, self.offset = data, 0
        self.primitives = []
        self.font, self.style, self.count = None, 'CONTINUOUS', 0

    def take(self, fmt):
        size = struct.calcsize('<' + fmt)
        if self.offset + size > len(self.data):
            raise ValueError(f'Truncated display command at {self.offset}.')
        values = struct.unpack_from('<' + fmt, self.data, self.offset)
        self.offset += size
        if any(isinstance(v, float) and not math.isfinite(v) for v in values):
            raise ValueError('Non-finite display command.')
        return values[0] if len(values) == 1 else values

    def string(self):
        try:
            text, self.offset = read_string(self.data, self.offset)
        except ValueError as exc:
            raise ValueError(f'{exc} At display byte {self.offset}.') from exc
        return text

    def points(self, count):
        if not 1 <= count <= MAX_COMMANDS:
            raise ValueError('Display point count exceeds limits.')
        points = [list(self.take('3d')) for _ in range(count)]
        if any(abs(v) > 10 for point in points for v in point):
            raise ValueError('Unsupported display coordinate extent.')
        return points

    def add(self, kind, **fields):
        self.primitives.append({'kind': kind, 'style': self.style, **fields})

    def read(self, count, depth=0):
        if not 0 <= count <= MAX_COMMANDS or depth > 4:
            raise ValueError('Display count or nesting exceeds limits.')
        for _ in range(count):
            self.count += 1
            if self.count > MAX_COMMANDS:
                raise ValueError('Too many display commands.')
            start = self.offset
            size, kind = self.take('2I')
            if kind == 1 and size == 56:
                origin = self.points(1)[0]
                marker, flags = self.take('2I')
                if marker != 2 or flags != 0:
                    raise ValueError('Unsupported drawing point marker or flags.')
                self.add('point', origin=origin, marker=marker)
            elif kind == 4 and size == 80:
                a, b = self.points(2)
                if self.take('B') != 0:
                    raise ValueError('Unsupported line flags.')
                self.add('line', start=a, end=b)
            elif kind in (2, 101) and size == 128:
                a, b, center, normal = self.points(4)
                flags = self.take('I')
                if flags != 0 and not (flags == 1 and a == b):
                    raise ValueError('Unsupported arc flags.')
                self.add('arc', start=a, end=b, center=center, normal=normal)
            elif kind == 6:
                mode, vertices = self.take('2I')
                if mode != 1 or size != 48 + 24 * vertices:
                    raise ValueError('Unsupported filled polygon layout.')
                self.add('polygon', points=self.points(vertices))
            elif kind == 5:
                vertices = self.take('I')
                if vertices < 2 or size != 48 + 24 * vertices:
                    raise ValueError('Unsupported drawing polyline array.')
                points = self.points(vertices)
                if self.take('I') != 0:
                    raise ValueError('Unsupported drawing polyline flags.')
                # Successive vertices form a strip. Earlier examples repeated
                # shared endpoints, which made a strip look like line pairs.
                self.add('polyline',points=points)
            elif kind == 9 and size == 60:
                self.take('4I'); self.take('H'); self.take('f'); self.take('I'); self.take('Q')
            elif kind == 12 and size in (70, 72, 78):
                self.take('I'); self.take('H'); self.take('f'); self.take('Q')
                self.style = self.string()
                if self.style not in ('CONTINUOUS', 'CENTER', 'PHANTOM'):
                    raise ValueError('Unsupported drawing line style: ' + self.style)
            elif kind == 10 and 98 <= size <= 8290:
                height, angle = self.take('2d')
                style, spacing, flags = self.take('I'), self.take('d'), self.take('I')
                family = self.string()
                if size != 98 + 2 * len(family):
                    raise ValueError('Unsupported font record size.')
                width, slant = self.take('2d')
                logical = struct.unpack_from('<i', self.data, start + 16)[0]
                em_points = logical if height == -1 else height * 72 / .0254 * 4 / 3
                if not 0 < em_points <= 1000 or not 0 < width <= 10:
                    raise ValueError('Unsupported font size or stretch.')
                self.font = {'family': family, 'em_points': em_points, 'width': width,
                             'flags': flags, 'spacing': spacing, 'style': style,
                             'slant': slant, 'legacy': height == -1,
                             'angle': angle if height != -1 else 0}
            elif kind == 18:
                origin = self.points(1)[0]
                flags, angle, reserved = self.take('I'), self.take('d'), self.take('I')
                text = self.string()
                version = self.take('H')
                vertices = self.take('I') if version == 1 else 0
                single_glyph = version == 0 and vertices == 0 and len(text) == 1
                if ((not single_glyph and (version != 1 or vertices != len(text)))
                        or vertices > 4096 or self.font is None):
                    raise ValueError('Unsupported text framing or missing font.')
                # A single glyph has no relative glyph positions to recover.
                advances = [0.] if single_glyph else [self.take('f') for _ in range(vertices)]
                if any(not 0 <= value <= 1 for value in advances):
                    raise ValueError('Unsupported text advance.')
                text_flags, text_scale = self.take('I'), self.take('d')
                if single_glyph and (text_flags != 0 or text_scale != 1):
                    raise ValueError('Unsupported single-glyph text suffix.')
                if flags or reserved:
                    raise ValueError('Unsupported text flags.')
                self.add('text', origin=origin, angle=angle, text=text,
                         advances=advances, font=dict(self.font))
            elif kind == 19:
                self.points(1); self.take('I'); self.take('d'); self.take('d')
                self.string(); self.string()
                self.read(self.take('I'), depth + 1)
            elif kind == 24 and size == 64:
                self.take('I'); self.points(1); self.take('Q')
            elif kind in (25, 26) and size == 28:
                self.take('I')
            elif kind == 29 and 80 <= size <= 1024:
                tag, node, version, _ = self.take('4I')
                if tag != 199 or version not in (1, 2):
                    raise ValueError('Unsupported annotation group.')
                component = node in (3,6,7,8) and version == 2
                if component:
                    references = self.take('I')
                    if not 1 <= references <= 2:
                        raise ValueError('Unsupported component annotation reference count.')
                    for _ in range(references):
                        self.take('I')
                    coordinates = self.take('I')
                    if coordinates not in (0,2):
                        raise ValueError('Unsupported component annotation point count.')
                    if coordinates:
                        self.points(coordinates)
                    if self.take('I') != 1:
                        raise ValueError('Unsupported component annotation suffix.')
                    self.string(); self.take('2I')
                else:
                    self.take('5I')
                for _ in range(4):
                    self.string()
                if component:
                    self.take('6I')
                    for _ in range(4):
                        self.string()
            elif kind == 30 and size == 56:
                self.take('3d'); self.take('I')
            elif kind in (16, 17, 20) and size == 24:
                self.add('fill', enabled=kind != 17)
            elif kind == 23 and size == 120:
                self.take('3I'); self.string(); self.take('2I'); self.string()
            else:
                raise ValueError(f'Unsupported drawing command {kind}, size {size}, at byte {start}.')
        return self.offset
