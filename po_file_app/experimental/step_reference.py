"""Inspect STEP geometry; optionally join disconnected surfaces into one solid.

Requires the optional cadquery-ocp package. Does not read SolidWorks files.
"""
import argparse
import json
import math
from pathlib import Path


def analyze_step(path, repaired_step=None):
    from OCP.BRepBndLib import BRepBndLib
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Sewing, BRepBuilderAPI_MakeSolid
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.BRepGProp import BRepGProp
    from OCP.Bnd import Bnd_Box
    from OCP.GProp import GProp_GProps
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.Interface import Interface_Static
    from OCP.STEPControl import STEPControl_Reader, STEPControl_Writer, STEPControl_AsIs
    from OCP.TopAbs import TopAbs_SOLID, TopAbs_SHELL, TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    def shapes(shape, kind):
        result = []
        explorer = TopExp_Explorer(shape, kind)
        while explorer.More():
            result.append(explorer.Current())
            explorer.Next()
        return result

    reader = STEPControl_Reader()
    Interface_Static.SetCVal_s('xstep.cascade.unit', 'MM')
    if reader.ReadFile(str(path)) != IFSelect_RetDone or not reader.TransferRoots():
        raise ValueError('STEP import failed or no roots transferred.')
    shape = reader.OneShape()
    if shape.IsNull():
        raise ValueError('No geometry imported.')
    bounds = Bnd_Box()
    BRepBndLib.AddOptimal_s(shape, bounds, False, False)
    extents = bounds.Get()
    report = {'file': Path(path).name, 'units': 'mm',
              'dimensions_mm': [extents[i+3] - extents[i] for i in range(3)],
              'imported_solids': len(shapes(shape, TopAbs_SOLID)),
              'imported_shells': len(shapes(shape, TopAbs_SHELL)),
              'imported_faces': len(shapes(shape, TopAbs_FACE)),
              'imported_shape_valid': BRepCheck_Analyzer(shape).IsValid()}
    solids = shapes(shape, TopAbs_SOLID)
    solid = solids[0] if len(solids) == 1 else None
    if not solids:
        sew = BRepBuilderAPI_Sewing(0.00001)
        sew.Add(shape)
        sew.Perform()
        shells = shapes(sew.SewedShape(), TopAbs_SHELL)
        report.update(sewn_shells=len(shells), free_edges=sew.NbFreeEdges(), multiple_edges=sew.NbMultipleEdges())
        if len(shells) == 1 and sew.NbFreeEdges() == 0 and sew.NbMultipleEdges() == 0:
            shell = TopoDS.Shell_s(shells[0])
            candidate = BRepBuilderAPI_MakeSolid(shell).Solid()
            if shell.Closed() and BRepCheck_Analyzer(candidate).IsValid():
                solid = candidate
    report['single_valid_solid'] = solid is not None and BRepCheck_Analyzer(solid).IsValid()
    if report['single_valid_solid']:
        volume = GProp_GProps()
        BRepGProp.VolumeProperties_s(solid, volume, Eps=1e-9, OnlyClosed=True)
        if volume.Mass() < 0:
            solid.Reverse()
            volume = GProp_GProps()
            BRepGProp.VolumeProperties_s(solid, volume, Eps=1e-9, OnlyClosed=True)
        area = GProp_GProps()
        BRepGProp.SurfaceProperties_s(solid, area, Eps=1e-9)
        report['solid_volume_mm3'] = volume.Mass()
        report['solid_surface_area_mm2'] = area.Mass()
    volumes,areas,face_counts=[],[],[]
    validities=[]
    for item in solids:
        props,area=GProp_GProps(),GProp_GProps()
        BRepGProp.VolumeProperties_s(item,props,Eps=1e-9,OnlyClosed=True)
        BRepGProp.SurfaceProperties_s(item,area,Eps=1e-9)
        volumes.append(props.Mass())
        areas.append(area.Mass())
        face_counts.append(len(shapes(item,TopAbs_FACE)))
        validities.append(BRepCheck_Analyzer(item).IsValid())
    report['all_solids_valid']=bool(solids) and all(validities) and all(
        math.isfinite(value) and value>0 for value in volumes+areas)
    report['solid_volumes_mm3']=volumes
    report['solid_face_counts']=face_counts
    if report['all_solids_valid']:
        report['total_solid_volume_mm3']=sum(volumes)
        report['total_solid_surface_area_mm2']=sum(areas)
    if repaired_step is not None:
        target = Path(repaired_step)
        if target.exists():
            raise FileExistsError(f'Will not overwrite {target}')
        if not report['single_valid_solid']:
            raise ValueError('Cannot export: did not obtain one valid solid.')
        writer = STEPControl_Writer()
        Interface_Static.SetCVal_s('write.step.unit', 'MM')
        if writer.Transfer(solid, STEPControl_AsIs) != IFSelect_RetDone or writer.Write(str(target)) != IFSelect_RetDone:
            raise ValueError('STEP export failed.')
        report['validated_step'] = str(target)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file', type=Path)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--repaired-step', type=Path)
    args = parser.parse_args()
    if args.report.exists():
        raise FileExistsError(f'Will not overwrite {args.report}')
    result = analyze_step(args.file, args.repaired_step)
    args.report.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
