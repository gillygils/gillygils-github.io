# PO File Packager

Local browser app for text-based POs matching the supplied PO 1530 layout. Run on the Windows PC that can read your Z: drive. GitHub Pages cannot access your network drive or run SolidWorks.

## Windows setup

Install Python 3.11 or newer for Windows (including the Python launcher). Extract the app to a local folder, then double-click `run_windows.bat`. It installs the Python packages, including the free OpenCascade geometry library and PySide6/Qt on Windows for optional drawing automation, and opens the app in your browser. **The default STEP converter is our independent Python reader. Normal setup does not download Convert3D components or Node.** Package installation requires internet access once; conversion runs locally. Keep the terminal open while using the app.

Alternatively, from this directory in PowerShell:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1
```

Open the local address printed by Streamlit on that PC. Run as the same Windows user who has the drive mapping. If a mapped drive is unavailable, enter its UNC path, e.g. `\\server\share\Engineering`. Do not expose this app to the network without adding authentication and reviewing access controls.

## Workflow

1. Upload the PO. Check every extracted line against the original.
2. Enter `Z:\`, which contains the IDT folders (for example, `Z:\IDT C13000` for C13030). Fast search is enabled by default: C13030 is searched under IDT C13000, and C15732_001 under IDT C15000, including their subfolders. Shared folders are scanned only once. Progress and completion messages appear during search. If grouping differs or files are missing, disable **Search only matching IDT folders (faster)** to search the entire source folder. Missing group folders produce missing matches, not an automatic full-drive search.
3. Choose an output parent outside the searched source tree. Use a narrower source folder if you want output elsewhere on the same share.
4. Search and review matches. Filename matching is case-insensitive and accepts an exact part number, optionally followed by a space or dash and description. `C15732_001` does not match `C15732` or `C15732_002`. Duplicate matches require a choice. Revisions are not guessed.
5. Select the files, acknowledge review, and process. Each run creates a unique `PO <number> Parts - <timestamp>` folder with all collected files, the uploaded PO, and a JSON report together in one folder. There are no per-part subfolders, and the ZIP contains these files directly at its root. Missing or skipped items and individual failures appear in the report. Outputs are never overwritten. After processing, click **Download PO files ZIP** to download the collected files, uploaded PO, and report. A ZIP is also saved beside the output folder. Missing or failed items are reported; the ZIP may therefore be incomplete. The browser download is named `PO <number> Parts.zip`, so its default extracted folder name is `PO <number> Parts`. Clicking the ZIP download clears the current PO, search results, file selections, and review checkbox, while preserving source/output folder settings. The app resets when the download is requested; it cannot detect when the browser finishes saving. A **Download last ZIP again** button remains available in case the download is interrupted. Local files are retained.

SolidWorks is not required. The sidebar defaults to **Independent native reader (experimental)**. **Convert copied part files to STEP locally** is enabled when OpenCascade can load. Our Python code reads the saved configuration, decodes its Parasolid entities, reconstructs trimmed analytic and spline geometry, and exports STEP using OpenCascade. It does not use Convert3D code, downloads, Node or a conversion service. It never falls back to the vendor reader automatically. Generated STEP files appear directly in the PO folder and ZIP. A selected existing STEP with the same stem is copied instead of regenerated. Errors appear in the report and keep the original part; processing continues with other parts.

This is a functioning but limited independent converter, verified on C15999 and C04571_001/_002, with limited SolidWorks format coverage. It supports compatible writer revisions in the `SCH_3501xxx_35102_13006` layout family (tested builds 3501210 and 3501256), one saved solid, planes, cylinders, cones, linear extrusions, lines, circles and non-rational non-periodic 3D B-spline curves. It selects the most recently saved configuration, rejects stale configurations, and requires a complete base partition with a matching backward leaf history mark. History edits are not replayed. Unsupported versions, geometry, framing, assembly transforms, multi-body parts or current states produce an error rather than a guessed export. See [native_part/README.md](native_part/README.md).

The previous **Convert3D adapter (optional legacy)** remains an explicit sidebar choice for users who want it. Install it separately using `install_convert3d_windows.bat`; it is not needed for independent conversion.

Drawing PDFs now have an optional Windows automation path. Enable **Automatically print drawings to PDF (experimental)** after updating the app. It uses the installed eDrawings ActiveX control and Microsoft Print to PDF, prints all sheets to a chosen paper size (default Tabloid landscape, fit to page), checks PDF page count and content, and adds successful PDFs to the ZIP. It opens the original drawing read-only so model references retain their source location. Run while signed into Windows; a viewer window may appear. The checkbox is off by default until a first Windows acceptance test. See [drawing_converter/README.md](drawing_converter/README.md). If automation fails, open the drawings in eDrawings and print manually. The post-processing export uploader still accepts these PDFs and manually converted STEP files; click **Add exports and update ZIP**. Uploaded exports are checked for exact PO part association and recognizable headers, which do not themselves validate geometry or drawing accuracy. Check drawings for missing views and clipped content. Referenced dependencies are not automatically bundled. Existing files are never overwritten.

## Validation and limits

Parsing was validated against all 12 lines in the supplied two-page PO 1530. Automated tests cover parsing, exact suffix matching, duplicate discovery, copying without overwrites, output path validation, and the browser packaging workflow. New independent-converter tests decode and export an authored cube through both the worker and app backend, check known dimensions/volume/area, block Python network access and vendor cache reads, and exercise malformed topology, stale configuration, timeout and failure cleanup.

Our independent reader decoded all 1,815 records in the supplied C15999 base partition. Its STEP reimports as one valid solid with 53 faces, dimensions approximately 177.8 × 4.7625 × 146.05 mm, volume 74,032.5848864 mm³, and area 38,604.1960504 mm², agreeing with the provided STEP reference. The reference is only a validation input; conversion does not read it. C04571_001 and C04571_002 were also converted into valid 15-face solids and checked against an analytic volume calculation accounting for their rounded/chamfered bar outline, circular hole and oblong slot. Unknown layout families still fail, and errors now include the detected schema. The original CAD files and reference are not published. Structural validation and a matching history mark do not prove fidelity for every other native feature or file. Review the first exports from other parts in a STEP viewer.

Parts are limited to 64 MiB with a 120-second conversion timeout. Assemblies, requested configuration selection, general delta replay, additional Parasolid versions, spline surfaces and many less common geometry types remain unsupported. Drawings still use the experimental eDrawings/manual PDF workflow; independent drawing PDF rendering is unfinished. This Linux workspace cannot access Z: or execute the Windows launcher or Windows printing. Scanned PDFs, other PO layouts, revision-specific matching, and unattended/shared-user processing are not implemented.

Run core tests from this directory:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```


## Optional legacy Convert3D adapter

Inspection of Convert3D's public JavaScript on October 7, 2026 found a local SolidWorks reader that accepts file buffers, reads the SLD archive, extracts embedded Parasolid B-rep or LocalBodies geometry, and returns STEP output bytes through a JavaScript STEP writer. This supports browser-local part conversion. The broader app also loads OpenCascade WebAssembly for other geometry operations; installing OpenCascade alone does not supply this custom SolidWorks reader.

The repository owner confirmed permission to integrate the reader. Converter code is downloaded privately into ignored `.converter/modules`; it is not redistributed in this GitHub repository. The adapter uses pinned SHA-256 checksums and preserves the downloaded files. Do not publish the downloaded directory unless your permission covers redistribution. The [privacy policy](https://convert3d.org/about/privacy) notes server processing for some other conversions; this adapter runs the SolidWorks STEP path locally and refuses network fetches and dynamic components.

If Convert3D removes the pinned build URLs or alters those files, optional vendor setup fails visibly instead of bypassing verification. This does not affect the independent reader. See [converter/README.md](converter/README.md) for installation and architecture details.

## Start without package downloads

After `run_windows.bat` installs the Python dependencies once, use `run_windows_offline.bat` for normal subsequent launches. It checks `.venv` and the Python libraries and starts the app without pip, Node checks or vendor downloads. It disables Streamlit usage telemetry. The independent reader needs neither `.converter` nor internet access. You can stay connected to your network to access Z:; “offline” here means the converter has no internet service dependency, not that your network drive must be disconnected.

If the STEP checkbox is disabled, expand **STEP converter diagnostics**. For the independent reader it shows the running app folder, Python environment and any OpenCascade import failure. Close older command windows and launch the newest app folder; the launchers use port 8501 explicitly.
