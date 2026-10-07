# Experimental SolidWorks diagnostic reader

This is an independent, limited binary reader, not a STEP converter. It uses Python's standard library and includes no Convert3D code or decoding tables.

```powershell
py -3 experimental\sld_reader.py "C:\Parts\C15999.SLDPRT" --output "C:\PO Reader\C15999"
```

The output directory must not already exist. The reader writes `inspection.json` and any complete standard zlib streams it can recover. Streams beginning with Parasolid binary magic are saved as `.x_b`. A valid compression checksum or a Parasolid header does **not** establish that a stream contains usable part geometry.

The sample C15999.SLDPRT yielded 60 candidate archive-name records and one 1,176-byte decompressed Parasolid stream. The drawing yielded 54 candidate records and no standard zlib streams. Candidate names can repeat because local records and embedded/archive metadata are not yet distinguished. The sample includes names for geometry partitions, display lists, and previews, but their payloads remain undecoded.

Remaining conversion prerequisites:

1. Decode and validate the proprietary archive's payload framing/transformations, with bounds and integrity checks.
2. Read the complete geometry partitions and configuration association. Extracting one stream is insufficient.
3. Decode Parasolid topology and analytic surfaces, preserving geometry, units, trims, orientation, and solid connectivity.
4. Create corresponding OpenCascade or STEP entities and validate shape count, bounds, volume, surface geometry and tolerances against reference exports.
5. Add conversion to the production app only after those checks pass on representative files.

The production app continues to use the existing guided conversion workflow. This tool does not create a substitute mesh STEP, drawing PDF, or claim complete format support. More native-format samples and a reference STEP exported from the same C15999 configuration would help future validation; they do not themselves resolve the missing archive/geometry decoders.
