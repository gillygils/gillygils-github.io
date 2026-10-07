# PO File Packager

Local browser app for text-based POs matching the supplied PO 1530 layout. Run on the Windows PC that can read your Z: drive. GitHub Pages cannot access your network drive or run SolidWorks.

## Windows setup

Install Python 3.11 or newer for Windows (including the Python launcher). Extract the app to a local folder, then double-click `run_windows.bat`. It installs dependencies on the first run and opens the app in your browser. First launch downloads the Python CAD libraries and a checksum-verified private copy of the permitted Convert3D reader. If Node.js 20 or newer is not installed, setup downloads a checksum-verified portable Node 24 runtime from nodejs.org into `.converter/runtime` (64-bit Windows only). No administrator installation is required for this runtime. Setup requires access to the Python package registry, convert3d.org and nodejs.org; conversion itself runs locally without sending CAD files to a server. Keep the terminal open while using the app.

Alternatively, from this directory in PowerShell:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe converter\setup.py
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1
```

Open the local address printed by Streamlit on that PC. Run as the same Windows user who has the drive mapping. If a mapped drive is unavailable, enter its UNC path, e.g. `\\server\share\Engineering`. Do not expose this app to the network without adding authentication and reviewing access controls.

## Workflow

1. Upload the PO. Check every extracted line against the original.
2. Enter `Z:\`, which contains the IDT folders (for example, `Z:\IDT C13000` for C13030). Fast search is enabled by default: C13030 is searched under IDT C13000, and C15732_001 under IDT C15000, including their subfolders. Shared folders are scanned only once. Progress and completion messages appear during search. If grouping differs or files are missing, disable **Search only matching IDT folders (faster)** to search the entire source folder. Missing group folders produce missing matches, not an automatic full-drive search.
3. Choose an output parent outside the searched source tree. Use a narrower source folder if you want output elsewhere on the same share.
4. Search and review matches. Filename matching is case-insensitive and accepts an exact part number, optionally followed by a space or dash and description. `C15732_001` does not match `C15732` or `C15732_002`. Duplicate matches require a choice. Revisions are not guessed.
5. Select the files, acknowledge review, and process. Each run creates a unique `PO <number> Parts - <timestamp>` folder with all collected files, the uploaded PO, and a JSON report together in one folder. There are no per-part subfolders, and the ZIP contains these files directly at its root. Missing or skipped items and individual failures appear in the report. Outputs are never overwritten. After processing, click **Download PO files ZIP** to download the collected files, uploaded PO, and report. A ZIP is also saved beside the output folder. Missing or failed items are reported; the ZIP may therefore be incomplete. The browser download is named `PO <number> Parts.zip`, so its default extracted folder name is `PO <number> Parts`. Clicking the ZIP download clears the current PO, search results, file selections, and review checkbox, while preserving source/output folder settings. The app resets when the download is requested; it cannot detect when the browser finishes saving. A **Download last ZIP again** button remains available in case the download is interrupted. Local files are retained.

SolidWorks is not required. **Convert copied part files to STEP locally** is enabled by default when the local converter is installed. Processing copies each selected part first, converts its stored B-rep geometry, joins surfaces if needed, and validates that the STEP reimports as one valid solid with agreeing dimensions and volume. Generated STEP files appear directly in the PO folder and ZIP. A selected existing STEP with the same stem is copied instead of regenerated. Errors appear in the report and do not remove the native part or stop processing other parts.

Drawing PDFs remain manual: open the copied drawings in eDrawings and print all required sheets with Microsoft Print to PDF. The post-processing export uploader still accepts these PDFs and manually converted STEP files; click **Add exports and update ZIP**. Uploaded exports are checked for exact PO part association and recognizable headers, which do not themselves validate geometry or drawing accuracy. Check drawings for missing views and clipped content. Referenced dependencies are not automatically bundled. Existing files are never overwritten.

## Validation and limits

Parsing was validated against all 12 lines in the supplied two-page PO 1530. Automated tests cover parsing, exact suffix matching, duplicate discovery, copying without overwrites, and output path validation. The browser workflow can be smoke-tested using Streamlit's AppTest. The actual C15999 part was converted locally and tested through the app into a ZIP; the validated STEP contains one solid and matches the supplied Convert3D reference dimensions and adaptively calculated volume. The conversion adapter blocks network fetches. This Linux workspace cannot access Z: or execute the Windows launcher. Test the first job on Windows and check the copied files before production use.

Initial automatic conversion is limited to part files up to 64 MiB, with a 120-second reader timeout and exactly one valid resulting solid. Multi-body parts, configuration selection, assemblies, and drawing conversion are not supported by the local adapter. Only C15999 has been acceptance-tested against a supplied reference; other files and SolidWorks versions need review. Scanned PDFs, other PO layouts, revision-specific matching, and unattended/shared-user processing are not implemented. Structural STEP validation cannot prove fidelity to every native feature or selection of the intended configuration. Review the processing report and copied files before production use.

Run core tests from this directory:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```


## Convert3D implementation findings

Inspection of Convert3D's public JavaScript on October 7, 2026 found a local SolidWorks reader that accepts file buffers, reads the SLD archive, extracts embedded Parasolid B-rep or LocalBodies geometry, and returns STEP output bytes through a JavaScript STEP writer. This supports browser-local part conversion. The broader app also loads OpenCascade WebAssembly for other geometry operations; installing OpenCascade alone does not supply this custom SolidWorks reader.

The repository owner confirmed permission to integrate the reader. Converter code is downloaded privately into ignored `.converter/modules`; it is not redistributed in this GitHub repository. The adapter uses pinned SHA-256 checksums and preserves the downloaded files. Do not publish the downloaded directory unless your permission covers redistribution. The [privacy policy](https://convert3d.org/about/privacy) notes server processing for some other conversions; this adapter runs the SolidWorks STEP path locally and refuses network fetches and dynamic components.

If Convert3D removes the pinned build URLs or alters those files, setup fails visibly instead of bypassing verification. The app remains available for copying and guided conversion when optional converter setup fails. See [converter/README.md](converter/README.md) for installation and architecture details.
