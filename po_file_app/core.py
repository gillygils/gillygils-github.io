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


def find_files(root, parts):
    root = Path(root)
    if not root.is_dir():
        raise ValueError('The source folder is unavailable. Check the drive mapping and access permissions.')
    matches = {p: [] for p in parts}
    # One traversal for all PO lines. Never silently skip unreadable directories.
    import os
    def fail(error):
        raise OSError(f'Cannot search {error.filename}: {error.strerror}')
    for folder, dirs, names in os.walk(root, onerror=fail, followlinks=False):
        dirs[:] = [d for d in dirs if not Path(folder, d).is_symlink()]
        for name in names:
            path = Path(folder, name)
            if path.is_symlink() or path.suffix.lower() not in SUPPORTED:
                continue
            for part in matches:
                # A descriptive name is accepted after a space or dash, not another part/configuration suffix.
                if re.match(r'^' + re.escape(part) + r'(?:$|[ -])', path.stem, re.I):
                    matches[part].append(path)
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
