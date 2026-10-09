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
2. Open **Drawing exports**. Upload a `.slddrw` or `.dwg` file.
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
not install a service or printer. PDF/DXF from SolidWorks drawings do not
require these tools; DWG input does.
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
  framed full/compact saved transforms, MFC reused-view class references, camera basis,
  declared edge/silhouette group counts, hidden edges and additional saved
  display-state commands.
- Leading empty display views matched to their null cached-bucket pointers,
  interleaved empty views mapped through the populated display transforms,
  the two observed closing-tail variants, connected polyline arrays, single-glyph
  section labels and component annotations. Unknown layouts still fail.
- The observed detail-view bucket stores projected XY samples. Its typed
  detail feature and planar cache identify those coordinates; its model
  rotation is not applied a second time. These samples remain reported
  polylines, not exact splines recovered from unrelated 3D part points.
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
  Unsupported periodic/rational/non-3D curves in the optional part are
  reported as unavailable candidates; they do not abort the drawing draft.
  Structurally invalid supported part curves still fail.

PDF uses local Windows `GOTHIC.TTF` and `GOTHICB.TTF` when available. Otherwise
it substitutes Helvetica/Helvetica Bold and reports that substitution. Fonts
are not bundled or downloaded. DXF/DWG reference `gothic.ttf`/`gothicb.ttf`;
their viewer must have the fonts. Baseline and
font sizing are observations from Century Gothic in the supplied drawing,
not support for arbitrary fonts or text layouts.
The observed older `TXT` font record is also decoded. Native PDF drafts
substitute Courier with an explicit warning; DXF/DWG retain a `txt.shx`
font reference. Its baseline and font metrics have not been validated.

## DWG input

The same upload control accepts `.dwg`. LibreDWG 0.14 decodes it into DXF
locally. ezdxf resolves model-space entities, dimension/block geometry,
line patterns and glyph paths; our ReportLab backend writes a vector PDF
without rasterizing the drawing. The downloaded DXF retains the decoded
source units and geometry. The PDF fits model space to A3 landscape and
does **not** preserve the original plot scale or export paper-space layouts.
Rendering does not fetch external images/underlays; these objects stop export.
Unknown skipped entities or DXF audit repairs also stop export. LibreDWG
decoder warnings remain visible in the app and report: a clean DXF audit
does not prove that the upstream decoder preserved every source object.

The five supplied DWGs C07403–C07407 decode without ezdxf audit errors or
repairs and produce vector PDFs. They include dimensions, leaders, text,
block references and curved geometry. LibreDWG reports decoding warnings
for all five, which are retained. Original plotted PDFs were not supplied
for comparison. No new package, printer or eDrawings installation is needed
beyond the existing optional local DWG tools.

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

Four more supplied drawings now export locally:

| Drawing | Populated views | Sheet, mm | Model curves | DXF/DWG entities |
| --- | ---: | --- | ---: | ---: |
| C15966 | 2 | 914.4 x 609.6 | 181 | 1,074 |
| C15961 | 3 | 431.8 x 279.4 | 15 | 792 |
| C15962 | 3 | 431.8 x 279.4 | 12 | 790 |
| C15959 | 7 | 914.4 x 609.6 | 722 | 2,634 |

C15966 uses a compact identity view transform. C15961/C15962 use the second
observed tail variant. C15959 contains ten leading empty saved views plus
section/detail views and hatching. Its repeated post-label section selection
curves are excluded only after their declaration and every point match the
preceding drawing array. Shaded assembly labels do not count as additional
drawing views. The report records populated views, empty views, coordinate
spaces and verified selection copies.

Their rendered PDFs were compared with the embedded drawing previews, and
all generated DWGs passed the local entity/geometry/text round-trip check.
No printed PDF or DXF references have been supplied for these four files.
C15961/C15962 retain two edge-on sampled curves each. C15959 retains 243
unresolved spline samples and 116 other sampled curves; matching its supplied
part does not make those exact. Its PHANTOM line style uses the standard
dash pattern, whose original spacing remains unverified. A successful export
does not establish full fidelity for arbitrary section/detail drawings.

C16001, C16002, C16016, C16018 and C16043 now export their populated saved
views as PDF/DXF/DWG drafts. This adds compact component annotations,
full-circle flags, odd-length connected polyline commands, two-reference
curve records and interleaved empty display views. PDFs were compared with
their embedded previews; DWGs passed the geometry/text/style round-trip.
C10679 also produces a four-view draft using the reported TXT font substitution.
Visual comparison found differences in its solid/dashed edge visibility;
the app reports that older TXT view styles are unverified. This file is
not a fidelity-verified conversion.
The supplied C10675, C10676, C10677, C10678, C10680 and C10681 remain
unsupported at cached view/group records and produce no completed downloads.

The supplied Imperial File Opener Windows ZIP contains a C# file opener,
not the website's drawing converter. It identifies
`shared/public/js/cad-finder.js` as the browser-side conversion entry point.
That JavaScript and its imported modules have not been supplied, so no code
from that converter has been integrated or validated.

The DWG bridge adapts a temporary generated R2000 DXF for LibreDWG 0.14:
it remaps typed handles for model space and omits optional object dictionaries
and class definitions. These are exporter defaults, not source drawing data.
The downloadable DXF remains intact. DWG is offered only if its recovered DXF
passes an audit without repairs and matches every supported entity, font and
line pattern. Failure leaves PDF/DXF available and is recorded in the report.

Document metadata, layers, line weights and portions of view metadata remain
opaque. Only the observed single-sheet layout is supported. Multiple sheets,
other native archive/command versions, arbitrary section/detail/table layouts
and other font families are not validated. A structurally accepted export does not prove
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
