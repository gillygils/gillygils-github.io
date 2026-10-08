# Independent SolidWorks part reader: STEP decoder work in progress

This is the first stage of a converter that does **not** use Convert3D code,
its downloads, JavaScript bundles, Node, web APIs or any installed CAD viewer.
It uses our independent ZIP-shaped archive reader and Python's zlib library.
It does not produce STEP yet and is not the app's production conversion path.

Run from `po_file_app`:

```powershell
.venv\Scripts\python.exe -m native_part "Z:\IDT C15000\C15999.SLDPRT" --output "C:\PO-Research\C15999-Part"
```

The output directory must be new. The tool verifies archive entry CRCs,
checks bounds and expansion limits, extracts supported configuration partition
blocks, and writes their bytes plus an inspection report. Inputs stay unchanged.
Opaque framing gaps and tails remain explicitly reported as uninterpreted.

On C15999.SLDPRT, the independent reader recovered 45 verified archive entries
and two framed Parasolid streams from configuration archive ID 2:

| Stream | Kind | Recovered bytes |
| --- | --- | ---: |
| 0 | Base partition | 63,271 |
| 1 | Deltas | 40,751 |

Both streams report modeller version 3501210 and schema
`SCH_3501210_35102_13006`. Extraction took about 0.03 seconds on the cloud
machine, excluding Python startup. This is **extraction timing**, not a complete
STEP conversion benchmark. A valid compressed stream and Parasolid header do
not establish usable or complete geometry. The recovered files are research
artifacts, not validated exports of the current body.

Remaining required stages:

1. Decode Parasolid schemas and entity records with bounded parsing and stable
   reference identities, including version-specific schema changes.
2. Apply delta records to base partitions in saved order. Determine the active
   configuration and units. Do not treat an earlier saved body as current.
3. Reconstruct bodies, shells, faces, trim loops, oriented edges and vertices;
   decode their analytic and spline curves/surfaces.
4. Build OpenCascade boundary-representation shapes and export STEP. Refuse
   unsupported geometry instead of replacing it with a tessellated display mesh.
5. Validate configuration, dimensions, volume, topology and shape fidelity against
   reference exports before exposing this path in PO packaging.

The existing permitted Convert3D adapter remains available in the app while
these stages are unfinished. This independent reader does not silently fall
back to it and reports `step_conversion_supported: false` in its output.
Original parts, recovered proprietary data and reference exports are kept
outside the public repository; only implementation and synthetic tests are
committed.
