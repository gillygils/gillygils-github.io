"""Local DWG decoding and vector PDF rendering using LibreDWG and ezdxf.

This path renders model space fitted to an A3 landscape page. It does not
recover a CAD application's plot configuration or promise original fonts.
"""
import hashlib
import math
import subprocess
import tempfile
from collections import Counter
from pathlib import Path
from .archive import MAX_FILE
from .dwg import find_tools
from .exports import NOTICE


def vector_pdf(doc, output):
    from reportlab.pdfgen import canvas
    from ezdxf.addons.drawing import Frontend, RenderContext
    from ezdxf.addons.drawing.backend import Backend
    from ezdxf.addons.drawing.recorder import Recorder
    from ezdxf.addons.drawing.config import Configuration, BackgroundPolicy, ColorPolicy
    from ezdxf.path import Command

    # Reject external/raster objects before the frontend can resolve paths
    # stored in the drawing, including objects nested inside block definitions.
    raster={'IMAGE','OLE2FRAME','PDFUNDERLAY','DWFUNDERLAY','DGNUNDERLAY'}
    if any(entity.dxftype() in raster for entity in doc.entitydb.values()):
        raise ValueError('Raster or external DWG content is not supported by the vector exporter.')

    skipped = []
    class CheckedFrontend(Frontend):
        def skip_entity(self, entity, msg):
            skipped.append({'type': entity.dxftype(), 'handle': entity.dxf.handle, 'reason': msg})

    recorder = Recorder()
    config = Configuration(background_policy=BackgroundPolicy.WHITE, color_policy=ColorPolicy.BLACK)
    CheckedFrontend(RenderContext(doc), recorder, config=config).draw_layout(doc.modelspace())
    player = recorder.player()
    box = player.bbox()
    if not box.has_data:
        raise ValueError('No visible vector geometry in DWG model space.')
    extent = box.size
    if not all(math.isfinite(v) and v >= 0 for v in extent) or max(extent) == 0:
        raise ValueError('Invalid DWG model-space extent.')
    if skipped:
        raise ValueError('DWG rendering would omit entities: '+str(skipped[:5]))
    if len(recorder.records) > 500000:
        raise ValueError('DWG vector output exceeds its primitive limit.')
    page = (420 * 72/25.4, 297 * 72/25.4)
    margin, title = 18., 24.
    scale = min((page[0]-2*margin)/max(extent.x,1e-12),
                (page[1]-2*margin-title)/max(extent.y,1e-12))
    c = canvas.Canvas(str(output), pagesize=page, pageCompression=1)
    c.setTitle('Experimental DWG vector export')
    c.setSubject(NOTICE)
    c.saveState()
    c.translate(margin-box.extmin.x*scale, margin-box.extmin.y*scale)
    c.scale(scale,scale)

    class PdfBackend(Backend):
        def set_background(self, color):
            pass

        def properties(self, props):
            c.setStrokeColorRGB(0,0,0); c.setFillColorRGB(0,0,0)
            c.setLineWidth(max(.1,props.lineweight*72/25.4)/scale)

        def draw_point(self, pos, props):
            self.properties(props);c.circle(pos.x,pos.y,.3/scale,stroke=0,fill=1)

        def draw_line(self, a, b, props):
            self.properties(props);c.line(a.x,a.y,b.x,b.y)

        def path(self, target, source, close=False):
            current = source.start
            target.moveTo(current.x,current.y)
            for cmd in source.commands():
                end = cmd.end
                if cmd.type == Command.MOVE_TO:
                    target.moveTo(end.x,end.y)
                elif cmd.type == Command.LINE_TO:
                    target.lineTo(end.x,end.y)
                elif cmd.type == Command.CURVE4_TO:
                    target.curveTo(cmd.ctrl1.x,cmd.ctrl1.y,cmd.ctrl2.x,cmd.ctrl2.y,end.x,end.y)
                elif cmd.type == Command.CURVE3_TO:
                    a=current+(cmd.ctrl-current)*2/3
                    b=end+(cmd.ctrl-end)*2/3
                    target.curveTo(a.x,a.y,b.x,b.y,end.x,end.y)
                else:
                    raise ValueError('Unsupported DWG vector path command.')
                current=end
            if close:target.close()

        def draw_path(self, path, props):
            self.properties(props);target=c.beginPath();self.path(target,path)
            c.drawPath(target,stroke=1,fill=0)

        def draw_filled_paths(self, paths, props):
            self.properties(props);target=c.beginPath()
            for path in paths:self.path(target,path,True)
            c.drawPath(target,stroke=0,fill=1,fillMode=0)

        def draw_filled_polygon(self, points, props):
            vertices=points.vertices()
            if not vertices:return
            self.properties(props);target=c.beginPath();target.moveTo(*vertices[0])
            for p in vertices[1:]:target.lineTo(*p)
            target.close();c.drawPath(target,stroke=0,fill=1)

        def draw_image(self, image, props):
            raise ValueError('Raster DWG content is not supported by the vector exporter.')

        def clear(self):
            raise ValueError('Unexpected DWG renderer reset.')

    player.replay(PdfBackend())
    c.restoreState();c.setFont('Helvetica',10);c.setFillColorRGB(.8,0,0)
    c.drawString(margin,page[1]-16,NOTICE)
    c.showPage();c.save()
    return {'pages':1,'vector':True,'layout':'Model','fitted_to_page':True,
            'sheet_size_mm':[420,297],'entity_count':len(doc.modelspace()),
            'entity_types':dict(Counter(e.dxftype() for e in doc.modelspace())),
            'warnings':['Model space is fitted to A3 landscape; original plot scale is not preserved.',
                        'Paper-space layouts and their plot configurations are not exported.',
                        'Text uses locally available CAD fonts or substitutes; compare with the original.']}


def export_dwg(source, output, tools=None):
    import ezdxf
    from pypdf import PdfReader
    source, output = Path(source), Path(output)
    if source.suffix.lower() != '.dwg' or not 0 < source.stat().st_size <= MAX_FILE:
        raise ValueError('Supply a nonempty DWG of at most 64 MiB.')
    if output.exists():
        raise FileExistsError('Choose a new output directory.')
    commands=find_tools(tools)
    version=subprocess.run([commands['dwg2dxf'],'--version'],capture_output=True,text=True,timeout=10)
    if version.returncode or '0.14' not in version.stdout:
        raise ValueError('DWG input requires LibreDWG 0.14.')
    with tempfile.TemporaryDirectory(prefix='dwg-input-') as temp:
        dxf=Path(temp)/'drawing.dxf'
        result=subprocess.run([commands['dwg2dxf'],'-o',str(dxf),str(source.resolve())],
                              capture_output=True,text=True,timeout=45)
        if result.returncode or not dxf.is_file() or not 0 < dxf.stat().st_size <= MAX_FILE:
            raise ValueError('LibreDWG could not decode the DWG: '+result.stderr[-1000:])
        doc=ezdxf.readfile(dxf)
        audit=doc.audit()
        if audit.has_errors or audit.has_fixes:
            raise ValueError('Decoded DWG requires DXF repairs; exports were stopped.')
        pdf=Path(temp)/'drawing.pdf'
        metrics=vector_pdf(doc,pdf)
        pages=PdfReader(pdf).pages
        if len(pages)!=1 or NOTICE not in pages[0].extract_text() or len(pages[0].images):
            raise ValueError('DWG PDF failed vector/page validation.')
        stem=source.stem+'-EXPERIMENTAL'
        report={'implementation':'local-libredwg-input','production_supported':False,
                'source':source.name,'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
                'notice':NOTICE,'views':1,'geometry':{'geometry_primitives':metrics['entity_count'],
                'unresolved_splines':[]},'exports':{'pdf':{'file':stem+'.pdf',**metrics},
                'dxf':{'file':stem+'.dxf','audit_errors':0,'audit_fixes':0}},
                'decoder_warnings':result.stderr[-4000:],
                'limitations':metrics['warnings']+['LibreDWG decoding can be incomplete; inspect decoder warnings.']}
        output.mkdir(parents=True,exist_ok=False)
        try:
            import json
            (output/(stem+'.pdf')).write_bytes(pdf.read_bytes())
            (output/(stem+'.dxf')).write_bytes(dxf.read_bytes())
            (output/'drawing-report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        except Exception:
            import shutil
            shutil.rmtree(output)
            raise
        return report
