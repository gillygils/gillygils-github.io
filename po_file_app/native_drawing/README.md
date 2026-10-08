# Experimental native drawing exports

Custom Python code reads saved SolidWorks drawing commands and cached view
geometry, then writes vector PDF and millimetre DXF. Optional DWG export uses
the free GNU LibreDWG command-line tools locally. Neither path uses eDrawings,
SolidWorks, Convert3D, a print driver, or a conversion service.

**This is still an incomplete decoder, not a production drawing converter.**
PDF, DXF and DWG carry an `INCOMPLETE NATIVE DECODER - NOT FOR MANUFACTURING`
notice and use `-EXPERIMENTAL` filenames. The app keeps these drafts separate
from PO packages. Compare each export with the original drawing before use.

## Use the app

1. Update the app and run `run_windows.bat` once to install the new `reportlab`
   and `ezdxf` libraries.
2. Open **Drawing exports**. Upload a `.slddrw` file.
3. Optionally upload its matching `.sldprt`, with the same filename stem. This
   supplies exact native spline definitions when saved drawing points alone
   do not contain the spline control points.
4. Click **Create experimental drawing exports**, then download the ZIP or
   each PDF/DXF individually. No PO, file-server search, or output folder is
   needed. The browser chooses the download location.

For DWG on 64-bit Windows, close the app and run `install_dwg_tools.bat` once,
then restart. The installer downloads the official LibreDWG 0.14 Windows ZIP,
checks its pinned SHA-256, and installs executables/DLLs into ignored
`.dwg-tools/`. It includes the GPL license and upstream source link. It does
not install a service or printer. PDF/DXF do not require these tools.
Installation needs internet access; subsequent conversion does not. You may
remain connected to Z: normally. Use `run_windows_offline.bat` after installing
the updated dependencies.

## Command line

Run from `po_file_app`, using the app's Python environment:

```powershell
.venv\Scripts\python.exe -m native_drawing "Z:\IDT C15000\C15999.SLDDRW" --part "Z:\IDT C15000\C15999.SLDPRT" --output "C:\Drawing-Drafts\C15999"
```

The output directory must be new. It receives marked PDF/DXF files and
`drawing-report.json`. Add `--dwg` for optional DWG. On other platforms, build
GNU LibreDWG 0.14 and specify `--dwg-tools <programs-directory>`; the app can
also find tools via `PO_DWG_TOOLS` or PATH. A local Century Gothic TrueType font
can be supplied with `--font <font-path>`. Files are read without modifying
their original contents. The legacy line-only `inspect()` research function
remains available in `native_drawing.__main__`; the CLI now exports the scene.

## What is decoded

- Archive framing, ordinary and observed nibble-swapped filenames, bounded
  decompression, local/central agreement, entry sizes and CRCs.
- Sequential observed display commands for lines, circular arcs, vector
  symbols, triangular arrows, compound fills, Unicode text, rotations, glyph
  advances and supported font/style changes. Unsupported commands stop export.
  Structure sizes are not mistaken for serialized byte lengths.
- The observed annotation-point command retains its saved location as a PDF
  dot and a DXF/DWG POINT. Its original marker appearance is not yet verified
  and is identified in the drawing report.
- Observed single-sheet framing and physical sheet size, named cached views,
  saved rigid transforms, MFC reused-view class references, camera basis,
  declared edge/silhouette group counts, hidden edges and additional saved
  display-state commands.
- Analytic lines, circles and arcs after checking all cached points. Exact
  cubic splines are resolved from the matching part by checking every saved
  point against one unique native curve. Control points are not fitted from
  drawing samples. Polynomial Bezier spans render those splines in PDF.
- Spatial circles project to analytic ellipses in isometric views after
  verifying their plane and radius against independent cached samples.
  Three points alone are not accepted as proof of a circular curve. Other
  unresolved curves retain their saved polyline samples and are reported.
- If a spline cannot be resolved, the marked draft retains its sampled
  polyline, with each unresolved curve and reason listed in the report.

PDF uses local Windows `GOTHIC.TTF` and `GOTHICB.TTF` when available. Otherwise
it substitutes Helvetica/Helvetica Bold and reports that substitution. Fonts
are not bundled or downloaded. DXF/DWG reference `gothic.ttf`/`gothicb.ttf`;
their viewer must have the fonts. Baseline and
font sizing are observations from Century Gothic in the supplied drawing,
not support for arbitrary fonts or text layouts.

## Validation and known limits

C15999.SLDDRW with its matching part now exports both saved views, all eight
hole circles, curved outline, saved dimensions, vector symbols, arrows, fills
and text. The 55 model curves (24 lines, 15 arcs, 8 circles and 8 cubic splines)
match the supplied C15999.DXF to numerical precision. The eight spline
commands use projected/trimmed native curves, not polylines. PDF is a single
431.8 x 279.4 mm vector page. Customer CAD, PDFs and fonts are not published.
Windows font discovery still needs a Windows check.

C15997 and C15996 also export all three saved views, including isometric
holes, hidden edges, symbols and bold annotations, on 558.8 x 431.8 mm pages.
All 148/151 decoded model lines and circles respectively match the reference
DXFs to numerical precision after accounting for their model-to-paper scale.
The isometric holes export as 32/34 analytic ellipses. Another 29/32 small
non-analytic curves retain sampled polylines rather than claiming exact
splines. Each is listed in the report and causes an app warning. All three
native PDFs preserve the same text characters as their printed references,
excluding the added notice and whitespace. Rendered output was visually
compared using private font subsets from the reference PDFs; these fonts are
only validation inputs and are neither needed by the app nor published.

CAD exports preserve the physical sheet and its saved view scale. These are
drawing-sheet exports, not a new 1:1 manufacturing profile. For example the
two crossbar drawings retain 1:2 views. Their supplied SolidWorks DXFs enlarge
the sheet to model scale; the numerical comparison accounts for that factor.

The generated C15999 DXF has 867 entities, including individually positioned
text glyphs and the notice. The local R2000 DWG round-trip retains all 867
entities, their geometry, glyphs, font definitions, line patterns and mm units,
with a clean ezdxf audit. This used LibreDWG built on Linux; the Windows binary
and an independent CAD viewer have not been tested here. Successful native
PDF/DXF/DWG export took about 2.2 seconds on this cloud machine, excluding
Python startup. This is a single-file result, not a general speed guarantee.
C15997/C15996 DWG round-trips also retain all 1,533/1,596 generated entities
respectively, including ellipse definitions, with clean audits.

C15977 exports all three saved views on its 914.4 x 609.6 mm sheet, including
the flat-pattern view, dimensions and an annotation point. Its numbered
`Display State-2` label is consumed before the next view; saved display scale
and depth distinguish sheet transforms from model transforms with the same
orientation. Its DXF/DWG round-trip retains all 809 generated entities. Two
edge-on circles retain their saved polylines and are reported. The saved
preview was checked against the rendered PDF, but no printed reference PDF
has been supplied for this drawing; marker appearance remains unverified.

The DWG bridge adapts a temporary generated R2000 DXF for LibreDWG 0.14:
it remaps typed handles for model space and omits optional object dictionaries
and class definitions. These are exporter defaults, not source drawing data.
The downloadable DXF remains intact. DWG is offered only if its recovered DXF
passes an audit without repairs and matches every supported entity, font and
line pattern. Failure leaves PDF/DXF available and is recorded in the report.

Document metadata, layers, line weights and portions of view metadata remain
opaque. Only the observed single-sheet layout is supported. Multiple sheets,
other native archive/command versions, section/detail views, tables and other
font families are not validated. A structurally accepted export does not prove
that all source content has been interpreted. The three matched source/reference
drawings improve coverage but do not validate arbitrary drawing layouts.
Limits are 64 MiB per input, bounded archive
expansion, command/point counts, and a 90-second app worker timeout. The app
never treats these outputs as production PDFs or adds them automatically to
the PO ZIP.

Authored fixture tests cover framing and transforms, malformed commands,
multiple-sheet rejection, exact spline matching, vector PDF size/notice,
millimetre DXF, fills, DWG loss/change detection, download integrity,
upload/output handling, failure cleanup, and independent Streamlit tab state.
No private CAD or font assets are included in the tests.

## GNU LibreDWG

Upstream: https://www.gnu.org/software/libredwg/ and
https://github.com/LibreDWG/libredwg/releases/tag/0.14 (source and binaries).
LibreDWG is GPLv3-or-later; see [licenses/LibreDWG-COPYING](licenses/LibreDWG-COPYING).
The optional installer obtains unmodified upstream binaries and runs them as
separate local processes. This repository does not include those binaries or
copy LibreDWG implementation code. The adapter and drawing decoder are our
Python implementation.
