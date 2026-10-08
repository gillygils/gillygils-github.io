"""Bounded, isolated entry point for native experimental drawing exports."""
import argparse
import hashlib
import json
import time
from pathlib import Path
from .archive import read_archive
from .scene import decode_scene
from .curves import drawing_geometry
from .exports import write_pdf, write_dxf, NOTICE


def export_drawing(source, output, part=None, dwg=False, dwg_tools=None, font=None, bold_font=None):
    started = time.monotonic()
    source, output = Path(source), Path(output)
    if source.suffix.lower() != '.slddrw':
        raise ValueError('Supply a .slddrw drawing.')
    if part:
        part = Path(part)
        if part.suffix.lower() != '.sldprt' or part.stem.casefold() != source.stem.casefold():
            raise ValueError('The optional .sldprt must have the same name as the drawing.')
    if output.exists():
        raise FileExistsError('Choose a new output directory; existing files are never replaced.')
    scene = decode_scene(read_archive(source))
    geometry, metrics = drawing_geometry(scene, part)
    output.mkdir(parents=True, exist_ok=False)
    stem = source.stem + '-EXPERIMENTAL'
    report = {'implementation': 'independent-native-drawing', 'production_supported': False,
              'notice': NOTICE, 'source': source.name,
              'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
              'sheet': scene['sheet'], 'sheet_size_mm': [v*1000 for v in scene['size_m']],
              'views': len(scene['views']), 'commands': scene['command_count'],
              'annotation_primitives': len(scene['primitives']),
              'opaque_prefix_bytes': scene['opaque_prefix_bytes'],
              'opaque_view_metadata_bytes': scene['opaque_view_metadata_bytes'],
              'limitations': scene['limitations'], 'geometry': metrics, 'exports': {}}
    try:
        pdf, dxf = output/(stem+'.pdf'), output/(stem+'.dxf')
        pdf_metrics = write_pdf(scene, geometry, pdf, font, bold_font)
        from pypdf import PdfReader
        pages = PdfReader(pdf).pages
        if (len(pages) != 1 or NOTICE not in pages[0].extract_text()
                or max(abs(float(pages[0].mediabox[i+2])-scene['size_m'][i]*72/.0254)
                       for i in range(2)) > .01):
            raise ValueError('Experimental PDF failed page-size or notice validation.')
        report['exports']['pdf'] = {'file': pdf.name, 'pages': 1, **pdf_metrics}
        report['exports']['dxf'] = {'file': dxf.name, **write_dxf(scene, geometry, dxf)}
        if dwg:
            from .dwg import write_dwg
            target = output/(stem+'.dwg')
            try:
                report['exports']['dwg'] = {'file': target.name, **write_dwg(dxf, target, dwg_tools)}
            except Exception as exc:
                report['exports']['dwg'] = {'error': str(exc)}
        report['elapsed_seconds'] = time.monotonic()-started
        (output/'drawing-report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        return report
    except Exception:
        # This directory belongs only to this operation; never offer a partial
        # PDF/DXF pair as a completed download.
        import shutil
        shutil.rmtree(output)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--part', type=Path)
    parser.add_argument('--dwg', action='store_true')
    parser.add_argument('--dwg-tools', type=Path)
    parser.add_argument('--font', type=Path)
    parser.add_argument('--bold-font', type=Path)
    args = parser.parse_args()
    try:
        report = export_drawing(args.source, args.output, args.part, args.dwg, args.dwg_tools, args.font, args.bold_font)
        print(json.dumps(report))
    except Exception as exc:
        parser.exit(1, str(exc) + '\n')


if __name__ == '__main__':
    main()
