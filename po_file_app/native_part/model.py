"""Select and verify a saved configuration before rebuilding its base body."""
import math
import struct
import xml.etree.ElementTree as ET
from pathlib import Path

from native_drawing.archive import read_archive
from .entities import decode_prefix
from .partition import recover_blocks, parasolid_header


class UnsupportedPart(ValueError):
    pass


def saved_configuration(xml):
    if len(xml) > 4 * 1024 * 1024 or b'<!DOCTYPE' in xml.upper() or b'<!ENTITY' in xml.upper():
        raise UnsupportedPart('Unsupported configuration XML.')
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise UnsupportedPart('Cannot read saved configuration metadata.') from exc
    candidates = [e.attrib for e in root.iter()
                  if e.tag.rsplit('}', 1)[-1] == 'swConfiguration'
                  and e.get('swMostRecentConfiguration') == 'YES']
    if len(candidates) != 1:
        raise UnsupportedPart('Exactly one most-recent saved configuration is required.')
    config = candidates[0]
    if (config.get('swConfigurationNeedsUpdate') != 'NO'
            or config.get('swDefeatureConfiguration') != 'NO'
            or not config.get('swID', '').isascii()
            or not config.get('swID', '').isdigit()):
        raise UnsupportedPart('Saved configuration is stale, defeatured or unsupported.')
    return config['swID'], config.get('swName', '')


def only_record(report, kind):
    matches = [r for r in report['records'] if r['type'] == kind]
    if len(matches) != 1:
        raise UnsupportedPart(f'Exactly one entity of type {kind} is required.')
    return matches[0]


def check_history(base, history):
    """Accept an already-current full partition, never replay partial undo data.

    The observed file stores a complete body and a backward history stream.
    Only a leaf mark matching that full partition is supported. This is a
    narrow version-specific acceptance rule, not a general history interpreter.
    """
    root = only_record(base, 101)['fields']
    hroot = only_record(history, 3)['fields']
    marks = [r for r in history['records']
             if r['type'] == 4 and r['identity'] == hroot['current_pmark']]
    if len(marks) != 1:
        raise UnsupportedPart('Current history mark was not decoded.')
    mark = marks[0]['fields']
    if (hroot['highest_id'] != root['highest_id'] or mark['id'] != root['current_id']
            or mark['first_following'] != 0 or mark['delta_is_forward'] != 0):
        raise UnsupportedPart('The saved base partition is not a supported current leaf state; history replay is unavailable.')
    return {'history_replayed': False, 'current_base_mark_matched': True,
            'current_mark_id': mark['id'], 'highest_mark_id': root['highest_id']}


def load_model(source):
    entries = read_archive(Path(source))
    if 'swXmlContents/Features' not in entries:
        raise UnsupportedPart('Saved configuration metadata is missing.')
    config_id, name = saved_configuration(entries['swXmlContents/Features'])
    key = f'Contents/Config-{config_id}-Partition'
    if key not in entries:
        raise UnsupportedPart('The saved configuration has no supported full partition.')
    data = entries[key]
    framed = recover_blocks(data)
    # Observed framing: total length minus 4, a 16-byte identifier, the
    # size-framed zlib stream, and eight zero trailer bytes. Validate every
    # byte around the recovered streams rather than accepting opaque gaps.
    cursor = 0
    identifier = data[4:20]
    for block in framed['blocks']:
        end = block['offset'] + 8 + block['compressed_bytes']
        if (block['offset'] != cursor + 20
                or struct.unpack_from('<I', data, cursor)[0] != block['compressed_bytes'] + 32
                or data[cursor+4:cursor+20] != identifier
                or data[end:end+8] != b'\x00' * 8):
            raise UnsupportedPart('Unsupported partition framing or trailing data.')
        cursor = end + 8
    if cursor != len(data):
        raise UnsupportedPart('Unsupported partition framing or trailing data.')
    bases, histories = [], []
    for block in framed['blocks']:
        header = parasolid_header(block['data'])
        if not header or header['kind'] not in {'partition', 'deltas'}:
            raise UnsupportedPart('Unsupported saved geometry stream.')
        decoded = decode_prefix(block['data'])
        (bases if header['kind'] == 'partition' else histories).append(decoded)
    if len(bases) != 1 or len(histories) != 1:
        raise UnsupportedPart('This reader requires one full base partition and its saved history mark.')
    base = bases[0]
    if not base['complete']:
        raise UnsupportedPart('Unsupported part geometry: ' + base.get('stopped_reason', 'incomplete entity stream'))
    root = only_record(base, 101)
    body = only_record(base, 12)
    state = body['fields']
    if (root['fields']['body'] != body['identity'] or state['owner'] != root['identity']
            or root['fields']['alive'] != 1 or state['state'] != 1
            or state['body_type'] != 1 or state['ref_instance'] != 0
            or any(root['fields'].get(k,0) for k in ('assembly','transform','mesh','polyline','lattice'))
            or any(state.get(k,0) for k in ('mesh','polyline','lattice','boundary_mesh','boundary_polyline','boundary_lattice'))
            or not math.isclose(state['res_size'], 1000, abs_tol=1e-8, rel_tol=0)):
        raise UnsupportedPart('Unsupported body ownership, body type or unit scale.')
    history = check_history(base, histories[0])
    return base, {'implementation': 'independent-native', 'configuration': name,
                  'configuration_archive_id': config_id,
                  'schema': 'SCH_3501210_35102_13006',
                  'decoded_entities': len(base['records']), **history}
