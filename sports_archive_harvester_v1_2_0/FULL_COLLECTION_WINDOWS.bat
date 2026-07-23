@echo off
setlocal
cd /d "%~dp0"
title Sports Archive Harvester - FULL COLLECTION
echo ================================================================
echo FULL COLLECTION: historical international football from 1872
echo Essential data only. No videos, banners, raw JSON, or duplicate media.
echo ================================================================
python -u sports_harvester.py full --enrich-limit 100
set CODE=%ERRORLEVEL%
python -u enrich_players.py --limit 250
echo.
python -u sports_harvester.py report
echo.
echo Full live log: logs\live_sync.log
pause
exit /b %CODE%
