"""App adapter. Native decoding runs separately with a total time limit."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

APP = Path(__file__).resolve().parents[1]


def drawing_diagnostics():
    problems = []
    try:
        import ezdxf
        import reportlab
        import OCP
    except ImportError as exc:
        problems.append(str(exc))
    from .dwg import find_tools
    try:
        find_tools()
        dwg_ready = True
    except RuntimeError:
        dwg_ready = False
    return {'ready': not problems, 'problems': problems, 'dwg_ready': dwg_ready}


def convert_drawing_native(source, output, part=None, dwg=False):
    from core import copy_new
    source, output = Path(source).resolve(), Path(output).resolve()
    if output.exists():
        raise FileExistsError('Choose a new output directory.')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='native-drawing-', dir=output.parent) as temp:
        staging = Path(temp)/'exports'
        command = [sys.executable, '-m', 'native_drawing.worker', str(source), '--output', str(staging)]
        if part:
            command += ['--part', str(Path(part).resolve())]
        if dwg:
            command.append('--dwg')
        try:
            result = subprocess.run(command, cwd=APP, capture_output=True, text=True, timeout=90)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError('Native drawing export exceeded 90 seconds. No downloads were published.') from exc
        if result.returncode:
            raise RuntimeError(result.stderr.strip()[-1500:] or 'Native drawing export failed.')
        files = ['drawing-report.json']
        try:
            report = json.loads(result.stdout.strip().splitlines()[-1])
            expected = 'local-libredwg-input' if source.suffix.lower() == '.dwg' else 'independent-native-drawing'
            if (report['implementation'] != expected
                    or report['production_supported'] is not False
                    or not all(report['exports'][kind].get('file') for kind in ('pdf', 'dxf'))):
                raise ValueError('Unexpected drawing export result.')
            for kind, entry in report['exports'].items():
                if 'file' in entry:
                    name = entry['file']
                    if (kind not in ('pdf', 'dxf', 'dwg')
                            or name != source.stem+'-EXPERIMENTAL.'+kind
                            or not (staging/name).is_file()):
                        raise ValueError('Drawing output is missing or invalid.')
                    files.append(name)
            if not (staging/'drawing-report.json').is_file():
                raise ValueError('Drawing report is missing.')
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise RuntimeError('Native decoder did not produce verified experimental exports.') from exc
        output.mkdir(exist_ok=False)
        try:
            for name in files:
                copy_new(staging/name, output/name)
        except Exception:
            import shutil
            shutil.rmtree(output)
            raise
    return report
