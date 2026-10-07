"""PO parsing and conservative exact file lookup. No source files are modified."""
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader


@dataclass(frozen=True)
class Item:
    number: int
    quantity: str
    unit: str
    part: str


def parse_po(file):
    reader = PdfReader(file)
    text = '\n'.join(page.extract_text(extraction_mode='layout') or '' for page in reader.pages)
    match = re.search(r'\bPO\s*#\s*:?\s*(\d+)\b', text, re.I)
    if not match:
        raise ValueError('Cannot find a PO number. Upload a text-based PDF like the sample PO; scanned PDFs need OCR.')
    standard = r'^\s*(\d+)\s+(\d+(?:\.\d+)?)\s+([A-Z]{1,4})\s+([A-Z]\d{5}(?:_\d+)?)\b'
    reordered = r'^\s*(\d+)\s+([A-Z]{1,4})\s+([A-Z]\d{5}(?:_\d+)?)\s+(\d+(?:\.\d+)?)\b'
    items = []
    for line in text.splitlines():
        found = re.match(standard, line)
        if found:
            n, qty, unit, part = found.groups()
        else:
            found = re.match(reordered, line)
            if not found:
                continue
            n, unit, part, qty = found.groups()
        items.append(Item(int(n), qty, unit, part.upper()))
    if not items:
        raise ValueError('No line items found. This parser expects the layout used by PO 1530; review other PO formats separately.')
    if len({i.number for i in items}) != len(items):
        raise ValueError('Duplicate line numbers found; check the PDF before proceeding.')
    if [i.number for i in items] != list(range(1, len(items) + 1)):
        raise ValueError('Line numbers are incomplete or out of order. Review the PDF format before proceeding.')
    return match[1], items


SUPPORTED = {'.sldprt', '.slddrw', '.sldasm', '.step', '.stp', '.pdf'}


def idt_folder(part):
    match = re.fullmatch(r'([A-Z])(\d{5})(?:_\d+)?', part.upper())
    if not match:
        raise ValueError(f'Cannot determine IDT folder for {part}')
    return f'IDT {match[1]}{int(match[2]) // 1000 * 1000:05d}'


def find_files(root, parts, grouped=False, progress=None):
    import os
    import stat
    root = Path(root)
    if not root.is_dir():
        raise ValueError('The source folder is unavailable. Check the drive mapping and access permissions.')
    matches = {p: [] for p in parts}
    lookup = {p.upper(): p for p in matches}
    if grouped:
        folders = sorted({idt_folder(p) for p in parts})
        scopes = [root if root.name.casefold() == name.casefold() else root / name for name in folders]
    else:
        scopes = [root]
    scanned = 0
    for index, scope in enumerate(scopes):
        if progress:
            progress(index, len(scopes), str(scope), scanned)
        try:
            mode = scope.stat().st_mode
        except FileNotFoundError:
            continue
        if not stat.S_ISDIR(mode):
            raise ValueError(f'Expected a folder: {scope}')
        if scope.is_symlink():
            raise ValueError(f'Source folder cannot be a symbolic link: {scope}')
        pending = [scope]
        while pending:
            folder = pending.pop()
            try:
                # DirEntry uses cached directory metadata, reducing network round trips.
                with os.scandir(folder) as entries:
                    for entry in entries:
                        if entry.is_dir(follow_symlinks=False):
                            pending.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            stem, suffix = os.path.splitext(entry.name)
                            if suffix.lower() not in SUPPORTED:
                                continue
                            candidate = re.match(r'^([A-Z]\d{5}(?:_\d+)?)(?:$|[ -])', stem, re.I)
                            if candidate and candidate[1].upper() in lookup:
                                matches[lookup[candidate[1].upper()]].append(Path(entry.path))
            except OSError as exc:
                raise OSError(f'Cannot search {folder}: {exc}') from exc
            scanned += 1
            if progress:
                progress(index, len(scopes), str(folder), scanned)
    if progress:
        progress(len(scopes), len(scopes), 'Search complete', scanned)
    return {p: sorted(paths, key=lambda x: str(x).lower()) for p, paths in matches.items()}


def validate_destination(source, output):
    source = Path(source).resolve()
    output = Path(output).resolve()
    if output == source or source in output.parents:
        raise ValueError('Choose an output folder outside the searched source tree so generated files are not matched on future runs.')
    return output


def copy_new(source, destination):
    """Exclusive destination creation: never overwrite an existing file."""
    source, destination = Path(source), Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with source.open('rb') as src, destination.open('xb') as dst:
            shutil.copyfileobj(src, dst)
    except FileExistsError:
        raise
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    shutil.copystat(source, destination)
    return destination


def add_converted_exports(completed, uploads):
    """Add manually converted files and atomically replace the downloadable ZIP."""
    import json
    import os
    import tempfile
    job = Path(completed['folder'])
    report = json.loads(json.dumps(completed['report']))
    parts = {item['part'].upper() for item in report['items']}
    prepared = []
    names = set()
    existing = {p.name.casefold() for p in job.iterdir()}
    for upload in uploads:
        name = upload.name
        if '/' in name or '\\' in name or name in {'.', '..'}:
            raise ValueError('Export filenames must not contain directory paths.')
        path = Path(name)
        if path.suffix.lower() not in {'.step', '.stp', '.pdf'}:
            raise ValueError(f'{name}: only STEP and PDF exports can be added.')
        match = re.match(r'^([A-Z]\d{5}(?:_\d+)?)(?:$|[ -])', path.stem, re.I)
        if not match or match[1].upper() not in parts:
            raise ValueError(f'{name}: filename must start with an exact part number from this PO, such as C15999.step.')
        if name.casefold() in names or name.casefold() in existing:
            raise ValueError(f'{name}: already exists. Existing files are never overwritten; remove it from the upload selection.')
        data = upload.getvalue()
        if path.suffix.lower() == '.pdf':
            valid = data.lstrip().startswith(b'%PDF-')
        else:
            valid = data.lstrip().startswith(b'ISO-10303-21;') and b'END-ISO-10303-21;' in data
        if not valid:
            raise ValueError(f'{name}: does not have a recognized {path.suffix} file header. Renaming a native file does not convert it.')
        prepared.append((name, data, match[1].upper()))
        names.add(name.casefold())
    if not prepared:
        raise ValueError('Upload at least one converted STEP or PDF.')
    previous_report = (job / 'report.json').read_bytes()
    created = []
    archive = Path(completed['archive']) if completed.get('archive') else job.with_suffix('.zip')
    try:
        for name, data, part in prepared:
            destination = job / name
            with destination.open('xb') as file:
                created.append(destination)
                file.write(data)
            report['results'].append({'part': part, 'source': f'Manually converted export: {name}', 'copy': str(destination), 'status': 'Added export'})
        (job / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        with tempfile.TemporaryDirectory(prefix='po-export-', dir=job.parent) as temp:
            new_archive = shutil.make_archive(str(Path(temp) / 'package'), 'zip', root_dir=job)
            os.replace(new_archive, archive)
    except Exception:
        for path in created:
            path.unlink(missing_ok=True)
        (job / 'report.json').write_bytes(previous_report)
        raise
    return {**completed, 'report': report, 'archive': str(archive)}
