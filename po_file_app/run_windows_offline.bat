@echo off
setlocal
cd /d "%~dp0"
echo Starting app in: %CD%
echo Close any older PO File Packager command windows before starting.
if not exist ".venv\Scripts\python.exe" (
  echo Offline startup requires an existing installation. Run run_windows.bat once while connected.
  goto failed
)
".venv\Scripts\python.exe" -c "import streamlit, pypdf, OCP"
if errorlevel 1 (
  echo Required app dependencies are missing. Run run_windows.bat once while connected.
  goto failed
)
echo Independent native STEP converter ready. No vendor cache or internet is required.
".venv\Scripts\python.exe" -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501 --browser.gatherUsageStats false
if errorlevel 1 goto failed
exit /b 0
:failed
echo Offline startup failed. No packages or converter components were downloaded.
pause
exit /b 1
