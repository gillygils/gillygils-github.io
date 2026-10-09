"""Recover a single saved drawing sheet and its named cached view geometry.

These version-specific observations are deliberately kept separate from
production acceptance. Metadata outside the decoded commands is still opaque.
"""
import math
import re
import struct
from .commands import Commands, MAX_COMMANDS
from .display import STRING, read_string

IDENTITY = [1,0,0,0,1,0,0,0,1]


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
    for match in re.finditer(rb'mo(?:Absolute|Unfolded|Detail)View(?![A-Za-z0-9_])', definition):
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
    def accept(values):
        if (all(abs(values[i]-rotation[i]) < 1e-8 for i in range(9))
                and rigid(values) and 0 < values[9] < size[0] and 0 < values[10] < size[1]
                # Model-space transforms can have the same orientation.
                # Display scale and depth independently identify the sheet view.
                and (len(rotation) == 9 or
                     (abs(values[12]-rotation[12]) < 1e-9
                      and abs(values[11]-rotation[11]) < 1e-9))):
            if not any(max(abs(x-y) for x,y in zip(values,v)) < 1e-9 for v in candidates):
                candidates.append(values)
    for index in matches:
        a = features[index][0]
        b = features[index+1][0] if index+1 < len(features) else len(definition)
        header = struct.pack('<IIB',1,0,1)
        for match in re.finditer(re.escape(header),definition[a:b]):
            p = a+match.end()
            if p+104 <= b:
                accept(struct.unpack_from('<13d', definition, p))
        # The observed definition uses a one-byte rotation-present flag;
        # identity rotations omit the nine doubles. Require the surrounding
        # saved-transform header, not merely four plausible numbers.
        if max(abs(rotation[i]-IDENTITY[i]) for i in range(9)) < 1e-12:
            header = struct.pack('<IIB',1,0,0)
            for match in re.finditer(re.escape(header),definition[a:b]):
                p = a+match.end()
                if p+32 <= b:
                    accept(IDENTITY+list(struct.unpack_from('<4d',definition,p)))
    if len(candidates) != 1:
        raise ValueError(f'Saved view transform is ambiguous or unsupported: {name}.')
    return list(candidates[0])


def view_geometry(data, definition, size, rotations, present=None):
    # Each observed bucket ends in its component/view identifier. Ignore the
    # later 3D tessellation buffers, which are not drawing primitives.
    present = [True]*len(rotations) if present is None else present
    empty = next((i for i,value in enumerate(present) if value),len(present))
    populated = [i for i,value in enumerate(present) if value]
    if (len(data)<4 or struct.unpack_from('<I',data)[0] != len(rotations)
            or data[4:4+2*empty] != bytes(2*empty)):
        raise ValueError('Cached empty view pointers do not match the display views.')
    # Primary bucket labels have one or two reference entries. Later shaded
    # assembly buffers can repeat the same strings and are not drawing edges.
    labels = [(p,e,s) for p,e,s in strings(data)
              if '@' in s and p >= 6 and data[p-6:p] in
              (struct.pack('<HI',1,1),struct.pack('<HI',2,1))]
    if not 1 <= len(labels) <= 32 or len(labels) != len(populated):
        raise ValueError('Unsupported cached drawing view mapping.')
    result, begin = [], 0
    for label, end, full_name in labels:
        curves = []
        pattern = re.compile(rb'[\x01\x02]\x00\x00\x00(?:\x31\x03|\x21\x03|\x01\x03)\x00\x00')
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
        # Section buckets can repeat their final curve array after the label
        # for selection data. Verify the declaration and every saved point
        # against the preceding bucket before excluding this exact duplicate.
        if result and data[begin:begin+20] == bytes(20) and begin+32 <= label:
            copies, marker, version = struct.unpack_from('<3I',data,begin+20)
            if marker == 0xffffffff and version == 1:
                previous = result[-1]['curves']
                if (not 1 <= copies <= len(previous) or copies >= len(curves)
                        or curves[0]['offset'] != begin+32
                        or any(a['record_type'] != b['record_type'] or a['points'] != b['points']
                               for a,b in zip(curves[:copies],previous[-copies:]))):
                    raise ValueError('Section selection curves differ from their declared drawing copies.')
                curves = curves[copies:]
                result[-1]['verified_selection_copies'] = copies
        first_header = curves[0]['offset']-12
        hidden_header = first_header if curves[0]['record_type'] == 817 else first_header-4
        if hidden_header-52 < begin or (curves[0]['record_type'] != 817 and struct.unpack_from('<I',data,hidden_header)[0]):
            raise ValueError('Unsupported cached hidden-group header.')
        normal_start = hidden_header-52
        normal = list(struct.unpack_from('<3d',data,normal_start))
        if abs(sum(v*v for v in normal)-1)>1e-9:
            normal_start = hidden_header-48
            if (normal_start<begin or struct.unpack_from('<I',data,normal_start+24)[0] not in (0,1,2,3)
                    or struct.unpack_from('<2I',data,normal_start+40) != (25,0)):
                raise ValueError('Unsupported view camera basis.')
            normal = list(struct.unpack_from('<3d',data,normal_start))
        if any(not math.isfinite(v) for v in normal) or abs(sum(v*v for v in normal)-1)>1e-9:
            raise ValueError('Unsupported view camera basis.')
        mode = struct.unpack_from('<I',data,normal_start+24)[0]
        if mode not in (0,1,2,3):
            raise ValueError('Unsupported cached bucket mode.')
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
            if mode != 1 and groups and hidden:
                raise ValueError('Unsupported cached hidden group ordering.')
            if mode == 1 and groups and hidden and not groups[-1]['hidden']:
                raise ValueError('Unsupported cached hidden group ordering.')
            if mode == 1:
                slot = (0 if hidden else 2) if not groups else max(groups[-1]['slot']+1,0 if hidden else 2)
            else:
                slot = (0 if hidden else 1) if not groups else groups[-1]['slot']+1
            if slot > 3:
                raise ValueError('Unsupported cached edge/silhouette group count.')
            # Modes 0/2/3 interleave hidden and visible edge/silhouette
            # arrays. Mode 1 groups hidden arrays before visible arrays.
            style = ('HIDDEN' if hidden else 'CONTINUOUS') if mode == 1 else ('HIDDEN' if slot in (0,2) else 'CONTINUOUS')
            for curve in group:
                curve['style'] = style
            groups.append({'hidden':style=='HIDDEN','count':count,'offset':header,'slot':slot})
            index += count
        name = full_name.split('@',1)[1]
        matrix = saved_transform(definition, name, size, rotations[populated[len(result)]],
                                 [value.split('@',1)[1] for _,_,value in labels])
        detail = False
        for match in re.finditer(rb'moDetailView(?![A-Za-z0-9_])',definition):
            first_name = next(strings(definition[match.end():match.end()+160]),None)
            if first_name and first_name[2] == name:
                detail = True
        # The observed detail bucket contains already projected XY samples,
        # independently identified by its typed detail feature and planar
        # camera/geometry. Applying its model orientation would collapse it.
        planar = (detail and abs(abs(normal[2])-1)<1e-9
                  and all(c['record_type']==769 and all(abs(p[2])<1e-12 for p in c['points'])
                          for c in curves))
        projection = IDENTITY+matrix[9:] if planar else matrix
        for curve in curves:
            curve['projected'] = [transform(point,projection) for point in curve['points']]
        result.append({'name':name,'component':full_name,'transform':matrix,'curves':curves,'groups':groups,
                       'coordinate_space':'view_plane' if planar else 'model'})
        begin = end
    if struct.unpack_from('<I',data)[0] != len(result)+present.count(False):
        raise ValueError('Cached view count differs from decoded views.')
    return result


def view_tail(data, offset, commands_present=True):
    reader = Commands(data); reader.offset = offset
    rotated = reader.take('B')
    if rotated not in (0,1):
        raise ValueError('Unsupported view metadata framing.')
    matrix = (list(reader.take('13d')) if rotated
              else IDENTITY+list(reader.take('4d')))
    if not rigid(matrix):
        raise ValueError('Invalid saved display transform.')
    # Bounds and component display-state metadata have not been sequentially
    # decoded yet. Bound this recovery, retain its length, and never use it as
    # evidence that an entire document has been interpreted.
    metadata = reader.offset
    tail = list(strings(data[metadata:offset+4096]))
    states = [(p,e,s) for p,e,s in tail
              if re.search(r'(?:^|_)(?:Appearance )?Display State(?:[ -]\d+)?$',s)]
    if not states:
        raise ValueError('Unsupported view display-state framing.')
    p,end,state = states[0]
    reader.offset = metadata+end
    configuration, reserved, marker = reader.take('3I')
    if configuration not in (1,2) or reserved != 0 or marker != 0xffffffff:
        raise ValueError('Unsupported view display-state suffix.')
    if commands_present:
        reader.read(reader.take('H'))
    return reader.offset, reader.offset-offset, matrix, reader.primitives


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
        if p<6 or struct.unpack_from('<I',data,p-6)[0] != 1:continue
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
    opaque, rotations, present_views = [], [], []
    for _ in range(views):
        present = reader.take('I')
        if present not in (0,1):
            raise ValueError('Unsupported view command framing.')
        if present:
            reader.read(reader.take('H'))
        present_views.append(bool(present))
        reader.offset, span, rotation, extra = view_tail(data,reader.offset,present)
        reader.primitives.extend(extra)
        opaque.append(span)
        rotations.append(rotation)
    ending = data[reader.offset:]
    prefix_end = b'\x00'*16 + STRING+b'\x00'
    if (len(ending) != len(prefix_end)+12 or not ending.startswith(prefix_end)
            or struct.unpack_from('<3I',ending,len(prefix_end)) not in ((1,3,0),(1,8,0))):
        raise ValueError('Unsupported drawing tail or additional sheet data.')
    geometry = view_geometry(entries['Contents/VBLists'],entries['Contents/Definition'],size,rotations,present_views)
    if len(geometry)!=sum(present_views):
        raise ValueError('Annotation views and cached geometry views disagree.')
    limitations = ['Document metadata and layer/style interpretation are incomplete.',
                   'Cached splines need the matching part file for exact geometry.',
                   'Only the observed single-sheet layout is supported.',
                   'Outputs are experimental and must be compared with a reference drawing.']
    if any(item['kind'] == 'point' for item in reader.primitives):
        limitations.append('Saved annotation points retain their locations; marker appearance is unverified.')
    if any(item.get('style') == 'PHANTOM' for item in reader.primitives):
        limitations.append('PHANTOM uses a standard dash pattern; its saved dash spacing is unverified.')
    return {'sheet':sheet_name,'size_m':size,'primitives':reader.primitives,'views':geometry,
            'command_count':reader.count,'production_supported':False,
            'empty_saved_views':present_views.count(False),
            'display_tail_variant':struct.unpack_from('<3I',ending,len(prefix_end))[1],
            'opaque_prefix_bytes':prefix,'opaque_view_metadata_bytes':opaque,
            'limitations':limitations}
