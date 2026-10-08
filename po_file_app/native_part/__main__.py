"""Extract verified archive entries and part geometry blocks without Convert3D."""
import argparse
import hashlib
import json
import re
import time
from pathlib import Path
from native_drawing.archive import read_archive
from .partition import recover_blocks, parasolid_header


PARTITION = re.compile(r'(^|/)Config-(\d+)-Partition$', re.I)


def inspect(source, output):
    started = time.monotonic()
    source, output = Path(source), Path(output)
    if source.suffix.lower() != '.sldprt':
        raise ValueError('Supply a SolidWorks .sldprt part.')
    entries = read_archive(source)
    partitions, recovered = [], []
    for name, data in entries.items():
        match = PARTITION.search(name)
        if not match:
            continue
        result = recover_blocks(data)
        streams = []
        for block in result['blocks']:
            payload = block['data']
            header = parasolid_header(payload)
            if header is not None:
                filename = f'config-{match[2]}-block-{len(streams):03d}.x_b'
                recovered.append((filename, payload))
            else:
                filename = None
            streams.append({key: value for key, value in block.items() if key != 'data'} |
                           {'parasolid_header': header, 'extracted_file': filename})
        partitions.append({'entry': name, 'configuration_archive_id': match[2],
                           'blocks': streams, 'opaque_gaps': result['opaque_gaps'],
                           'unparsed_tail_bytes': result['unparsed_tail_bytes']})
    if not partitions or not recovered:
        raise ValueError('No supported saved Parasolid partition blocks were found.')
    report = {'source': source.name, 'sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
              'archive_entry_count': len(entries), 'partitions': partitions,
              'step_conversion_supported': False, 'current_body_reconstructed': False,
              'limitations': ['Parasolid entities, topology and geometry are not decoded.',
                              'Delta streams have not been applied to their base partitions.',
                              'Archive configuration IDs are not mapped to user configuration names.',
                              'Opaque framing gaps and tails remain uninterpreted.',
                              'No STEP or display-mesh substitute is generated.']}
    output.mkdir(parents=True, exist_ok=False)
    for filename, payload in recovered:
        with (output / filename).open('xb') as file:
            file.write(payload)
    report['elapsed_seconds'] = time.monotonic() - started
    (output / 'inspection.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = inspect(args.source, args.output)
    print(json.dumps({'step_conversion_supported': False,
                      'archive_entries': report['archive_entry_count'],
                      'partitions': len(report['partitions']),
                      'recovered_blocks': sum(len(p['blocks']) for p in report['partitions']),
                      'elapsed_seconds': report['elapsed_seconds']}))


if __name__ == '__main__':
    main()
