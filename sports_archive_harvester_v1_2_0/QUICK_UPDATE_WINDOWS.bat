@echo off
setlocal
cd /d "%~dp0"
title Sports Archive Harvester v1.2.1 - QUICK UPDATE

echo ================================================================
echo QUICK UPDATE: only current-year new/changed matches are checked
echo Team logos and player photos are saved OUTSIDE SQLite.
echo SQLite stores only local relative-path links and small metadata.
echo Every saved match, team, player and external media file is shown.
echo ================================================================

python -u sports_harvester_external_media.py quick --enrich-limit 50
set CODE=%ERRORLEVEL%
if %CODE% GEQ 2 echo Team enrichment had one or more non-fatal warnings.
python -u enrich_players_external.py --limit 100
set PLAYER_CODE=%ERRORLEVEL%
echo.
python -u sports_harvester_external_media.py report
set REPORT_CODE=%ERRORLEVEL%
echo.
echo Full live log: logs\live_sync.log
pause
if %CODE% NEQ 0 exit /b %CODE%
if %PLAYER_CODE% GEQ 3 exit /b %PLAYER_CODE%
exit /b %REPORT_CODE%
