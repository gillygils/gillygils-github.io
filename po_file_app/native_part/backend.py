"""App adapter for our Python decoder; no vendor cache, Node or web calls."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

APP = Path(__file__).resolve().parents[1]


def native_diagnostics():
    report = {'implementation': 'independent-native', 'app_folder': str(APP),
              'python': sys.executable, 'problems': []}
    try:
        import OCP
    except Exception as exc:
        report['problems'].append('Geometry library cannot load: ' + str(exc))
    report['ready'] = not report['problems']
    return report


def convert_part_native(source, destination):
    from core import copy_new
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if destination.exists():
        raise FileExistsError(f'Will not overwrite {destination}')
    if not native_diagnostics()['ready']:
        raise RuntimeError('Geometry library is missing. Run run_windows.bat once to install Python dependencies.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='native-step-', dir=destination.parent) as temp:
        output = Path(temp) / 'validated.step'
        try:
            result = subprocess.run([sys.executable, '-m', 'native_part.worker', str(source), str(output)],
                                    cwd=APP, capture_output=True, text=True, timeout=120)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError('Independent conversion exceeded 120 seconds; no STEP was published.') from exc
        if result.returncode:
            raise RuntimeError(result.stderr.strip()[-1500:] or 'Independent conversion failed.')
        try:
            response = json.loads(result.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError) as exc:
            raise RuntimeError('Independent converter returned an unexpected result.') from exc
        if (not isinstance(response, dict) or response.get('implementation') != 'independent-native'
                or response.get('success') is not True or not response.get('single_valid_solid')
                or not output.is_file()):
            raise RuntimeError('Independent converter did not produce a validated STEP.')
        copy_new(output, destination)
    return response
