"""Authored geometry regressions; no private SolidWorks assets are included."""
import copy
import math
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_native_conversion import cube_records, binary_stream, sample_part
from native_part.entities import Cursor, DecodeError, LAYOUTS, read_schema, decode_prefix
from native_part.geometry import Geometry, GeometryError, point
from native_part.backend import convert_part_native
from native_part.worker import convert
from experimental.step_reference import analyze_step


def two_cubes():
    records=cube_records()
    second=copy.deepcopy(cube_records()[1:])
    shift=len(records)-1
    for record in second:
        record['identity']+=shift
        fields=record['fields']
        for name,kind,count in LAYOUTS[record['type']]:
            if kind=='p' and fields.get(name):
                fields[name]=1 if fields[name]==1 else fields[name]+shift
        if record['type'] in (29,30,50):
            fields['pvec']=[fields['pvec'][0]+0.03,*fields['pvec'][1:]]
    records[1]['fields']['next']=second[0]['identity']
    second[0]['fields']['previous']=records[1]['identity']
    return records+second


def cone_records():
    records=[]
    def add(kind,**fields):
        identity=len(records)+1
        records.append({'type':kind,'identity':identity,'fields':fields,'variable':[]})
        return identity
    def f(i):return records[i-1]['fields']
    root=add(101,highest_id=10,current_id=9,alive=1)
    body=add(12,owner=root,body_type=1,res_size=1000,state=1)
    shell=add(13,body=body)
    f(root)['body']=body;f(body)['shell']=shell
    angle=math.atan(5/20)
    surf=add(52,pvec=[0,0,0],axis=[0,0,1],x_axis=[1,0,0],radius=.005,
             sin_half_angle=-math.sin(angle),cos_half_angle=math.cos(angle),sense=43)
    plane=add(50,pvec=[0,0,0],normal=[0,0,1],x_axis=[1,0,0],sense=43)
    circle=add(31,centre=[0,0,0],normal=[0,0,1],x_axis=[1,0,0],radius=.005,sense=43)
    vertex=add(18,point=add(29,pvec=[0,0,.020]))
    cone=add(14,surface=surf,sense=43,shell=shell)
    bottom=add(14,surface=plane,sense=45,shell=shell)
    tip_loop=add(15,face=cone)
    boundary=add(15,face=cone)
    base_loop=add(15,face=bottom)
    tip=add(17,loop=tip_loop,vertex=vertex,sense=63)
    cone_fin=add(17,loop=boundary,sense=45)
    base_fin=add(17,loop=base_loop,sense=43)
    edge=add(16,fin=base_fin,curve=circle)
    f(cone_fin).update(edge=edge,other=base_fin)
    f(base_fin).update(edge=edge,other=cone_fin)
    for loop,fin in [(tip_loop,tip),(boundary,cone_fin),(base_loop,base_fin)]:
        f(loop)['fin']=fin;f(fin).update(forward=fin,backward=fin)
    f(tip_loop)['next']=boundary
    f(cone).update(loop=tip_loop,next=bottom)
    f(bottom)['loop']=base_loop;f(shell)['face']=cone
    return records


def cylinder_intersection():
    # Two perpendicular cylinders: radius 10 about Z, radius 6 about X.
    # The negative-X intersection is one smooth closed analytic branch.
    chart=[]
    for i in range(33):
        theta=math.tau*i/32
        y,z=6*math.cos(theta),6*math.sin(theta)
        chart.append([-math.sqrt(100-y*y)/1000,y/1000,z/1000])
    records={
        1:{'type':51,'fields':{'pvec':[0,0,0],'axis':[0,0,1],'x_axis':[1,0,0],'radius':.010}},
        2:{'type':51,'fields':{'pvec':[0,0,0],'axis':[1,0,0],'x_axis':[0,1,0],'radius':.006}},
        3:{'type':40,'fields':{'chart_count':len(chart),'chordal_error':1e-6},'variable':chart},
        4:{'type':38,'fields':{'surface':[1,2],'chart':3}},
    }
    def node(i,kind=None):
        record=records[i]
        if kind is not None and record['type']!=kind:raise GeometryError('Wrong record type')
        return record
    return Geometry(node),records


class NativeGeometryTests(unittest.TestCase):
    def test_two_disjoint_bodies_remain_two_valid_step_solids(self):
        with tempfile.TemporaryDirectory() as temp:
            source,output=Path(temp)/'two.sldprt',Path(temp)/'two.step'
            sample_part(source,records=two_cubes())
            result=convert_part_native(source,output)
            metrics=analyze_step(output)
            self.assertTrue(result['all_solids_valid'])
            self.assertFalse(result['single_valid_solid'])
            self.assertEqual(result['solid_count'],2)
            self.assertEqual(metrics['solid_face_counts'],[6,6])
            self.assertEqual(result['decoded_faces'],12)
            self.assertAlmostEqual(result['volume_mm3'],2000,places=6)
            self.assertAlmostEqual(result['surface_area_mm2'],1200,places=6)
            for actual,expected in zip(result['dimensions_mm'],[40,10,10]):
                self.assertAlmostEqual(actual,expected,places=5)
            # Corrupting either body must prevent a partial export.
            broken=two_cubes()
            next(r for r in reversed(broken) if r['type']==50)['type']=124
            sample_part(source,records=broken)
            other=Path(temp)/'partial.step'
            with self.assertRaisesRegex(ValueError,'Unsupported surface'):convert(source,other)
            self.assertFalse(other.exists())

    def test_cone_pole_preserves_analytic_volume_and_surface_area(self):
        with tempfile.TemporaryDirectory() as temp:
            source,output=Path(temp)/'cone.sldprt',Path(temp)/'cone.step'
            sample_part(source,records=cone_records())
            result=convert(source,output)
            self.assertTrue(result['single_valid_solid'])
            self.assertEqual(result['decoded_faces'],2)
            self.assertAlmostEqual(result['volume_mm3'],math.pi*25*20/3,places=6)
            self.assertAlmostEqual(result['surface_area_mm2'],math.pi*5*math.sqrt(425)+math.pi*25,places=6)
            broken=cone_records()
            next(r for r in broken if r['type']==29)['fields']['pvec'][2]=.019
            sample_part(source,records=broken)
            other=Path(temp)/'bad.step'
            with self.assertRaisesRegex(ValueError,'cone apex'):convert(source,other)
            self.assertFalse(other.exists())

    def test_closed_intersection_supports_trim_across_parameter_seam(self):
        from OCP.GeomAPI import GeomAPI_ProjectPointOnCurve,GeomAPI_ProjectPointOnSurf
        from OCP.gp import gp_Pnt,gp_Vec
        geometry,records=cylinder_intersection()
        curve=geometry.curve(4)
        self.assertTrue(curve.IsClosed())
        self.assertTrue(curve.IsPeriodic())
        period=curve.Period()
        # Parameters can extend beyond the seam without changing the branch.
        for fraction in (0.1,0.3,0.7,0.9):
            u=curve.FirstParameter()+period*fraction
            position=curve.Value(u)
            self.assertLess(position.Distance(curve.Value(u+period)),1e-7)
            self.assertLess(position.X(),0)
            for surface_id in (1,2):
                self.assertLess(GeomAPI_ProjectPointOnSurf(position,geometry.surface(surface_id)).LowerDistance(),1e-5)
        first=point(records[3]['variable'][0]);next_point=point(records[3]['variable'][1])
        u=GeomAPI_ProjectPointOnCurve(first,curve).LowerDistanceParameter()
        p,t=gp_Pnt(),gp_Vec();curve.D1(u,p,t)
        self.assertGreater(t.Dot(gp_Vec(first,next_point)),0)
        geometry,records=cylinder_intersection()
        records[3]['variable'][10][0]=.1
        with self.assertRaisesRegex(GeometryError,'one analytic branch'):geometry.curve(4)

    def test_vector_array_and_embedded_schema_are_bounded_and_checked(self):
        vectors={'type':86,'identity':1,'fields':{},'variable':[[1,2,3],[4,5,6]]}
        stream=binary_stream([vectors])
        decoded=decode_prefix(stream)
        self.assertTrue(decoded['complete'])
        self.assertEqual(decoded['records'][0]['variable'],vectors['variable'])
        self.assertFalse(decode_prefix(stream[:-8])['complete'])
        def string(text):
            data=text.encode('ascii');return bytes([len(data)])+data
        embedded=bytes([2])+string('intersection_data')+string('UV metadata')
        for name,kind,count in [('uv_type','u',1),('values','f',2)]:
            embedded+=string(name)+struct.pack('>hh',0,count)+string(kind)
        embedded+=b'\x01'
        self.assertEqual(read_schema(Cursor(embedded),LAYOUTS[204],True),LAYOUTS[204])
        for bad in (embedded[:-1]+b'\0',embedded.replace(string('values'),string('wrong!')),embedded[:-3]):
            with self.assertRaises(DecodeError):read_schema(Cursor(bad),LAYOUTS[204],True)

    def test_round_trip_losing_one_body_is_rejected(self):
        from native_part.shape import reconstruct
        from native_part.worker import export_validated
        report=decode_prefix(binary_stream(two_cubes()))
        solid,topology=reconstruct(report)
        with tempfile.TemporaryDirectory() as temp, patch('experimental.step_reference.analyze_step',return_value={
            'imported_solids':1,'all_solids_valid':True,'imported_faces':12}):
            with self.assertRaisesRegex(ValueError,'changed solid topology'):
                export_validated(solid,Path(temp)/'candidate.step',12,2)


if __name__=='__main__':unittest.main()
