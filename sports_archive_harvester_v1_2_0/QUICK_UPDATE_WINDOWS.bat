@echo off
setlocal
cd /d "%~dp0"
title Sports Archive Harvester - QUICK UPDATE
echo ================================================================
echo QUICK UPDATE: only current-year new/changed matches are checked
echo Every saved match, team, player and media file will be shown here
echo ================================================================
python -u sports_harvester.py quick --enrich-limit 50
set CODE=%ERRORLEVEL%
if %CODE% GEQ 2 echo Team/player enrichment had one or more non-fatal warnings.
python -u enrich_players.py --limit 100
echo.
python -u sports_harvester.py report
echo.
echo Full live log: logs\live_sync.log
pause
exit /b %CODE%
