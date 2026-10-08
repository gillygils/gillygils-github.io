"""Independently decode a supported SLDPRT and export a validated STEP solid."""
import argparse
import json
import math
import sys
import tempfile
from pathlib import Path

from .model import load_model
from .shape import reconstruct


def export_validated(solid, output, expected_faces, expected_bodies=1):
    from OCP.BRepBndLib import BRepBndLib
    from OCP.BRepGProp import BRepGProp
    from OCP.Bnd import Bnd_Box
    from OCP.GProp import GProp_GProps
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.Interface import Interface_Static
    from OCP.STEPControl import STEPControl_Writer, STEPControl_AsIs
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer
    from experimental.step_reference import analyze_step

    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(solid, props, Eps=1e-9, OnlyClosed=True)
    volume = props.Mass()
    if not math.isfinite(volume) or volume <= 0:
        raise ValueError('Reconstructed body has no positive finite volume.')
    individual_volumes=[]
    explorer=TopExp_Explorer(solid,TopAbs_SOLID)
    while explorer.More():
        body_props=GProp_GProps()
        BRepGProp.VolumeProperties_s(explorer.Current(),body_props,Eps=1e-9,OnlyClosed=True)
        individual_volumes.append(body_props.Mass())
        explorer.Next()
    if len(individual_volumes)!=expected_bodies or any(not math.isfinite(v) or v<=0 for v in individual_volumes):
        raise ValueError('Not every reconstructed body is a positive-volume solid.')
    area_props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(solid, area_props, Eps=1e-9)
    area = area_props.Mass()
    bounds = Bnd_Box()
    BRepBndLib.AddOptimal_s(solid, bounds, False, False)
    extents = bounds.Get()
    dimensions = [extents[i+3] - extents[i] for i in range(3)]
    writer = STEPControl_Writer()
    Interface_Static.SetCVal_s('write.step.unit', 'MM')
    if (writer.Transfer(solid, STEPControl_AsIs) != IFSelect_RetDone
            or writer.Write(str(output)) != IFSelect_RetDone):
        raise ValueError('Native STEP export failed.')
    verified = analyze_step(output)
    if (verified['imported_solids'] != expected_bodies or not verified['all_solids_valid']
            or not verified['imported_shape_valid']
            or verified['imported_faces'] != expected_faces):
        raise ValueError('STEP round-trip changed solid topology.')
    measurements = [verified['total_solid_volume_mm3'], verified['total_solid_surface_area_mm2'],
                    area, *dimensions, *verified['dimensions_mm']]
    if any(not math.isfinite(value) or value <= 0 for value in measurements):
        raise ValueError('STEP geometry measurements are not positive and finite.')
    if abs(verified['total_solid_volume_mm3'] - volume) > max(0.001, volume * 1e-7):
        raise ValueError('STEP round-trip changed the body volume.')
    if abs(verified['total_solid_surface_area_mm2'] - area) > max(0.001, area * 1e-7):
        raise ValueError('STEP round-trip changed the surface area.')
    if any(abs(a-b) > 1e-5 for a,b in zip(dimensions, verified['dimensions_mm'])):
        raise ValueError('STEP round-trip changed the bounding dimensions.')
    if any(abs(a-b)>max(0.001,a*1e-7) for a,b in zip(sorted(individual_volumes),sorted(verified['solid_volumes_mm3']))):
        raise ValueError('STEP round-trip changed an individual body volume.')
    return {'dimensions_mm': verified['dimensions_mm'], 'volume_mm3': verified['total_solid_volume_mm3'],
            'surface_area_mm2': verified['total_solid_surface_area_mm2'],
            'single_valid_solid': verified['single_valid_solid'], 'all_solids_valid':True,
            'solid_count':verified['imported_solids'], 'solid_volumes_mm3':verified['solid_volumes_mm3']}


def convert(source, output):
    from core import copy_new
    source, output = Path(source), Path(output)
    if source.suffix.lower() != '.sldprt' or not source.is_file():
        raise ValueError('Select an existing .sldprt file.')
    if output.exists():
        raise FileExistsError(f'Will not overwrite {output}')
    base, metadata = load_model(source)
    solid, topology = reconstruct(base)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='native-export-', dir=output.parent) as temp:
        exported = Path(temp) / 'validated.step'
        validation = export_validated(solid, exported, topology['decoded_faces'], topology['decoded_bodies'])
        copy_new(exported, output)
    return {**metadata, **topology, **validation, 'success': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(convert(args.source, args.output)))
    except Exception as exc:
        print(f'Independent STEP conversion failed: {exc}', file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == '__main__':
    main()
