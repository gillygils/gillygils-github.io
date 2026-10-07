# PO File Packager

Local browser app for text-based POs matching the supplied PO 1530 layout. Run on the Windows PC that can read your Z: drive. GitHub Pages cannot access your network drive or run SolidWorks.

## Windows setup

Install Python 3.11 or newer for Windows (including the Python launcher). Extract the app to a local folder, then double-click `run_windows.bat`. It installs dependencies on the first run and opens the app in your browser. Internet access to the Python package registry is required for installation. Keep the terminal open while using the app.

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

SolidWorks is not required. After processing, the app offers a guided conversion step: open Convert3D to upload parts and download STEP exports, and open drawings locally in eDrawings then print with Microsoft Print to PDF. These conversions are performed manually; the app does not automate Convert3D or printing, and does not itself upload CAD files to an external service. Install eDrawings separately. Check all drawing sheets and exported geometry. Name exports using their exact PO part numbers, preserving `_001` suffixes, upload them under **Converted STEP and drawing PDF files**, then click **Add exports and update ZIP**. Exports are validated for filename association and recognizable PDF/STEP headers, copied into the flat output folder, recorded in the report, and added to the final ZIP. Header checks do not validate CAD geometry or drawing accuracy. Existing files cannot be overwritten. Any matching existing PDFs and STEP files can still be selected and copied. Referenced assembly/drawing dependencies are not bundled automatically.

## Validation and limits

Parsing was validated against all 12 lines in the supplied two-page PO 1530. Automated tests cover parsing, exact suffix matching, duplicate discovery, copying without overwrites, and output path validation. The browser workflow can be smoke-tested using Streamlit's AppTest. This Linux workspace cannot access Z:. Test the first job on Windows and check the copied files before production use.

Scanned PDFs, other PO layouts, revision-specific matching, configuration selection, and unattended/shared-user processing are not implemented. Review the processing report and copied files before production use.

Run core tests from this directory:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```
