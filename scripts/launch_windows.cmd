@echo off
setlocal
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
  echo Install first: powershell -File scripts\install_windows.ps1
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m ecnmr --open --port 8765 %*
if errorlevel 1 pause
