"""Independent conversion acceptance tests using an authored cube, no CAD assets."""
import contextlib
import io
import json
import struct
import sys
import tempfile
import unittest
import zipfile
import zlib
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from native_part.entities import LAYOUTS, decode_prefix
from native_part.model import saved_configuration, check_history, UnsupportedPart
from native_part.shape import reconstruct, ShapeError
from native_part.worker import convert
from native_part.backend import convert_part_native
from experimental.step_reference import analyze_step

XML = b'<root><swConfiguration swID="2" swName="Default" swMostRecentConfiguration="YES" swConfigurationNeedsUpdate="NO" swDefeatureConfiguration="NO"/></root>'


def cube_records():
    records = []
    def add(kind, **fields):
        identity = len(records) + 1
        records.append({'type': kind, 'identity': identity, 'fields': fields, 'variable': []})
        return identity
    def f(identity):
        return records[identity-1]['fields']
    root = add(101, highest_id=10, current_id=9, alive=1)
    body = add(12, owner=root, body_type=1, res_size=1000, state=1, ref_instance=0)
    shell = add(13, body=body, next=0)
    f(root)['body'] = body
    f(body)['shell'] = shell
    coords = [(0,0,0),(10,0,0),(10,10,0),(0,10,0),(0,0,10),(10,0,10),(10,10,10),(0,10,10)]
    vertices = [add(18, point=add(29, pvec=[x/1000 for x in xyz])) for xyz in coords]
    polygons = [[0,3,2,1],[4,5,6,7],[0,1,5,4],[3,7,6,2],[0,4,7,3],[1,2,6,5]]
    normals = [(0,0,-1),(0,0,1),(0,-1,0),(0,1,0),(-1,0,0),(1,0,0)]
    faces, edges = [], {}
    for polygon, normal in zip(polygons, normals):
        start, end = coords[polygon[0]], coords[polygon[1]]
        direction = [(b-a)/10 for a,b in zip(start,end)]
        surface = add(50, pvec=[a/1000 for a in start], normal=normal, x_axis=direction, sense=43)
        face = add(14, surface=surface, sense=43, shell=shell, next=0)
        faces.append(face)
        loop = add(15, face=face, next=0)
        f(face)['loop'] = loop
        fins = []
        for a,b in zip(polygon,polygon[1:]+polygon[:1]):
            fin = add(17, loop=loop, vertex=vertices[b], sense=43)
            fins.append(fin)
            key = tuple(sorted((a,b)))
            if key not in edges:
                vector = [(v-u)/10 for u,v in zip(coords[a],coords[b])]
                curve = add(30, pvec=[u/1000 for u in coords[a]], direction=vector, sense=43)
                edge = add(16, fin=fin, curve=curve)
                edges[key] = edge
            else:
                edge = edges[key]
                other = f(edge)['fin']
                f(other)['other'] = fin
                f(fin).update(other=other,sense=45)
            f(fin)['edge'] = edge
        for i,fin in enumerate(fins):
            f(fin).update(forward=fins[(i+1)%4], backward=fins[(i-1)%4])
        f(loop)['fin'] = fins[0]
    for a,b in zip(faces,faces[1:]):
        f(a)['next'] = b
    f(shell)['face'] = faces[0]
    return records


def encode(kind, value):
    if kind == 'p':
        return struct.pack('>h',value+1)
    if kind in ('v','h','b','i'):
        return b''.join(struct.pack('>d',v) for v in value)
    return struct.pack('>'+{'u':'B','c':'B','l':'B','n':'h','w':'h','d':'i','f':'d'}[kind],value)


def binary_stream(records, kind='partition', schema='SCH_3501210_35102_13006'):
    description = f': TRANSMIT FILE ({kind}) created by modeller version {schema.split("_")[1]}'.encode()
    schema = schema.encode('ascii')
    data = b'PS\0\0'+struct.pack('>H',len(description))+description+struct.pack('>I',len(schema))+schema+struct.pack('>Hi',231,0)
    seen = set()
    for record in records:
        kind = record['type']
        data += struct.pack('>h',kind)
        if kind not in seen:
            data += b'\xff'
            seen.add(kind)
        data += encode('p',record['identity'])
        for name, scalar, count in LAYOUTS[kind]:
            value = record['fields'].get(name,[0]*{'v':3,'h':3,'b':6,'i':2}.get(scalar,1) if scalar in 'vhbi' else 0)
            data += encode(scalar,value)
    return data+b'\0\1\0\1'


def sample_part(path, schema='SCH_3501210_35102_13006', history_schema=None):
    base = binary_stream(cube_records(), schema=schema)
    history = binary_stream([
        {'type':3,'identity':100,'fields':{'current_pmark':101,'highest_id':10}},
        {'type':4,'identity':101,'fields':{'id':9,'delta_is_forward':0,'first_following':0}},
    ],'deltas',schema=history_schema or schema)
    partition = b''
    for payload in (base,history):
        compressed = zlib.compress(payload)
        partition += struct.pack('<I',len(compressed)+32)+b'synthetic-format'+struct.pack('<II',len(payload),len(compressed))+compressed+b'\0'*8
    with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('swXmlContents/Features',XML)
        archive.writestr('Contents/Config-2-Partition',partition)


class NativeConversionTests(unittest.TestCase):
    def test_cube_round_trip_without_network_or_vendor_files(self):
        with tempfile.TemporaryDirectory() as temp:
            source, output = Path(temp)/'cube.sldprt', Path(temp)/'cube.step'
            sample_part(source)
            original = source.read_bytes()
            actual_open = io.open
            def forbid_vendor(file,*args,**kwargs):
                if '.converter' in str(file):
                    raise AssertionError('Independent conversion accessed vendor files')
                return actual_open(file,*args,**kwargs)
            with patch('socket.socket.connect',side_effect=AssertionError('Network access')), patch('urllib.request.urlopen',side_effect=AssertionError('HTTP access')), patch('io.open',side_effect=forbid_vendor):
                response = convert(source,output)
            metrics = analyze_step(output)
            self.assertTrue(response['single_valid_solid'])
            self.assertEqual(response['implementation'],'independent-native')
            self.assertEqual(response['configuration'],'Default')
            self.assertFalse(response['history_replayed'])
            self.assertEqual(metrics['imported_faces'],6)
            self.assertEqual(metrics['imported_solids'],1)
            self.assertAlmostEqual(metrics['solid_volume_mm3'],1000,places=6)
            self.assertAlmostEqual(metrics['solid_surface_area_mm2'],600,places=6)
            for extent in metrics['dimensions_mm']:
                self.assertAlmostEqual(extent,10,places=5)
            self.assertEqual(source.read_bytes(),original)
            with self.assertRaises(FileExistsError):convert(source,output)
            self.assertEqual(set(Path(temp).iterdir()),{source,output})

    def test_app_backend_runs_own_worker(self):
        with tempfile.TemporaryDirectory() as temp:
            source,output = Path(temp)/'cube.sldprt',Path(temp)/'cube.step'
            sample_part(source)
            result = convert_part_native(source,output)
            self.assertEqual(result['implementation'],'independent-native')
            self.assertAlmostEqual(result['volume_mm3'],1000,places=6)
            self.assertTrue(output.is_file())

    def test_compatible_build_converts_and_reports_actual_schema(self):
        with tempfile.TemporaryDirectory() as temp:
            source,output = Path(temp)/'cube.sldprt',Path(temp)/'cube.step'
            schema = 'SCH_3501256_35102_13006'
            sample_part(source,schema=schema)
            result = convert_part_native(source,output)
            self.assertEqual(result['schema'],schema)
            self.assertAlmostEqual(result['volume_mm3'],1000,places=6)
            self.assertTrue(result['single_valid_solid'])

    def test_unknown_layout_or_mismatched_history_is_not_published(self):
        with tempfile.TemporaryDirectory() as temp:
            source,output = Path(temp)/'cube.sldprt',Path(temp)/'cube.step'
            for schema in ('SCH_3601256_35102_13006','SCH_3501256_35103_13006','SCH_3501256_35102_13007'):
                sample_part(source,schema=schema)
                with self.assertRaisesRegex(UnsupportedPart,schema):convert(source,output)
                self.assertFalse(output.exists())
            sample_part(source,history_schema='SCH_3501256_35102_13006')
            with self.assertRaisesRegex(UnsupportedPart,'schema mismatch'):convert(source,output)
            self.assertFalse(output.exists())

    def test_app_defaults_to_native_and_packages_success_while_retaining_failures(self):
        from streamlit.testing.v1 import AppTest
        from core import Item
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)/'source'
            group = root/'IDT C04000'
            group.mkdir(parents=True)
            source = group/'C04571_001.sldprt'
            sample_part(source,schema='SCH_3501256_35102_13006')
            original = source.read_bytes()
            second = group/'C04571_002.sldprt'
            sample_part(second)
            second_original = second.read_bytes()
            (group/'C04572_002.sldprt').write_bytes(b'unsupported-part')
            output = Path(temp)/'output'
            upload = io.BytesIO(b'synthetic-po')
            def uploader(*args,**kwargs):
                return [] if kwargs.get('accept_multiple_files') else upload
            with patch('streamlit.file_uploader',side_effect=uploader), patch('core.parse_po',return_value=('999',[Item(1,'1','PC','C04571_001'),Item(2,'1','PC','C04571_002'),Item(3,'1','PC','C04572_002')])), patch('local_converter.converter_diagnostics',side_effect=AssertionError('Vendor readiness was checked')):
                app = AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'),default_timeout=20).run()
                provider = next(s for s in app.selectbox if s.label=='STEP converter')
                self.assertEqual(provider.value,'Independent native reader (experimental)')
                automatic = next(c for c in app.checkbox if c.label=='Convert copied part files to STEP locally')
                self.assertTrue(automatic.value)
                self.assertFalse(automatic.disabled)
                app.sidebar.text_input[0].set_value(str(root))
                app.sidebar.text_input[1].set_value(str(output))
                next(b for b in app.button if b.label=='Search source folder').click().run()
                next(c for c in app.checkbox if c.label.startswith('I checked')).check().run()
                next(b for b in app.button if b.label=='Create PO folder and process files').click().run()
                self.assertFalse(app.exception)
                job = app.session_state['completed_job']
                with zipfile.ZipFile(job['archive']) as archive:
                    self.assertEqual(archive.read('C04571_001.sldprt'),original)
                    self.assertEqual(archive.read('C04571_002.sldprt'),second_original)
                    self.assertEqual(archive.read('C04572_002.sldprt'),b'unsupported-part')
                    self.assertIn('C04571_001.step',archive.namelist())
                    self.assertIn('C04571_002.step',archive.namelist())
                    self.assertNotIn('C04571.step',archive.namelist())
                    self.assertNotIn('C04572_002.step',archive.namelist())
                    report = json.loads(archive.read('report.json'))
                conversions = [r for r in report['results'] if r['status']=='Converted STEP']
                self.assertEqual(len(conversions),2)
                self.assertTrue(all(r['validation']['implementation']=='independent-native' for r in conversions))
                self.assertEqual({r['validation']['schema'] for r in conversions},
                                 {'SCH_3501256_35102_13006','SCH_3501210_35102_13006'})
                self.assertTrue(any(r['status'].startswith('Conversion failed:') for r in report['results']))

    def test_bad_loop_or_unsupported_surface_cannot_be_exported(self):
        records = cube_records()
        fin = next(r for r in records if r['type']==17)
        fin['fields']['forward'] = fin['identity']
        with self.assertRaises(ShapeError):reconstruct({'complete':True,'records':records})
        records = cube_records()
        next(r for r in records if r['type']==50)['type'] = 124
        with self.assertRaisesRegex(ShapeError,'Unsupported surface'):reconstruct({'complete':True,'records':records})

    def test_decoder_requires_terminal_marker_and_unique_identity(self):
        data = binary_stream(cube_records())
        self.assertTrue(decode_prefix(data)['complete'])
        self.assertFalse(decode_prefix(data[:-1])['complete'])
        self.assertFalse(decode_prefix(data+b'extra')['complete'])
        duplicate = cube_records()
        duplicate[-1]['identity'] = duplicate[0]['identity']
        self.assertIn('duplicate',decode_prefix(binary_stream(duplicate))['stopped_reason'])

    def test_stale_config_and_mismatched_current_mark_rejected(self):
        self.assertEqual(saved_configuration(XML),('2','Default'))
        for xml in (XML.replace(b'swConfigurationNeedsUpdate="NO"',b'swConfigurationNeedsUpdate="YES"'),XML.replace(b'</root>',XML.split(b'<root>')[1]),b'<!DOCTYPE root>'+XML):
            with self.assertRaises(UnsupportedPart):saved_configuration(xml)
        base={'records':[{'type':101,'fields':{'highest_id':10,'current_id':9}}]}
        history={'records':[{'type':3,'fields':{'current_pmark':20,'highest_id':10}}, {'type':4,'identity':20,'fields':{'id':8,'first_following':0,'delta_is_forward':0}}]}
        with self.assertRaisesRegex(UnsupportedPart,'leaf state'):check_history(base,history)
        history['records'][1]['fields']['id']=9
        self.assertTrue(check_history(base,history)['current_base_mark_matched'])
        history['records'][1]['fields']['delta_is_forward']=1
        with self.assertRaises(UnsupportedPart):check_history(base,history)

    def test_unsupported_input_timeout_and_worker_failure_leave_no_step(self):
        with tempfile.TemporaryDirectory() as temp:
            source,output = Path(temp)/'part.sldprt',Path(temp)/'part.step'
            source.write_bytes(b'not a part')
            with self.assertRaises(ValueError):convert(source,output)
            self.assertFalse(output.exists())
            import subprocess
            with patch('native_part.backend.subprocess.run',side_effect=subprocess.TimeoutExpired('worker',120)):
                with self.assertRaisesRegex(RuntimeError,'120 seconds'):convert_part_native(source,output)
            with patch('native_part.backend.subprocess.run',return_value=subprocess.CompletedProcess([],1,'','unsupported schema')):
                with self.assertRaisesRegex(RuntimeError,'unsupported schema'):convert_part_native(source,output)
            self.assertFalse(output.exists())
            self.assertEqual(list(Path(temp).iterdir()),[source])
