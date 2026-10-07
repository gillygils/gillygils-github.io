"""Run the permitted reader offline and validate a single-solid STEP result."""
import importlib.util
import json
import math
import os
import subprocess
import tempfile
from pathlib import Path

from converter.setup import APP, MANIFEST, node_executable


def converter_ready():
    files = json.loads(MANIFEST.read_text())['files']
    return bool(node_executable() and importlib.util.find_spec('OCP') and all((APP / '.converter' / 'modules' / file['name']).is_file() for file in files))


def convert_part(source, destination):
    from experimental.step_reference import analyze_step
    source, destination = Path(source), Path(destination)
    if destination.exists():
        raise FileExistsError(f'Will not overwrite {destination}')
    if not converter_ready():
        raise RuntimeError('Local converter is not installed. Run run_windows.bat again or converter/setup.py.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='part-step-', dir=destination.parent) as temp:
        raw = Path(temp) / 'raw.step'
        repaired = Path(temp) / 'validated.step'
        try:
            result = subprocess.run([node_executable(), '--max-old-space-size=1024', str(APP / 'converter' / 'run.cjs'), str(source), str(raw)], capture_output=True, text=True, timeout=120)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError('Conversion exceeded 120 seconds; the part was not exported.') from exc
        if result.returncode:
            detail = result.stderr.strip()[-1500:] or result.stdout.strip()[-1500:]
            raise RuntimeError(detail or 'The local converter failed.')
        try:
            response = json.loads(result.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError) as exc:
            raise RuntimeError('Local converter returned an unexpected result.') from exc
        if response.get('geometry_source') not in {'parasolid', 'localbodies'}:
            raise RuntimeError('The converter did not recover boundary-representation geometry; no mesh substitute will be used.')
        reference = analyze_step(raw, repaired_step=repaired)
        validated = analyze_step(repaired)
        if validated['imported_solids'] != 1 or not validated['single_valid_solid']:
            raise RuntimeError('Converted STEP did not import as one valid solid.')
        if not math.isfinite(validated['solid_volume_mm3']) or validated['solid_volume_mm3'] <= 0:
            raise RuntimeError('Converted solid has no positive finite volume.')
        volume = reference['solid_volume_mm3']
        if abs(validated['solid_volume_mm3'] - volume) > max(0.001, abs(volume) * 1e-7):
            raise RuntimeError('STEP round-trip changed the calculated volume.')
        if any(abs(a-b) > 0.00001 for a,b in zip(reference['dimensions_mm'], validated['dimensions_mm'])):
            raise RuntimeError('STEP round-trip changed the bounding dimensions.')
        # Exclusive publication avoids overwriting an output created during conversion.
        from core import copy_new
        copy_new(repaired, destination)
    return {'geometry_source': response['geometry_source'], 'dimensions_mm': validated['dimensions_mm'], 'volume_mm3': validated['solid_volume_mm3']}
