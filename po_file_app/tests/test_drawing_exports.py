"""Authored drawing fixtures; no customer CAD, fonts, or reference exports."""
import io
import json
import math
import struct
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ezdxf
from pypdf import PdfReader
from native_drawing.commands import Commands
from native_drawing.scene import decode_scene, transform, saved_transform, view_tail
from native_drawing.curves import circular, resolve_spline, projected_circle
from native_drawing.exports import write_pdf, write_dxf, append_path, flatten_arc, NOTICE
from native_drawing.worker import export_drawing
from native_drawing.backend import convert_drawing_native
from native_drawing.dwg import adapter_dxf, validate_roundtrip, signature, same
from native_drawing.setup_dwg import verified_files
from drawings import convert_upload, prepare_upload


def string(value):
    return b'\xff\xfe\xff'+bytes([len(value)])+value.encode('utf-16le')


def line(a=(0, 0, 0), b=(.02, .01, 0)):
    return struct.pack('<II6dB', 80, 4, *a, *b, 0)


def matrix():
    return [1, 0, 0, 0, 1, 0, 0, 0, 1, .05, .04, 0, 1]


def drawing_entries():
    setup = struct.pack('<II4IHfIQ', 60, 9, 0, 0, 0, 0, 0, 0, 0, 0)
    display = (struct.pack('<I', 1)+b'authored opaque metadata'
               +struct.pack('<H', 2)+setup+line()
               +struct.pack('<2d', .2794, .4318)+string('Sheet1-Active')
               +struct.pack('<2IB4dBI', 1, 1, 0, 0, 0, 0, 0, 0, 1)
               +struct.pack('<IH', 1, 1)+line()
               +struct.pack('<B13d', 1, *matrix())+string('Default_Display State')+struct.pack('<3IH', 1, 0, 0xffffffff, 0)
               +bytes(16)+string('')+struct.pack('<3I', 1, 3, 0))
    vb = (struct.pack('<I3d', 1, 0, 0, 1)+bytes(28)+struct.pack('<5I', 0, 1, 0, 1, 801)
          +struct.pack('<I6d', 2, 0, 0, 0, .02, .01, 0)+string('Test-1@Drawing View1'))
    definition = b'moAbsoluteView'+string('Drawing View1')+b'opaque'+struct.pack('<13d', *matrix())
    return {'Contents/DisplayLists': display, 'Contents/VBLists': vb,
            'Contents/Definition': definition, 'SheetPreviews/SheetNames': struct.pack('<H', 1)+string('Sheet1')+bytes(4)}


def sample_drawing(path):
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in drawing_entries().items():
            archive.writestr(name, data)


def upload(name, data):
    value = io.BytesIO(data)
    value.name, value.size = name, len(data)
    return value


class DrawingCommandsTests(unittest.TestCase):
    def test_sequential_sizes_are_not_serialized_lengths(self):
        reader = Commands(line()+line())
        self.assertEqual(reader.read(2), 114)
        self.assertEqual(len(reader.primitives), 2)
        with self.assertRaisesRegex(ValueError, 'Unsupported drawing command'):
            Commands(struct.pack('<II', 80, 999)+line()).read(2)

    def test_bounds_nonfinite_counts_and_nesting(self):
        for data in (line()[:-1], line(b=(float('nan'), 0, 0))):
            with self.assertRaises(ValueError):
                Commands(data).read(1)
        with self.assertRaises(ValueError):
            Commands(b'').read(20001)
        with self.assertRaises(ValueError):
            Commands(b'').read(0, depth=5)

    def test_font_and_rotated_text_preserve_native_advances(self):
        font = (struct.pack('<II2dIdI', 126, 10, .002, 0, 0, 1, 128)
                +string('Century Gothic')+struct.pack('<2d', 1, 0))
        text = (struct.pack('<II3dIdI', 150, 18, .1, .1, 0, 0, math.pi/2, 0)
                +string('AB')+struct.pack('<HI2fId', 1, 2, .001, .003, 0, 0))
        reader = Commands(font+text); reader.read(2)
        result = reader.primitives[0]
        self.assertEqual(result['text'], 'AB')
        self.assertAlmostEqual(result['angle'], math.pi/2)
        self.assertAlmostEqual(sum(result['advances']), .004)

    def test_scene_uses_saved_transform_and_sheet_size(self):
        scene = decode_scene(drawing_entries())
        self.assertEqual(scene['size_m'], [.4318, .2794])
        self.assertEqual(scene['views'][0]['curves'][0]['projected'][1], [.07, .05, 0])
        self.assertFalse(scene['production_supported'])
        self.assertTrue(scene['opaque_prefix_bytes'])

    def test_multiple_sheets_unmapped_views_and_unknown_tail_fail(self):
        entries = drawing_entries()
        entries['SheetPreviews/SheetNames'] = struct.pack('<H', 2)+entries['SheetPreviews/SheetNames'][2:]
        with self.assertRaisesRegex(ValueError, 'Multiple-sheet'):
            decode_scene(entries)
        entries = drawing_entries()
        entries['Contents/DisplayLists'] += b'unknown'
        with self.assertRaisesRegex(ValueError, 'tail'):
            decode_scene(entries)
        entries = drawing_entries()
        entries['Contents/Definition'] = b'unknown'
        with self.assertRaisesRegex(ValueError, 'transform'):
            decode_scene(entries)

    def test_circular_validation_refuses_irregular_or_reversed_samples(self):
        pts = [[.02*math.cos(a), .02*math.sin(a), 0] for a in (0, .3, .6, .9)]
        self.assertAlmostEqual(circular(pts)['radius'], .02)
        pts[1][0] += .001
        with self.assertRaises(ValueError):
            circular(pts)

    def test_exact_spline_is_not_fitted_from_cached_points(self):
        from OCP.Geom import Geom_BSplineCurve
        from OCP.gp import gp_Pnt
        from OCP.TColgp import TColgp_Array1OfPnt
        from OCP.TColStd import TColStd_Array1OfReal, TColStd_Array1OfInteger
        poles = TColgp_Array1OfPnt(1, 4)
        coordinates = [(0, 0, 0), (2, 6, 0), (8, 6, 0), (10, 0, 0)]
        for i, point in enumerate(coordinates, 1):
            poles.SetValue(i, gp_Pnt(*point))
        knots, mult = TColStd_Array1OfReal(1, 2), TColStd_Array1OfInteger(1, 2)
        knots.SetValue(1, 0); knots.SetValue(2, 1); mult.SetValue(1, 4); mult.SetValue(2, 4)
        curve = Geom_BSplineCurve(poles, knots, mult, 3)
        points = [[v/1000 for v in curve.Value(u).Coord()] for u in (0, .25, .5, .75, 1)]
        result = resolve_spline(points, [(42, curve)], matrix())
        self.assertEqual(result['source_curve'], 42)
        for actual, expected in zip(result['poles'], coordinates):
            self.assertTrue(same(actual, transform([v/1000 for v in expected], matrix())))
        with self.assertRaisesRegex(ValueError, 'unique'):
            resolve_spline(points, [(42, curve), (43, curve)], matrix())
        points[2][1] += .001
        with self.assertRaises(ValueError):
            resolve_spline(points, [(42, curve)], matrix())

    def test_isometric_circle_projects_to_analytic_ellipse(self):
        rotation = [0.5, 0, -math.sqrt(.75), 0, 1, 0, math.sqrt(.75), 0, .5, 0, 0, 0, 1]
        points = [[.01*math.cos(i*math.tau/16), .01*math.sin(i*math.tau/16), 0] for i in range(17)]
        curve = projected_circle(points, rotation)
        self.assertEqual(curve['kind'], 'ellipse')
        self.assertAlmostEqual(curve['ratio'], .5)
        self.assertAlmostEqual(math.hypot(*curve['major']), .01)
        for p in points:
            x,y,_ = transform(p, rotation)
            self.assertAlmostEqual((x/.005)**2+(y/.01)**2, 1)
        with self.assertRaisesRegex(ValueError, 'Too few'):
            projected_circle(points[:3], rotation)
        points[4][2] = .001
        with self.assertRaises(ValueError):
            projected_circle(points, rotation)

    def test_spatial_annotation_circle_preserves_projected_ellipse(self):
        item = {'kind': 'arc', 'style': 'CONTINUOUS', 'center': [0, 0, 0],
                'start': [.01, 0, 0], 'end': [.01, 0, 0],
                'normal': [0, math.sqrt(.75), .5]}
        result = flatten_arc(item)
        self.assertEqual(result['kind'], 'ellipse')
        self.assertAlmostEqual(result['ratio'], .5)
        self.assertAlmostEqual(abs(result['sweep']), math.tau)

    def test_reused_view_class_reference_and_ambiguous_transforms(self):
        definition = b'opaque'+struct.pack('<H',0x80d8)+string('Reused View')+struct.pack('<13d',*matrix())
        self.assertEqual(saved_transform(definition,'Reused View',[.4318,.2794],matrix()[:9]),matrix())
        another = matrix(); another[9] += .01
        definition += struct.pack('<H',0x80d8)+string('Reused View')+struct.pack('<13d',*another)
        with self.assertRaisesRegex(ValueError,'ambiguous'):
            saved_transform(definition,'Reused View',[.4318,.2794],matrix()[:9])

    def test_display_state_suffix_commands_are_consumed_and_retained(self):
        data = (struct.pack('<B13d',1,*matrix())+string('Default_Appearance Display State')
                +struct.pack('<3IH',1,0,0xffffffff,1)+line())
        offset, span, rotation, primitives = view_tail(data,0)
        self.assertEqual(offset,len(data))
        self.assertEqual(primitives[0]['kind'],'line')
        with self.assertRaises(ValueError):
            view_tail(data[:-1],0)

    def test_hidden_and_additional_visible_groups_are_validated(self):
        entries = drawing_entries()
        def group(kind):
            return struct.pack('<5I6d',1,99,1,kind,2,0,0,0,.02,.01,0)
        entries['Contents/VBLists'] = (struct.pack('<I3d',1,0,0,1)+bytes(28)
                                      +group(817)+group(801)+group(801)+string('Test-1@Drawing View1'))
        scene = decode_scene(entries)
        view = scene['views'][0]
        self.assertEqual([p['style'] for p in view['curves']],['HIDDEN','CONTINUOUS','HIDDEN'])
        self.assertEqual([p['count'] for p in view['groups']],[1,1,1])
        broken = bytearray(entries['Contents/VBLists']);struct.pack_into('<I',broken,56,2)
        entries['Contents/VBLists'] = bytes(broken)
        with self.assertRaisesRegex(ValueError,'visibility'):
            decode_scene(entries)


class DrawingOutputTests(unittest.TestCase):
    def test_worker_and_isolated_backend_export_without_network(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); source = root/'Authored.SLDDRW'; sample_drawing(source)
            with patch('urllib.request.urlopen', side_effect=AssertionError('Network prohibited')):
                report = export_drawing(source, root/'direct')
            page = PdfReader(root/'direct'/report['exports']['pdf']['file']).pages[0]
            self.assertIn(NOTICE, page.extract_text())
            self.assertAlmostEqual(float(page.mediabox.width), 1224)
            self.assertAlmostEqual(float(page.mediabox.height), 792)
            self.assertNotIn('/XObject', page['/Resources'])
            self.assertIsInstance(report['exports']['pdf']['font_substituted'], bool)
            with self.assertRaises(FileExistsError):
                export_drawing(source, root/'direct')
            result = convert_drawing_native(source, root/'isolated')
            self.assertFalse(result['production_supported'])
            self.assertEqual(result['geometry']['geometry_primitives'], 1)

    def test_filled_paths_continue_across_native_line_commands(self):
        from reportlab.pdfgen import canvas
        c = canvas.Canvas(io.BytesIO()); path = c.beginPath()
        append_path(path, [('line', [[0, 0], [1, 0]])], 1)
        append_path(path, [('line', [[1, 0], [1, 1]])], 1)
        self.assertEqual(path.getCode().count(' m'), 1)

    def test_dxf_units_splines_text_rotation_and_hole_entities(self):
        font = {'family': 'Century Gothic', 'em_points': 10, 'width': 1, 'flags': 128}
        scene = {'size_m': [.4318, .2794], 'primitives': [
            {'kind': 'text', 'style': 'CONTINUOUS', 'font': font, 'origin': [.05, .05, 0],
             'text': '12', 'advances': [.003, .003], 'angle': math.pi/2}]}
        geometry = [{'kind': 'circle', 'style': 'CONTINUOUS', 'center': [.1, .1, 0],
                     'radius': .005, 'angle': 0, 'sweep': math.tau},
                    {'kind': 'spline', 'style': 'CONTINUOUS', 'degree': 3,
                     'poles': [[0, 0, 0], [.01, .02, 0], [.02, .02, 0], [.03, 0, 0]],
                     'knots': [0]*4+[1]*4}]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'output.dxf'; write_dxf(scene, geometry, path)
            doc = ezdxf.readfile(path); model = doc.modelspace()
            self.assertEqual(doc.units, 4)
            self.assertAlmostEqual(model.query('CIRCLE')[0].dxf.radius, 5)
            self.assertEqual(list(model.query('SPLINE')[0].control_points)[-1][0], 30)
            self.assertAlmostEqual(model.query('TEXT')[0].dxf.rotation, 90)
            self.assertTrue(any(e.dxf.text == NOTICE for e in model.query('TEXT')))

    def test_dwg_checks_detect_changed_curves_text_units_or_dropped_entities(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); before, after = root/'a.dxf', root/'b.dxf'
            doc = ezdxf.new('R2000'); doc.units = 4
            doc.modelspace().add_line((0, 0), (10, 20))
            doc.modelspace().add_text('17', dxfattribs={'height': 2})
            doc.modelspace().add_ellipse((0,0),major_axis=(10,0,0),ratio=.5)
            doc.saveas(before); doc.saveas(after)
            self.assertTrue(validate_roundtrip(before, after)['roundtrip_verified'])
            doc.modelspace().query('LINE')[0].dxf.end = (10, 21)
            doc.saveas(after)
            with self.assertRaisesRegex(ValueError, 'changed entity'):
                validate_roundtrip(before, after)
            doc = ezdxf.readfile(before); doc.units = 1; doc.saveas(after)
            with self.assertRaisesRegex(ValueError, 'units'):
                validate_roundtrip(before, after)
            doc = ezdxf.readfile(before); doc.modelspace().query('TEXT')[0].dxf.text = '18'; doc.saveas(after)
            with self.assertRaisesRegex(ValueError, 'changed entity'):
                validate_roundtrip(before, after)
            doc.modelspace().delete_entity(doc.modelspace().query('TEXT')[0]); doc.saveas(after)
            with self.assertRaisesRegex(ValueError, 'lost'):
                validate_roundtrip(before, after)

    def test_dwg_adapter_preserves_text_that_looks_like_a_handle(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); source, output = root/'a.dxf', root/'adapter.dxf'
            doc = ezdxf.new('R2000'); doc.units = 4
            model_handle = doc.block_records.get('*Model_Space').dxf.handle
            doc.modelspace().add_text(model_handle, dxfattribs={'height': 2})
            doc.saveas(source); adapter_dxf(source, output)
            adapted = ezdxf.readfile(output)
            self.assertEqual(adapted.block_records.get('*Model_Space').dxf.handle, '1F')
            self.assertEqual(adapted.modelspace().query('TEXT')[0].dxf.text, model_handle)
            self.assertNotIn('ACAD_MATERIAL', output.read_text(encoding='cp1252'))

    def test_dwg_download_integrity_is_mandatory(self):
        with self.assertRaisesRegex(ValueError, 'checksum'):
            verified_files(b'untrusted zip')

    def test_dwg_failure_keeps_pdf_dxf_and_reports_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); source = root/'Test.slddrw'; sample_drawing(source)
            with patch('native_drawing.dwg.write_dwg', side_effect=ValueError('lost curve')):
                report = export_drawing(source, root/'output', dwg=True)
            self.assertEqual(report['exports']['dwg'], {'error': 'lost curve'})
            self.assertEqual(len(list((root/'output').glob('*.pdf'))), 1)
            self.assertEqual(len(list((root/'output').glob('*.dxf'))), 1)
            self.assertFalse(list((root/'output').glob('*.dwg')))

    def test_failed_writer_removes_only_its_new_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); source = root/'Test.slddrw'; sample_drawing(source)
            with patch('native_drawing.worker.write_dxf', side_effect=ValueError('bad curve')):
                with self.assertRaisesRegex(ValueError, 'bad curve'):
                    export_drawing(source, root/'output')
            self.assertFalse((root/'output').exists())
            self.assertTrue(source.exists())

    def test_drawing_tab_converts_without_po_and_hides_stale_downloads(self):
        from streamlit.testing.v1 import AppTest
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp)/'Test.slddrw'; sample_drawing(source)
            current = [upload(source.name, source.read_bytes())]
            def uploader(label, *args, **kwargs):
                if label == 'SolidWorks drawing (.slddrw)':
                    return current[0]
                return [] if kwargs.get('accept_multiple_files') else None
            with patch('streamlit.file_uploader', side_effect=uploader), patch('core.find_files', side_effect=AssertionError('Searched network drive')):
                app = AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'), default_timeout=20).run()
                self.assertFalse(app.exception)
                app.session_state['completed_job'] = {'sentinel': 'unchanged PO'}
                next(b for b in app.button if b.label == 'Create experimental drawing exports').click().run()
                self.assertFalse(app.exception)
                self.assertEqual(app.session_state['completed_job'], {'sentinel': 'unchanged PO'})
                result = app.session_state['native_drawing_result']
                self.assertEqual(set(result['outputs']), {'Test-EXPERIMENTAL.pdf', 'Test-EXPERIMENTAL.dxf'})
                self.assertTrue(any(b.label == 'Download experimental drawing ZIP' for b in app.get('download_button')))
                current[0] = upload('Changed.slddrw', b'changed input')
                app.run()
                self.assertNotIn('native_drawing_result', app.session_state)
                self.assertFalse(any(b.label == 'Download experimental drawing ZIP' for b in app.get('download_button')))
                next(b for b in app.button if b.label == 'Create experimental drawing exports').click().run()
                self.assertFalse(app.exception)
                self.assertTrue(app.error)
                self.assertNotIn('native_drawing_result', app.session_state)

    def test_uploads_zip_outputs_failures_and_source_preservation(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp)/'Authored.slddrw'; sample_drawing(source)
            data = source.read_bytes(); drawing = upload(source.name, data)
            result = convert_upload(drawing)
            self.assertEqual(drawing.getvalue(), data)
            with zipfile.ZipFile(io.BytesIO(result['zip'])) as archive:
                self.assertEqual(set(archive.namelist()), {'Authored-EXPERIMENTAL.pdf',
                                                          'Authored-EXPERIMENTAL.dxf', 'drawing-report.json'})
                self.assertFalse(json.loads(archive.read('drawing-report.json'))['production_supported'])
            with self.assertRaisesRegex(ValueError, 'matching part'):
                convert_upload(drawing, upload('Wrong.sldprt', b'not CAD'))
            for name in ('../bad.slddrw', r'C:\bad.slddrw', 'bad.pdf'):
                with self.assertRaises(ValueError):
                    prepare_upload(upload(name, data), '.slddrw')


if __name__ == '__main__':
    unittest.main()
