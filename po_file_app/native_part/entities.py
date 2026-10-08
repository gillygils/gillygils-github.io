"""Bounded, partial Parasolid entity decoding for the observed binary schema.

Only the partition/body/assembly prefix is currently understood. Stop at the
first unsupported entity rather than scanning for plausible geometry records.
No shape or STEP export is claimed by this diagnostic decoder.
"""
import math
import struct
from .partition import parasolid_header


class DecodeError(ValueError):
    pass


class Cursor:
    def __init__(self, data, offset=0):
        self.data, self.offset = data, offset

    def take(self, count):
        if count < 0 or self.offset + count > len(self.data):
            raise DecodeError(f'Truncated entity at byte {self.offset}.')
        result = self.data[self.offset:self.offset + count]
        self.offset += count
        return result

    def unpack(self, format):
        return struct.unpack('>' + format, self.take(struct.calcsize('>' + format)))[0]

    def string(self):
        return self.take(self.unpack('B')).decode('ascii')

    def pointer(self):
        low = self.unpack('h')
        if low >= 0:
            return low - 1
        high = self.unpack('h')
        if high < 0:
            raise DecodeError('Negative extended reference quotient.')
        return high * 32767 - low - 1

    def value(self, kind):
        if kind == 'p':
            return self.pointer()
        formats = {'u':'B', 'c':'B', 'l':'B', 'n':'h', 'w':'h', 'd':'i', 'f':'d'}
        if kind not in formats:
            raise DecodeError('Unsupported scalar field type: ' + kind)
        value = self.unpack(formats[kind])
        if isinstance(value, float) and not math.isfinite(value):
            raise DecodeError('Non-finite entity field.')
        return value


def fields(spec):
    return [(word.split(':')[0], word.split(':')[1], 1) for word in spec.split()]


# Explicit layouts for the observed 13006 schema's partition/body prefix.
# Additional schemas, geometric entities and variable records are unsupported.
LAYOUTS = {
    101: fields('assembly:p attribute:p body:p transform:p surface:p curve:p point:p '
                'alive:l attrib_def:p highest_id:d current_id:d'),
    12: fields('highest_node_id:d attributes_groups:p attribute_chains:p surface:p curve:p '
               'point:p key:p res_size:f res_linear:f ref_instance:p next:p previous:p '
               'state:u owner:p body_type:u nom_geom_state:u shell:p boundary_surface:p '
               'boundary_curve:p boundary_point:p region:p edge:p vertex:p'),
    10: fields('highest_node_id:d attributes_features:p attribute_chains:p list:p surface:p '
               'curve:p point:p key:p res_size:f res_linear:f ref_instance:p next:p '
               'previous:p state:u owner:p type:u sub_instance:p'),
}


def read_schema(cursor, inherited):
    declaration = cursor.unpack('B')
    if declaration == 255:
        return inherited
    if not 1 <= declaration <= 100:
        raise DecodeError('Unsupported entity schema declaration.')
    result, index = [], 0
    for _ in range(250):
        action = chr(cursor.unpack('B'))
        if action == 'Z':
            if len(result) != declaration:
                raise DecodeError('Schema field count disagrees with its declaration.')
            return result
        if action in ('C', 'D'):
            if index >= len(inherited):
                raise DecodeError('Schema exceeds inherited field layout.')
            if action == 'C':
                result.append(inherited[index])
            index += 1
        elif action in ('I', 'A'):
            name = cursor.string()
            reference_type, count = cursor.unpack('h'), cursor.unpack('h')
            if not name or not 0 <= count <= 1:
                raise DecodeError('Variable or array schema field is not supported.')
            kind = cursor.string().lower() if reference_type == 0 else 'p'
            if kind not in 'uclnwdpf' or len(kind) != 1:
                raise DecodeError('Unsupported schema field encoding.')
            result.append((name, kind, max(count, 1)))
        else:
            raise DecodeError('Unsupported schema patch action: ' + repr(action))
    raise DecodeError('Schema patch exceeds its instruction limit.')


def decode_prefix(data):
    header = parasolid_header(data)
    report = {'complete':False, 'geometry_reconstructed':False, 'records':[]}
    if not header or header['schema'] != 'SCH_3501210_35102_13006':
        return report | {'stopped_reason':'Unsupported Parasolid binary schema.', 'stopped_offset':0}
    cursor = Cursor(data,header['header_bytes'])
    schemas = {}
    try:
        marker, stride = cursor.unpack('H'), cursor.unpack('i')
        if marker != 231 or not 0 <= stride <= 64:
            raise DecodeError('Unsupported entity framing marker or stride.')
        for _ in range(100000):
            start = cursor.offset
            node_type = cursor.unpack('h')
            if node_type not in LAYOUTS:
                return report | {'stopped_reason':f'Unsupported entity type {node_type}.',
                                 'stopped_offset':start, 'unsupported_entity_type':node_type}
            if node_type not in schemas:
                schemas[node_type] = read_schema(cursor,LAYOUTS[node_type])
            identity = cursor.pointer()
            if identity < 1:
                raise DecodeError('Invalid entity identity.')
            values = {name:cursor.value(kind) for name,kind,count in schemas[node_type]}
            cursor.take(stride)
            report['records'].append({'type':node_type,'identity':identity,'offset':start,
                                      'end_offset':cursor.offset,'fields':values})
        raise DecodeError('Entity count limit exceeded.')
    except (DecodeError, UnicodeError) as exc:
        return report | {'stopped_reason':str(exc),'stopped_offset':cursor.offset}
