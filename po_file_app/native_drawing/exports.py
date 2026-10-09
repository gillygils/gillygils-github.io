"""Local vector PDF and millimetre DXF output for experimental drawing scenes."""
import math
import os
from pathlib import Path

NOTICE = 'INCOMPLETE NATIVE DECODER - NOT FOR MANUFACTURING'
METRES_TO_POINTS = 72 / .0254


def flatten_arc(item):
    """Project an explicitly defined saved spatial arc onto the sheet."""
    if item['kind']!='arc' or abs(abs(item['normal'][2])-1)<1e-8:
        return item
    import numpy as np
    from .curves import projected_circle
    center=np.asarray(item['center']);normal=np.asarray(item['normal'])
    radial=np.asarray(item['start'])-center;end=np.asarray(item['end'])-center
    radius=float(np.linalg.norm(radial))
    if (radius<=0 or abs(np.linalg.norm(normal)-1)>1e-8
            or abs(np.dot(radial,normal))>1e-9 or abs(np.dot(end,normal))>1e-9
            or abs(np.linalg.norm(end)-radius)>1e-9):
        raise ValueError('Invalid spatial annotation arc.')
    u=radial/radius;v=np.cross(normal,u)
    sweep=math.atan2(float(np.dot(end,v)),float(np.dot(end,u)))%math.tau
    if sweep<1e-12:sweep=math.tau
    points=[(center+radius*(u*math.cos(sweep*i/16)+v*math.sin(sweep*i/16))).tolist() for i in range(17)]
    result=projected_circle(points,[1,0,0,0,1,0,0,0,1,0,0,0,1])
    result['style']=item['style']
    return result


def arc_parameters(item):
    if item['kind'] in ('circle','circular_arc'):
        return item['center'],item['radius'],item['angle'],item['sweep']
    a,b,c,n = (item[k] for k in ('start','end','center','normal'))
    radius = math.hypot(a[0]-c[0],a[1]-c[1])
    if abs(abs(n[2])-1)>1e-8 or abs(n[0])+abs(n[1])>1e-8 or radius<=0:
        raise ValueError('Unsupported annotation arc plane.')
    angle = math.atan2(a[1]-c[1],a[0]-c[0])
    end = math.atan2(b[1]-c[1],b[0]-c[0])
    sign = 1 if n[2]>0 else -1
    sweep = sign*((sign*(end-angle))%(2*math.pi))
    if abs(sweep)<1e-12:sweep=sign*2*math.pi
    return c,radius,angle,sweep


def arc_beziers(item):
    center,radius,angle,sweep = arc_parameters(item)
    count = max(1,math.ceil(abs(sweep)/(math.pi/2)))
    delta = sweep/count
    result = []
    for i in range(count):
        a,b = angle+i*delta,angle+(i+1)*delta
        factor = 4/3*math.tan(delta/4)
        ca,sa,cb,sb = math.cos(a),math.sin(a),math.cos(b),math.sin(b)
        result.append([[center[0]+radius*ca,center[1]+radius*sa],
                       [center[0]+radius*(ca-factor*sa),center[1]+radius*(sa+factor*ca)],
                       [center[0]+radius*(cb+factor*sb),center[1]+radius*(sb-factor*cb)],
                       [center[0]+radius*cb,center[1]+radius*sb]])
    return result


def font_choice(font_path=None, bold=False):
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    if font_path is None and os.name=='nt':
        candidate = Path(os.environ.get('WINDIR',r'C:\Windows'))/'Fonts'/('GOTHICB.TTF' if bold else 'GOTHIC.TTF')
        if candidate.is_file():font_path=candidate
    if font_path:
        # Register by content identity rather than reusing another user's font.
        import hashlib
        name = 'DrawingFont_'+hashlib.sha256(Path(font_path).read_bytes()).hexdigest()[:16]
        if name not in pdfmetrics.getRegisteredFontNames():
            font=TTFont(name,str(font_path))
            # ReportLab otherwise shares document resources by PostScript
            # face name even if different files have the same internal name.
            font.face.name=name.encode('ascii')
            pdfmetrics.registerFont(font)
        return name,False
    return 'Helvetica-Bold' if bold else 'Helvetica',True


def text_positions(item):
    x,y = item['origin'][:2]
    angle = item['angle']
    font = item['font']
    # Observed text origin is the lower Windows font cell edge. This Century
    # Gothic baseline relation was checked against the supplied PDF; other
    # font/layout families remain experimental rather than silently accepted.
    offset = font['em_points']*.2168/METRES_TO_POINTS
    x -= math.sin(angle)*offset
    y += math.cos(angle)*offset
    for char,advance in zip(item['text'],item['advances']):
        yield char,x,y
        x += math.cos(angle)*advance
        y += math.sin(angle)*advance


def path_segments(item):
    item=flatten_arc(item)
    kind = item['kind']
    if kind=='line':return [('line',[item['start'],item['end']])]
    if kind in ('arc','circle','circular_arc'):
        return [('bezier',points) for points in arc_beziers(item)]
    if kind=='ellipse':
        angle,sweep=item['angle'],item['sweep']
        count=max(1,math.ceil(abs(sweep)/(math.pi/2)))
        center,major,minor=item['center'],item['major'],item['minor']
        def point(t):return [center[j]+major[j]*math.cos(t)+minor[j]*math.sin(t) for j in range(2)]
        def tangent(t):return [-major[j]*math.sin(t)+minor[j]*math.cos(t) for j in range(2)]
        segments=[]
        for i in range(count):
            a,b=angle+sweep*i/count,angle+sweep*(i+1)/count
            factor=4/3*math.tan((b-a)/4)
            start,end=point(a),point(b);ta,tb=tangent(a),tangent(b)
            segments.append(('bezier',[start,[start[j]+factor*ta[j] for j in range(2)],
                                        [end[j]-factor*tb[j] for j in range(2)],end]))
        return segments
    if kind=='spline':return [('bezier',points) for points in item['beziers']]
    if kind in ('polyline','polygon'):
        points=item['points']
        if kind=='polygon':points=points+[points[0]]
        return [('line',[a,b]) for a,b in zip(points,points[1:])]
    raise ValueError('Unsupported vector primitive: '+kind)


def append_path(path,segments,scale):
    last = getattr(path,'_native_last',None)
    for kind,points in segments:
        start=tuple(v*scale for v in points[0][:2])
        if last is None or math.dist(start,last)>1e-6:path.moveTo(*start)
        if kind=='line':
            end=tuple(v*scale for v in points[-1][:2]);path.lineTo(*end)
        else:
            path.curveTo(*(v*scale for point in points[1:] for v in point[:2]))
            end=tuple(v*scale for v in points[-1][:2])
        last=end
    path._native_last=last


def write_pdf(scene,geometry,output,font_path=None,bold_font=None):
    from reportlab.pdfgen import canvas
    name,substituted = font_choice(font_path)
    bold_name,bold_substituted = font_choice(bold_font,True)
    warnings=[]
    uses_txt=any(p['kind']=='text' and p['font']['family'].casefold()=='txt' for p in scene['primitives'])
    if uses_txt:
        warnings.append('TXT stroke font is unavailable in native PDF export; Courier is substituted. TXT baseline and font metrics are unverified.')
        warnings.append('Older TXT drawing view styles are unverified; solid/dashed edge visibility can differ from the saved preview.')
    if substituted:warnings.append('Century Gothic is unavailable; PDF text uses Helvetica.')
    uses_bold=any(p['kind']=='text' and p['font']['flags'] & 8 for p in scene['primitives'])
    if uses_bold and bold_substituted:warnings.append('Century Gothic Bold is unavailable; bold PDF text uses Helvetica Bold.')
    c=canvas.Canvas(str(output),pagesize=tuple(v*METRES_TO_POINTS for v in scene['size_m']),
                    pageCompression=1)
    c.setTitle('Experimental native drawing export')
    c.setSubject(NOTICE)
    c.setLineWidth(.18*72/25.4)
    filled=None
    for item in scene['primitives']+geometry:
        item=flatten_arc(item)
        kind=item['kind']
        if kind=='fill':
            if not item['enabled'] and filled is not None:
                c.drawPath(filled,stroke=0,fill=1,fillMode=0);filled=None
            elif item['enabled'] and filled is None:filled=c.beginPath()
            continue
        if kind=='text':
            font=item['font']
            if font['family'].casefold() not in ('century gothic','txt'):
                raise ValueError('Unsupported drawing font family: '+font['family'])
            for char,x,y in text_positions(item):
                c.saveState();c.translate(x*METRES_TO_POINTS,y*METRES_TO_POINTS)
                c.rotate(math.degrees(item['angle']));c.scale(font['width'],1)
                chosen='Courier' if font['family'].casefold()=='txt' else (bold_name if font['flags'] & 8 else name)
                c.setFont(chosen,font['em_points']);c.drawString(0,0,char)
                c.restoreState()
            if item['text'] and font['flags'] & 2:
                length=sum(item['advances'])*METRES_TO_POINTS
                _,x,y=next(text_positions(item))
                c.saveState();c.translate(x*METRES_TO_POINTS,y*METRES_TO_POINTS)
                c.rotate(math.degrees(item['angle']));c.line(0,-.6,length,-.6);c.restoreState()
            continue
        if kind=='point':
            if filled is not None:
                raise ValueError('Unsupported point inside a filled annotation.')
            # Preserve the saved location with a dot of the default line
            # thickness. The report marks marker appearance as unverified.
            c.circle(item['origin'][0]*METRES_TO_POINTS,
                     item['origin'][1]*METRES_TO_POINTS,.09*72/25.4,stroke=0,fill=1)
            continue
        segments=path_segments(item)
        if filled is not None:
            append_path(filled,segments,METRES_TO_POINTS)
        else:
            pattern={'CENTER':[43.2,3.6,3.6,3.6],'HIDDEN':[3.6,1.8],
                     'PHANTOM':[90,18,18,18,18,18]}.get(item['style'],[])
            phase=(math.dist(item['start'][:2],item['end'][:2])*METRES_TO_POINTS/2
                   if item['style']=='HIDDEN' and kind=='line' else 0)
            c.setDash(pattern,phase)
            p=c.beginPath();append_path(p,segments,METRES_TO_POINTS)
            c.drawPath(p,stroke=0 if kind=='polygon' else 1,fill=1 if kind=='polygon' else 0)
    if filled is not None:raise ValueError('Unclosed annotation fill group.')
    c.setDash([]);c.setFillColorRGB(.8,0,0);c.setFont('Helvetica',12)
    c.drawString(14,scene['size_m'][1]*METRES_TO_POINTS-14,NOTICE)
    c.showPage();c.save()
    return {'font_substituted':substituted or (uses_bold and bold_substituted),'warnings':warnings}


def write_dxf(scene,geometry,output):
    import ezdxf
    d=ezdxf.new('R2000')
    d.units=4  # Millimetres, including the sheet. No fitted manufacturing scale.
    d.header['$MEASUREMENT']=1
    d.header['$EXTMIN']=(0,0,0)
    d.header['$EXTMAX']=(*[v*1000 for v in scene['size_m']],0)
    d.linetypes.new('CENTER',dxfattribs={'description':'Center','pattern':[19.05,15.24,-1.27,1.27,-1.27]})
    d.linetypes.new('HIDDEN',dxfattribs={'description':'Hidden edges','pattern':[1.905,1.27,-.635]})
    d.linetypes.new('PHANTOM',dxfattribs={'description':'Phantom (standard pattern)',
                                      'pattern':[63.5,31.75,-6.35,6.35,-6.35,6.35,-6.35]})
    d.styles.new('DrawingFont',dxfattribs={'font':'gothic.ttf'})
    d.styles.new('DrawingFontBold',dxfattribs={'font':'gothicb.ttf'})
    d.styles.new('DrawingTxt',dxfattribs={'font':'txt.shx'})
    d.layers.new('EXPERIMENTAL_NOTICE',dxfattribs={'color':1})
    m=d.modelspace()
    def xy(point):return tuple(v*1000 for v in point[:2])
    filled=None
    for item in scene['primitives']+geometry:
        item=flatten_arc(item)
        kind=item['kind']
        attrs={'linetype':item['style']}
        if kind=='fill':
            if item['enabled']:
                if filled is None:filled=[]
            elif filled is not None:
                hatch=m.add_hatch(color=7)
                edge=hatch.paths.add_edge_path()
                for entry in filled:
                    if entry['kind']=='line':edge.add_line(xy(entry['start']),xy(entry['end']))
                    else:
                        center,r,a,s=arc_parameters(entry)
                        edge.add_arc(xy(center),r*1000,math.degrees(a),math.degrees(a+s),ccw=s>0)
                filled=None
            continue
        if filled is not None:
            if kind not in ('line','arc'):raise ValueError('Unsupported filled annotation geometry.')
            filled.append(item);continue
        if kind=='point':m.add_point(xy(item['origin']),dxfattribs=attrs)
        elif kind=='line':m.add_line(xy(item['start']),xy(item['end']),dxfattribs=attrs)
        elif kind in ('arc','circle','circular_arc'):
            center,r,a,s=arc_parameters(item)
            if abs(abs(s)-2*math.pi)<1e-8:m.add_circle(xy(center),r*1000,dxfattribs=attrs)
            else:
                start,end=(a,a+s) if s>0 else (a+s,a)
                m.add_arc(xy(center),r*1000,math.degrees(start)%360,math.degrees(end)%360,dxfattribs=attrs)
        elif kind=='ellipse':
            a,s=item['angle'],item['sweep']
            start,end=(0,math.tau) if abs(abs(s)-math.tau)<1e-8 else ((a,a+s) if s>0 else (a+s,a))
            m.add_ellipse(xy(item['center']),major_axis=(*xy(item['major']),0),
                          ratio=item['ratio'],start_param=start,end_param=end,dxfattribs=attrs)
        elif kind=='spline':
            spline=m.add_spline(dxfattribs=attrs)
            spline.dxf.degree=item['degree']
            spline.control_points=[(*xy(p),0) for p in item['poles']]
            spline.knots=item['knots']
        elif kind=='polyline':m.add_lwpolyline([xy(p) for p in item['points']],dxfattribs=attrs)
        elif kind=='polygon':
            if len(item['points'])!=3:raise ValueError('Only triangular arrow fills are supported.')
            m.add_solid([xy(p) for p in item['points']],dxfattribs=attrs)
        elif kind=='text':
            font=item['font']
            for char,x,y in text_positions(item):
                m.add_text(char,dxfattribs={'insert':(x*1000,y*1000,0),
                    'height':font['em_points']/METRES_TO_POINTS*1000*.718,
                    'rotation':math.degrees(item['angle']),'width':font['width'],
                    'style':'DrawingTxt' if font['family'].casefold()=='txt' else ('DrawingFontBold' if font['flags'] & 8 else 'DrawingFont')})
            if item['text'] and font['flags'] & 2:
                _,x,y=next(text_positions(item))
                angle=item['angle']
                offset=.6/METRES_TO_POINTS
                x+=math.sin(angle)*offset; y-=math.cos(angle)*offset
                length=sum(item['advances'])
                m.add_line((x*1000,y*1000),
                           ((x+math.cos(angle)*length)*1000,(y+math.sin(angle)*length)*1000))
        else:raise ValueError('Unsupported DXF primitive: '+kind)
    if filled is not None:raise ValueError('Unclosed DXF annotation fill.')
    m.add_text(NOTICE,dxfattribs={'height':2.5,'insert':(5,scene['size_m'][1]*1000-5,0),
                                  'layer':'EXPERIMENTAL_NOTICE'})
    d.saveas(output)
    checked=ezdxf.readfile(output)
    auditor=checked.audit()
    if auditor.has_errors or auditor.has_fixes:
        raise ValueError('DXF validation found errors or needed repairs.')
    return {'entity_count':len(checked.modelspace()),'units':'mm','version':checked.dxfversion}
