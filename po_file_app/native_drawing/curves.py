"""Recover analytic cached curves and resolve spline definitions from a part.

Cached spline points identify a saved native curve. They are never fitted to
invent spline control points. If no unique matching curve exists, the output
retains a visibly experimental polyline and reports the missing definition.
"""
import math
from .scene import transform


def projected_circle(points, matrix):
    """Verify a spatial circle, then project its analytic ellipse to the sheet."""
    import numpy as np
    if len(points)<5:
        raise ValueError('Too few independent cached samples to verify an analytic circle.')
    xyz = np.asarray(points, dtype=float)
    a,b,c = (xyz[i] for i in (0,len(points)//3,2*len(points)//3))
    ab,ac = b-a,c-a
    cross = np.cross(ab,ac)
    norm2 = float(np.dot(cross,cross))
    if norm2 < 1e-28:
        raise ValueError('Cached spatial curve is not a verified circle.')
    center = a+(np.dot(ac,ac)*np.cross(cross,ab)+np.dot(ab,ab)*np.cross(ac,cross))/(2*norm2)
    radius = float(np.linalg.norm(a-center))
    normal = cross/math.sqrt(norm2)
    if (not 1e-7 < radius < 10 or np.max(np.abs((xyz-center)@normal))>1e-9
            or np.max(np.abs(np.linalg.norm(xyz-center,axis=1)-radius))>1e-9):
        raise ValueError('Cached spatial curve does not lie on one verified circle.')
    u = (a-center)/radius
    v = np.cross(normal,u)
    angles = np.arctan2((xyz-center)@v,(xyz-center)@u)
    sweep = 0
    for first,last in zip(angles,angles[1:]):
        delta = float((last-first+math.pi)%math.tau-math.pi)
        if abs(delta)<1e-12 or sweep*delta<0:
            raise ValueError('Ambiguous spatial circle direction.')
        sweep += delta
    if abs(sweep)>math.tau+1e-8:
        raise ValueError('Cached spatial circle exceeds one turn.')
    rotation = np.asarray(matrix[:9]).reshape(3,3)
    axes = np.column_stack(((u@rotation)[:2],(v@rotation)[:2]))*radius*matrix[12]
    vectors,lengths,_ = np.linalg.svd(axes)
    if lengths[1]<1e-9:
        raise ValueError('Edge-on circle needs a cached polyline.')
    major = vectors[:,0]*lengths[0]
    minor = np.array([-major[1],major[0]])*(lengths[1]/lengths[0])
    start = axes[:,0]
    angle = math.atan2(float(np.dot(start,minor)/(lengths[1]**2)),
                       float(np.dot(start,major)/(lengths[0]**2)))
    sweep *= 1 if np.linalg.det(axes)>0 else -1
    projected_center = transform(center,matrix)
    if abs(lengths[0]-lengths[1])<1e-9:
        return {'kind':'circle' if abs(abs(sweep)-math.tau)<1e-8 else 'circular_arc',
                'center':projected_center,'radius':float(lengths[0]),
                'angle':math.atan2(start[1],start[0]),'sweep':sweep,'style':'CONTINUOUS'}
    return {'kind':'ellipse','center':projected_center,'major':major.tolist(),
            'minor':minor.tolist(),'ratio':float(lengths[1]/lengths[0]),
            'angle':angle,'sweep':sweep,'style':'CONTINUOUS'}


def circular(points):
    if len(points) < 3:
        raise ValueError('A cached circular curve needs three points.')
    a,b,c = (points[i] for i in (0,len(points)//3,2*len(points)//3))
    ax,ay = a[:2]; bx,by = b[:2]; cx,cy = c[:2]
    den = 2*(ax*(by-cy)+bx*(cy-ay)+cx*(ay-by))
    if abs(den)<1e-18:
        raise ValueError('Cached curve is not a supported planar circle.')
    aa,bb,cc = ax*ax+ay*ay,bx*bx+by*by,cx*cx+cy*cy
    x = (aa*(by-cy)+bb*(cy-ay)+cc*(ay-by))/den
    y = (aa*(cx-bx)+bb*(ax-cx)+cc*(bx-ax))/den
    radius = math.hypot(ax-x,ay-y)
    if not 1e-7 < radius < 10 or any(abs(math.hypot(p[0]-x,p[1]-y)-radius)>1e-9 for p in points):
        raise ValueError('Cached curve does not lie on one verified planar circle.')
    angles = [math.atan2(p[1]-y,p[0]-x) for p in points]
    sweep = 0
    for a,b in zip(angles,angles[1:]):
        delta = (b-a+math.pi) % (2*math.pi)-math.pi
        if abs(delta)<1e-12 or sweep*delta<0:
            raise ValueError('Ambiguous cached circular curve direction.')
        sweep += delta
    if abs(sweep)>2*math.pi+1e-8:
        raise ValueError('Cached circular curve exceeds one turn.')
    return {'kind':'circle' if abs(abs(sweep)-2*math.pi)<1e-8 else 'circular_arc',
            'center':[x,y,0],'radius':radius,'angle':angles[0],'sweep':sweep,
            'style':'CONTINUOUS'}


def part_splines(source):
    from native_part.model import load_model
    from native_part.geometry import Geometry
    report,metadata = load_model(source)
    records = {r['identity']:r for r in report['records']}
    def get(identity, kind=None):
        record = records[identity]
        if kind is not None and record['type'] != kind:
            raise ValueError('Spline reference has the wrong record type.')
        return record
    geometry = Geometry(get)
    return [(r['identity'],geometry.curve(r['identity'])) for r in report['records']
            if r['type']==134], metadata


def resolve_spline(points, candidates, matrix):
    from OCP.GeomAPI import GeomAPI_ProjectPointOnCurve
    from OCP.gp import gp_Pnt
    matches = []
    for identity,curve in candidates:
        parameters = []
        for point in points:
            projection = GeomAPI_ProjectPointOnCurve(gp_Pnt(*(v*1000 for v in point)),curve)
            if not projection.NbPoints() or projection.LowerDistance()>1e-6:
                break
            parameters.append(projection.LowerDistanceParameter())
        else:
            differences = [b-a for a,b in zip(parameters,parameters[1:])]
            if all(d>1e-12 for d in differences) or all(d<-1e-12 for d in differences):
                matches.append((identity,curve,parameters))
    if len(matches)!=1:
        raise ValueError('The matching part has no unique spline through all saved drawing points.')
    identity,curve,parameters = matches[0]
    curve = curve.Copy()
    curve.Segment(min(parameters[0],parameters[-1]),max(parameters[0],parameters[-1]),1e-10)
    if parameters[-1]<parameters[0]:curve.Reverse()
    poles = [transform([v/1000 for v in curve.Pole(i).Coord()],matrix) for i in range(1,curve.NbPoles()+1)]
    knots = [curve.Knot(i) for i in range(1,curve.NbKnots()+1)
             for _ in range(curve.Multiplicity(i))]
    if curve.IsRational() or curve.IsPeriodic() or curve.Degree()!=3:
        raise ValueError('Only non-rational, non-periodic cubic drawing splines are supported.')
    # A planar projected spline has exact polynomial Bezier spans, allowing
    # vector PDF curves without tessellating the CAD geometry.
    from OCP.GeomConvert import GeomConvert_BSplineCurveToBezierCurve
    builder = GeomConvert_BSplineCurveToBezierCurve(curve)
    beziers = []
    for i in range(1,builder.NbArcs()+1):
        arc = builder.Arc(i)
        if arc.NbPoles()!=4:
            raise ValueError('Unsupported drawing spline Bezier degree.')
        beziers.append([transform([v/1000 for v in arc.Pole(j).Coord()],matrix)
                        for j in range(1,5)])
    return {'kind':'spline','style':'CONTINUOUS','degree':curve.Degree(),
            'poles':poles,'knots':knots,'beziers':beziers,'source_curve':identity}


def drawing_geometry(scene, part=None):
    candidates, metadata = part_splines(part) if part else ([],None)
    result, unresolved, sampled = [], [], []
    for view in scene['views']:
        for curve in view['curves']:
            points = curve['projected']
            if curve['record_type']==769:
                try:
                    if not candidates:raise ValueError('Matching .sldprt is required for this exact spline.')
                    result.append(resolve_spline(curve['points'],candidates,view['transform']))
                except ValueError as exc:
                    result.append({'kind':'polyline','style':'CONTINUOUS','points':points})
                    unresolved.append({'view':view['name'],'offset':curve['offset'],'reason':str(exc)})
            elif len(points)==2:
                result.append({'kind':'line','style':'CONTINUOUS','start':points[0],'end':points[1]})
            else:
                try:
                    result.append(projected_circle(curve['points'],view['transform']))
                except ValueError as exc:
                    result.append({'kind':'polyline','style':'CONTINUOUS','points':points})
                    sampled.append({'view':view['name'],'offset':curve['offset'],
                                    'reason':str(exc),'vertices':len(points)})
            result[-1]['style'] = curve.get('style','CONTINUOUS')
    return result, {'exact_splines':sum(p['kind']=='spline' for p in result),
                    'unresolved_splines':unresolved,'matching_part':metadata,
                    'cached_polylines':sampled,
                    'analytic_ellipses':sum(p['kind']=='ellipse' for p in result),
                    'geometry_primitives':len(result)}
