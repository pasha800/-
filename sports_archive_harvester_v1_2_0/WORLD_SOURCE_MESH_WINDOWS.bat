@echo off
setlocal
cd /d "%~dp0"
title Sports Archive Harvester v1.5.0 - WORLD SOURCE MESH
where python >nul 2>nul
if errorlevel 1 (
  echo Python 3.11 or newer was not found in PATH.
  pause
  exit /b 1
)

echo =====================================================================
echo WORLD SOURCE MESH v1.5.0
echo.
echo No-key sources:
echo   OpenFootball JSON
echo   Football-Data.co.uk CSV
echo   OpenLigaDB
echo   StatsBomb Open Data
echo.
echo Auto-discovered when keys are configured:
echo   API-Football
echo   Sportmonks
echo   football-data.org
echo.
echo Every run continues from saved checkpoints.
echo Duplicate provider IDs are linked to one normalized local entity.
echo Raw JSON, odds, news and video are not stored.
echo =====================================================================
echo.
echo 1. Quick update
 echo 2. Full collection with lineups and essential events
 echo 3. Source mesh report
 echo 0. Exit
set /p CHOICE=Choose: 

if "%CHOICE%"=="1" goto :quick
if "%CHOICE%"=="2" goto :full
if "%CHOICE%"=="3" goto :report
if "%CHOICE%"=="0" exit /b 0
goto :end

:quick
python -u world_source_mesh.py sync --mode quick --max-statsbomb-matches 250
set CODE=%ERRORLEVEL%
goto :after

:full
python -u world_source_mesh.py sync --mode full --max-statsbomb-matches 1000 --statsbomb-events
set CODE=%ERRORLEVEL%
goto :after

:report
python -u world_source_mesh.py report
set CODE=%ERRORLEVEL%
goto :after

:after
echo.
python -u knowledge_graph.py --mode quick --merge-threshold 0.985
python -u sports_harvester_external_media.py report

echo.
echo Full live log: logs\live_sync.log
pause
exit /b %CODE%

:end
echo Invalid choice.
pause
exit /b 1
