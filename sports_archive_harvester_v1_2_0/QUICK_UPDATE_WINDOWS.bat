@echo off
setlocal
cd /d "%~dp0"
title Sports Archive Harvester v1.3.1 - QUICK GLOBAL UPDATE
where python >nul 2>nul
if errorlevel 1 (
  echo Python 3.11 or newer was not found in PATH.
  pause
  exit /b 1
)
echo =====================================================================
echo QUICK GLOBAL UPDATE v1.3.1
echo 1) New and changed national-team matches for the current year
echo 2) New and changed club matches from all active no-key sources
echo Images stay outside SQLite and are linked by local relative paths.
echo =====================================================================
python -u sports_harvester_external_media.py quick --enrich-limit 20
set NATIONAL_CODE=%ERRORLEVEL%
echo.
python -u global_football_sync_v2.py --mode quick
set CLUB_CODE=%ERRORLEVEL%
echo.
python -u enrich_players_external.py --limit 20
set PLAYER_CODE=%ERRORLEVEL%
echo.
python -u sports_harvester_external_media.py report
set REPORT_CODE=%ERRORLEVEL%
echo.
echo Full live log: logs\live_sync.log
pause
if %NATIONAL_CODE% GEQ 3 exit /b %NATIONAL_CODE%
if %CLUB_CODE% NEQ 0 exit /b %CLUB_CODE%
if %PLAYER_CODE% GEQ 3 exit /b %PLAYER_CODE%
exit /b %REPORT_CODE%
