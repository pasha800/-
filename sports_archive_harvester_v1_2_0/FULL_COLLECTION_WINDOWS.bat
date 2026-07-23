@echo off
setlocal
cd /d "%~dp0"
title Sports Archive Harvester v1.2.1 - FULL COLLECTION

echo ================================================================
echo FULL COLLECTION: historical international football from 1872
echo Essential text only inside SQLite.
echo Team logos and player photos are external files linked by local paths.
echo No image BLOBs, base64, videos, banners, or raw JSON are stored.
echo ================================================================

python -u sports_harvester_external_media.py full --enrich-limit 100
set CODE=%ERRORLEVEL%
python -u enrich_players_external.py --limit 250
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
