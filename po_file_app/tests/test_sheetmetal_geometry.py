"""Authored curved solids and surface curves, with analytic expected geometry."""
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_native_conversion import cube_records,sample_part,binary_stream
from test_native_geometry import cylinder_intersection
from native_part.entities import decode_prefix
from native_part.geometry import Geometry,GeometryError,point,join_intersection_segments
from native_part.worker import convert
from native_part.backend import convert_part_native


def arched_box_records():
    # 10 x 10 base; height = 10 + 6*v*(1-v) mm, v=y/10.
    # Its exact volume is 1100 mm^3. V varies fastest in the stored grid.
    records=cube_records()
    def add(kind,variable=None,**fields):
        identity=len(records)+1
        records.append({'type':kind,'identity':identity,'fields':fields,'variable':variable or []})
        return identity
    top=next(r for r in records if r['type']==50 and r['fields']['normal']==(0,0,1))
    controls=add(45,variable=[coord for x in (0,.010) for y,z in ((0,.010),(.005,.013),(.010,.010)) for coord in (x,y,z)])
    uk=add(128,variable=[0,1]);vk=add(128,variable=[0,1])
    um=add(127,variable=[2,2]);vm=add(127,variable=[3,3])
    params=add(126,u_degree=1,v_degree=2,n_u_vertices=2,n_v_vertices=3,n_u_knots=2,n_v_knots=2,
               vertex_dim=3,bspline_vertices=controls,u_knots=uk,v_knots=vk,u_knot_mult=um,v_knot_mult=vm)
    metadata=add(125)
    top['type']=124;top['fields']={'sense':43,'nurbs':params,'data':metadata}
    for r in list(records):
        if r['type']!=30:continue
        p=r['fields']['pvec'];direction=r['fields']['direction']
        if p[2]!=.010 or not direction[1]:continue
        end=[p[i]+direction[i]*.010 for i in range(3)]
        middle=[(p[i]+end[i])/2 for i in range(3)];middle[2]=.013
        vertices=add(45,variable=[*p,*middle,*end])
        knots=add(128,variable=[0,1]);mult=add(127,variable=[3,3])
        params=add(136,degree=2,n_vertices=3,vertex_dim=3,n_knots=2,
                   bspline_vertices=vertices,knots=knots,knot_mult=mult)
        r['type']=134;r['fields']={'sense':43,'nurbs':params,'data':0}
    return records


def quarter_torus_records():
    records=[]
    def add(kind,**fields):
        identity=len(records)+1
        records.append({'type':kind,'identity':identity,'fields':fields,'variable':[]})
        return identity
    def f(i):return records[i-1]['fields']
    root=add(101,highest_id=10,current_id=9,alive=1)
    body=add(12,owner=root,body_type=1,state=1,res_size=1000)
    shell=add(13,body=body);f(root)['body']=body;f(body)['shell']=shell
    surface=add(54,centre=[0,0,0],axis=[0,0,1],x_axis=[1,0,0],major_radius=.010,minor_radius=.002,sense=43)
    torus=add(14,shell=shell,surface=surface,sense=43)
    previous_loop=0;previous_face=torus
    for i,(centre,normal,x_axis,torus_sense) in enumerate([
            ([.010,0,0],[0,-1,0],[1,0,0],43),([0,.010,0],[-1,0,0],[0,1,0],45)]):
        curve=add(31,centre=centre,normal=[0,1,0] if i==0 else normal,x_axis=x_axis,radius=.002,sense=43)
        plane=add(50,pvec=centre,normal=normal,x_axis=x_axis,sense=43)
        cap=add(14,shell=shell,surface=plane,sense=43);f(previous_face)['next']=cap;previous_face=cap
        loop=add(15,face=torus);cap_loop=add(15,face=cap);f(cap)['loop']=cap_loop
        if previous_loop:f(previous_loop)['next']=loop
        else:f(torus)['loop']=loop
        previous_loop=loop
        fin=add(17,loop=loop,sense=torus_sense);other=add(17,loop=cap_loop,sense=45 if torus_sense==43 else 43)
        edge=add(16,fin=fin,curve=curve)
        for a,b,l in [(fin,other,loop),(other,fin,cap_loop)]:
            f(a).update(edge=edge,other=b,forward=a,backward=a);f(l)['fin']=a
    f(shell)['face']=torus
    return records


def on_cylinder():
    records={
        1:{'type':51,'fields':{'pvec':[0,0,0],'axis':[0,0,1],'x_axis':[1,0,0],'radius':.010}},
        2:{'type':45,'variable':[0,0,math.pi/2,.020]},
        3:{'type':128,'variable':[0,1]},4:{'type':127,'variable':[2,2]},
        5:{'type':136,'fields':{'periodic':0,'rational':0,'vertex_dim':2,'n_vertices':2,'degree':1,'n_knots':2,'bspline_vertices':2,'knots':3,'knot_mult':4}},
        6:{'type':134,'fields':{'nurbs':5,'sense':43}},
        7:{'type':137,'fields':{'surface':1,'b_curve':6,'original':0,'sense':43}},
    }
    def node(i,kind=None):
        r=records[i]
        if kind is not None and r['type']!=kind:raise GeometryError('Wrong record type')
        return r
    return Geometry(node),records


class SheetMetalGeometryTests(unittest.TestCase):
    def test_curved_spline_box_has_known_volume_area_and_dimensions(self):
        with tempfile.TemporaryDirectory() as temp:
            source,output=Path(temp)/'arched.sldprt',Path(temp)/'arched.step'
            sample_part(source,records=arched_box_records())
            result=convert_part_native(source,output)
            self.assertTrue(result['all_solids_valid'])
            self.assertEqual(result['decoded_faces'],6)
            self.assertAlmostEqual(result['volume_mm3'],1100,places=6)
            arc=.5*math.sqrt(136)+(25/3)*math.asinh(.6)
            self.assertAlmostEqual(result['surface_area_mm2'],520+10*arc,places=5)
            for actual,expected in zip(result['dimensions_mm'],[10,10,11.5]):self.assertAlmostEqual(actual,expected,places=5)
            decoded=decode_prefix(binary_stream(arched_box_records()))
            self.assertTrue(decoded['complete'])
            params=next(r for r in decoded['records'] if r['type']==126)['fields']
            self.assertEqual((params['n_u_knots'],params['n_v_knots'],params['vertex_dim']),(2,2,3))

    def test_quarter_torus_solid_preserves_analytic_bend_geometry(self):
        with tempfile.TemporaryDirectory() as temp:
            source,output=Path(temp)/'bend.sldprt',Path(temp)/'bend.step'
            sample_part(source,records=quarter_torus_records())
            result=convert(source,output)
            self.assertEqual(result['decoded_faces'],3)
            self.assertTrue(result['single_valid_solid'])
            self.assertAlmostEqual(result['volume_mm3'],20*math.pi**2,places=5)
            self.assertAlmostEqual(result['surface_area_mm2'],20*math.pi**2+8*math.pi,places=5)
            for actual,expected in zip(result['dimensions_mm'],[12,12,4]):self.assertAlmostEqual(actual,expected,places=5)

    def test_native_winding_can_also_select_the_long_torus_arc(self):
        # Reversing the native strip deliberately describes a 270 degree bend;
        # the exporter must not simply select the shorter of two possible arcs.
        records=quarter_torus_records()
        for r in records:
            if r['type']==17:r['fields']['sense']=45 if r['fields']['sense']==43 else 43
            if r['type']==50:r['fields']['normal']=[-x for x in r['fields']['normal']]
        with tempfile.TemporaryDirectory() as temp:
            source,output=Path(temp)/'long.sldprt',Path(temp)/'long.step'
            sample_part(source,records=records);result=convert(source,output)
            self.assertAlmostEqual(result['volume_mm3'],60*math.pi**2,places=5)
            self.assertAlmostEqual(result['surface_area_mm2'],60*math.pi**2+8*math.pi,places=5)
            for actual,expected in zip(result['dimensions_mm'],[24,24,4]):self.assertAlmostEqual(actual,expected,places=5)

    def test_surface_curve_preserves_cylindrical_uv_units_and_helix(self):
        from OCP.GeomAPI import GeomAPI_ProjectPointOnSurf
        geometry,_=on_cylinder();curve=geometry.curve(7)
        for i in range(33):
            t=i/32;actual=curve.Value(t);angle=t*math.pi/2
            expected=point([.010*math.cos(angle),.010*math.sin(angle),.020*t])
            self.assertLess(actual.Distance(expected),1e-7)
            self.assertLess(GeomAPI_ProjectPointOnSurf(actual,geometry.surface(1)).LowerDistance(),1e-7)

    def test_split_intersection_segments_form_one_closed_native_branch(self):
        from OCP.GeomAPI import GeomAPI_ProjectPointOnCurve
        geometry,records=cylinder_intersection()
        for xyz in records[3]['variable']:xyz[0]=-xyz[0]
        curve=geometry.curve(4)
        self.assertTrue(curve.IsPeriodic())
        for xyz in records[3]['variable']:
            self.assertLess(GeomAPI_ProjectPointOnCurve(point(xyz),curve).LowerDistance(),1e-5)
        for fraction in (.1,.3,.7,.9):self.assertGreater(curve.Value(curve.FirstParameter()+curve.Period()*fraction).X(),0)

    def test_unsupported_or_malformed_splines_do_not_publish_partial_step(self):
        with tempfile.TemporaryDirectory() as temp:
            source,output=Path(temp)/'bad.sldprt',Path(temp)/'bad.step'
            for field,value in [('rational',1),('u_periodic',1),('n_v_knots',3)]:
                records=arched_box_records()
                next(r for r in records if r['type']==126)['fields'][field]=value
                sample_part(source,records=records)
                with self.assertRaises(ValueError):convert(source,output)
                self.assertFalse(output.exists())
            geometry,records=on_cylinder();records[5]['fields']['vertex_dim']=3
            with self.assertRaisesRegex(GeometryError,'parameter curve'):geometry.curve(7)
            geometry,records=on_cylinder();records[7]['fields']['original']=99
            with self.assertRaisesRegex(GeometryError,'alternate original'):geometry.curve(7)

    def test_disconnected_or_branched_segments_are_not_joined(self):
        from OCP.Geom import Geom_BSplineCurve
        from OCP.TColgp import TColgp_Array1OfPnt
        from OCP.TColStd import TColStd_Array1OfReal,TColStd_Array1OfInteger
        def line(a,b):
            poles=TColgp_Array1OfPnt(1,2);poles.SetValue(1,point(a));poles.SetValue(2,point(b))
            knots=TColStd_Array1OfReal(1,2);knots.SetValue(1,0);knots.SetValue(2,1)
            mult=TColStd_Array1OfInteger(1,2);mult.SetValue(1,2);mult.SetValue(2,2)
            return Geom_BSplineCurve(poles,knots,mult,1,False)
        origin=[0,0,0]
        branches=[line(origin,p) for p in ([.010,0,0],[0,.010,0],[0,0,.010])]
        self.assertEqual(len(join_intersection_segments(branches)),3)
        disconnected=[line(origin,[.010,0,0]),line([.020,0,0],[.030,0,0])]
        self.assertEqual(len(join_intersection_segments(disconnected)),2)

    def test_assembly_is_rejected_before_part_decoding_or_output(self):
        with tempfile.TemporaryDirectory() as temp,patch('native_part.worker.load_model',side_effect=AssertionError('Read assembly as part')):
            source,output=Path(temp)/'assembly.sldasm',Path(temp)/'assembly.step'
            source.write_bytes(b'assembly')
            with self.assertRaisesRegex(ValueError,'referenced component files'):convert(source,output)
            self.assertFalse(output.exists())


if __name__=='__main__':unittest.main()
