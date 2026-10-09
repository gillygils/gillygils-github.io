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
from native_drawing.scene import decode_scene, transform, saved_transform, view_tail, view_geometry
from native_drawing.curves import circular, resolve_spline, projected_circle, part_splines, drawing_geometry
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

def saved_matrix(values=None, compact=False):
    values = matrix() if values is None else values
    return (struct.pack('<IIB',1,0,0 if compact else 1)
            +struct.pack('<4d' if compact else '<13d',*(values[9:] if compact else values)))

def bucket_header(mode=0):
    return (b'\xff\xff'+struct.pack('<HH',1,14)+b'uiViewBucket_c'
            +struct.pack('<3d2IdI',0,0,1,mode,0,1,25)
            +bytes(4 if mode == 1 else 8))

def bucket_label(value):
    return struct.pack('<HI',1,1)+string(value)

def curve_group(kind=801, a=(0,0,0), b=(.02,.01,0), identity=99):
    return struct.pack('<5I6d',1,identity,1,kind,2,*a,*b)


def drawing_entries():
    setup = struct.pack('<II4IHfIQ', 60, 9, 0, 0, 0, 0, 0, 0, 0, 0)
    display = (struct.pack('<I', 1)+b'authored opaque metadata'
               +struct.pack('<IH', 1, 2)+setup+line()
               +struct.pack('<2d', .2794, .4318)+string('Sheet1-Active')
               +struct.pack('<2IB4dBI', 1, 1, 0, 0, 0, 0, 0, 0, 1)
               +struct.pack('<IH', 1, 1)+line()
               +struct.pack('<B13d', 1, *matrix())+string('Default_Display State')+struct.pack('<3IH', 1, 0, 0xffffffff, 0)
               +bytes(16)+string('')+struct.pack('<3I', 1, 3, 0))
    vb = (struct.pack('<I',1)+bucket_header()+struct.pack('<5I', 0, 1, 0, 1, 801)
          +struct.pack('<I6d', 2, 0, 0, 0, .02, .01, 0)+bucket_label('Test-1@Drawing View1'))
    definition = b'moAbsoluteView'+string('Drawing View1')+b'opaque'+saved_matrix()
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
    def test_unsupported_optional_part_splines_are_reported_without_losing_supported_candidates(self):
        records = [
            {'identity':1,'type':134,'fields':{'nurbs':10}},
            {'identity':2,'type':134,'fields':{'nurbs':20}},
            {'identity':10,'type':136,'fields':{'periodic':0,'rational':0,'vertex_dim':3,
             'n_vertices':4,'n_knots':2,'degree':3,'bspline_vertices':11,'knots':12,'knot_mult':13}},
            {'identity':20,'type':136,'fields':{'periodic':1,'rational':0,'vertex_dim':3}},
            {'identity':11,'type':45,'variable':[0,0,0,.002,.006,0,.008,.006,0,.01,0,0]},
            {'identity':12,'type':128,'variable':[0,1]},
            {'identity':13,'type':127,'variable':[4,4]},
        ]
        with patch('native_part.model.load_model',return_value=({'records':records},{'configuration':'Authored'})):
            candidates,metadata=part_splines('Authored.SLDPRT')
        self.assertEqual(len(candidates),1)
        self.assertEqual(candidates[0][0],1)
        self.assertEqual(candidates[0][1].NbPoles(),4)
        self.assertEqual(metadata['unsupported_spline_candidates'][0]['identity'],2)
        # A broken supported curve is still an error, not an approximation.
        records[4]['variable']=records[4]['variable'][:-1]
        with patch('native_part.model.load_model',return_value=({'records':records},{})):
            with self.assertRaisesRegex(ValueError,'array sizes'):part_splines('Authored.SLDPRT')

    def test_polyline_arrays_preserve_connected_segments_and_reject_bad_layouts(self):
        data = struct.pack('<III12dI',144,5,4,0,0,0,.01,0,0,.01,0,0,.01,.02,0,0)
        reader = Commands(data+line());reader.read(2)
        self.assertEqual(reader.offset,len(data)+len(line()))
        self.assertEqual(len(reader.primitives),2)
        self.assertEqual(reader.primitives[0]['kind'],'polyline')
        self.assertEqual(reader.primitives[0]['points'][-1],[.01,.02,0])
        odd=struct.pack('<III9dI',120,5,3,0,0,0,.01,0,0,.01,.02,0,0)
        parsed=Commands(odd+line());parsed.read(2)
        self.assertEqual(parsed.offset,len(odd+line()))
        self.assertEqual(len(parsed.primitives[0]['points']),3)
        for offset,value in ((0,145),(8,1),(len(data)-4,1)):
            broken=bytearray(data);struct.pack_into('<I',broken,offset,value)
            with self.assertRaisesRegex(ValueError,'polyline'):
                Commands(bytes(broken)).read(1)

    def test_compact_component_reference_without_points_preserves_following_command(self):
        for node in (3,6,7,8):
            group=(struct.pack('<II8I',90,29,199,node,2,0,1,123,0,1)
                   +string('')+struct.pack('<2I',4,1)
                   +b''.join(string(v) for v in ('Test@View','','',''))
                   +struct.pack('<6I',5,0,0,0,0,0)
                   +b''.join(string(v) for v in ('','','','<objID=1>')))
            reader=Commands(group+line());reader.read(2)
            self.assertEqual(reader.offset,len(group+line()))
            self.assertEqual(reader.primitives[0]['kind'],'line')
        broken=bytearray(group);struct.pack_into('<I',broken,32,3)
        with self.assertRaisesRegex(ValueError,'point count'):Commands(bytes(broken)).read(1)
        broken=bytearray(group);struct.pack_into('<I',broken,24,3)
        with self.assertRaisesRegex(ValueError,'reference count'):Commands(bytes(broken)).read(1)

    def test_full_circle_flag_requires_identical_endpoints(self):
        data=struct.pack('<II12dI',128,2,.01,0,0,.01,0,0,0,0,0,0,0,1,1)
        reader=Commands(data+line());reader.read(2)
        self.assertEqual(reader.offset,len(data+line()))
        self.assertEqual(reader.primitives[0]['start'],reader.primitives[0]['end'])
        broken=bytearray(data);struct.pack_into('<d',broken,32,.02)
        with self.assertRaisesRegex(ValueError,'arc flags'):Commands(bytes(broken)).read(1)

    def test_font_record_size_tracks_unicode_family_without_skipping_unknown_sizes(self):
        data=struct.pack('<II2dIdI',104,10,.002,0,0,1,128)+string('TXT')+struct.pack('<2d',1,0)
        reader=Commands(data+line());reader.read(2)
        self.assertEqual(reader.font['family'],'TXT')
        self.assertEqual(reader.offset,len(data+line()))
        broken=bytearray(data);struct.pack_into('<I',broken,0,106)
        with self.assertRaisesRegex(ValueError,'font record size'):Commands(bytes(broken)).read(1)

    def test_single_glyph_text_without_advances_keeps_the_next_command_aligned(self):
        font = (struct.pack('<II2dIdI',126,10,.002,0,0,1,0)
                +string('Century Gothic')+struct.pack('<2d',1,0))
        text = (struct.pack('<II3dIdI',156,18,.1,.1,0,0,0,0)
                +string('A')+struct.pack('<HId',0,0,1))
        reader=Commands(font+text+line());reader.read(3)
        self.assertEqual(reader.offset,len(font+text+line()))
        self.assertEqual(reader.primitives[0]['text'],'A')
        self.assertEqual(reader.primitives[0]['advances'],[0.])
        self.assertEqual(reader.primitives[1]['kind'],'line')
        unsupported=text.replace(string('A'),string('AB'))
        with self.assertRaisesRegex(ValueError,'text framing'):
            Commands(font+unsupported).read(2)
        unsupported=text[:-8]+struct.pack('<d',2)
        with self.assertRaisesRegex(ValueError,'single-glyph text suffix'):
            Commands(font+unsupported).read(2)

    def test_section_component_annotation_and_phantom_style_preserve_following_line(self):
        group = (struct.pack('<II8I6dI',90,29,199,8,2,1,2,123,124,2,*([0.]*6),1)
                 +string('')+struct.pack('<2I',4,1)
                 +b''.join(string(v) for v in ('Test@View','','',''))
                 +struct.pack('<6I',5,0,0,0,0,0)
                 +b''.join(string(v) for v in ('','','','<objID=1>')))
        style=struct.pack('<IIIHfQ',72,12,0,2,-1,0)+string('PHANTOM')
        reader=Commands(group+style+line());reader.read(3)
        self.assertEqual(reader.offset,len(group+style+line()))
        self.assertEqual(reader.primitives[0]['style'],'PHANTOM')

    def test_compact_identity_view_consumes_only_its_own_metadata(self):
        first = (struct.pack('<B4d',0,*matrix()[9:])+string('Default_Display State')
                 +struct.pack('<3IH',1,0,0xffffffff,1)+line())
        offset,span,pose,primitives=view_tail(first+b'next-view',0)
        self.assertEqual(offset,len(first));self.assertEqual(pose,matrix())
        self.assertEqual(primitives[0]['kind'],'line')
        with self.assertRaises(ValueError):view_tail(first[:-1],0)
        with self.assertRaisesRegex(ValueError,'metadata framing'):view_tail(b'\x02'+first[1:],0)

    def test_framed_compact_transform_rejects_unframed_or_ambiguous_poses(self):
        definition = b'moAbsoluteView'+string('Drawing View1')+struct.pack('<13d',*matrix())
        with self.assertRaisesRegex(ValueError,'unsupported'):
            saved_transform(definition,'Drawing View1',[.4318,.2794],matrix())
        definition += saved_matrix(compact=True)
        self.assertEqual(saved_transform(definition,'Drawing View1',[.4318,.2794],matrix()),matrix())
        another=matrix();another[9]+=.01
        with self.assertRaisesRegex(ValueError,'ambiguous'):
            saved_transform(definition+saved_matrix(another,compact=True),'Drawing View1',[.4318,.2794],matrix())

    def test_sheet_command_suffix_without_list_header_is_not_a_second_sheet_candidate(self):
        entries=drawing_entries();data=entries['Contents/DisplayLists']
        setup=struct.pack('<II4IHfIQ',60,9,0,0,0,0,0,0,0,0)
        fake_count=struct.pack('<II4IHfIQ',60,9,0,0,0,0,0,0,0,2<<48)
        entries['Contents/DisplayLists']=data.replace(
            struct.pack('<IH',1,2)+setup+line(),struct.pack('<IH',1,3)+fake_count+setup+line(),1)
        scene=decode_scene(entries)
        self.assertEqual(scene['size_m'],[.4318,.2794])

    def test_observed_tail_variant_eight_does_not_allow_unknown_or_extra_bytes(self):
        entries=drawing_entries();data=entries['Contents/DisplayLists']
        entries['Contents/DisplayLists']=data[:-12]+struct.pack('<3I',1,8,0)
        self.assertEqual(decode_scene(entries)['display_tail_variant'],8)
        for tail in (struct.pack('<3I',1,9,0),struct.pack('<3I',1,8,1),struct.pack('<3I',1,8,0)+b'new sheet'):
            entries['Contents/DisplayLists']=data[:-12]+tail
            with self.assertRaisesRegex(ValueError,'drawing tail'):decode_scene(entries)

    def test_empty_saved_views_match_null_bucket_pointers_without_eating_next_view(self):
        entries=drawing_entries();data=entries['Contents/DisplayLists']
        framing=struct.pack('<2IB4dBI',1,1,0,0,0,0,0,0,1)
        empty=(struct.pack('<IB4d',0,0,*matrix()[9:])+string('Default_Display State')
               +struct.pack('<3I',1,0,0xffffffff))
        entries['Contents/DisplayLists']=data.replace(framing,framing[:-4]+struct.pack('<I',2)+empty,1)
        entries['Contents/VBLists']=struct.pack('<IH',2,0)+entries['Contents/VBLists'][4:]
        scene=decode_scene(entries)
        self.assertEqual(scene['empty_saved_views'],1);self.assertEqual(len(scene['views']),1)
        broken=bytearray(entries['Contents/VBLists']);struct.pack_into('<H',broken,4,1)
        entries['Contents/VBLists']=bytes(broken)
        with self.assertRaisesRegex(ValueError,'empty view pointers'):decode_scene(entries)

    def test_mode_one_groups_hidden_arrays_before_visible_arrays(self):
        data=(struct.pack('<I',1)+bucket_header(1)+curve_group(817)+curve_group(817)
              +curve_group(801)+curve_group(801)+bucket_label('Test@Drawing View1'))
        definition=b'moAbsoluteView'+string('Drawing View1')+saved_matrix()
        view=view_geometry(data,definition,[.4318,.2794],[matrix()])[0]
        self.assertEqual([c['style'] for c in view['curves']],['HIDDEN','HIDDEN','CONTINUOUS','CONTINUOUS'])
        broken=data.replace(curve_group(801)+curve_group(801),curve_group(801)+curve_group(817),1)
        with self.assertRaisesRegex(ValueError,'hidden group ordering'):
            view_geometry(broken,definition,[.4318,.2794],[matrix()])

    def test_interleaved_empty_views_use_only_populated_display_transforms(self):
        first=bucket_header()+struct.pack('<I',0)+curve_group()+bucket_label('A@Drawing View1')
        second=bucket_header()+struct.pack('<I',0)+curve_group()+bucket_label('B@Drawing View2')
        pose=matrix();pose[9]=.09
        definition=(b'moAbsoluteView'+string('Drawing View1')+saved_matrix()
                    +b'moUnfoldedView'+string('Drawing View2')+saved_matrix(pose))
        data=struct.pack('<I',3)+first+bytes(2)+second
        views=view_geometry(data,definition,[.4318,.2794],[matrix(),[0]*13,pose],[True,False,True])
        self.assertEqual([v['transform'][9] for v in views],[.05,.09])
        with self.assertRaisesRegex(ValueError,'mapping'):
            view_geometry(data,definition,[.4318,.2794],[matrix(),pose,pose],[True,True,True])

    def test_two_reference_curves_and_two_label_entries_keep_the_primary_view(self):
        group=bytearray(curve_group(817));struct.pack_into('<I',group,8,2)
        data=(struct.pack('<I',1)+bucket_header()+bytes(group)
              +struct.pack('<HI',2,1)+string('Test@Drawing View1')
              +struct.pack('<I',2)+string('Test@Drawing View1'))
        definition=b'moAbsoluteView'+string('Drawing View1')+saved_matrix()
        view=view_geometry(data,definition,[.4318,.2794],[matrix()])[0]
        self.assertEqual(len(view['curves']),1)
        self.assertEqual(view['curves'][0]['style'],'HIDDEN')

    def test_short_camera_header_accepts_mode_three_but_rejects_invalid_basis(self):
        header=bucket_header(3)[:-4]
        data=struct.pack('<I',1)+header+curve_group(817)+bucket_label('Test@Drawing View1')
        definition=b'moAbsoluteView'+string('Drawing View1')+saved_matrix()
        view=view_geometry(data,definition,[.4318,.2794],[matrix()])[0]
        self.assertEqual(view['curves'][0]['style'],'HIDDEN')
        broken=bytearray(data);struct.pack_into('<d',broken,40,2)
        with self.assertRaisesRegex(ValueError,'camera basis'):
            view_geometry(bytes(broken),definition,[.4318,.2794],[matrix()])

    def test_verified_section_selection_copies_are_excluded_and_changed_copies_fail(self):
        first=(bucket_header()+struct.pack('<I',0)+curve_group(801)+bucket_label('A@Drawing View1'))
        # The post-label array has a sentinel identity and identical points.
        copy=bytes(20)+curve_group(801,identity=0xffffffff)
        second=bucket_header()+struct.pack('<I',0)+curve_group(801)+bucket_label('B@Drawing View2')
        definition=(b'moAbsoluteView'+string('Drawing View1')+saved_matrix()
                    +b'moUnfoldedView'+string('Drawing View2')+saved_matrix())
        data=struct.pack('<I',2)+first+copy+second
        views=view_geometry(data,definition,[.4318,.2794],[matrix(),matrix()])
        self.assertEqual([len(v['curves']) for v in views],[1,1])
        self.assertEqual(views[0]['verified_selection_copies'],1)
        broken=data.replace(copy,bytes(20)+curve_group(801,b=(.03,.01,0),identity=0xffffffff),1)
        with self.assertRaisesRegex(ValueError,'selection curves differ'):
            view_geometry(broken,definition,[.4318,.2794],[matrix(),matrix()])

    def test_detail_plane_samples_keep_two_dimensions_and_skip_unrelated_shaded_labels(self):
        pose=[0,0,1,0,1,0,-1,0,0,.05,.04,0,1]
        definition=(b'moDetailView'+string('Detail1')+b'moDetailViewLabel_c'+string('Label')
                    +saved_matrix(pose))
        data=(struct.pack('<I',1)+bucket_header()+struct.pack('<I',0)
              +curve_group(769)+bucket_label('Test@Detail1')+string('Test@Detail1'))
        view=view_geometry(data,definition,[.4318,.2794],[pose])[0]
        self.assertEqual(view['coordinate_space'],'view_plane')
        self.assertEqual(view['curves'][0]['projected'][1],[.07,.05,0])
        with patch('native_drawing.curves.resolve_spline',side_effect=AssertionError('Used 2D samples as 3D part points')):
            geometry,report=drawing_geometry({'views':[view]})
        self.assertEqual(geometry[0]['kind'],'polyline')
        self.assertIn('projected samples',report['unresolved_splines'][0]['reason'])

    def test_saved_point_is_consumed_without_skipping_following_geometry(self):
        point = struct.pack('<II3d2I',56,1,.03,.04,0,2,0)
        reader = Commands(point+line()); reader.read(2)
        self.assertEqual(reader.offset,len(point)+len(line()))
        self.assertEqual(reader.primitives[0],
                         {'kind':'point','style':'CONTINUOUS','origin':[.03,.04,0], 'marker':2})
        self.assertEqual(reader.primitives[1]['kind'],'line')
        for marker,flags in ((3,0),(2,1)):
            with self.assertRaisesRegex(ValueError,'point marker'):
                Commands(struct.pack('<II3d2I',56,1,.03,.04,0,marker,flags)+line()).read(2)
        with self.assertRaisesRegex(ValueError,'Truncated'):
            Commands(point[:-1]).read(1)

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
        definition = b'opaque'+struct.pack('<H',0x80d8)+string('Reused View')+saved_matrix()
        self.assertEqual(saved_transform(definition,'Reused View',[.4318,.2794],matrix()[:9]),matrix())
        another = matrix(); another[9] += .01
        definition += struct.pack('<H',0x80d8)+string('Reused View')+saved_matrix(another)
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

    def test_numbered_display_state_does_not_consume_the_next_view(self):
        for label in ('Display State-2','Display State 2','Default_Display State-2'):
            first = (struct.pack('<B13d',1,*matrix())+string(label)
                     +struct.pack('<3IH',2,0,0xffffffff,1)+line())
            second = (struct.pack('<B13d',1,*matrix())+string('Default_Appearance Display State')
                      +struct.pack('<3IH',1,0,0xffffffff,0))
            offset,span,display,primitives = view_tail(first+second,0)
            self.assertEqual(offset,len(first))
            self.assertEqual(span,len(first))
            self.assertEqual(display,matrix())
            self.assertEqual(len(primitives),1)

    def test_saved_sheet_transform_uses_display_scale_and_depth(self):
        model = matrix(); model[12] = 2
        depth = matrix(); depth[11] = .01
        definition = (b'moUnfoldedView'+string('Drawing View1')
                      +saved_matrix(model)+saved_matrix(depth)+saved_matrix())
        with self.assertRaisesRegex(ValueError,'ambiguous'):
            saved_transform(definition,'Drawing View1',[.4318,.2794],matrix()[:9])
        self.assertEqual(saved_transform(definition,'Drawing View1',[.4318,.2794],matrix()),matrix())

    def test_scene_retains_points_and_reports_unverified_marker_appearance(self):
        entries = drawing_entries()
        point = struct.pack('<II3d2I',56,1,.03,.04,0,2,0)
        entries['Contents/DisplayLists'] = entries['Contents/DisplayLists'].replace(
            struct.pack('<IH',1,1)+line(),struct.pack('<IH',1,2)+point+line(),1)
        scene = decode_scene(entries)
        self.assertEqual(sum(p['kind']=='point' for p in scene['primitives']),1)
        self.assertTrue(any('marker appearance' in note for note in scene['limitations']))

    def test_hidden_and_additional_visible_groups_are_validated(self):
        entries = drawing_entries()
        def group(kind):
            return struct.pack('<5I6d',1,99,1,kind,2,0,0,0,.02,.01,0)
        entries['Contents/VBLists'] = (struct.pack('<I',1)+bucket_header()
                                      +group(817)+group(801)+group(801)+bucket_label('Test-1@Drawing View1'))
        scene = decode_scene(entries)
        view = scene['views'][0]
        self.assertEqual([p['style'] for p in view['curves']],['HIDDEN','CONTINUOUS','HIDDEN'])
        self.assertEqual([p['count'] for p in view['groups']],[1,1,1])
        broken = bytearray(entries['Contents/VBLists']);struct.pack_into('<I',broken,76,2)
        entries['Contents/VBLists'] = bytes(broken)
        with self.assertRaisesRegex(ValueError,'visibility'):
            decode_scene(entries)


class DrawingOutputTests(unittest.TestCase):
    def test_dwg_check_rejects_changed_dash_gap_signs(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);before,after=root/'a.dxf',root/'b.dxf'
            doc=ezdxf.new('R2000');doc.units=4
            doc.linetypes.new('PHANTOM',dxfattribs={'pattern':[6,3,-1,1,-1]})
            doc.modelspace().add_line((0,0),(10,0),dxfattribs={'linetype':'PHANTOM'})
            doc.saveas(before)
            pattern=doc.linetypes.get('PHANTOM').pattern_tags.tags
            index=next(i for i,t in enumerate(pattern) if t.code==49 and t.value<0)
            pattern[index]=type(pattern[index])(49,abs(pattern[index].value))
            doc.saveas(after)
            with self.assertRaisesRegex(ValueError,'line pattern'):validate_roundtrip(before,after)

    def test_phantom_style_is_saved_in_pdf_and_dxf(self):
        scene={'size_m':[.4318,.2794],'primitives':[
            {'kind':'line','style':'PHANTOM','start':[.03,.04,0],'end':[.06,.04,0]}]}
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);write_pdf(scene,[],root/'a.pdf');write_dxf(scene,[],root/'a.dxf')
            data=PdfReader(root/'a.pdf').pages[0].get_contents().get_data()
            self.assertIn(b'[90 18 18 18 18 18]',data)
            doc=ezdxf.readfile(root/'a.dxf')
            self.assertEqual(doc.modelspace().query('LINE')[0].dxf.linetype,'PHANTOM')
            self.assertEqual([tag.value for tag in doc.linetypes.get('PHANTOM').pattern_tags.tags if tag.code==49],
                             [31.75,-6.35,6.35,-6.35,6.35,-6.35])

    def test_point_is_preserved_in_vector_pdf_dxf_and_roundtrip_validation(self):
        scene = {'size_m':[.4318,.2794],'primitives':[
            {'kind':'point','style':'CONTINUOUS','origin':[.03,.04,0],'marker':2}]}
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); before,after=root/'a.dxf',root/'b.dxf'
            write_pdf(scene,[],root/'a.pdf');write_dxf(scene,[],before)
            page=PdfReader(root/'a.pdf').pages[0]
            self.assertNotIn('/XObject',page['/Resources'])
            self.assertIn(b' c',page.get_contents().get_data())
            doc=ezdxf.readfile(before); point=doc.modelspace().query('POINT')[0]
            self.assertEqual(tuple(point.dxf.location),(30,40,0))
            doc.saveas(after)
            self.assertTrue(validate_roundtrip(before,after)['roundtrip_verified'])
            point.dxf.location=(30,41,0);doc.saveas(after)
            with self.assertRaisesRegex(ValueError,'changed entity'):
                validate_roundtrip(before,after)

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
                if kwargs.get('key') == 'native_drawing_upload':
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
