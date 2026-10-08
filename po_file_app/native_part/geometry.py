"""Build decoded geometry, including analytic surface-intersection curves.

Intersection chart points identify the native branch and direction. They are
not exported as a display polyline: OpenCascade computes the actual trim curve
from the two decoded analytic surfaces.
"""
import math

from OCP.gp import gp_Pnt, gp_Dir, gp_Ax2, gp_Ax3, gp_Vec
from OCP.Geom import (Geom_Line, Geom_Circle, Geom_BSplineCurve, Geom_Plane,
                      Geom_CylindricalSurface, Geom_ConicalSurface,
                      Geom_SurfaceOfLinearExtrusion)
from OCP.GeomAPI import GeomAPI_IntSS, GeomAPI_ProjectPointOnCurve, GeomAPI_ProjectPointOnSurf
from OCP.TColgp import TColgp_Array1OfPnt
from OCP.TColStd import TColStd_Array1OfReal, TColStd_Array1OfInteger


class GeometryError(ValueError):
    pass


def point(vector):
    return gp_Pnt(*(value * 1000 for value in vector))


def axis(origin, normal, x_axis):
    return gp_Ax3(point(origin), gp_Dir(*normal), gp_Dir(*x_axis))


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
            elif kind == 67:
                result = Geom_SurfaceOfLinearExtrusion(self.curve(data['section']),gp_Dir(*data['sweep']))
            else:
                raise GeometryError(f'Unsupported surface type {kind}.')
            self.surfaces[identity] = result
            return result
        finally:
            self.active.remove(('surface',identity))

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
        candidates = []
        for index in range(1,intersection.NbLines()+1):
            curve = intersection.Line(index)
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
