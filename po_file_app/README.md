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
2. Enter `Z:\`, which contains the IDT folders (for example, `Z:\IDT C13000` for C13030). The app recursively searches this folder once per search; it does not assume the folder ranges from the screenshot.
3. Choose an output parent outside the searched source tree. Use a narrower source folder if you want output elsewhere on the same share.
4. Search and review matches. Filename matching is case-insensitive and accepts an exact part number, optionally followed by a space or dash and description. `C15732_001` does not match `C15732` or `C15732_002`. Duplicate matches require a choice. Revisions are not guessed.
5. Select the files, acknowledge review, and process. Each run creates a unique `PO <number> - <timestamp>` folder with the uploaded PO, per-part folders, and a JSON report. Missing or skipped items and individual failures appear in the report. Outputs are never overwritten.

SolidWorks is not required. Conversion is intentionally skipped; any matching existing PDFs and STEP files can be selected and copied. Referenced assembly/drawing dependencies are not bundled automatically.

## Validation and limits

Parsing was validated against all 12 lines in the supplied two-page PO 1530. Automated tests cover parsing, exact suffix matching, duplicate discovery, copying without overwrites, and output path validation. The browser workflow can be smoke-tested using Streamlit's AppTest. This Linux workspace cannot access Z:. Test the first job on Windows and check the copied files before production use.

Scanned PDFs, other PO layouts, revision-specific matching, configuration selection, and unattended/shared-user processing are not implemented. Review the processing report and copied files before production use.

Run core tests from this directory:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```
