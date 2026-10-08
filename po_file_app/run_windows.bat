@echo off
setlocal
cd /d "%~dp0"
echo Starting app in: %CD%
echo Close any older PO File Packager command windows before starting.
where py >nul 2>&1
if errorlevel 1 (
  echo Install Python 3.11 or newer for Windows, including the Python launcher, then run this file again.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv
  if errorlevel 1 goto failed
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
".venv\Scripts\python.exe" converter\setup.py
if errorlevel 1 echo Local STEP converter setup failed. The app will still open for copying and manual conversion.
".venv\Scripts\python.exe" -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
if errorlevel 1 goto failed
exit /b 0
:failed
echo Setup or startup failed. Review the error above.
pause
exit /b 1
