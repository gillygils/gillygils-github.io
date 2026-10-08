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
".venv\Scripts\python.exe" -c "import streamlit, pypdf, OCP, ezdxf, reportlab"
if errorlevel 1 goto failed
echo Independent native STEP converter ready. No Convert3D components are required.
".venv\Scripts\python.exe" -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501 --browser.gatherUsageStats false
if errorlevel 1 goto failed
exit /b 0
:failed
echo Setup or startup failed. Review the error above.
pause
exit /b 1
