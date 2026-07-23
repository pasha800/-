#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Global club + national-team football synchronizer v1.3.0.

Supported providers:
- API-Football (API-Sports): broad leagues, clubs, fixtures, squads and logos.
- Sportmonks Football: broad competitions, seasons, fixtures, teams and players.
- football-data.org: major competitions, clubs, matches and standings.
- OpenLigaDB: free German/European league fixtures and tables.

Only normalized essential fields are stored. Raw JSON, odds, predictions, news,
videos and display-only payloads are never written to SQLite.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import time
import urllib.parse
import urllib.request
from typing import Any, Iterable

import sports_harvester_external_media as app

VERSION = "1.3.0"

GLOBAL_SCHEMA = r"""
CREATE TABLE IF NOT EXISTS seasons (
  id INTEGER PRIMARY KEY,
  competition_id INTEGER NOT NULL REFERENCES competitions(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  start_date TEXT,
  end_date TEXT,
  is_current INTEGER NOT NULL DEFAULT 0,
  UNIQUE(competition_id,name)
);

CREATE TABLE IF NOT EXISTS provider_ids (
  provider TEXT NOT NULL,
  entity_type TEXT NOT NULL CHECK(entity_type IN ('competition','season','team','player','match')),
  provider_id TEXT NOT NULL,
  local_id INTEGER NOT NULL,
  PRIMARY KEY(provider,entity_type,provider_id),
  UNIQUE(provider,entity_type,local_id)
);

CREATE TABLE IF NOT EXISTS standings (
  season_id INTEGER NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
  team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  rank INTEGER,
  played INTEGER,
  won INTEGER,
  drawn INTEGER,
  lost INTEGER,
  goals_for INTEGER,
  goals_against INTEGER,
  goal_difference INTEGER,
  points INTEGER,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(season_id,team_id)
);

CREATE INDEX IF NOT EXISTS idx_provider_ids_local ON provider_ids(entity_type,local_id);
CREATE INDEX IF NOT EXISTS idx_standings_rank ON standings(season_id,rank);
"""


def cfg() -> dict[str, Any]:
    data = app.load_config()
    data.setdefault("global_sources", {})
    sources = data["global_sources"]
    sources.setdefault("api_football_key", "")
    sources.setdefault("football_data_token", "")
    sources.setdefault("sportmonks_token", "")
    sources.setdefault("enable_openligadb", True)
    sources.setdefault("api_football_league_ids", [])
    sources.setdefault("football_data_competitions", ["PL", "PD", "SA", "BL1", "FL1", "CL"])
    sources.setdefault("sportmonks_league_ids", [])
    sources.setdefault("historical_seasons", 5)
    return data


def request_json(url: str, headers: dict[str, str] | None = None, timeout: int = 45) -> Any:
    request_headers = {"User-Agent": f"SportsArchiveHarvester/{VERSION}"}
    if headers:
        request_headers.update(headers)
    req = urllib.request.Request(url, headers=request_headers)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def ensure_schema(a: app.Archive) -> None:
    a.conn.executescript(GLOBAL_SCHEMA)
    for name, base, note in [
        ("API-Football", "https://v3.football.api-sports.io", "API-Sports provider terms apply"),
        ("Sportmonks", "https://api.sportmonks.com/v3/football", "Sportmonks provider terms apply"),
        ("football-data.org", "https://api.football-data.org/v4", "Provider terms apply"),
        ("OpenLigaDB", "https://api.openligadb.de", "Open API; verify reuse terms"),
    ]:
        a.conn.execute(
            "INSERT OR IGNORE INTO sources(name,base_url,license_note) VALUES(?,?,?)",
            (name, base, note),
        )
    a.conn.commit()


def provider_local_id(a: app.Archive, provider: str, entity_type: str, provider_id: Any) -> int | None:
    row = a.conn.execute(
        "SELECT local_id FROM provider_ids WHERE provider=? AND entity_type=? AND provider_id=?",
        (provider, entity_type, str(provider_id)),
    ).fetchone()
    return int(row[0]) if row else None


def bind_provider_id(a: app.Archive, provider: str, entity_type: str, provider_id: Any, local_id: int) -> None:
    a.conn.execute(
        """INSERT INTO provider_ids(provider,entity_type,provider_id,local_id)
           VALUES(?,?,?,?)
           ON CONFLICT(provider,entity_type,provider_id) DO UPDATE SET local_id=excluded.local_id""",
        (provider, entity_type, str(provider_id), local_id),
    )


def competition(a: app.Archive, provider: str, pid: Any, name: str, country: str | None, kind: str | None = None) -> int:
    existing = provider_local_id(a, provider, "competition", pid)
    if existing:
        return existing
    cid = a.competition_id(name, country)
    assert cid is not None
    if kind:
        a.conn.execute("UPDATE competitions SET competition_type=COALESCE(competition_type,?) WHERE id=?", (kind, cid))
    bind_provider_id(a, provider, "competition", pid, cid)
    return cid


def season(a: app.Archive, provider: str, pid: Any, competition_id: int, name: str, start: str | None, end: str | None, current: bool) -> int:
    existing = provider_local_id(a, provider, "season", pid)
    if existing:
        return existing
    a.conn.execute(
        """INSERT OR IGNORE INTO seasons(competition_id,name,start_date,end_date,is_current)
           VALUES(?,?,?,?,?)""",
        (competition_id, name, start, end, int(current)),
    )
    row = a.conn.execute("SELECT id FROM seasons WHERE competition_id=? AND name=?", (competition_id, name)).fetchone()
    sid = int(row[0])
    bind_provider_id(a, provider, "season", pid, sid)
    return sid


def team(a: app.Archive, provider: str, pid: Any, name: str, country: str | None = None, extra: dict[str, Any] | None = None, logo: str | None = None) -> int:
    existing = provider_local_id(a, provider, "team", pid)
    if existing:
        tid = existing
    else:
        tid, _ = a.team_id(name, country)
        bind_provider_id(a, provider, "team", pid, tid)
    if extra:
        a.conn.execute(
            """UPDATE teams SET short_name=COALESCE(?,short_name),founded_year=COALESCE(?,founded_year),
               city=COALESCE(?,city),stadium=COALESCE(?,stadium),gender=COALESCE(?,gender),
               source_key=COALESCE(source_key,?),updated_at=? WHERE id=?""",
            (extra.get("short"), extra.get("founded"), extra.get("city"), extra.get("stadium"), extra.get("gender"), f"{provider}:{pid}", app.now_iso(), tid),
        )
    if logo:
        limit = int(cfg().get("media_limits", {}).get("team_logo_bytes", app.MAX_TEAM_LOGO_BYTES))
        app.download_media(a, "team", tid, "logo", logo, limit, app.TEAM_LOGO_DIR)
    return tid


def player(a: app.Archive, provider: str, pid: Any, name: str, details: dict[str, Any], photo: str | None = None) -> int:
    existing = provider_local_id(a, provider, "player", pid)
    if existing:
        plid = existing
    else:
        plid, _ = a.player_id(name, details.get("birth"), details.get("nationality"))
        bind_provider_id(a, provider, "player", pid, plid)
    a.conn.execute(
        """UPDATE players SET date_of_birth=COALESCE(?,date_of_birth),nationality=COALESCE(?,nationality),
           place_of_birth=COALESCE(?,place_of_birth),position=COALESCE(?,position),height_cm=COALESCE(?,height_cm),
           weight_kg=COALESCE(?,weight_kg),gender=COALESCE(?,gender),source_key=COALESCE(source_key,?),updated_at=? WHERE id=?""",
        (details.get("birth"), details.get("nationality"), details.get("birthplace"), details.get("position"), details.get("height"), details.get("weight"), details.get("gender"), f"{provider}:{pid}", app.now_iso(), plid),
    )
    if photo:
        limit = int(cfg().get("media_limits", {}).get("player_photo_bytes", app.MAX_PLAYER_PHOTO_BYTES))
        app.download_media(a, "player", plid, "photo", photo, limit, app.PLAYER_PHOTO_DIR)
    return plid


def upsert_match(a: app.Archive, provider: str, pid: Any, competition_id: int, date: str, home_id: int, away_id: int, hs: int | None, aw: int | None, status: str, venue: str | None, referee: str | None = None) -> str:
    existing = provider_local_id(a, provider, "match", pid)
    now = app.now_iso()
    if existing:
        a.conn.execute(
            """UPDATE matches SET home_score=?,away_score=?,status=?,venue=COALESCE(?,venue),referee=COALESCE(?,referee),updated_at=? WHERE id=?""",
            (hs, aw, status, venue, referee, now, existing),
        )
        return "UPDATED"
    row = a.conn.execute(
        """SELECT id FROM matches WHERE sport_id=? AND match_date=? AND home_team_id=? AND away_team_id=? AND competition_id=?""",
        (a.sport_id(), date[:10], home_id, away_id, competition_id),
    ).fetchone()
    if row:
        mid = int(row[0])
        bind_provider_id(a, provider, "match", pid, mid)
        return "LINKED"
    cur = a.conn.execute(
        """INSERT INTO matches(sport_id,competition_id,match_date,kickoff_time,home_team_id,away_team_id,
           home_score,away_score,status,venue,referee,source_key,created_at,updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (a.sport_id(), competition_id, date[:10], date[11:19] if len(date) >= 19 else None, home_id, away_id, hs, aw, status, venue, referee, f"{provider}:{pid}", now, now),
    )
    mid = int(cur.lastrowid)
    bind_provider_id(a, provider, "match", pid, mid)
    return "INSERTED"


def as_int(v: Any) -> int | None:
    try:
        return int(v) if v is not None and str(v) != "" else None
    except (ValueError, TypeError):
        return None


def api_football(a: app.Archive, conf: dict[str, Any], season_year: int) -> dict[str, int]:
    key = conf["global_sources"].get("api_football_key", "").strip()
    league_ids = conf["global_sources"].get("api_football_league_ids", [])
    stats = {"competitions": 0, "teams": 0, "players": 0, "matches": 0, "errors": 0}
    if not key or not league_ids:
        app.log("API-FOOTBALL SKIPPED | add api_football_key and api_football_league_ids in config.json", "WARN")
        return stats
    headers = {"x-apisports-key": key}
    for league_id in league_ids:
        try:
            meta = request_json(f"https://v3.football.api-sports.io/leagues?id={league_id}&season={season_year}", headers)
            item = (meta.get("response") or [None])[0]
            if not item:
                continue
            lg, country = item["league"], item.get("country") or {}
            cid = competition(a, "API-Football", lg["id"], lg["name"], country.get("name"), lg.get("type"))
            stats["competitions"] += 1
            season_item = next((s for s in item.get("seasons", []) if int(s.get("year", 0)) == season_year), None)
            if season_item:
                season(a, "API-Football", f"{lg['id']}:{season_year}", cid, str(season_year), season_item.get("start"), season_item.get("end"), bool(season_item.get("current")))
            fixtures = request_json(f"https://v3.football.api-sports.io/fixtures?league={league_id}&season={season_year}", headers)
            for idx, fx in enumerate(fixtures.get("response") or [], 1):
                teams = fx.get("teams") or {}; goals = fx.get("goals") or {}; fixture = fx.get("fixture") or {}
                home = teams.get("home") or {}; away = teams.get("away") or {}
                hid = team(a, "API-Football", home.get("id"), home.get("name") or "Unknown", country.get("name"), logo=home.get("logo"))
                aid = team(a, "API-Football", away.get("id"), away.get("name") or "Unknown", country.get("name"), logo=away.get("logo"))
                result = upsert_match(a, "API-Football", fixture.get("id"), cid, fixture.get("date") or "", hid, aid, as_int(goals.get("home")), as_int(goals.get("away")), (fixture.get("status") or {}).get("short") or "unknown", (fixture.get("venue") or {}).get("name"), fixture.get("referee"))
                stats["matches"] += int(result == "INSERTED")
                app.log(f"API-FOOTBALL {result} | league={lg['name']} | {home.get('name')} vs {away.get('name')}")
                if idx % 100 == 0: a.conn.commit()
            a.conn.commit()
        except Exception as exc:
            stats["errors"] += 1
            app.log(f"API-FOOTBALL ERROR | league={league_id} | {exc}", "ERROR")
    return stats


def football_data(a: app.Archive, conf: dict[str, Any]) -> dict[str, int]:
    token = conf["global_sources"].get("football_data_token", "").strip()
    codes = conf["global_sources"].get("football_data_competitions", [])
    stats = {"competitions": 0, "teams": 0, "players": 0, "matches": 0, "errors": 0}
    if not token:
        app.log("FOOTBALL-DATA SKIPPED | add football_data_token in config.json", "WARN")
        return stats
    headers = {"X-Auth-Token": token}
    for code in codes:
        try:
            comp = request_json(f"https://api.football-data.org/v4/competitions/{urllib.parse.quote(str(code))}", headers)
            cid = competition(a, "football-data.org", comp["id"], comp["name"], (comp.get("area") or {}).get("name"), comp.get("type"))
            stats["competitions"] += 1
            current = comp.get("currentSeason") or {}
            if current:
                season(a, "football-data.org", current.get("id"), cid, str(current.get("startDate", ""))[:4] or str(current.get("id")), current.get("startDate"), current.get("endDate"), True)
            teams_payload = request_json(f"https://api.football-data.org/v4/competitions/{urllib.parse.quote(str(code))}/teams", headers)
            for tm in teams_payload.get("teams") or []:
                team(a, "football-data.org", tm["id"], tm["name"], (tm.get("area") or {}).get("name"), {"short": tm.get("shortName"), "founded": tm.get("founded"), "stadium": tm.get("venue")}, tm.get("crest"))
                stats["teams"] += 1
            matches = request_json(f"https://api.football-data.org/v4/competitions/{urllib.parse.quote(str(code))}/matches", headers)
            for m in matches.get("matches") or []:
                home = m.get("homeTeam") or {}; away = m.get("awayTeam") or {}; score = m.get("score") or {}; full = score.get("fullTime") or {}
                hid = team(a, "football-data.org", home.get("id"), home.get("name") or "Unknown")
                aid = team(a, "football-data.org", away.get("id"), away.get("name") or "Unknown")
                result = upsert_match(a, "football-data.org", m.get("id"), cid, m.get("utcDate") or "", hid, aid, as_int(full.get("home")), as_int(full.get("away")), m.get("status") or "unknown", None, None)
                stats["matches"] += int(result == "INSERTED")
                app.log(f"FOOTBALL-DATA {result} | {comp['name']} | {home.get('name')} vs {away.get('name')}")
            a.conn.commit()
            time.sleep(6.5)
        except Exception as exc:
            stats["errors"] += 1
            app.log(f"FOOTBALL-DATA ERROR | competition={code} | {exc}", "ERROR")
    return stats


def openligadb(a: app.Archive, conf: dict[str, Any]) -> dict[str, int]:
    stats = {"competitions": 0, "teams": 0, "players": 0, "matches": 0, "errors": 0}
    if not conf["global_sources"].get("enable_openligadb", True):
        return stats
    try:
        leagues = request_json("https://api.openligadb.de/getavailableleagues")
        for lg in leagues:
            shortcut = lg.get("leagueShortcut")
            season_name = lg.get("leagueSeason")
            if not shortcut or not season_name:
                continue
            cid = competition(a, "OpenLigaDB", f"{shortcut}:{season_name}", lg.get("leagueName") or shortcut, "Germany")
            stats["competitions"] += 1
            season(a, "OpenLigaDB", f"{shortcut}:{season_name}", cid, str(season_name), None, None, True)
            matches = request_json(f"https://api.openligadb.de/getmatchdata/{urllib.parse.quote(shortcut)}/{urllib.parse.quote(str(season_name))}")
            for m in matches:
                t1 = m.get("team1") or {}; t2 = m.get("team2") or {}
                hid = team(a, "OpenLigaDB", t1.get("teamId"), t1.get("teamName") or "Unknown", "Germany", {"short": t1.get("shortName")}, t1.get("teamIconUrl"))
                aid = team(a, "OpenLigaDB", t2.get("teamId"), t2.get("teamName") or "Unknown", "Germany", {"short": t2.get("shortName")}, t2.get("teamIconUrl"))
                results = m.get("matchResults") or []
                final = next((r for r in results if r.get("resultTypeID") == 2), results[-1] if results else {})
                result = upsert_match(a, "OpenLigaDB", m.get("matchID"), cid, m.get("matchDateTimeUTC") or m.get("matchDateTime") or "", hid, aid, as_int(final.get("pointsTeam1")), as_int(final.get("pointsTeam2")), "finished" if m.get("matchIsFinished") else "scheduled", (m.get("location") or {}).get("locationStadium"))
                stats["matches"] += int(result == "INSERTED")
                app.log(f"OPENLIGADB {result} | {lg.get('leagueName')} | {t1.get('teamName')} vs {t2.get('teamName')}")
            a.conn.commit()
    except Exception as exc:
        stats["errors"] += 1
        app.log(f"OPENLIGADB ERROR | {exc}", "ERROR")
    return stats


def sportmonks(a: app.Archive, conf: dict[str, Any]) -> dict[str, int]:
    token = conf["global_sources"].get("sportmonks_token", "").strip()
    league_ids = conf["global_sources"].get("sportmonks_league_ids", [])
    stats = {"competitions": 0, "teams": 0, "players": 0, "matches": 0, "errors": 0}
    if not token or not league_ids:
        app.log("SPORTMONKS SKIPPED | add sportmonks_token and sportmonks_league_ids in config.json", "WARN")
        return stats
    for league_id in league_ids:
        try:
            league_payload = request_json(f"https://api.sportmonks.com/v3/football/leagues/{league_id}?api_token={urllib.parse.quote(token)}&include=country;currentSeason")
            lg = league_payload.get("data") or {}
            country_name = ((lg.get("country") or {}).get("name"))
            cid = competition(a, "Sportmonks", lg.get("id"), lg.get("name") or f"League {league_id}", country_name, lg.get("type"))
            stats["competitions"] += 1
            current = lg.get("currentseason") or lg.get("currentSeason") or {}
            season_id = current.get("id")
            if season_id:
                season(a, "Sportmonks", season_id, cid, current.get("name") or str(season_id), current.get("starting_at"), current.get("ending_at"), True)
                page = 1
                while True:
                    url = f"https://api.sportmonks.com/v3/football/fixtures?api_token={urllib.parse.quote(token)}&filter[season_id]={season_id}&include=participants;venue&page={page}"
                    payload = request_json(url)
                    for fx in payload.get("data") or []:
                        participants = fx.get("participants") or []
                        home = next((p for p in participants if (p.get("meta") or {}).get("location") == "home"), participants[0] if participants else {})
                        away = next((p for p in participants if (p.get("meta") or {}).get("location") == "away"), participants[1] if len(participants) > 1 else {})
                        hid = team(a, "Sportmonks", home.get("id"), home.get("name") or "Unknown", country_name, logo=home.get("image_path"))
                        aid = team(a, "Sportmonks", away.get("id"), away.get("name") or "Unknown", country_name, logo=away.get("image_path"))
                        scores = fx.get("scores") or []
                        hs = aw = None
                        for sc in scores:
                            participant = sc.get("participant_id")
                            goals = ((sc.get("score") or {}).get("goals"))
                            if participant == home.get("id"): hs = as_int(goals)
                            if participant == away.get("id"): aw = as_int(goals)
                        result = upsert_match(a, "Sportmonks", fx.get("id"), cid, fx.get("starting_at") or "", hid, aid, hs, aw, str(fx.get("state_id") or "unknown"), (fx.get("venue") or {}).get("name"))
                        stats["matches"] += int(result == "INSERTED")
                        app.log(f"SPORTMONKS {result} | {lg.get('name')} | {home.get('name')} vs {away.get('name')}")
                    pagination = payload.get("pagination") or {}
                    if not pagination.get("has_more"): break
                    page += 1
                    a.conn.commit()
            a.conn.commit()
        except Exception as exc:
            stats["errors"] += 1
            app.log(f"SPORTMONKS ERROR | league={league_id} | {exc}", "ERROR")
    return stats


def run(selected: Iterable[str], year: int) -> int:
    conf = cfg()
    a = app.Archive()
    ensure_schema(a)
    totals = {"competitions": 0, "teams": 0, "players": 0, "matches": 0, "errors": 0}
    try:
        app.log("=" * 78)
        app.log(f"GLOBAL FOOTBALL SYNC v{VERSION} | year={year} | providers={','.join(selected)}")
        app.log("Scope: clubs + national teams + leagues + cups; essential normalized data only")
        runners = {
            "api-football": lambda: api_football(a, conf, year),
            "football-data": lambda: football_data(a, conf),
            "openligadb": lambda: openligadb(a, conf),
            "sportmonks": lambda: sportmonks(a, conf),
        }
        for name in selected:
            if name not in runners:
                continue
            app.log(f"PROVIDER START | {name}")
            result = runners[name]()
            for k in totals: totals[k] += result.get(k, 0)
            app.log(f"PROVIDER COMPLETE | {name} | {result}")
            a.conn.commit()
        app.database_report(a)
        app.log(f"GLOBAL SYNC COMPLETE | {totals}")
        return 0 if totals["errors"] == 0 else 2
    finally:
        a.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--providers", default="openligadb,football-data,api-football,sportmonks")
    parser.add_argument("--year", type=int, default=dt.date.today().year)
    args = parser.parse_args()
    selected = [x.strip().lower() for x in args.providers.split(",") if x.strip()]
    return run(selected, args.year)


if __name__ == "__main__":
    raise SystemExit(main())
