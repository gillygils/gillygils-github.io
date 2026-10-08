"""Experimental reconstruction of decoded analytic and spline B-rep records.

This builds an already-current full partition. The model loader verifies the
saved configuration and matching leaf history mark before invoking this code.
"""
import math


class ShapeError(ValueError):
    pass


def reconstruct_body(report, body_id):
    from OCP.gp import gp_Pnt, gp_Dir
    from OCP.GeomAPI import GeomAPI_ProjectPointOnCurve
    from OCP.BRepBuilderAPI import (BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire,
                                    BRepBuilderAPI_MakeFace, BRepBuilderAPI_Sewing, BRepBuilderAPI_MakeSolid)
    from OCP.ShapeFix import ShapeFix_Face, ShapeFix_Solid
    from OCP.TopoDS import TopoDS
    from OCP.TopAbs import TopAbs_SHELL
    from OCP.TopExp import TopExp_Explorer
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.BRepCheck import BRepCheck_Shell, BRepCheck_NoError
    if not report['complete']:
        raise ShapeError('Entity decoding is incomplete.')
    nodes = {record['identity']:record for record in report['records']}
    if len(nodes) != len(report['records']):
        raise ShapeError('Duplicate entity identities.')
    if any(n['fields'].get('sense',43) not in (43,45)
           and not (n['type']==17 and n['fields'].get('sense')==63
                    and not n['fields']['edge'] and not n['fields']['other'])
           for n in nodes.values()):
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
    def chain(first, kind, link):
        result,seen = [],set()
        while first:
            if first in seen:
                raise ShapeError('Unexpected cycle in a linear topology chain.')
            seen.add(first);result.append(first);first=f(first,kind)[link]
        return result
    from .geometry import Geometry, GeometryError
    geometry = Geometry(node)
    def curve(identity):
        try:
            return geometry.curve(identity)
        except GeometryError as exc:
            raise ShapeError(str(exc)) from exc
    def surface(identity):
        try:
            return geometry.surface(identity)
        except GeometryError as exc:
            raise ShapeError(str(exc)) from exc
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
    def singular(loop):
        fin=f(loop,15)['fin'];data=f(fin,17)
        return not data['edge'] and not data['other']
    def cone_with_apex(surf,loops):
        from OCP.Geom import Geom_ConicalSurface
        from OCP.gp import gp_Vec
        if not isinstance(surf,Geom_ConicalSurface) or len(loops)!=2:
            raise ShapeError('Unsupported singular trim boundary.')
        tips=[loop for loop in loops if singular(loop)]
        regular=[loop for loop in loops if not singular(loop)]
        if len(tips)!=1 or len(regular)!=1:
            raise ShapeError('A full cone needs one circular boundary and one apex loop.')
        tip_fin=f(tips[0],15)['fin'];tip=f(tip_fin,17)
        if (tip['forward']!=tip_fin or tip['backward']!=tip_fin or tip['loop']!=tips[0]
                or tip['sense']!=63 or tip['curve'] or not tip['vertex']):
            raise ShapeError('Malformed singular cone loop.')
        apex=vertex(tip['vertex'])
        if apex.Distance(surf.Apex())>1e-5:
            raise ShapeError('Singular vertex is not the analytic cone apex.')
        if tip_fin in used_fins:raise ShapeError('Singular fin is shared between loops.')
        used_fins.add(tip_fin)
        boundary_fin=f(regular[0],15)['fin'];boundary=f(boundary_fin,17)
        if boundary['forward']!=boundary_fin or boundary['backward']!=boundary_fin:
            raise ShapeError('Singular cone boundary is not one full circle.')
        circle=f(f(boundary['edge'],16)['curve'],31)
        # Traverse the actual native circular edge so reference and coverage
        # checks still apply. The kernel creates its matching singular seam.
        wire(regular[0])
        cone_axis=gp_Vec(surf.Position().Direction())
        offset=gp_Vec(surf.Location(),point(circle['centre']))
        if (offset.Crossed(cone_axis).Magnitude()>1e-5
                or gp_Vec(direction(circle['normal'])).Crossed(cone_axis).Magnitude()>1e-10):
            raise ShapeError('Cone boundary circle is not coaxial.')
        angle=surf.SemiAngle();v=offset.Dot(cone_axis)/math.cos(angle)
        if abs(abs(surf.RefRadius()+v*math.sin(angle))-circle['radius']*1000)>1e-5:
            raise ShapeError('Cone boundary radius disagrees with the native circle.')
        apex_v=-surf.RefRadius()/math.sin(angle)
        maker=BRepBuilderAPI_MakeFace(surf,0,math.tau,min(v,apex_v),max(v,apex_v),1e-7)
        if not maker.IsDone():raise ShapeError('Cannot build the analytic cone apex face.')
        return maker
    body=f(body_id,12)
    shell_ids=chain(body['shell'],13,'next')
    if any(f(shell,13)['body']!=body_id for shell in shell_ids):
        raise ShapeError('Shell belongs to another body.')
    face_ids=[]
    for shell in shell_ids:face_ids+=chain(f(shell,13)['face'],14,'next')
    if not face_ids or len(face_ids)!=len(set(face_ids)):
        raise ShapeError('Body shell traversal does not cover every decoded face exactly once.')
    sewing=BRepBuilderAPI_Sewing(1e-5)
    for identity in face_ids:
        p=f(identity,14);loops=chain(p['loop'],15,'next')
        if not loops:raise ShapeError('Face has no boundary loops.')
        if any(f(loop,15)['face']!=identity for loop in loops):
            raise ShapeError('Boundary loop belongs to another face.')
        surf=surface(p['surface'])
        if any(singular(loop) for loop in loops):
            maker=cone_with_apex(surf,loops)
        else:
            maker=BRepBuilderAPI_MakeFace(surf,wire(loops[0]),True)
            for loop in loops[1:]:maker.Add(wire(loop))
        if not maker.IsDone():raise ShapeError(f'Cannot build face {identity}.')
        fixer=ShapeFix_Face(maker.Face());fixer.SetPrecision(1e-6);fixer.SetMaxTolerance(1e-5);fixer.Perform()
        face=fixer.Face()
        if p['sense']==45:face=TopoDS.Face_s(face.Reversed())
        sewing.Add(face)
    sewing.Perform();joined=sewing.SewedShape();explorer=TopExp_Explorer(joined,TopAbs_SHELL);shells=[]
    if joined.ShapeType()==TopAbs_SHELL:shells=[TopoDS.Shell_s(joined)]
    else:
        while explorer.More():shells.append(TopoDS.Shell_s(explorer.Current()));explorer.Next()
    if (len(shells)!=1 or sewing.NbFreeEdges() or sewing.NbMultipleEdges()
            or BRepCheck_Shell(shells[0]).Closed()!=BRepCheck_NoError):
        raise ShapeError(f'Sewing did not produce one closed shell: {len(shells)} shells, '
                         f'{sewing.NbFreeEdges()} free edges, {sewing.NbMultipleEdges()} multiple edges.')
    # Sewing can leave the cached Closed flag false for valid conical pole
    # edges. Set it only after the shell's actual closure check succeeds.
    shells[0].Closed(True)
    solid=BRepBuilderAPI_MakeSolid(shells[0]).Solid();fixer=ShapeFix_Solid(solid);fixer.Perform();solid=fixer.Solid()
    if not BRepCheck_Analyzer(solid).IsValid():raise ShapeError(f'Reconstructed body {body_id} is invalid.')
    return solid, {14:set(face_ids),16:set(edges),17:used_fins,18:used_vertices}


def reconstruct(report):
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound
    if not report['complete']:
        raise ShapeError('Entity decoding is incomplete.')
    body_ids=[r['identity'] for r in report['records'] if r['type']==12]
    if not body_ids:
        raise ShapeError('No saved solid bodies were decoded.')
    solids=[]
    covered={kind:set() for kind in (14,16,17,18)}
    for body_id in body_ids:
        solid,used=reconstruct_body(report,body_id)
        solids.append(solid)
        for kind,ids in used.items():
            if covered[kind]&ids:
                raise ShapeError('Topology is shared between different solid bodies.')
            covered[kind].update(ids)
    for kind,ids in covered.items():
        if ids!={r['identity'] for r in report['records'] if r['type']==kind}:
            raise ShapeError('Not all decoded topology belongs to the reconstructed bodies.')
    shape=solids[0]
    if len(solids)>1:
        shape=TopoDS_Compound();builder=BRep_Builder();builder.MakeCompound(shape)
        for solid in solids:builder.Add(shape,solid)
    return shape, {'decoded_faces':len(covered[14]), 'decoded_edges':len(covered[16]),
                   'decoded_bodies':len(solids), 'base_partition_only':True}
