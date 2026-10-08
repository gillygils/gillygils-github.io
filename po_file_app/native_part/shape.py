"""Experimental reconstruction of decoded analytic and spline B-rep records.

This builds an already-current full partition. The model loader verifies the
saved configuration and matching leaf history mark before invoking this code.
"""
import math


class ShapeError(ValueError):
    pass


def reconstruct(report):
    from OCP.gp import gp_Pnt, gp_Dir, gp_Ax2, gp_Ax3
    from OCP.Geom import (Geom_Line, Geom_Circle, Geom_BSplineCurve, Geom_Plane,
                          Geom_CylindricalSurface, Geom_ConicalSurface, Geom_SurfaceOfLinearExtrusion)
    from OCP.GeomAPI import GeomAPI_ProjectPointOnCurve
    from OCP.TColgp import TColgp_Array1OfPnt
    from OCP.TColStd import TColStd_Array1OfReal, TColStd_Array1OfInteger
    from OCP.BRepBuilderAPI import (BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire,
                                    BRepBuilderAPI_MakeFace, BRepBuilderAPI_Sewing, BRepBuilderAPI_MakeSolid)
    from OCP.ShapeFix import ShapeFix_Face, ShapeFix_Solid
    from OCP.TopoDS import TopoDS
    from OCP.TopAbs import TopAbs_SHELL, TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer
    from OCP.BRepCheck import BRepCheck_Analyzer
    if not report['complete']:
        raise ShapeError('Entity decoding is incomplete.')
    nodes = {record['identity']:record for record in report['records']}
    if len(nodes) != len(report['records']):
        raise ShapeError('Duplicate entity identities.')
    if any(n['fields'].get('sense',43) not in (43,45) for n in nodes.values()):
        raise ShapeError('Unsupported orientation encoding.')
    def node(identity, expected=None):
        result = nodes.get(identity)
        if result is None or (expected is not None and result['type'] != expected):
            raise ShapeError(f'Missing or wrong-type entity reference {identity}.')
        return result
    def f(identity, expected=None):
        return node(identity,expected)['fields']
    def point(v):
        return gp_Pnt(*(a*1000 for a in v))
    def direction(v):
        return gp_Dir(*v)
    def axis(v, normal, x):
        return gp_Ax3(point(v),direction(normal),direction(x))
    def chain(first, kind, link):
        result,seen = [],set()
        while first:
            if first in seen:
                raise ShapeError('Unexpected cycle in a linear topology chain.')
            seen.add(first);result.append(first);first=f(first,kind)[link]
        return result
    curves = {}
    def curve(identity):
        if identity in curves:
            return curves[identity]
        n=node(identity);p=n['fields'];t=n['type']
        if t==30:
            result=Geom_Line(point(p['pvec']),direction(p['direction']))
        elif t==31:
            result=Geom_Circle(gp_Ax2(point(p['centre']),direction(p['normal']),direction(p['x_axis'])),p['radius']*1000)
        elif t==134:
            data=f(p['nurbs'],136)
            if data['periodic'] or data['rational'] or data['vertex_dim']!=3:
                raise ShapeError('Periodic/rational or non-3D splines are not implemented.')
            controls=node(data['bspline_vertices'],45)['variable']
            knots=node(data['knots'],128)['variable'];multiplicities=node(data['knot_mult'],127)['variable']
            count=data['n_vertices']
            if len(controls)!=count*3 or len(knots)!=data['n_knots'] or len(knots)!=len(multiplicities):
                raise ShapeError('Spline array sizes disagree.')
            poles=TColgp_Array1OfPnt(1,count)
            for i in range(count):poles.SetValue(i+1,point(controls[i*3:i*3+3]))
            ka=TColStd_Array1OfReal(1,len(knots));ma=TColStd_Array1OfInteger(1,len(knots))
            for i,(k,m) in enumerate(zip(knots,multiplicities),1):ka.SetValue(i,k);ma.SetValue(i,m)
            result=Geom_BSplineCurve(poles,ka,ma,data['degree'],False)
        else:
            raise ShapeError(f'Unsupported curve type {t}.')
        curves[identity]=result
        return result
    def surface(identity):
        n=node(identity);p=n['fields'];t=n['type']
        if t==50:return Geom_Plane(axis(p['pvec'],p['normal'],p['x_axis']))
        if t==51:return Geom_CylindricalSurface(axis(p['pvec'],p['axis'],p['x_axis']),p['radius']*1000)
        if t==52:return Geom_ConicalSurface(axis(p['pvec'],p['axis'],p['x_axis']),math.atan2(p['sin_half_angle'],p['cos_half_angle']),p['radius']*1000)
        if t==67:return Geom_SurfaceOfLinearExtrusion(curve(p['section']),direction(p['sweep']))
        raise ShapeError(f'Unsupported surface type {t}.')
    used_vertices=set()
    used_fins=set()
    def vertex(identity):
        used_vertices.add(identity)
        return point(f(f(identity,18)['point'],29)['pvec'])
    edges={}
    def edge(identity):
        if identity in edges:return edges[identity]
        p=f(identity,16);fin=f(p['fin'],17);other=f(fin['other'],17)
        if (fin['edge']!=identity or other['edge']!=identity
                or other['other']!=p['fin']):
            raise ShapeError('Edge fins do not reference each other consistently.')
        c=curve(p['curve'])
        if not fin['vertex'] and not other['vertex']:
            if not c.IsClosed():raise ShapeError('An open curve has no endpoint vertices.')
            result=BRepBuilderAPI_MakeEdge(c).Edge()
            sign=(1 if fin['sense']==43 else -1)*(1 if f(p['curve'])['sense']==43 else -1)
            if sign<0:result=TopoDS.Edge_s(result.Reversed())
            edges[identity]=result
            return result
        a=vertex(other['vertex']);b=vertex(fin['vertex'])
        projections=[GeomAPI_ProjectPointOnCurve(v,c) for v in (a,b)]
        if any(proj.NbPoints()==0 or proj.LowerDistance()>1e-5 for proj in projections):
            raise ShapeError(f'Edge {identity} endpoints do not lie on its curve.')
        u,v=[proj.LowerDistanceParameter() for proj in projections]
        if c.IsPeriodic():
            period=c.Period()
            sign=(1 if fin['sense']==43 else -1)*(1 if f(p['curve'])['sense']==43 else -1)
            if sign>0:
                while v<=u+1e-12:v+=period
            else:
                while v>=u-1e-12:v-=period
        reverse=v<u
        maker=BRepBuilderAPI_MakeEdge(c,b,a,v,u) if reverse else BRepBuilderAPI_MakeEdge(c,a,b,u,v)
        if not maker.IsDone():raise ShapeError(f'Cannot build edge {identity}: {maker.Error()}.')
        result=maker.Edge()
        if reverse:result=TopoDS.Edge_s(result.Reversed())
        edges[identity]=result
        return result
    def wire(loop):
        first=f(loop,15)['fin'];current=first;seen=set();maker=BRepBuilderAPI_MakeWire()
        while current not in seen:
            seen.add(current);p=f(current,17)
            if current in used_fins:raise ShapeError('A fin is shared between boundary loops.')
            used_fins.add(current)
            if p['loop']!=loop:raise ShapeError('Fin belongs to another loop.')
            if (f(p['forward'],17)['backward']!=current
                    or f(p['backward'],17)['forward']!=current
                    or f(p['backward'],17)['vertex']!=f(p['other'],17)['vertex']):
                raise ShapeError('Loop links or endpoint continuity disagree.')
            e=edge(p['edge'])
            canonical=f(p['edge'],16)['fin']
            if canonical!=current:
                if f(canonical,17)['other']!=current:raise ShapeError('Non-manifold edge fin association.')
                e=TopoDS.Edge_s(e.Reversed())
            maker.Add(e)
            if not maker.IsDone():raise ShapeError(f'Cannot join loop {loop} at fin {current}.')
            current=p['forward']
        if current!=first:raise ShapeError('Loop does not return to its first fin.')
        return maker.Wire()
    bodies=[n for n in nodes.values() if n['type']==12]
    if len(bodies)!=1:raise ShapeError('Exactly one decoded body is required.')
    shell_ids=chain(bodies[0]['fields']['shell'],13,'next')
    face_ids=[]
    for shell in shell_ids:face_ids+=chain(f(shell,13)['face'],14,'next')
    if len(face_ids)!=len(set(face_ids)) or len(face_ids)!=sum(n['type']==14 for n in nodes.values()):
        raise ShapeError('Body shell traversal does not cover every decoded face exactly once.')
    sewing=BRepBuilderAPI_Sewing(1e-5)
    for identity in face_ids:
        p=f(identity,14);loops=chain(p['loop'],15,'next')
        if not loops:raise ShapeError('Face has no boundary loops.')
        if any(f(loop,15)['face']!=identity for loop in loops):
            raise ShapeError('Boundary loop belongs to another face.')
        surf=surface(p['surface']);maker=BRepBuilderAPI_MakeFace(surf,wire(loops[0]),True)
        for loop in loops[1:]:maker.Add(wire(loop))
        if not maker.IsDone():raise ShapeError(f'Cannot build face {identity}.')
        fixer=ShapeFix_Face(maker.Face());fixer.SetPrecision(1e-6);fixer.SetMaxTolerance(1e-5);fixer.Perform()
        face=fixer.Face()
        if p['sense']==45:face=TopoDS.Face_s(face.Reversed())
        sewing.Add(face)
    for kind,used in ((16,set(edges)),(17,used_fins),(18,used_vertices)):
        if used!={n['identity'] for n in nodes.values() if n['type']==kind}:
            raise ShapeError('Not all decoded topology belongs to the reconstructed body.')
    sewing.Perform();joined=sewing.SewedShape();explorer=TopExp_Explorer(joined,TopAbs_SHELL);shells=[]
    if joined.ShapeType()==TopAbs_SHELL:shells=[TopoDS.Shell_s(joined)]
    else:
        while explorer.More():shells.append(TopoDS.Shell_s(explorer.Current()));explorer.Next()
    if len(shells)!=1 or not shells[0].Closed():raise ShapeError(f'Sewing did not produce one closed shell: {len(shells)} shells.')
    solid=BRepBuilderAPI_MakeSolid(shells[0]).Solid();fixer=ShapeFix_Solid(solid);fixer.Perform();solid=fixer.Solid()
    if not BRepCheck_Analyzer(solid).IsValid():raise ShapeError('Reconstructed solid is invalid.')
    return solid, {'decoded_faces':len(face_ids),'decoded_edges':len(edges),'base_partition_only':True}
