@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run run_windows.bat once to install the app, close it, then run this file.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m native_drawing.setup_dwg
if errorlevel 1 (
  pause
  exit /b 1
)
echo Restart the app to enable the experimental DWG checkbox.
pause
