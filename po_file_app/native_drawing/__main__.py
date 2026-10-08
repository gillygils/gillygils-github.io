"""Native experimental exports and the legacy display-inspection helper."""
import argparse
import hashlib
import json
import time
from pathlib import Path
from .archive import read_archive
from .display import read_display
from .draft import write_draft


def inspect(source, output):
    started = time.monotonic()
    source,output = Path(source),Path(output)
    if source.suffix.lower() != '.slddrw':
        raise ValueError('Supply a SolidWorks .slddrw drawing.')
    entries = read_archive(source)
    if 'Contents/DisplayLists' not in entries:
        raise ValueError('No supported drawing display list found.')
    display = read_display(entries['Contents/DisplayLists'])
    report = {'source':source.name,'sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
              'production_pdf_supported':False,'sheet_mapping_verified':False,
              'archive_entries':[{'name':name,'bytes':len(data)} for name,data in entries.items()],
              'display':display,
              'limitations':['Curves, symbols, layers and view transforms are incomplete.',
                             'Only observed unrotated planar text is rendered, using a substituted font.',
                             'Single diagnostic page; all-sheet support is not implemented.',
                             'Record matching does not establish complete stream interpretation.',
                             'Drawing is fitted to page; manufacturing scale is not verified.']}
    output.mkdir(parents=True,exist_ok=False)
    write_draft(display,output/(source.stem+'-INCOMPLETE-draft.pdf'))
    report['elapsed_seconds'] = time.monotonic()-started
    (output/'inspection.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report


def inspect_main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    report = inspect(args.source,args.output)
    print(json.dumps({'production_pdf_supported':False,'line_records':len(report['display']['lines']),
                      'text_records':len(report['display']['texts']),'elapsed_seconds':report['elapsed_seconds']}))


if __name__ == '__main__':
    from .worker import main
    main()
