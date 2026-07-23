@echo off
setlocal
cd /d "%~dp0"
title Sports Archive Harvester v1.3.0 - GLOBAL FOOTBALL SYNC
where python >nul 2>nul
if errorlevel 1 (
  echo Python 3.11 or newer was not found in PATH.
  pause
  exit /b 1
)
echo =====================================================================
echo GLOBAL FOOTBALL SYNC: clubs, national teams, leagues and cups
echo Providers: OpenLigaDB + football-data.org + API-Football + Sportmonks
echo Only configured providers with valid keys will run.
echo Essential normalized data only. No odds, predictions, news or raw JSON.
echo =====================================================================
python -u global_football_sync.py
set CODE=%ERRORLEVEL%
echo.
python -u sports_harvester_external_media.py report
echo.
echo Full live log: logs\live_sync.log
pause
exit /b %CODE%
