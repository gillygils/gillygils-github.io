@echo off
setlocal
cd /d "%~dp0"
echo Optional legacy Convert3D adapter installation. Internet access is required.
echo The independent native converter does not require this installation.
if not exist ".venv\Scripts\python.exe" (
  echo Run run_windows.bat first to install the Python dependencies.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" converter\setup.py
if errorlevel 1 (
  echo Optional vendor setup failed. Independent native conversion remains available.
  pause
  exit /b 1
)
echo Select Convert3D adapter in the app only when you want to use that reader.
pause
