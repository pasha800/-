@echo off
setlocal
cd /d "%~dp0"
title Sports Archive Harvester v1.4.0 - FULL SMART BUILD
where python >nul 2>nul
if errorlevel 1 (
  echo Python 3.11 or newer was not found in PATH.
  pause
  exit /b 1
)
echo =====================================================================
echo FULL SMART FOOTBALL DATABASE BUILD v1.4.0
echo Phase 1: national-team history
echo Phase 2: global clubs, leagues and cups
echo Phase 3: controlled team/player media enrichment
echo Phase 4: knowledge graph, provenance, deduplication and quality scoring
echo Phase 5: database and external-media integrity validation
echo =====================================================================

python -u sports_harvester_external_media.py full --enrich-limit 30
if errorlevel 3 goto :failed

python -u global_football_sync_v3.py --mode full
if errorlevel 3 goto :failed

python -u enrich_players_media_fixed.py --limit 50
if errorlevel 3 goto :failed

python -u knowledge_graph.py --mode full --merge-threshold 0.985
if errorlevel 1 goto :failed

python -u sports_harvester_external_media.py compact
if errorlevel 1 goto :failed

python -u sports_harvester_external_media.py report
if errorlevel 1 goto :failed

python -u knowledge_graph.py --report-only
if errorlevel 1 goto :failed

echo.
echo FULL SMART BUILD COMPLETED SUCCESSFULLY.
echo Full live log: logs\live_sync.log
pause
exit /b 0

:failed
echo.
echo FULL SMART BUILD FAILED. Review logs\live_sync.log.
pause
exit /b 2
