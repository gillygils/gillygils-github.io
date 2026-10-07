# Native drawing decoder research prototype

This is custom Python code for reading saved SolidWorks drawing data without
SolidWorks, eDrawings, a print driver, Convert3D, or a network service. It is
**not a finished SLD DRW-to-PDF converter** and is not wired into production PO
packaging. Its output is visibly marked **INCOMPLETE — NOT FOR MANUFACTURING**.

Run from `po_file_app` using the app's Python environment:

```powershell
.venv\Scripts\python.exe -m native_drawing "Z:\IDT C15000\C15999.SLDDRW" --output "C:\PO-Research\C15999"
```

The output directory must be new. It receives `inspection.json` and
`C15999-INCOMPLETE-draft.pdf`. All source files remain unchanged. The PDF uses
recovered vectors and text records; it does not enlarge the stored preview PNG.

Implemented:

- Independently inspect ZIP-shaped archive framing, including the observed
  nibble-swapped names and nonstandard signatures. Validate entry sizes,
  offsets, bounds, local/central agreement, deflate completion and CRCs.
- Apply file, per-entry and total decompression limits. Reject encryption,
  legacy compound storage and unsupported compression.
- Recover the observed planar line records and Unicode text records, saved
  origins, glyph advances, font names and candidate font sizes.
- Render an incomplete vector draft with persistent visible limitations and
  produce the recovered-data report for further decoder work.

On the supplied C15999.SLDDRW, the custom reader recovered 36 CRC-verified archive
entries, 230 candidate planar line records and 55 positioned text records.
Archive reading, record recovery, and draft writing took approximately 0.03
seconds on the cloud machine (excluding Python startup). This is a partial
recovery timing, **not a benchmark for complete drawing conversion**.

The draft was rendered and inspected against the saved preview: borders and
many annotation lines are present, but the part outline and holes are missing,
fonts/sizing do not match, and some dimensions and notes cannot yet be placed.
It fails drawing fidelity acceptance and must not be used as a production PDF.

Remaining work: decode the curved/display geometry and view transforms; identify
sheet boundaries and ordering; interpret symbol runs, rotations, styles,
fonts and sizes; validate annotation placement, every sheet and geometry against
PDFs printed from the same source drawings. Record matching is a research
hypothesis, not a sequential complete format parser. Unknown content is neither
claimed to be decoded nor silently accepted as a successful production export.

A PDF printed from the supplied C15999 drawing and representative drawings
(multiple sheets, rotated dimensions, section/detail views, tables and symbols)
are needed to validate further work. Those files stay outside the public repo.
