"""Detect eDrawings and run PDF printing in an isolated Windows subprocess."""
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from pypdf import PdfReader


def drawing_capability():
    if sys.platform != 'win32':
        return None, 'Automatic drawing PDF printing requires Windows.'
    if importlib.util.find_spec('PySide6') is None:
        return None, 'Install the updated requirements using run_windows.bat.'
    import winreg
    for progid in ('EModelView.EModelViewControl', 'EModelView.EModelViewControl.1', 'eDrawingsSdk.EModelViewControl'):
        try:
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, progid + '\\CLSID') as key:
                clsid = winreg.QueryValueEx(key, None)[0]
            return clsid, 'eDrawings control detected. PDF automation needs a first-run Windows test.'
        except FileNotFoundError:
            continue
        except OSError as exc:
            return None, f'Cannot read eDrawings registration: {exc}'
    return None, 'eDrawings ActiveX control was not found. Repair/install eDrawings with matching 64-bit Python.'


def validate_pdf(path, expected_pages):
    if not isinstance(expected_pages, int) or isinstance(expected_pages, bool) or expected_pages <= 0:
        raise RuntimeError('The print worker returned an invalid sheet count.')
    reader = PdfReader(path)
    if reader.is_encrypted or len(reader.pages) != expected_pages:
        raise RuntimeError(f'PDF page count does not match the {expected_pages} drawing sheets.')
    for page in reader.pages:
        content = page.get_contents()
        if content is None or not content.get_data():
            raise RuntimeError('PDF includes an empty page; review the drawing manually.')
    return len(reader.pages)


def convert_drawing(source, destination, paper='Tabloid', landscape=True):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source.suffix.lower() != '.slddrw' or not source.is_file():
        raise ValueError('Supply an existing .slddrw drawing.')
    if destination.exists():
        raise FileExistsError(f'Will not overwrite {destination}')
    control, explanation = drawing_capability()
    if control is None:
        raise RuntimeError(explanation)
    if paper not in {'Letter', 'Tabloid', 'A4', 'A3'}:
        raise ValueError('Unsupported PDF paper size.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='drawing-pdf-', dir=destination.parent) as temp:
        pdf = Path(temp) / 'drawing.pdf'
        command = [sys.executable, str(Path(__file__).with_name('worker.py')), str(source), str(pdf), '--control', control, '--paper', paper]
        if not landscape:
            command.append('--portrait')
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=55)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError('eDrawings printing timed out. Check for a print dialog and try the manual PDF workflow.') from exc
        if result.returncode:
            raise RuntimeError(result.stderr.strip()[-1500:] or 'eDrawings did not produce a PDF.')
        try:
            response = json.loads(result.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError) as exc:
            raise RuntimeError('Unexpected response from eDrawings printing.') from exc
        if not response.get('success'):
            raise RuntimeError('eDrawings did not report successful PDF output.')
        pages = validate_pdf(pdf, response.get('sheets'))
        from core import copy_new
        copy_new(pdf, destination)
    return {**response, 'pages': pages}
