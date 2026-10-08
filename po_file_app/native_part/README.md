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
To convert without a PO, open **Part to STEP**, upload parts and click
**Convert uploaded parts to STEP**. Download individual STEP files or a flat
ZIP containing successful conversions and their report. Folder settings are
only needed for the PO workflow.
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

Supported curves are lines, circles, non-rational non-periodic 3D B-splines,
supported 2D parameter splines lifted onto surfaces, and supported
surface-intersection curves. The latter are computed
from the two decoded surfaces; native chart points identify the branch and
direction rather than becoming a polyline approximation. Closed intersection
splines are made periodic without changing sampled geometry so trims crossing
the parameter seam select the correct arc. Kernel segments split at surface
parameter seams can be joined when their endpoints define one unambiguous
chain or cycle. Joining must preserve the segment geometry. Branched junctions
remain separate, and ambiguous native branch selection is refused.

Supported surfaces are planes, cylinders, cones, linear extrusions,
non-degenerate ring tori and non-rational non-periodic 3D B-spline surfaces.
Spline surfaces validate their two knot arrays, multiplicities, dimensions
and control-grid ordering before construction. Toroidal trim loops retain
native winding, preserving either the short or long arc specified by the
source. Forcing a torus loop to the kernel's default inside orientation can
otherwise select the complementary bend despite producing a valid solid.

On-surface parameter curves support planes, cylinders, cones, ring tori and
supported B-spline surfaces, with explicit UV unit scaling for each. Their
non-rational non-periodic 2D splines are lifted by OpenCascade into 3D splines
at a maximum reported error of 0.0000001 mm, then checked against the native
surface positions. Alternate-original curves and other parameter scalings
remain unsupported. These are smooth CAD curves, not display polylines.

A full
cone apex trim is supported when its singular vertex matches the analytic
apex and its circular boundary is coaxial with the correct radius. Other
singular boundary forms remain unsupported. Embedded schema definitions and
attribute-vector arrays are decoded within explicit layout and size bounds.

One or more active solid bodies are preserved separately in one STEP compound;
they are not fused. Each body must form one closed, valid solid. The saved body
chain, trim loops, paired oriented edge uses, endpoints and complete topology
coverage are checked. Coordinates use the observed supported metre-to-mm
scale. STEP reimport must preserve body and face counts, each body's positive
volume, total volume, surface area and bounding dimensions before publication.
No tessellated display-mesh substitute is used.

Unsupported schemas, unknown entities, rational/periodic spline surfaces, other geometry types,
assemblies/transforms, sheet bodies, different unit scales, requested
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
All ten additional supplied parts also pass independent conversion:

| Part | Faces | Solid bodies retained |
| --- | ---: | ---: |
| C04592 | 16 | 1 |
| C13029_001 | 42 | 1 |
| C13038_001 | 36 | 1 |
| C13065 | 21 | 1 |
| C13071 | 15 | 1 |
| C13228 | 17 | 1 |
| C00128_002 | 33 | 2 |
| C04045-001 | 50 | 1 |
| C16231 | 114 | 7 |
| C16663 | 119 | 8 |

The tests reimport all exports as valid solids and compare body counts, face
counts, volume, area and dimensions with reconstructed geometry. C04045-001
uses its most-recent `Default<As Machined>` configuration, as do C16231 and
C16663. C16231 decodes all 3,253 records, including spline bend transition
surfaces and cylindrical surface curves. C16663 decodes all 3,619 records,
including toroidal bends and split intersection curves. Its two bent round
rods also agree with a separate analytic length-and-cross-section volume
calculation. No reference STEP was supplied for these ten parts, so these checks establish structural and
round-trip consistency, not independent proof of all native-feature fidelity.
All 13 supplied part files pass; arbitrary SolidWorks files are not guaranteed.

Authored regressions exercise a pointed cone with known analytic volume and
area, perpendicular-cylinder intersections crossing a parameter seam, two
disjoint cubes retained as separate solids, and failure without partial output
when one body is unsupported. A spline-topped box has known volume and
surface area; toroidal bends validate both 90 and 270 degree native trims.
A cylindrical helix checks UV metres-to-mm scaling and curve lifting accuracy.
Malformed knots and unsupported spline variants must leave no STEP output.
Standalone app tests convert uploads without a
PO or network-drive search, preserve suffixes, report individual failures and
hide stale downloads after inputs change.

Synthetic tests author a 10 mm cube archive and exercise full binary decoding,
geometry construction and STEP import without private CAD assets; expected
volume is 1,000 mm³ and area is 600 mm². Failure tests cover malformed topology,
unsupported surfaces, incomplete streams, duplicate IDs, stale configurations,
unmatched history marks, timeouts and cleanup.

## Assemblies

`.sldasm` is deliberately rejected before part decoding. Complete assembly
conversion requires external component geometry, each instance's saved
configuration, suppression rules and placements; that pipeline is not yet
implemented. Multi-body `.sldprt` files are supported separately and do not
require assembly placement decoding.

The supplied C16210 assembly was inspected read-only. Its component XML lists
33 external part-file references and its archive holds six cached body
partitions. Those caches cannot establish complete assembly coverage. It is
not converted into a partial STEP. The app reports an explicit skip for a
copied assembly when no matching STEP export was copied. Existing assembly
STEP exports can still be selected and packaged. Development and acceptance
testing of assembly conversion need the assembly and its referenced parts.

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
