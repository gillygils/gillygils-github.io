"""Recover a single saved drawing sheet and its named cached view geometry.

These version-specific observations are deliberately kept separate from
production acceptance. Metadata outside the decoded commands is still opaque.
"""
import math
import re
import struct
from .commands import Commands, MAX_COMMANDS
from .display import STRING, read_string


def strings(data):
    for match in re.finditer(re.escape(STRING), data):
        try:
            value, end = read_string(data, match.start())
            yield match.start(), end, value
        except (ValueError, UnicodeError):
            continue


def transform(point, matrix):
    return [sum(point[j] * matrix[3*j+i] for j in range(3)) * matrix[12]
            + matrix[9+i] for i in range(3)]


def rigid(matrix):
    return (all(math.isfinite(v) and abs(v) <= 10 for v in matrix)
            and 0 < matrix[12] <= 10
            and all(abs(sum(matrix[3*i+k] * matrix[3*j+k] for k in range(3))
                        - (i == j)) < 1e-9 for i in range(3) for j in range(3)))


def saved_transform(definition, name, size, rotation, view_names=None):
    features = []
    for match in re.finditer(rb'mo(?:Absolute|Unfolded)View', definition):
        for p, end, value in strings(definition[match.end():match.end()+160]):
            features.append((match.start(), value))
            break
    # MFC reuses a serialized class via a short class-reference tag instead
    # of writing its ASCII class name on every subsequent instance. Limit
    # this recovery to names independently mapped from the cached views.
    for p, end, value in strings(definition):
        if value in (view_names or [name]) and p >= 2:
            reference = struct.unpack_from('<H', definition, p-2)[0]
            if 0x8001 <= reference <= 0x8fff:
                features.append((p-2, value))
    features.sort()
    matches = [i for i, (_, value) in enumerate(features) if value == name]
    candidates = []
    for index in matches:
        a = features[index][0]
        b = features[index+1][0] if index+1 < len(features) else len(definition)
        for p in range(a, b-104+1):
            values = struct.unpack_from('<13d', definition, p)
            if (rigid(values) and 0 < values[9] < size[0] and 0 < values[10] < size[1]
                    and max(abs(values[i]-rotation[i]) for i in range(9)) < 1e-8):
                if not any(max(abs(x-y) for x,y in zip(values,v)) < 1e-9 for v in candidates):
                    candidates.append(values)
    if len(candidates) != 1:
        raise ValueError(f'Saved view transform is ambiguous or unsupported: {name}.')
    return list(candidates[0])


def view_geometry(data, definition, size, rotations):
    # Each observed bucket ends in its component/view identifier. Ignore the
    # later 3D tessellation buffers, which are not drawing primitives.
    labels = [(p,e,s) for p,e,s in strings(data) if '@' in s]
    if not 1 <= len(labels) <= 32 or len(labels) != len(rotations):
        raise ValueError('Unsupported cached drawing view mapping.')
    result, begin = [], 0
    for label, end, full_name in labels:
        curves = []
        pattern = re.compile(re.escape(struct.pack('<I', 1)) + rb'(?:\x31\x03|\x21\x03|\x01\x03)\x00\x00')
        for match in pattern.finditer(data, begin, label):
            p = match.start()+4
            kind, count = struct.unpack_from('<II', data, p)
            if not 2 <= count <= MAX_COMMANDS or p+8+24*count > label:
                raise ValueError('Invalid cached drawing curve count.')
            points = [list(struct.unpack_from('<3d', data, p+8+24*i)) for i in range(count)]
            if any(not math.isfinite(v) or abs(v)>10 for point in points for v in point):
                raise ValueError('Invalid cached drawing geometry.')
            curves.append({'offset':p,'record_type':kind,'points':points})
        if not curves:
            raise ValueError(f'No cached geometry for {full_name}.')
        # Validate the observed bucket declaration and camera basis. No
        # inferred fitting/alignment against a preview or reference is used.
        groups, index = [], 0
        while index < len(curves):
            first = curves[index]
            header = first['offset']-12
            count = struct.unpack_from('<I', data, header)[0]
            if not 1 <= count <= len(curves)-index or len(groups) >= 4:
                raise ValueError('Cached geometry does not cover its declared group records.')
            group = curves[index:index+count]
            hidden = first['record_type'] == 817
            if any((curve['record_type'] == 817) != hidden for curve in group):
                raise ValueError('Unsupported cached visibility group.')
            if groups and hidden:
                raise ValueError('Unsupported cached hidden group ordering.')
            slot = (0 if hidden else 1) if not groups else groups[-1]['slot']+1
            if slot > 3:
                raise ValueError('Unsupported cached edge/silhouette group count.')
            # Observed bucket arrays: hidden edges, visible edges, hidden
            # silhouettes, visible silhouettes. Silhouette records use the
            # same geometry tag; visibility belongs to the array slot.
            style = 'HIDDEN' if slot in (0,2) else 'CONTINUOUS'
            for curve in group:
                curve['style'] = style
            groups.append({'hidden':style=='HIDDEN','count':count,'offset':header,'slot':slot})
            index += count
        hidden_header = groups[0]['offset'] if groups[0]['hidden'] else groups[0]['offset']-4
        if hidden_header-52 < begin or (not groups[0]['hidden'] and struct.unpack_from('<I', data, hidden_header)[0]):
            raise ValueError('Unsupported cached hidden-group header.')
        normal = list(struct.unpack_from('<3d',data,hidden_header-52))
        if abs(sum(v*v for v in normal)-1)>1e-9:
            raise ValueError('Unsupported view camera basis.')
        name = full_name.split('@',1)[1]
        matrix = saved_transform(definition, name, size, rotations[len(result)],
                                 [value.split('@',1)[1] for _,_,value in labels])
        for curve in curves:
            curve['projected'] = [transform(point,matrix) for point in curve['points']]
        result.append({'name':name,'component':full_name,'transform':matrix,'curves':curves,'groups':groups})
        begin = end
    if struct.unpack_from('<I',data)[0] != len(result):
        raise ValueError('Cached view count differs from decoded views.')
    return result


def view_tail(data, offset):
    reader = Commands(data); reader.offset = offset
    if reader.take('B') != 1:
        raise ValueError('Unsupported view metadata framing.')
    matrix = list(reader.take('13d'))
    if not rigid(matrix):
        raise ValueError('Invalid saved display transform.')
    # Bounds and component display-state metadata have not been sequentially
    # decoded yet. Bound this recovery, retain its length, and never use it as
    # evidence that an entire document has been interpreted.
    tail = list(strings(data[offset+105:offset+4096]))
    states = [(p,e,s) for p,e,s in tail if re.search(r'_((?:Appearance )?Display State)(?: \d+)?$',s)]
    if not states:
        raise ValueError('Unsupported view display-state framing.')
    p,end,state = states[0]
    reader.offset = offset+105+end
    configuration, reserved, marker = reader.take('3I')
    if configuration not in (1,2) or reserved != 0 or marker != 0xffffffff:
        raise ValueError('Unsupported view display-state suffix.')
    reader.read(reader.take('H'))
    return reader.offset, reader.offset-offset, matrix[:9], reader.primitives


def decode_scene(entries):
    required = ('Contents/DisplayLists','Contents/VBLists','Contents/Definition',
                'SheetPreviews/SheetNames')
    if any(name not in entries for name in required):
        raise ValueError('Required saved drawing streams are missing.')
    names = entries['SheetPreviews/SheetNames']
    if len(names)<2 or struct.unpack_from('<H',names)[0] != 1:
        raise ValueError('Multiple-sheet native drawing export is not implemented yet.')
    sheet_name, end = read_string(names,2)
    if names[end:] != b'\x00'*4:
        raise ValueError('Unsupported sheet-name metadata.')
    data = entries['Contents/DisplayLists']
    if len(data)<4 or struct.unpack_from('<I',data)[0] != 1:
        raise ValueError('Unsupported drawing display-list version.')
    candidates = []
    for match in re.finditer(re.escape(struct.pack('<II',60,9)),data):
        p = match.start()
        if p<2:continue
        count = struct.unpack_from('<H',data,p-2)[0]
        if not 1 <= count <= MAX_COMMANDS:continue
        reader = Commands(data); reader.offset=p
        try:
            reader.read(count)
            height,width = reader.take('2d')
            label = reader.string()
            if (label == sheet_name+'-Active' and .01 <= width <= 5 and .01 <= height <= 5):
                candidates.append((p,reader,[width,height]))
        except (ValueError,UnicodeError,struct.error):
            continue
        if len(candidates)>1:break
    if len(candidates)!=1:
        raise ValueError('No unique, supported single-sheet display command sequence.')
    prefix, reader, size = candidates[0]
    if reader.take('2I') != (1,1) or reader.take('B') != 0:
        raise ValueError('Unsupported sheet display framing.')
    reader.take('4d')
    if reader.take('B') != 0:
        raise ValueError('Unsupported sheet display flags.')
    views = reader.take('I')
    if not 1 <= views <= 32:
        raise ValueError('Unsupported drawing view count.')
    opaque, rotations = [], []
    for _ in range(views):
        if reader.take('I') != 1:
            raise ValueError('Unsupported view command framing.')
        reader.read(reader.take('H'))
        reader.offset, span, rotation, extra = view_tail(data,reader.offset)
        reader.primitives.extend(extra)
        opaque.append(span)
        rotations.append(rotation)
    if data[reader.offset:] != b'\x00'*16 + STRING+b'\x00' + struct.pack('<3I',1,3,0):
        raise ValueError('Unsupported drawing tail or additional sheet data.')
    geometry = view_geometry(entries['Contents/VBLists'],entries['Contents/Definition'],size,rotations)
    if len(geometry)!=views:
        raise ValueError('Annotation views and cached geometry views disagree.')
    return {'sheet':sheet_name,'size_m':size,'primitives':reader.primitives,'views':geometry,
            'command_count':reader.count,'production_supported':False,
            'opaque_prefix_bytes':prefix,'opaque_view_metadata_bytes':opaque,
            'limitations':['Document metadata and layer/style interpretation are incomplete.',
                           'Cached splines need the matching part file for exact geometry.',
                           'Only the observed single-sheet layout is supported.',
                           'Outputs are experimental and must be compared with a reference drawing.']}
