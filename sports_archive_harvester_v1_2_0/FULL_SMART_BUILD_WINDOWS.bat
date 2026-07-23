@echo off
setlocal
cd /d "%~dp0"
title Sports Archive Harvester v1.5.0 - WORLD FULL SMART BUILD
where python >nul 2>nul
if errorlevel 1 (
  echo Python 3.11 or newer was not found in PATH.
  pause
  exit /b 1
)
echo =====================================================================
echo WORLD FOOTBALL DATABASE BUILD v1.5.0
echo Phase 1: international history from 1872
echo Phase 2: world source mesh - leagues, cups, clubs, seasons and matches
echo Phase 3: StatsBomb lineups and essential events
echo Phase 4: controlled team/player media enrichment
echo Phase 5: knowledge graph, provenance, deduplication and quality scoring
echo Phase 6: database and external-media integrity validation
echo.
echo Premium sources are auto-discovered when their keys are configured.
echo Re-run this file to continue from provider checkpoints until full coverage.
echo =====================================================================

python -u media_download_fix.py full --enrich-limit 30
if errorlevel 3 goto :failed

python -u world_source_mesh.py sync --mode full --max-statsbomb-matches 1000 --statsbomb-events
if errorlevel 3 goto :failed

python -u enrich_players_media_fixed.py --limit 100
if errorlevel 3 goto :failed

python -u knowledge_graph.py --mode full --merge-threshold 0.985
if errorlevel 1 goto :failed

python -u sports_harvester_external_media.py compact
if errorlevel 1 goto :failed

python -u sports_harvester_external_media.py report
if errorlevel 1 goto :failed

python -u world_source_mesh.py report
if errorlevel 1 goto :failed

python -u knowledge_graph.py --report-only
if errorlevel 1 goto :failed

echo.
echo WORLD FULL SMART BUILD COMPLETED.
echo Run this file again to continue remaining provider checkpoints.
echo Full live log: logs\live_sync.log
pause
exit /b 0

:failed
echo.
echo WORLD FULL SMART BUILD FAILED. Review logs\live_sync.log.
pause
exit /b 2
