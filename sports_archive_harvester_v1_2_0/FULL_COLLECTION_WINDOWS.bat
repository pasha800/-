@echo off
setlocal
cd /d "%~dp0"
title Sports Archive Harvester v1.3.2 - FULL GLOBAL COLLECTION
where python >nul 2>nul
if errorlevel 1 (
  echo Python 3.11 or newer was not found in PATH.
  pause
  exit /b 1
)
echo =====================================================================
echo FULL GLOBAL COLLECTION v1.3.2
echo 1) Historical national-team football from 1872
echo 2) Historical club leagues and cups from no-key global sources
echo 3) Resilient media downloads with Wikimedia thumbnail resolution
echo Team logos and player photos remain external files linked to SQLite.
echo Broken URLs are cached; HTTP 429 uses persistent exponential backoff.
echo Odds, predictions, news, video, banners and raw JSON are not stored.
echo =====================================================================
python -u media_download_fix.py full --enrich-limit 30
set NATIONAL_CODE=%ERRORLEVEL%
echo.
python -u global_football_sync_v3.py --mode full
set CLUB_CODE=%ERRORLEVEL%
echo.
python -u enrich_players_media_fixed.py --limit 30
set PLAYER_CODE=%ERRORLEVEL%
echo.
python -u media_download_fix.py compact
set COMPACT_CODE=%ERRORLEVEL%
echo.
python -u media_download_fix.py report
set REPORT_CODE=%ERRORLEVEL%
echo.
echo Full live log: logs\live_sync.log
pause
if %NATIONAL_CODE% GEQ 3 exit /b %NATIONAL_CODE%
if %CLUB_CODE% NEQ 0 exit /b %CLUB_CODE%
if %PLAYER_CODE% GEQ 3 exit /b %PLAYER_CODE%
if %COMPACT_CODE% NEQ 0 exit /b %COMPACT_CODE%
exit /b %REPORT_CODE%
