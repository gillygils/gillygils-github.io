# Independent SolidWorks part → STEP converter (experimental)

The default app converter is independently authored Python: archive validation,
configuration selection, binary entity decoding and topology reconstruction.
OpenCascade (the free `cadquery-ocp` package) supplies the geometry kernel and
STEP writer. This path does not execute Convert3D code, open its bundles,
read `.converter`, run Node, download components or make web requests.
Previously inspected vendor code and supplied files helped identify format
layouts; they are not runtime dependencies or redistributed implementations.

## Run it

In the app, leave **STEP converter** set to **Independent native reader
(experimental)** and enable **Convert copied part files to STEP locally**.
STEP exports are added to the flat PO folder and ZIP. Originals are retained.
The processing report identifies `implementation: independent-native`, the
saved configuration, decoded counts and round-trip geometry measurements.

Or run from `po_file_app` after installing `requirements.txt`:

```powershell
.venv\Scripts\python.exe -m native_part.worker "Z:\IDT C15000\C15999.SLDPRT" "C:\PO-Exports\C15999.step"
```

The destination must not exist. The app adapter isolates conversion in a
subprocess with a 120-second deadline. The worker validates a temporary STEP
before publishing an exclusive output. Neither path overwrites existing files.
Initial Python-package installation needs internet; subsequent conversion does
not. You can remain connected to Z: throughout.

## Supported saved state and geometry

This implementation supports compatible writer build revisions in the
`SCH_3501xxx_35102_13006` binary layout family and its explicit field patches.
Builds 3501210 and 3501256 have been verified against supplied parts. The writer
build can vary; layout components 35102/13006, entity framing, complete decoding
and all geometry checks are still required. Other release/layout families are
rejected with the exact detected schema in the error. It reads
the most recently saved configuration from the archive XML, rejects stale or
ambiguous configurations, and checks all archive CRCs, decompression bounds,
partition framing, entity identities and topology references.

It requires one complete current base partition and one backward history
stream whose current leaf mark matches the base's current/highest IDs.
The base and history must report matching schemas.
History metadata is decoded far enough to perform this check; general history
payload decoding and delta replay are not implemented. This version-specific
rule only accepts an already-current full partition. It refuses unmatched
marks and forward edits instead of using an earlier body.

Supported curves are lines, circles, and non-rational non-periodic 3D B-splines.
Supported surfaces are planes, cylinders, cones and linear extrusions. Trim
loops, paired oriented edge uses, endpoints, shell coverage and a single closed
valid solid are checked. Coordinates use the observed supported metre-to-mm
scale. STEP reimport must preserve face count, positive volume and bounding
dimensions before publication. No tessellated display-mesh substitute is used.

Unsupported schemas, unknown entities, spline surfaces, other geometry types,
assemblies/transforms, multi-body parts, different unit scales, requested
configuration selection and history states needing replay fail explicitly.
Other SolidWorks versions and parts still need acceptance testing. A saved
configuration match and valid solid alone cannot prove native-feature fidelity.
There is no automatic fallback to Convert3D. The app's optional legacy reader
must be separately installed and explicitly selected to use it.

## Validation

C15999 was converted using only this implementation and OpenCascade, with
Python audit hooks blocking network connections, vendor imports and vendor
cache access. Conversion does not use the supplied reference STEP as input.

| Measurement | Independent export | Supplied reference |
| --- | ---: | ---: |
| Faces | 53 | 53 |
| Dimensions, mm | 177.8 × 4.7625 × 146.05 | 177.8 × 4.7625 × 146.05 |
| Volume, mm³ | 74032.5848864 | 74032.5848864 |
| Surface area, mm² | 38604.1960504 | 38604.1960504 |

The base partition decodes completely: 1,815 records, including 53 faces,
141 edges and 86 vertices. The export reimports as one valid solid. Private CAD
files and recovered proprietary data stay outside the public repository.
OpenCascade solid subtraction against the validated reference found zero
remaining volume in either direction at the comparison kernel's tolerances.
The supplied C04571_001 (build 3501256) and C04571_002 (build 3501210) also
convert into valid 15-face solids. Their bounding dimensions are 647.7 × 31.75 ×
9.525 mm. Calculated volume is 191176.322102 mm³, agreeing with a separate
analytic calculation of the bar, two rounded corners, two chamfers, circular
hole and oblong slot. No reference STEP was supplied for these two parts.
The app packages their exact suffixed STEP filenames separately. CAD assets
remain outside the repository; regression tests use authored cube archives.
Synthetic tests author a 10 mm cube archive and exercise full binary decoding,
geometry construction and STEP import without private CAD assets; expected
volume is 1,000 mm³ and area is 600 mm². Failure tests cover malformed topology,
unsupported surfaces, incomplete streams, duplicate IDs, stale configurations,
unmatched history marks, timeouts and cleanup.

## Inspect unsupported files

The separate inspection command remains available for decoder development:

```powershell
.venv\Scripts\python.exe -m native_part "Z:\IDT C15000\C15999.SLDPRT" --output "C:\PO-Research\C15999-Part"
```

It writes bounded recovered `.x_b` streams and a JSON record report into a new
directory. It does not build or export geometry; `step_conversion_supported:
false` in that inspection report describes the inspection operation, not the
worker's capabilities. Partial history records include the stopping reason.
Inspecting a supported header alone is not proof of a usable current solid.
