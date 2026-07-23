@echo off
setlocal
cd /d "%~dp0"
title Sports Archive Harvester v1.3.2 - GLOBAL CLUB FOOTBALL SYNC
where python >nul 2>nul
if errorlevel 1 (
  echo Python 3.11 or newer was not found in PATH.
  pause
  exit /b 1
)
echo =====================================================================
echo GLOBAL CLUB FOOTBALL SYNC v1.3.2
echo Always-active no-key sources:
echo   OpenFootball JSON + Football-Data.co.uk CSV + OpenLigaDB
echo Optional configured sources:
echo   football-data.org + API-Football + Sportmonks
echo Media downloader fixes SVG/GIF thumbnails, HTTP 400 and HTTP 429.
echo Broken media URLs are not requested repeatedly for every match.
echo Odds, predictions, news, video and raw JSON are NOT stored.
echo =====================================================================
python -u global_football_sync_v3.py --mode quick
set CODE=%ERRORLEVEL%
echo.
python -u media_download_fix.py report
set REPORT_CODE=%ERRORLEVEL%
echo.
echo Full live log: logs\live_sync.log
pause
if %CODE% NEQ 0 exit /b %CODE%
exit /b %REPORT_CODE%
