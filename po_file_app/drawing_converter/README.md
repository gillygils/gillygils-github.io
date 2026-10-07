# Experimental automatic drawing PDF printing (Windows)

Uses the installed eDrawings ActiveX viewer with Microsoft Print to PDF. SolidWorks itself is not required. The original drawing is opened read-only at its original location so relative model references remain available. No drawing changes are saved. The worker hosts its own viewer and closes only that viewer.

Install the updated requirements through `run_windows.bat` (adds PySide6/ActiveQt on Windows). eDrawings and the Microsoft Print to PDF printer must already be installed; Python and eDrawings bitness must match. Run in your signed-in Windows desktop session. A viewer window may appear during conversion. The checkbox is off by default because the eDrawings/Microsoft PDF path requires a first-run test on your PC.

1. Enable **Automatically print drawings to PDF (experimental)** in the sidebar.
2. Choose paper and orientation. Default: Tabloid landscape, scaled to fit, all sheets. This is not a full-size 1:1 plotting workflow.
3. Process a small PO with one known drawing first. Inspect its PDF against eDrawings before using a larger batch.

The worker waits for `OnFinishedLoadingDocument`, calls `SetPageSetupOptions` with Microsoft Print to PDF, and calls `Print5` with dialogs disabled, all sheets and an output filename. It observes printing-finished and failure events. Event subscriptions use named Qt signals when available and fall back to Qt’s generic COM event signal when the control does not generate named signals; raw COM argument pointers are not read. A completion event is not treated as proof of success: a parseable PDF must exist with nonempty page content and page count equal to eDrawings' SheetCount. The backend rechecks the PDF and publishes it exclusively into the PO folder before ZIP creation. Existing selected PDFs are kept rather than regenerated. Errors are reported without discarding original drawings or stopping other files.

The process has a 150-second parent timeout and 120-second worker deadline. Unexpected driver save dialogs, unsupported ActiveX registration or API exposure, missing printers, inaccessible references, or mismatching page counts are failures. If printing is interrupted, check the Windows PDF print queue and any pending dialog before retrying. Use the existing manual print/upload workflow for those files. No default printer setting is changed.

## Evidence and current limitation

Official eDrawings documentation defines the relevant APIs:

- [OpenDoc](https://help.solidworks.com/2025/english/api/emodelapi/eDrawings.Interop.EModelViewControl~eDrawings.Interop.EModelViewControl.IEModelViewControl~OpenDoc.html)
- [SetPageSetupOptions](https://help.solidworks.com/2025/english/api/emodelapi/eDrawings.Interop.EModelViewControl~eDrawings.Interop.EModelViewControl.IEModelViewControl~SetPageSetupOptions.html)
- [Print5](https://help.solidworks.com/2025/english/api/emodelapi/eDrawings.Interop.EModelViewControl~eDrawings.Interop.EModelViewControl.IEModelViewControl~Print5.html)

This cloud machine runs Linux and cannot execute eDrawings ActiveX or the Windows PDF printer. Automated tests exercise output validation, failure handling, and app packaging with a simulated print worker. The real rendering/printing path has **not** been validated. The checkbox is explicitly experimental until a Windows acceptance run confirms the installed control and PDF driver honor the silent output filename. PDF page-count/content validation does not establish drawing accuracy, legibility, or complete reference resolution.
