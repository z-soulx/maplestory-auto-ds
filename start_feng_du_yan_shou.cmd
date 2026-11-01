@echo off
setlocal
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"
if errorlevel 1 (
  echo Cannot open the project folder.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  echo Python environment missing. See GETTING_STARTED_CN.md.
  pause
  exit /b 1
)
if not exist "log" mkdir "log"
if not exist "log" (
  echo Cannot create the log folder.
  pause
  exit /b 1
)
echo Opening settings. Keep this console open while using the script.
set "MSBOT_START_LOG=%~dp0log\launcher_startup_%RANDOM%_%RANDOM%.log"
echo Startup log: "%MSBOT_START_LOG%"
"%~dp0.venv\Scripts\python.exe" -u "%~dp0src\launcher.py" > "%MSBOT_START_LOG%" 2>&1
if errorlevel 1 (
  echo Launcher failed. Error details:
  type "%MSBOT_START_LOG%"
  pause
  exit /b 1
)
