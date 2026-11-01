@echo off
setlocal
set "MSBOT_START_DIR=%~dp0"
if not exist "%~dp0.venv\Scripts\pythonw.exe" (
  echo Python environment missing. See GETTING_STARTED_CN.md.
  pause
  exit /b 1
)
powershell.exe -NoProfile -Command "try { $launcher = Join-Path $env:MSBOT_START_DIR 'start_feng_du_yan_shou.cmd'; $arguments = '/d /c ' + [char]34 + [char]34 + $launcher + [char]34 + [char]34; Start-Process -FilePath $env:ComSpec -ArgumentList $arguments -WorkingDirectory $env:MSBOT_START_DIR -Verb RunAs -ErrorAction Stop } catch { Write-Host $_.Exception.Message; exit 1 }"
if errorlevel 1 pause
