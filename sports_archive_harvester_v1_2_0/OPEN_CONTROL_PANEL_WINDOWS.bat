@echo off
setlocal
cd /d "%~dp0"
title Sports Archive Harvester v1.2.1 - External Media Control Panel
where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Install Python 3.11 or newer and enable Add Python to PATH.
  pause
  exit /b 1
)
python -u sports_harvester_external_media.py menu
set EXITCODE=%ERRORLEVEL%
echo.
echo Exit code: %EXITCODE%
pause
exit /b %EXITCODE%
