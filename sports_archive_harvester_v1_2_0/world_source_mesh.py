#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sports Archive Harvester v1.5.0 - World Source Mesh.

Goals:
- run every useful no-key collector;
- auto-discover competitions for configured premium APIs;
- import StatsBomb Open Data matches, lineups and essential events;
- use persistent checkpoints so repeated runs continue instead of restarting;
- bind every provider identifier to one normalized local entity;
- never store raw JSON, betting odds, news or video.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import media_download_fix as media
import global_football_sync as legacy
import global_football_sync_v2 as no_key
import knowledge_graph as graph

VERSION = "1.5.0"
ROOT = Path(__file__).resolve().parent

MESH_SCHEMA = r"""
CREATE TABLE IF NOT EXISTS source_mesh_catalog (
  provider TEXT PRIMARY KEY,
  category TEXT NOT NULL,
  requires_key INTEGER NOT NULL DEFAULT 0,
  enabled INTEGER NOT NULL DEFAULT 1,
  priority INTEGER NOT NULL DEFAULT 100,
  coverage_note TEXT,
  last_success_at TEXT,
  last_error_at TEXT,
  last_error TEXT
);

CREATE TABLE IF NOT EXISTS source_mesh_checkpoint (
  provider TEXT NOT NULL,
  checkpoint_key TEXT NOT NULL,
  checkpoint_value TEXT,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(provider,checkpoint_key)
);

CREATE TABLE IF NOT EXISTS source_mesh_runs (
  id INTEGER PRIMARY KEY,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  mode TEXT NOT NULL,
  providers_started INTEGER NOT NULL DEFAULT 0,
  providers_completed INTEGER NOT NULL DEFAULT 0,
  competitions INTEGER NOT NULL DEFAULT 0,
  teams INTEGER NOT NULL DEFAULT 0,
  players INTEGER NOT NULL DEFAULT 0,
  matches INTEGER NOT NULL DEFAULT 0,
  lineups INTEGER NOT NULL DEFAULT 0,
  events INTEGER NOT NULL DEFAULT 0,
  errors INTEGER NOT NULL DEFAULT 0,
  note TEXT
);
"""

PROVIDERS = [
    ("OpenFootball JSON", "open-data", 0, 10, "Many countries, divisions and seasons"),
    ("Football-Data.co.uk", "open-data", 0, 20, "Historical results for major European divisions"),
    ("OpenLigaDB", "open-api", 0, 30, "German and selected European competitions"),
    ("StatsBomb Open Data", "open-data", 0, 40, "Selected competitions with lineups and detailed events"),
    ("API-Football", "premium-api", 1, 50, "Broad worldwide competition coverage"),
    ("Sportmonks", "premium-api", 1, 60, "Broad worldwide leagues, seasons, fixtures and participants"),
    ("football-data.org", "api", 1, 70, "Major competitions, teams and matches"),
    ("TheSportsDB", "api", 1, 80, "Team/player enrichment and media"),
]


def now() -> str:
    return media.now_iso()


def request_json(url: str, headers: dict[str, str] | None = None, timeout: int = 60) -> Any:
    req_headers = {"User-Agent": f"SportsArchiveHarvester/{VERSION}", "Accept": "application/json"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, headers=req_headers)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8-sig"))


def ensure_schema(a: media.Archive) -> None:
    legacy.ensure_schema(a)
    no_key.ensure_schema(a)
    graph.ensure_schema(a.conn)
    a.conn.executescript(MESH_SCHEMA)
    for provider, category, requires_key, priority, note in PROVIDERS:
        a.conn.execute(
            """INSERT INTO source_mesh_catalog(provider,category,requires_key,priority,coverage_note)
               VALUES(?,?,?,?,?)
               ON CONFLICT(provider) DO UPDATE SET category=excluded.category,
               requires_key=excluded.requires_key,priority=excluded.priority,
               coverage_note=excluded.coverage_note""",
            (provider, category, requires_key, priority, note),
        )
    a.conn.commit()


def checkpoint_get(a: media.Archive, provider: str, key: str, default: str = "") -> str:
    row = a.conn.execute(
        "SELECT checkpoint_value FROM source_mesh_checkpoint WHERE provider=? AND checkpoint_key=?",
        (provider, key),
    ).fetchone()
    return str(row[0]) if row and row[0] is not None else default


def checkpoint_set(a: media.Archive, provider: str, key: str, value: Any) -> None:
    a.conn.execute(
        """INSERT INTO source_mesh_checkpoint(provider,checkpoint_key,checkpoint_value,updated_at)
           VALUES(?,?,?,?) ON CONFLICT(provider,checkpoint_key) DO UPDATE SET
           checkpoint_value=excluded.checkpoint_value,updated_at=excluded.updated_at""",
        (provider, key, str(value), now()),
    )


def source_ok(a: media.Archive, provider: str) -> None:
    a.conn.execute(
        "UPDATE source_mesh_catalog SET last_success_at=?,last_error=NULL WHERE provider=?",
        (now(), provider),
    )


def source_error(a: media.Archive, provider: str, exc: Exception) -> None:
    a.conn.execute(
        "UPDATE source_mesh_catalog SET last_error_at=?,last_error=? WHERE provider=?",
        (now(), str(exc)[:1000], provider),
    )


def stats_template() -> dict[str, int]:
    return {"competitions": 0, "teams": 0, "players": 0, "matches": 0, "lineups": 0, "events": 0, "errors": 0}


def team_from_statsbomb(a: media.Archive, item: dict[str, Any]) -> int:
    pid = item.get("home_team_id") or item.get("away_team_id") or item.get("team_id") or item.get("id")
    name = item.get("home_team_name") or item.get("away_team_name") or item.get("team_name") or item.get("name") or "Unknown"
    country_obj = item.get("country") or {}
    country = country_obj.get("name") if isinstance(country_obj, dict) else None
    return legacy.team(a, "StatsBomb Open Data", pid, str(name), country)


def statsbomb_match(a: media.Archive, competition: dict[str, Any], match: dict[str, Any]) -> tuple[int, int, int]:
    comp_id = competition["competition_id"]
    season_id = competition["season_id"]
    country = competition.get("country_name")
    cid = legacy.competition(
        a, "StatsBomb Open Data", comp_id,
        competition.get("competition_name") or f"Competition {comp_id}",
        country, competition.get("competition_gender") or "competition",
    )
    sid = legacy.season(
        a, "StatsBomb Open Data", season_id, cid,
        competition.get("season_name") or str(season_id), None, None, False,
    )
    home = match.get("home_team") or {}
    away = match.get("away_team") or {}
    hid = legacy.team(a, "StatsBomb Open Data", home.get("home_team_id"), home.get("home_team_name") or "Unknown", country)
    aid = legacy.team(a, "StatsBomb Open Data", away.get("away_team_id"), away.get("away_team_name") or "Unknown", country)
    date = str(match.get("match_date") or "")
    kickoff = str(match.get("kick_off") or "")
    stamp = f"{date}T{kickoff}" if kickoff else date
    stage = (match.get("competition_stage") or {}).get("name")
    stadium = (match.get("stadium") or {}).get("name")
    referee = (match.get("referee") or {}).get("name")
    result = no_key.improved_match(
        a, "StatsBomb Open Data", str(match.get("match_id")), cid, sid, stamp,
        hid, aid, legacy.as_int(match.get("home_score")), legacy.as_int(match.get("away_score")),
        "finished", stadium, stage, referee,
    )
    local_mid = legacy.provider_local_id(a, "StatsBomb Open Data", "match", match.get("match_id"))
    if local_mid is None:
        raise RuntimeError("StatsBomb match provider binding missing")
    return local_mid, int(result == "INSERTED"), int(result in {"UPDATED", "LINKED"})


def import_statsbomb_lineups(a: media.Archive, match_id: int, provider_match_id: int) -> tuple[int, int]:
    url = f"https://raw.githubusercontent.com/statsbomb/open-data/master/data/lineups/{provider_match_id}.json"
    try:
        payload = request_json(url)
    except Exception:
        return 0, 0
    lineups = players = 0
    for team_item in payload if isinstance(payload, list) else []:
        team_id = legacy.team(
            a, "StatsBomb Open Data", team_item.get("team_id"),
            team_item.get("team_name") or "Unknown",
        )
        for player_item in team_item.get("lineup") or []:
            pid = player_item.get("player_id")
            name = player_item.get("player_name") or player_item.get("player_nickname") or "Unknown"
            country = (player_item.get("country") or {}).get("name")
            player_id = legacy.player(
                a, "StatsBomb Open Data", pid, name,
                {"birth": None, "nationality": country, "birthplace": None, "position": None, "height": None, "weight": None, "gender": None},
            )
            players += 1
            positions = player_item.get("positions") or []
            first = positions[0] if positions else {}
            position = first.get("position")
            position_name = position.get("name") if isinstance(position, dict) else None
            from_time = first.get("from")
            to_time = first.get("to")
            starter = 1 if not from_time or str(from_time).startswith("00:00") else 0
            a.conn.execute(
                """INSERT INTO match_lineups(match_id,team_id,player_id,is_starting,shirt_number,position,formation_slot,captain,minute_on,minute_off)
                   VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(match_id,team_id,player_id) DO UPDATE SET
                   is_starting=excluded.is_starting,shirt_number=COALESCE(excluded.shirt_number,match_lineups.shirt_number),
                   position=COALESCE(excluded.position,match_lineups.position),captain=MAX(match_lineups.captain,excluded.captain)""",
                (match_id, team_id, player_id, starter, legacy.as_int(player_item.get("jersey_number")),
                 position_name, None, 0, None, None),
            )
            lineups += 1
    return players, lineups


def import_statsbomb_events(a: media.Archive, match_id: int, provider_match_id: int) -> int:
    url = f"https://raw.githubusercontent.com/statsbomb/open-data/master/data/events/{provider_match_id}.json"
    try:
        payload = request_json(url)
    except Exception:
        return 0
    saved = 0
    useful = {"Goal", "Own Goal For", "Own Goal Against", "Yellow Card", "Red Card", "Second Yellow", "Substitution"}
    for event in payload if isinstance(payload, list) else []:
        event_type = (event.get("type") or {}).get("name") or ""
        detail = ""
        normalized_type = ""
        if event_type == "Shot" and (event.get("shot") or {}).get("outcome", {}).get("name") == "Goal":
            normalized_type = "goal"
            detail = (event.get("shot") or {}).get("technique", {}).get("name") or ""
        elif event_type in useful:
            normalized_type = event_type.casefold().replace(" ", "_")
        elif event_type == "Foul Committed":
            card = (event.get("foul_committed") or {}).get("card", {}).get("name")
            if card:
                normalized_type = card.casefold().replace(" ", "_")
        if not normalized_type:
            continue
        team_obj = event.get("team") or {}
        player_obj = event.get("player") or {}
        local_team = None
        local_player = None
        if team_obj.get("id"):
            local_team = legacy.team(a, "StatsBomb Open Data", team_obj.get("id"), team_obj.get("name") or "Unknown")
        if player_obj.get("id"):
            local_player = legacy.player(
                a, "StatsBomb Open Data", player_obj.get("id"), player_obj.get("name") or "Unknown",
                {"birth": None, "nationality": None, "birthplace": None, "position": None, "height": None, "weight": None, "gender": None},
            )
        minute = legacy.as_int(event.get("minute"))
        second = legacy.as_int(event.get("second"))
        unique_detail = f"statsbomb:{event.get('id')}|{detail}|second={second}"
        a.conn.execute(
            """INSERT OR IGNORE INTO match_events(match_id,team_id,player_id,event_type,minute,minute_extra,detail)
               VALUES(?,?,?,?,?,?,?)""",
            (match_id, local_team, local_player, normalized_type, minute, None, unique_detail),
        )
        saved += 1
    return saved


def statsbomb(a: media.Archive, mode: str, max_matches: int, include_events: bool) -> dict[str, int]:
    provider = "StatsBomb Open Data"
    stats = stats_template()
    competitions = request_json("https://raw.githubusercontent.com/statsbomb/open-data/master/data/competitions.json")
    if not isinstance(competitions, list):
        return stats
    start = int(checkpoint_get(a, provider, "competition_index", "0") or 0)
    selected = competitions[start:] if mode == "full" else competitions[max(0, len(competitions) - 8):]
    processed_matches = 0
    for offset, comp in enumerate(selected):
        comp_id = comp.get("competition_id")
        season_id = comp.get("season_id")
        if comp_id is None or season_id is None:
            continue
        try:
            matches = request_json(
                f"https://raw.githubusercontent.com/statsbomb/open-data/master/data/matches/{comp_id}/{season_id}.json"
            )
            stats["competitions"] += 1
            for match in matches if isinstance(matches, list) else []:
                if max_matches > 0 and processed_matches >= max_matches:
                    checkpoint_set(a, provider, "competition_index", start + offset)
                    a.conn.commit()
                    return stats
                local_mid, inserted, changed = statsbomb_match(a, comp, match)
                stats["matches"] += inserted + changed
                stats["teams"] += 2
                p, l = import_statsbomb_lineups(a, local_mid, int(match.get("match_id")))
                stats["players"] += p
                stats["lineups"] += l
                if include_events:
                    stats["events"] += import_statsbomb_events(a, local_mid, int(match.get("match_id")))
                processed_matches += 1
                if processed_matches % 25 == 0:
                    a.conn.commit()
                    media.log(f"STATSBOMB PROGRESS | matches={processed_matches} | lineups={stats['lineups']} | events={stats['events']}")
            checkpoint_set(a, provider, "competition_index", start + offset + 1)
            a.conn.commit()
        except Exception as exc:
            stats["errors"] += 1
            media.log(f"STATSBOMB ERROR | competition={comp_id} season={season_id} | {exc}", "WARN")
    checkpoint_set(a, provider, "competition_index", 0)
    return stats


def discover_api_football(a: media.Archive, conf: dict[str, Any], mode: str) -> dict[str, int]:
    gs = conf["global_sources"]
    key = str(gs.get("api_football_key") or "").strip()
    if not key:
        media.log("API-FOOTBALL INACTIVE | add api_football_key to config.json")
        return stats_template()
    headers = {"x-apisports-key": key}
    payload = request_json("https://v3.football.api-sports.io/leagues", headers)
    items = payload.get("response") or []
    league_ids = sorted({int((x.get("league") or {}).get("id")) for x in items if (x.get("league") or {}).get("id")})
    start = int(checkpoint_get(a, "API-Football", "league_index", "0") or 0)
    batch = int(gs.get("api_football_leagues_per_run", 40 if mode == "quick" else 120))
    selected = league_ids[start:start + batch]
    if not selected:
        checkpoint_set(a, "API-Football", "league_index", 0)
        selected = league_ids[:batch]
        start = 0
    original = gs.get("api_football_league_ids", [])
    gs["api_football_league_ids"] = selected
    years = [dt.date.today().year]
    if mode == "full":
        depth = int(gs.get("api_football_history_seasons", 3))
        years = list(range(dt.date.today().year, dt.date.today().year - max(1, depth), -1))
    total = stats_template()
    try:
        for year in years:
            result = legacy.api_football(a, conf, year)
            total["competitions"] += result.get("competitions", 0)
            total["teams"] += result.get("teams", 0)
            total["players"] += result.get("players", 0)
            total["matches"] += result.get("matches", 0)
            total["errors"] += result.get("errors", 0)
        checkpoint_set(a, "API-Football", "league_index", start + len(selected))
    finally:
        gs["api_football_league_ids"] = original
    return total


def discover_football_data(a: media.Archive, conf: dict[str, Any]) -> dict[str, int]:
    gs = conf["global_sources"]
    token = str(gs.get("football_data_token") or "").strip()
    if not token:
        media.log("FOOTBALL-DATA.ORG INACTIVE | add football_data_token to config.json")
        return stats_template()
    payload = request_json("https://api.football-data.org/v4/competitions", {"X-Auth-Token": token})
    codes = [str(x.get("code")) for x in payload.get("competitions") or [] if x.get("code")]
    original = gs.get("football_data_competitions", [])
    gs["football_data_competitions"] = codes
    try:
        result = legacy.football_data(a, conf)
    finally:
        gs["football_data_competitions"] = original
    out = stats_template()
    for key in ("competitions", "teams", "players", "matches", "errors"):
        out[key] = result.get(key, 0)
    return out


def discover_sportmonks(a: media.Archive, conf: dict[str, Any], mode: str) -> dict[str, int]:
    gs = conf["global_sources"]
    token = str(gs.get("sportmonks_token") or "").strip()
    if not token:
        media.log("SPORTMONKS INACTIVE | add sportmonks_token to config.json")
        return stats_template()
    page = 1
    ids: list[int] = []
    while True:
        payload = request_json(
            f"https://api.sportmonks.com/v3/football/leagues?api_token={urllib.parse.quote(token)}&page={page}"
        )
        ids.extend(int(x["id"]) for x in payload.get("data") or [] if x.get("id"))
        pagination = payload.get("pagination") or {}
        if not pagination.get("has_more"):
            break
        page += 1
        if page > 100:
            break
    start = int(checkpoint_get(a, "Sportmonks", "league_index", "0") or 0)
    batch = int(gs.get("sportmonks_leagues_per_run", 30 if mode == "quick" else 100))
    selected = ids[start:start + batch]
    if not selected:
        checkpoint_set(a, "Sportmonks", "league_index", 0)
        selected = ids[:batch]
        start = 0
    original = gs.get("sportmonks_league_ids", [])
    gs["sportmonks_league_ids"] = selected
    try:
        result = legacy.sportmonks(a, conf)
        checkpoint_set(a, "Sportmonks", "league_index", start + len(selected))
    finally:
        gs["sportmonks_league_ids"] = original
    out = stats_template()
    for key in ("competitions", "teams", "players", "matches", "errors"):
        out[key] = result.get(key, 0)
    return out


def run_provider(a: media.Archive, name: str, fn: Any) -> dict[str, int]:
    media.log(f"WORLD SOURCE START | {name}")
    try:
        result = fn()
        source_ok(a, name)
        a.conn.commit()
        media.log(f"WORLD SOURCE COMPLETE | {name} | {result}")
        return result
    except Exception as exc:
        source_error(a, name, exc)
        a.conn.commit()
        media.log(f"WORLD SOURCE ERROR | {name} | {exc}", "ERROR")
        result = stats_template()
        result["errors"] = 1
        return result


def run(mode: str, max_statsbomb_matches: int, include_statsbomb_events: bool) -> int:
    conf = no_key.config()
    gs = conf.setdefault("global_sources", {})
    a = media.Archive()
    ensure_schema(a)
    cur = a.conn.execute("INSERT INTO source_mesh_runs(started_at,mode) VALUES(?,?)", (now(), mode))
    run_id = int(cur.lastrowid)
    totals = stats_template()
    providers_started = providers_completed = 0
    try:
        media.log("=" * 90)
        media.log(f"WORLD SOURCE MESH v{VERSION} | mode={mode}")
        jobs = [
            ("OpenFootball JSON", lambda: no_key.openfootball(a, conf, mode, False)),
            ("Football-Data.co.uk", lambda: no_key.football_data_csv(a, conf, mode, False)),
            ("OpenLigaDB", lambda: no_key.openligadb_provider(a, conf)),
            ("StatsBomb Open Data", lambda: statsbomb(a, mode, max_statsbomb_matches, include_statsbomb_events)),
            ("API-Football", lambda: discover_api_football(a, conf, mode)),
            ("Sportmonks", lambda: discover_sportmonks(a, conf, mode)),
            ("football-data.org", lambda: discover_football_data(a, conf)),
        ]
        for name, fn in jobs:
            if not gs.get("source_mesh_disabled", []) or name not in gs.get("source_mesh_disabled", []):
                providers_started += 1
                result = run_provider(a, name, fn)
                if result.get("errors", 0) == 0:
                    providers_completed += 1
                for key in totals:
                    totals[key] += int(result.get(key, 0))
        graph.ensure_schema(a.conn)
        graph.seed_aliases(a.conn)
        graph.store_candidates(a.conn)
        graph.calculate_quality(a.conn)
        graph.rebuild_edges(a.conn)
        a.conn.execute("PRAGMA optimize")
        a.conn.execute(
            """UPDATE source_mesh_runs SET finished_at=?,providers_started=?,providers_completed=?,
               competitions=?,teams=?,players=?,matches=?,lineups=?,events=?,errors=? WHERE id=?""",
            (now(), providers_started, providers_completed, totals["competitions"], totals["teams"],
             totals["players"], totals["matches"], totals["lineups"], totals["events"], totals["errors"], run_id),
        )
        a.conn.commit()
        media.log(f"WORLD SOURCE MESH COMPLETE | providers={providers_completed}/{providers_started} | totals={totals}")
        return 0 if totals["errors"] == 0 else 2
    except Exception as exc:
        a.conn.execute(
            "UPDATE source_mesh_runs SET finished_at=?,errors=errors+1,note=? WHERE id=?",
            (now(), str(exc), run_id),
        )
        a.conn.commit()
        media.log(f"WORLD SOURCE MESH FATAL | {exc}", "ERROR")
        return 3
    finally:
        a.close()


def report() -> int:
    a = media.Archive()
    ensure_schema(a)
    try:
        media.log(f"WORLD SOURCE MESH REPORT v{VERSION}")
        rows = a.conn.execute(
            "SELECT provider,enabled,requires_key,last_success_at,last_error FROM source_mesh_catalog ORDER BY priority"
        ).fetchall()
        for row in rows:
            media.log(f"  {row[0]:24} enabled={row[1]} key={row[2]} success={row[3] or '-'} error={row[4] or '-'}")
        latest = a.conn.execute(
            "SELECT started_at,finished_at,providers_completed,providers_started,competitions,teams,players,matches,lineups,events,errors FROM source_mesh_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if latest:
            media.log(f"  latest_run={tuple(latest)}")
        return 0
    finally:
        a.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Worldwide multi-provider football source mesh")
    sub = parser.add_subparsers(dest="command")
    sync = sub.add_parser("sync")
    sync.add_argument("--mode", choices=["quick", "full"], default="quick")
    sync.add_argument("--max-statsbomb-matches", type=int, default=250)
    sync.add_argument("--statsbomb-events", action="store_true")
    sub.add_parser("report")
    args = parser.parse_args()
    if args.command == "report":
        return report()
    return run(getattr(args, "mode", "quick"), max(0, getattr(args, "max_statsbomb_matches", 250)), bool(getattr(args, "statsbomb_events", False)))


if __name__ == "__main__":
    raise SystemExit(main())
