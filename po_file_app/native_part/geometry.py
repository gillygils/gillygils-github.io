"""Build decoded geometry, including analytic surface-intersection curves.

Intersection chart points identify the native branch and direction. They are
not exported as a display polyline: OpenCascade computes the actual trim curve
from the two decoded analytic surfaces.
"""
import math

from OCP.gp import gp_Pnt, gp_Dir, gp_Ax2, gp_Ax3, gp_Vec
from OCP.Geom import (Geom_Line, Geom_Circle, Geom_BSplineCurve, Geom_BSplineSurface, Geom_Plane,
                      Geom_CylindricalSurface, Geom_ConicalSurface,
                      Geom_SurfaceOfLinearExtrusion, Geom_ToroidalSurface)
from OCP.GeomAPI import GeomAPI_IntSS, GeomAPI_ProjectPointOnCurve, GeomAPI_ProjectPointOnSurf
from OCP.TColgp import TColgp_Array1OfPnt, TColgp_Array2OfPnt
from OCP.TColStd import TColStd_Array1OfReal, TColStd_Array1OfInteger


class GeometryError(ValueError):
    pass


def point(vector):
    return gp_Pnt(*(value * 1000 for value in vector))


def axis(origin, normal, x_axis):
    return gp_Ax3(point(origin), gp_Dir(*normal), gp_Dir(*x_axis))


def join_intersection_segments(curves):
    """Join unambiguous kernel segments into their continuous branches.

    Surface parameter seams can split one native intersection into several
    bounded curves. Only matching endpoints are joined; display chart points
    never supply replacement geometry. Branches at a junction are left apart.
    """
    from OCP.GeomConvert import GeomConvert_CompCurveToBSplineCurve
    bounded=[i for i,c in enumerate(curves) if isinstance(c,Geom_BSplineCurve) and not c.IsClosed()]
    ends={(i,side):curves[i].Value(curves[i].FirstParameter() if side==0 else curves[i].LastParameter())
          for i in bounded for side in (0,1)}
    neighbors={key:[] for key in ends}
    keys=list(ends)
    for index,a in enumerate(keys):
        for b in keys[index+1:]:
            if a[0]!=b[0] and ends[a].Distance(ends[b])<=1e-7:
                neighbors[a].append(b);neighbors[b].append(a)
    seen=set();result=[c for i,c in enumerate(curves) if i not in bounded]
    for first in bounded:
        if first in seen:continue
        group=set();pending=[first]
        while pending:
            current=pending.pop()
            if current in group:continue
            group.add(current)
            pending.extend(other[0] for side in (0,1) for other in neighbors[current,side])
        seen.update(group)
        endpoints=[(i,side) for i in group for side in (0,1) if not neighbors[i,side]]
        if len(group)==1 or len(endpoints) not in (0,2) or any(
                len(neighbors[i,side])>1 for i in group for side in (0,1)):
            result.extend(curves[i] for i in sorted(group));continue
        start=endpoints[0] if endpoints else (min(group),0)
        current=start;used=set();ordered=[]
        while current[0] not in used:
            index,side=current;used.add(index)
            curve=curves[index].Copy()
            if side:curve.Reverse()
            ordered.append(curve)
            next_ends=neighbors[index,1-side]
            if not next_ends:break
            current=next_ends[0]
        if used!=group or (not endpoints and current!=start):
            raise GeometryError('Intersection segment traversal is inconsistent.')
        builder=GeomConvert_CompCurveToBSplineCurve(ordered[0])
        for curve in ordered[1:]:
            if not builder.Add(curve,1e-7,True):
                raise GeometryError('Cannot join continuous intersection segments.')
        joined=builder.BSplineCurve()
        for curve in ordered:
            a,b=curve.FirstParameter(),curve.LastParameter()
            for i in range(33):
                projection=GeomAPI_ProjectPointOnCurve(curve.Value(a+(b-a)*i/32),joined)
                if not projection.NbPoints() or projection.LowerDistance()>1e-5:
                    raise GeometryError('Joining intersection segments changed their geometry.')
        result.append(joined)
    return result


class Geometry:
    def __init__(self, get_record):
        self.get_record = get_record
        self.curves = {}
        self.surfaces = {}
        self.active = set()

    def fields(self, identity, kind=None):
        return self.get_record(identity, kind)['fields']

    def curve(self, identity):
        if identity in self.curves:
            return self.curves[identity]
        if ('curve',identity) in self.active:
            raise GeometryError('Cyclic geometry reference.')
        self.active.add(('curve',identity))
        try:
            record = self.get_record(identity)
            data = record['fields']
            kind = record['type']
            if kind == 30:
                result = Geom_Line(point(data['pvec']), gp_Dir(*data['direction']))
            elif kind == 31:
                result = Geom_Circle(gp_Ax2(point(data['centre']), gp_Dir(*data['normal']),
                                           gp_Dir(*data['x_axis'])), data['radius'] * 1000)
            elif kind == 134:
                result = self.spline(data)
            elif kind == 38:
                result = self.intersection(data)
            elif kind == 137:
                result = self.on_surface(data)
            else:
                raise GeometryError(f'Unsupported curve type {kind}.')
            self.curves[identity] = result
            return result
        finally:
            self.active.remove(('curve',identity))

    def spline(self, data):
        params = self.fields(data['nurbs'],136)
        if params['periodic'] or params['rational'] or params['vertex_dim'] != 3:
            raise GeometryError('Periodic/rational or non-3D splines are not implemented.')
        controls = self.get_record(params['bspline_vertices'],45)['variable']
        knots = self.get_record(params['knots'],128)['variable']
        multiplicities = self.get_record(params['knot_mult'],127)['variable']
        count = params['n_vertices']
        if (len(controls) != count*3 or len(knots) != params['n_knots']
                or len(knots) != len(multiplicities)):
            raise GeometryError('Spline array sizes disagree.')
        poles = TColgp_Array1OfPnt(1,count)
        for index in range(count):
            poles.SetValue(index+1,point(controls[index*3:index*3+3]))
        ka = TColStd_Array1OfReal(1,len(knots))
        ma = TColStd_Array1OfInteger(1,len(knots))
        for index,(knot,multiplicity) in enumerate(zip(knots,multiplicities),1):
            ka.SetValue(index,knot)
            ma.SetValue(index,multiplicity)
        return Geom_BSplineCurve(poles,ka,ma,params['degree'],False)

    def surface(self, identity):
        if identity in self.surfaces:
            return self.surfaces[identity]
        if ('surface',identity) in self.active:
            raise GeometryError('Cyclic geometry reference.')
        self.active.add(('surface',identity))
        try:
            record = self.get_record(identity)
            data = record['fields']
            kind = record['type']
            if kind == 50:
                result = Geom_Plane(axis(data['pvec'],data['normal'],data['x_axis']))
            elif kind == 51:
                result = Geom_CylindricalSurface(axis(data['pvec'],data['axis'],data['x_axis']),data['radius']*1000)
            elif kind == 52:
                result = Geom_ConicalSurface(axis(data['pvec'],data['axis'],data['x_axis']),
                                           math.atan2(data['sin_half_angle'],data['cos_half_angle']),data['radius']*1000)
            elif kind == 54:
                if not 0<data['minor_radius']<data['major_radius']:
                    raise GeometryError('Only non-degenerate ring torus surfaces are supported.')
                result = Geom_ToroidalSurface(axis(data['centre'],data['axis'],data['x_axis']),
                                             data['major_radius']*1000,data['minor_radius']*1000)
            elif kind == 67:
                result = Geom_SurfaceOfLinearExtrusion(self.curve(data['section']),gp_Dir(*data['sweep']))
            elif kind == 124:
                result = self.spline_surface(data)
            else:
                raise GeometryError(f'Unsupported surface type {kind}.')
            self.surfaces[identity] = result
            return result
        finally:
            self.active.remove(('surface',identity))

    def knot_arrays(self, knots_id, mult_id, count, degree, poles):
        knots=self.get_record(knots_id,128)['variable']
        multiplicities=self.get_record(mult_id,127)['variable']
        if (len(knots)!=count or len(multiplicities)!=count or count<2
                or not 1<=degree<=25 or poles<degree+1
                or any(a>=b for a,b in zip(knots,knots[1:]))
                or any(not 1<=m<=degree+1 for m in multiplicities)
                or sum(multiplicities)!=poles+degree+1):
            raise GeometryError('Invalid non-periodic spline knot arrays.')
        ka=TColStd_Array1OfReal(1,count);ma=TColStd_Array1OfInteger(1,count)
        for i,(knot,mult) in enumerate(zip(knots,multiplicities),1):
            ka.SetValue(i,knot);ma.SetValue(i,mult)
        return ka,ma

    def spline_surface(self, data):
        params=self.fields(data['nurbs'],126)
        if params['u_periodic'] or params['v_periodic'] or params['rational'] or params['vertex_dim']!=3:
            raise GeometryError('Periodic/rational or non-3D spline surfaces are not implemented.')
        nu,nv=params['n_u_vertices'],params['n_v_vertices']
        controls=self.get_record(params['bspline_vertices'],45)['variable']
        if nu<2 or nv<2 or len(controls)!=nu*nv*3:
            raise GeometryError('Spline surface control array sizes disagree.')
        uk,um=self.knot_arrays(params['u_knots'],params['u_knot_mult'],params['n_u_knots'],params['u_degree'],nu)
        vk,vm=self.knot_arrays(params['v_knots'],params['v_knot_mult'],params['n_v_knots'],params['v_degree'],nv)
        poles=TColgp_Array2OfPnt(1,nu,1,nv)
        for u in range(nu):
            for v in range(nv):
                index=(u*nv+v)*3
                poles.SetValue(u+1,v+1,point(controls[index:index+3]))
        return Geom_BSplineSurface(poles,uk,vk,um,vm,params['u_degree'],params['v_degree'],False,False)

    def on_surface(self, data):
        from OCP.Geom2d import Geom2d_BSplineCurve
        from OCP.TColgp import TColgp_Array1OfPnt2d
        from OCP.gp import gp_Pnt2d
        from OCP.Geom2dAdaptor import Geom2dAdaptor_Curve
        from OCP.GeomAdaptor import GeomAdaptor_Surface
        from OCP.Adaptor3d import Adaptor3d_CurveOnSurface
        from OCP.Approx import Approx_Curve3d
        from OCP.GeomAbs import GeomAbs_C1
        if data.get('original',0):
            raise GeometryError('On-surface curves with an alternate original are not implemented.')
        basis=self.fields(data['b_curve'],134)
        params=self.fields(basis['nurbs'],136)
        if params['periodic'] or params['rational'] or params['vertex_dim']!=2 or basis['sense']!=43:
            raise GeometryError('Unsupported on-surface parameter curve.')
        kind=self.get_record(data['surface'])['type']
        scales={50:(1000,1000),51:(1,1000),52:(1,1000),54:(1,1),124:(1,1)}
        if kind not in scales:
            raise GeometryError('Unsupported on-surface parameter scale.')
        controls=self.get_record(params['bspline_vertices'],45)['variable']
        count=params['n_vertices']
        if count<2 or len(controls)!=count*2:
            raise GeometryError('On-surface control array sizes disagree.')
        ka,ma=self.knot_arrays(params['knots'],params['knot_mult'],params['n_knots'],params['degree'],count)
        poles=TColgp_Array1OfPnt2d(1,count)
        su,sv=scales[kind]
        for i in range(count):poles.SetValue(i+1,gp_Pnt2d(controls[i*2]*su,controls[i*2+1]*sv))
        curve2d=Geom2d_BSplineCurve(poles,ka,ma,params['degree'],False)
        surface=self.surface(data['surface'])
        adaptor=Adaptor3d_CurveOnSurface(Geom2dAdaptor_Curve(curve2d),GeomAdaptor_Surface(surface))
        approximation=Approx_Curve3d(adaptor,1e-7,GeomAbs_C1,200,14)
        if not approximation.IsDone() or not math.isfinite(approximation.MaxError()) or approximation.MaxError()>1e-7:
            raise GeometryError('On-surface curve approximation exceeds 0.0000001 mm.')
        result=approximation.Curve()
        # The approximation retains the UV curve's parameterization. Check
        # its actual positions, not only the kernel's reported error estimate.
        start,end=curve2d.FirstParameter(),curve2d.LastParameter()
        for i in range(65):
            u=start+(end-start)*i/64
            if result.Value(u).Distance(adaptor.Value(u))>1e-7:
                raise GeometryError('On-surface curve does not match its native parameter curve.')
        return result

    def intersection(self, data):
        surfaces = [self.surface(identity) for identity in data['surface']]
        chart = self.get_record(data['chart'],40)
        points = [point(vector) for vector in chart['variable']]
        if len(points) < 3 or chart['fields']['chart_count'] != len(points):
            raise GeometryError('Intersection chart is incomplete.')
        tolerance = max(1e-5, chart['fields']['chordal_error']*1000)
        if not math.isfinite(tolerance) or not 0 < tolerance <= 1:
            raise GeometryError('Unsupported intersection chart tolerance.')
        intersection = GeomAPI_IntSS(surfaces[0],surfaces[1],1e-7)
        if not intersection.IsDone() or not intersection.NbLines():
            raise GeometryError('Analytic surfaces did not yield an intersection curve.')
        if intersection.NbLines()>128:
            raise GeometryError('Surface intersection exceeds the branch limit.')
        candidates = []
        branches=join_intersection_segments([intersection.Line(index) for index in range(1,intersection.NbLines()+1)])
        for curve in branches:
            errors = []
            for position in points:
                projection = GeomAPI_ProjectPointOnCurve(position,curve)
                if not projection.NbPoints():
                    errors = [math.inf]
                    break
                errors.append(projection.LowerDistance())
            candidates.append((max(errors),curve))
        candidates.sort(key=lambda candidate: candidate[0])
        if candidates[0][0] > tolerance or (len(candidates)>1 and candidates[1][0] <= tolerance):
            raise GeometryError('Native intersection chart does not identify one analytic branch.')
        curve = candidates[0][1]
        first = GeomAPI_ProjectPointOnCurve(points[0],curve).LowerDistanceParameter()
        position,tangent = gp_Pnt(),gp_Vec()
        curve.D1(first,position,tangent)
        forward = gp_Vec(points[0],points[1])
        if tangent.Dot(forward) < 0:
            curve.Reverse()
        if curve.IsClosed() and not curve.IsPeriodic():
            # IntSS returns closed B-splines with a finite seam. Native fins
            # can cross that seam; treating them as ordinary open splines
            # selects the complementary arc and corrupts the trim boundary.
            # Preserve the computed curve while giving edge construction a
            # period with which to unwrap its endpoint parameters.
            if not isinstance(curve,Geom_BSplineCurve):
                raise GeometryError('Unsupported closed intersection curve.')
            start,end=curve.FirstParameter(),curve.LastParameter()
            samples=[curve.Value(start+(end-start)*i/32) for i in range(33)]
            curve.SetPeriodic()
            if any(before.Distance(curve.Value(start+(end-start)*i/32))>1e-5
                   for i,before in enumerate(samples)):
                raise GeometryError('Periodic intersection changed its geometry.')
        # Validate the selected curve on both surfaces, not just its chart fit.
        for position in points:
            projection = GeomAPI_ProjectPointOnCurve(position,curve)
            actual = curve.Value(projection.LowerDistanceParameter())
            for surface in surfaces:
                check = GeomAPI_ProjectPointOnSurf(actual,surface)
                if not check.NbPoints() or check.LowerDistance() > 1e-5:
                    raise GeometryError('Computed trim curve does not lie on both native surfaces.')
        return curve
