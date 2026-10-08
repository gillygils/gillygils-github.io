"""Bounded Parasolid decoding for the observed 13006 binary schema.

Complete full partitions and partial history metadata are supported. Stop at
the first unsupported entity rather than scanning for plausible records.
"""
import math
import re
import struct
from .partition import parasolid_header


# The writer build (first component) varies between saved parts. Its 35.1
# patch revisions share the observed 35102/13006 on-stream layout family.
# Entity schema patches still have to decode completely; this does not allow
# arbitrary Parasolid releases, layout revisions or unknown entity types.
SCHEMA_FAMILY = re.compile(r'SCH_3501[0-9]{3}_35102_13006\Z')


def supported_schema(schema):
    return SCHEMA_FAMILY.fullmatch(schema) is not None


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
        if kind in ('v','h','b','i'):
            return [self.value('f') for _ in range({'v':3,'h':3,'b':6,'i':2}[kind])]
        formats = {'u':'B', 'c':'B', 'l':'B', 'n':'h', 'w':'h', 'd':'i', 'f':'d'}
        if kind not in formats:
            raise DecodeError('Unsupported scalar field type: ' + kind)
        value = self.unpack(formats[kind])
        if isinstance(value, float) and not math.isfinite(value):
            raise DecodeError('Non-finite entity field.')
        return value


def fields(spec):
    return [(word.split(':')[0], word.split(':')[1], 1) for word in spec.split()]


# Explicit field layouts; on-stream version patches are checked against them.
LAYOUTS = {
    3: fields('current_pmark:p highest_id:d'),
    4: fields('preceding:p first_following:p next_sibling:p prev_sibling:p n_new_nodes:d n_del_nodes:d n_copy_mod_nodes:d delta_key:d delta_is_forward:l id:d'),
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


GEOMETRIC = 'node_id:d attributes_groups:p owner:p next:p previous:p geometric_owner:p sense:c '
LAYOUTS.update({
    13: fields('node_id:d attributes_groups:p body:p next:p face:p edge:p vertex:p region:p front_face:p'),
    14: fields('node_id:d attributes_groups:p tolerance:f next:p previous:p loop:p shell:p surface:p sense:c next_on_surface:p previous_on_surface:p next_front:p previous_front:p front_shell:p'),
    15: fields('node_id:d attributes_groups:p fin:p face:p next:p'),
    16: fields('node_id:d attributes_groups:p tolerance:f fin:p previous:p next:p curve:p next_on_curve:p previous_on_curve:p owner:p'),
    17: fields('attributes_groups:p loop:p forward:p backward:p vertex:p other:p edge:p curve:p next_at_vx:p sense:c'),
    18: fields('node_id:d attributes_groups:p fin:p previous:p next:p point:p tolerance:f owner:p'),
    19: fields('node_id:d attributes_groups:p body:p next:p previous:p shell:p type:c'),
    29: fields('node_id:d attributes_groups:p owner:p next:p previous:p pvec:v'),
    30: fields(GEOMETRIC+'pvec:v direction:v'),
    31: fields(GEOMETRIC+'centre:v normal:v x_axis:v radius:f'),
    32: fields(GEOMETRIC+'centre:v normal:v x_axis:v major_radius:f minor_radius:f'),
    50: fields(GEOMETRIC+'pvec:v normal:v x_axis:v'),
    51: fields(GEOMETRIC+'pvec:v axis:v radius:f x_axis:v'),
    52: fields(GEOMETRIC+'pvec:v axis:v radius:f sin_half_angle:f cos_half_angle:f x_axis:v'),
    53: fields(GEOMETRIC+'centre:v radius:f axis:v x_axis:v'),
    54: fields(GEOMETRIC+'centre:v axis:v major_radius:f minor_radius:f x_axis:v'),
    70: fields('node_id:d owner:p next:p previous:p list_type:d list_length:d block_length:d size_of_entry:d list_block:p finger_block:p finger_index:d notransmit:l'),
    74: fields('n_entries:d next_block:p entries:p'),
    79: fields('string:c'), 98: fields('values:w'),
    80: fields('next:p identifier:p type_id:d') + [('actions','u',8)] + fields('field_names:p') + [('legal_owners','l',14)] + fields('fields:u'),
    81: fields('node_id:d definition:p owner:p next:p previous:p next_of_type:p previous_of_type:p fields:p'),
    82: fields('values:d'), 83: fields('values:f'), 84: fields('values:c'), 85: fields('values:v'),
    100: fields('node_id:d owner:p next:p previous:p') + [('rotation','f',9)] + fields('translation:v scale:f flag:d perspective_vector:v'),
})
LAYOUTS.update({
    67: fields(GEOMETRIC+'section:p sweep:v scale:f'),
    124: fields(GEOMETRIC+'nurbs:p data:p'),
    126: fields('u_periodic:l v_periodic:l u_degree:n v_degree:n n_u_vertices:d n_v_vertices:d u_knot_type:u v_knot_type:u rational:l u_closed:l v_closed:l surface_form:u vertex_dim:n bspline_vertices:p u_knot_mult:p v_knot_mult:p u_knots:p v_knots:p'),
    134: fields(GEOMETRIC+'nurbs:p data:p'),
    136: fields('degree:n n_vertices:d vertex_dim:n n_knots:d knot_type:u periodic:l closed:l rational:l curve_form:u bspline_vertices:p knot_mult:p knots:p'),
    45: fields('vertices:f'), 127: fields('mult:n'), 128: fields('knots:f'),
    135: fields('self_int:u analytic_form:p'),
    141: fields('owner:p next:p previous:p shared_geometry:p'),
    122: fields('key:p real_array:p int_array:p'),
    121: fields('geom_type:d real_array:p int_array:p'),
    137: fields(GEOMETRIC+'surface:p b_curve:p original:p tolerance_to_original:f'),
})
VARIABLE = {45,74,79,80,81,82,83,84,85,98,121,122,127,128}


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
            if not name or not 0 <= count <= 100:
                raise DecodeError('Variable or array schema field is not supported.')
            if count == 2:
                raise DecodeError('Dynamic two-count field is not decoded.')
            kind = cursor.string().lower() if reference_type == 0 else 'p'
            if kind not in 'uclnwdpfvbih' or len(kind) != 1:
                raise DecodeError('Unsupported schema field encoding.')
            result.append((name, kind, max(count, 1)))
        else:
            raise DecodeError('Unsupported schema patch action: ' + repr(action))
    raise DecodeError('Schema patch exceeds its instruction limit.')


def decode_prefix(data):
    header = parasolid_header(data)
    schema = header['schema'] if header else None
    report = {'schema':schema, 'complete':False, 'geometry_reconstructed':False, 'records':[]}
    if not header or not supported_schema(schema):
        return report | {'stopped_reason':f'Unsupported Parasolid binary schema: {schema or "unrecognized header"}. '
                         'Supported layout family: SCH_3501xxx_35102_13006.', 'stopped_offset':0}
    cursor = Cursor(data,header['header_bytes'])
    schemas = {}
    identities = set()
    try:
        marker, stride = cursor.unpack('H'), cursor.unpack('i')
        if marker != 231 or not 0 <= stride <= 64:
            raise DecodeError('Unsupported entity framing marker or stride.')
        for _ in range(100000):
            start = cursor.offset
            if cursor.data[start:] == b'\x00\x01\x00\x01':
                return report | {'complete':True, 'end_marker_offset':start}
            node_type = cursor.unpack('h')
            if node_type not in LAYOUTS:
                return report | {'stopped_reason':f'Unsupported entity type {node_type}.',
                                 'stopped_offset':start, 'unsupported_entity_type':node_type}
            if node_type not in schemas:
                schemas[node_type] = read_schema(cursor,LAYOUTS[node_type])
            variable_count = cursor.unpack('i') if node_type in VARIABLE else 0
            if not 0 <= variable_count <= 100000:
                raise DecodeError('Variable count outside limits.')
            identity = cursor.pointer()
            if identity < 1 or identity in identities:
                raise DecodeError('Invalid or duplicate entity identity.')
            identities.add(identity)
            fixed = schemas[node_type][:-1] if node_type in VARIABLE else schemas[node_type]
            values = {name:cursor.value(kind) if count == 1 else [cursor.value(kind) for _ in range(count)]
                      for name,kind,count in fixed}
            variable = []
            if node_type == 80 and variable_count:
                # This observed definition layout includes an implicit final
                # field terminator in its count, without a stored byte.
                variable_count -= 1
            if variable_count:
                kind = schemas[node_type][-1][1]
                variable = [cursor.value(kind) for _ in range(variable_count)]
            cursor.take(stride)
            report['records'].append({'type':node_type,'identity':identity,'offset':start,
                                      'end_offset':cursor.offset,'fields':values,'variable':variable})
        raise DecodeError('Entity count limit exceeded.')
    except (DecodeError, UnicodeError) as exc:
        return report | {'stopped_reason':str(exc),'stopped_offset':cursor.offset}
