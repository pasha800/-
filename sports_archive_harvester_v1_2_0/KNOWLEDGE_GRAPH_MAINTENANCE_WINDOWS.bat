@echo off
setlocal
cd /d "%~dp0"
title Sports Archive Harvester v1.4.0 - KNOWLEDGE GRAPH MAINTENANCE
where python >nul 2>nul
if errorlevel 1 (
  echo Python 3.11 or newer was not found in PATH.
  pause
  exit /b 1
)
echo =====================================================================
echo SPORTS ARCHIVE KNOWLEDGE GRAPH v1.4.0
echo - Connects teams, players, seasons, competitions, venues and matches
echo - Detects duplicates and auto-merges only very high-confidence records
echo - Keeps ambiguous candidates for review instead of unsafe merging
echo - Calculates completeness and confidence scores
echo - Removes empty/useless facts, never meaningful history
echo =====================================================================
python -u knowledge_graph.py --mode full --merge-threshold 0.985
set CODE=%ERRORLEVEL%
echo.
python -u knowledge_graph.py --report-only
set REPORT_CODE=%ERRORLEVEL%
echo.
echo Full live log: logs\live_sync.log
pause
if %CODE% NEQ 0 exit /b %CODE%
exit /b %REPORT_CODE%
