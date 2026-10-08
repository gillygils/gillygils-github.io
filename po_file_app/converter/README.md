# Local SolidWorks part conversion adapter

This adapter uses the Convert3D reader with permission reported by the repository owner. Third-party modules remain in a private ignored directory and are downloaded from public build URLs at setup. The public repository contains the adapter, URL/hash manifest, and setup instructions rather than third-party implementation copies. Internal-use permission is not assumed to authorize public redistribution of downloaded modules.

`setup.py` reuses verified module downloads, verifies every new module against the pinned SHA-256 manifest, and installs a portable Node runtime on supported Windows machines when necessary. Node's archive checksum is obtained from its official TLS-protected release manifest and verified before extraction. Original third-party module contents and the portable runtime's LICENSE are retained. A missing/changed vendor build is a setup error requiring a manifest refresh and revalidation, not an instruction to disable checksums.

`run.cjs` registers the pinned webpack module factories without running the browser application. For the pinned worker bundle, it extracts and registers only the helper module table; the browser worker message loop is not started. It calls only the SolidWorks reader's STEP entry point. Its VM context has no filesystem or process API exposed to the reader, blocks fetch calls, and rejects dynamic components. The adapter reads the input, passes its bytes to the reader, and exclusively writes a STEP result. It is not a general-purpose security sandbox for untrusted third-party code; use the verified, permitted build.

`local_converter.py` runs Node in a subprocess with a 120-second timeout. OpenCascade then joins/validates surfaces, requires one solid, reexports STEP and compares reimported dimensions and adaptively calculated volume. Outputs are published only after those checks, without overwriting existing files. There is no file upload to a conversion server.

First supported acceptance case: C15999.SLDPRT, compared with the supplied Convert3D C15999.stp. The local reader's output matched reference dimensions and volume after sewing; the packaged result reimports as one valid solid. Other versions, body layouts, saved configurations and feature types remain unverified. The app reports unsupported cases rather than substituting a display mesh. Drawing PDF conversion is unchanged and uses the guided eDrawings print workflow.

```powershell
.\.venv\Scripts\python.exe converter\setup.py
```

Run this from `po_file_app`, or use `run_windows.bat`. Setup downloads third-party modules and, if needed, portable Node; it does not submit CAD files.

The October 8, 2026 vendor build refresh replaces removed build URLs and pins the current worker helpers and module hashes. C15999 was revalidated after the update. Future vendor deployments can remove these URLs again; retain the app’s verified `.converter` cache when updating.

`setup.py --offline` validates the installed Node runtime and all cached module
checksums without fetching missing files. `run_windows_offline.bat` uses this
mode and skips pip entirely. Its first prerequisite is a completed installation
of this app version; an empty cache cannot be prepared without the required
components. This provides offline conversion with the existing vendor reader,
not a completed independent geometry decoder.
