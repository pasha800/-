#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sports Archive Harvester v1.3.1 - automatic global club collector.

This collector always has useful no-key providers:
* OpenFootball football.json (CC0, many countries/divisions/seasons)
* Football-Data.co.uk result CSV files (results only; odds are discarded)
* OpenLigaDB

Keyed providers remain optional and are delegated to global_football_sync.py.
Images stay outside SQLite through sports_harvester_external_media.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import io
import json
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterable

import sports_harvester_external_media as app
import global_football_sync as legacy

VERSION = "1.3.1"
ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "data" / "provider_cache"

EXTRA_SCHEMA = r"""
CREATE TABLE IF NOT EXISTS provider_files (
  provider TEXT NOT NULL,
  item_key TEXT NOT NULL,
  etag TEXT,
  last_modified TEXT,
  content_sha256 TEXT,
  last_checked_at TEXT NOT NULL,
  last_imported_at TEXT,
  rows_imported INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(provider,item_key)
);

CREATE TABLE IF NOT EXISTS provider_runs (
  id INTEGER PRIMARY KEY,
  provider TEXT NOT NULL,
  mode TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  status TEXT NOT NULL,
  files_checked INTEGER NOT NULL DEFAULT 0,
  files_changed INTEGER NOT NULL DEFAULT 0,
  competitions INTEGER NOT NULL DEFAULT 0,
  teams INTEGER NOT NULL DEFAULT 0,
  matches_inserted INTEGER NOT NULL DEFAULT 0,
  matches_updated INTEGER NOT NULL DEFAULT 0,
  matches_linked INTEGER NOT NULL DEFAULT 0,
  errors INTEGER NOT NULL DEFAULT 0,
  note TEXT
);
CREATE INDEX IF NOT EXISTS idx_provider_runs_provider ON provider_runs(provider,started_at);
"""

COUNTRY_BY_CODE = {
    "en": "England", "eng": "England", "sco": "Scotland", "de": "Germany",
    "at": "Austria", "es": "Spain", "it": "Italy", "fr": "France",
    "pt": "Portugal", "nl": "Netherlands", "be": "Belgium", "tr": "Turkey",
    "gr": "Greece", "ch": "Switzerland", "dk": "Denmark", "se": "Sweden",
    "no": "Norway", "fi": "Finland", "ie": "Ireland", "pl": "Poland",
    "cz": "Czech Republic", "sk": "Slovakia", "hu": "Hungary", "ro": "Romania",
    "bg": "Bulgaria", "hr": "Croatia", "rs": "Serbia", "ua": "Ukraine",
    "ru": "Russia", "il": "Israel", "us": "United States", "ca": "Canada",
    "mx": "Mexico", "br": "Brazil", "ar": "Argentina", "uy": "Uruguay",
    "cl": "Chile", "co": "Colombia", "pe": "Peru", "jp": "Japan",
    "cn": "China", "kr": "South Korea", "au": "Australia", "nz": "New Zealand",
    "za": "South Africa", "eg": "Egypt", "ma": "Morocco", "dz": "Algeria",
    "ng": "Nigeria", "sa": "Saudi Arabia", "ae": "United Arab Emirates",
}

FOOTBALL_DATA_LEAGUES = {
    "E0": ("Premier League", "England"),
    "E1": ("Championship", "England"),
    "E2": ("League One", "England"),
    "E3": ("League Two", "England"),
    "EC": ("National League", "England"),
    "SC0": ("Premiership", "Scotland"),
    "SC1": ("Championship", "Scotland"),
    "SC2": ("League One", "Scotland"),
    "SC3": ("League Two", "Scotland"),
    "D1": ("Bundesliga", "Germany"), "D2": ("2. Bundesliga", "Germany"),
    "I1": ("Serie A", "Italy"), "I2": ("Serie B", "Italy"),
    "SP1": ("La Liga", "Spain"), "SP2": ("Segunda Division", "Spain"),
    "F1": ("Ligue 1", "France"), "F2": ("Ligue 2", "France"),
    "N1": ("Eredivisie", "Netherlands"), "B1": ("First Division A", "Belgium"),
    "P1": ("Primeira Liga", "Portugal"), "T1": ("Super Lig", "Turkey"),
    "G1": ("Super League Greece", "Greece"),
}


def now() -> str:
    return app.now_iso()


def ensure_schema(a: app.Archive) -> None:
    legacy.ensure_schema(a)
    a.conn.executescript(EXTRA_SCHEMA)
    columns = {r[1] for r in a.conn.execute("PRAGMA table_info(matches)")}
    if "season_id" not in columns:
        a.conn.execute("ALTER TABLE matches ADD COLUMN season_id INTEGER REFERENCES seasons(id)")
    for name, base, note in [
        ("OpenFootball JSON", "https://github.com/openfootball/football.json", "CC0-1.0"),
        ("Football-Data.co.uk", "https://www.football-data.co.uk", "Results CSV; provider terms apply"),
    ]:
        a.conn.execute(
            "INSERT OR IGNORE INTO sources(name,base_url,license_note) VALUES(?,?,?)",
            (name, base, note),
        )
    a.conn.commit()


def config() -> dict[str, Any]:
    data = app.load_config()
    gs = data.setdefault("global_sources", {})
    gs.setdefault("enable_openfootball", True)
    gs.setdefault("openfootball_history_seasons", 35)
    gs.setdefault("openfootball_max_files_full", 0)
    gs.setdefault("openfootball_max_files_quick", 160)
    gs.setdefault("enable_football_data_csv", True)
    gs.setdefault("football_data_history_seasons", 12)
    gs.setdefault("football_data_league_codes", list(FOOTBALL_DATA_LEAGUES))
    gs.setdefault("enable_openligadb", True)
    gs.setdefault("request_retries", 4)
    gs.setdefault("request_pause_seconds", 0.08)
    gs.setdefault("fail_when_no_club_data", True)
    return data


def request_bytes(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: int = 50,
    retries: int = 4,
    allow_not_found: bool = False,
) -> tuple[bytes | None, dict[str, str], int]:
    base_headers = {"User-Agent": f"SportsArchiveHarvester/{VERSION}"}
    if headers:
        base_headers.update(headers)
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=base_headers)
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return response.read(), {k.lower(): v for k, v in response.headers.items()}, int(response.status)
        except urllib.error.HTTPError as exc:
            if exc.code == 304:
                return None, {k.lower(): v for k, v in exc.headers.items()}, 304
            if exc.code == 404 and allow_not_found:
                return None, {}, 404
            if exc.code == 429 or 500 <= exc.code < 600:
                if attempt >= retries:
                    raise
                retry_after = exc.headers.get("Retry-After")
                delay = float(retry_after) if retry_after and retry_after.isdigit() else min(60.0, 2.0 ** attempt * 2.0)
                app.log(f"HTTP RETRY | status={exc.code} | wait={delay:.1f}s | {url}", "WARN")
                time.sleep(delay)
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            if attempt >= retries:
                raise
            delay = min(30.0, 2.0 ** attempt)
            app.log(f"NETWORK RETRY | wait={delay:.1f}s | {url}", "WARN")
            time.sleep(delay)
    raise RuntimeError("request retry loop ended unexpectedly")


def cached_request(
    a: app.Archive,
    provider: str,
    item_key: str,
    url: str,
    *,
    retries: int,
    force: bool = False,
    allow_not_found: bool = False,
) -> tuple[bytes | None, bool, int]:
    row = a.conn.execute(
        "SELECT etag,last_modified,content_sha256 FROM provider_files WHERE provider=? AND item_key=?",
        (provider, item_key),
    ).fetchone()
    headers: dict[str, str] = {}
    if row and not force:
        if row[0]: headers["If-None-Match"] = str(row[0])
        if row[1]: headers["If-Modified-Since"] = str(row[1])
    data, response_headers, status = request_bytes(
        url, headers=headers, retries=retries, allow_not_found=allow_not_found
    )
    if status == 304:
        a.conn.execute(
            "UPDATE provider_files SET last_checked_at=? WHERE provider=? AND item_key=?",
            (now(), provider, item_key),
        )
        return None, False, status
    if status == 404:
        return None, False, status
    assert data is not None
    digest = hashlib.sha256(data).hexdigest()
    changed = not row or str(row[2] or "") != digest
    a.conn.execute(
        """INSERT INTO provider_files(provider,item_key,etag,last_modified,content_sha256,last_checked_at)
           VALUES(?,?,?,?,?,?)
           ON CONFLICT(provider,item_key) DO UPDATE SET
           etag=excluded.etag,last_modified=excluded.last_modified,
           content_sha256=excluded.content_sha256,last_checked_at=excluded.last_checked_at""",
        (provider, item_key, response_headers.get("etag"), response_headers.get("last-modified"), digest, now()),
    )
    return data, changed, status


def finish_file(a: app.Archive, provider: str, item_key: str, rows: int) -> None:
    a.conn.execute(
        """UPDATE provider_files SET last_imported_at=?,rows_imported=?
           WHERE provider=? AND item_key=?""",
        (now(), rows, provider, item_key),
    )


def provider_run_start(a: app.Archive, provider: str, mode: str) -> int:
    cur = a.conn.execute(
        "INSERT INTO provider_runs(provider,mode,started_at,status) VALUES(?,?,?,'running')",
        (provider, mode, now()),
    )
    a.conn.commit()
    return int(cur.lastrowid)


def provider_run_finish(a: app.Archive, run_id: int, stats: dict[str, int], status: str = "completed", note: str | None = None) -> None:
    a.conn.execute(
        """UPDATE provider_runs SET finished_at=?,status=?,files_checked=?,files_changed=?,
           competitions=?,teams=?,matches_inserted=?,matches_updated=?,matches_linked=?,errors=?,note=?
           WHERE id=?""",
        (now(), status, stats.get("files_checked", 0), stats.get("files_changed", 0),
         stats.get("competitions", 0), stats.get("teams", 0), stats.get("inserted", 0),
         stats.get("updated", 0), stats.get("linked", 0), stats.get("errors", 0), note, run_id),
    )
    a.conn.commit()


def normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def object_name(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return str(value.get("name") or value.get("title") or value.get("club") or "").strip()
    return str(value or "").strip()


def country_for_code(code: str) -> str | None:
    prefix = code.split(".", 1)[0].lower()
    return COUNTRY_BY_CODE.get(prefix)


def canonical_competition_name(payload_name: str, code: str, season_label: str) -> str:
    name = str(payload_name or "").strip()
    if name:
        name = re.sub(r"\b(?:19|20)\d{2}(?:[/\-](?:19|20)?\d{2})?\b", "", name)
        name = re.sub(r"\s+", " ", name).strip(" -/")
    return name or code


def stable_team_id(provider: str, country: str | None, name: str) -> str:
    text = f"{country or ''}|{normalize_name(name)}"
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def improved_match(
    a: app.Archive,
    provider: str,
    provider_id: str,
    competition_id: int,
    season_id: int | None,
    date: str,
    home_id: int,
    away_id: int,
    home_score: int | None,
    away_score: int | None,
    status: str,
    venue: str | None,
    stage: str | None = None,
    referee: str | None = None,
) -> str:
    existing = legacy.provider_local_id(a, provider, "match", provider_id)
    stamp = now()
    date_only = date[:10]
    kickoff = date[11:19] if len(date) >= 19 else None
    if existing:
        before = a.conn.execute(
            "SELECT home_score,away_score,status,venue,referee,tournament_stage,season_id FROM matches WHERE id=?",
            (existing,),
        ).fetchone()
        values = (home_score, away_score, status, venue, referee, stage, season_id)
        changed = tuple(before) != values if before else True
        a.conn.execute(
            """UPDATE matches SET home_score=?,away_score=?,status=?,venue=COALESCE(?,venue),
               referee=COALESCE(?,referee),tournament_stage=COALESCE(?,tournament_stage),
               season_id=COALESCE(?,season_id),kickoff_time=COALESCE(?,kickoff_time),updated_at=?
               WHERE id=?""",
            (home_score, away_score, status, venue, referee, stage, season_id, kickoff, stamp, existing),
        )
        return "UPDATED" if changed else "UNCHANGED"
    row = a.conn.execute(
        """SELECT id FROM matches WHERE sport_id=? AND match_date=?
           AND home_team_id=? AND away_team_id=? ORDER BY id LIMIT 1""",
        (a.sport_id(), date_only, home_id, away_id),
    ).fetchone()
    if row:
        match_id = int(row[0])
        legacy.bind_provider_id(a, provider, "match", provider_id, match_id)
        a.conn.execute(
            """UPDATE matches SET competition_id=COALESCE(competition_id,?),season_id=COALESCE(season_id,?),
               home_score=COALESCE(?,home_score),away_score=COALESCE(?,away_score),
               status=CASE WHEN status IN ('scheduled','unknown') THEN ? ELSE status END,
               venue=COALESCE(venue,?),tournament_stage=COALESCE(tournament_stage,?),updated_at=? WHERE id=?""",
            (competition_id, season_id, home_score, away_score, status, venue, stage, stamp, match_id),
        )
        return "LINKED"
    cur = a.conn.execute(
        """INSERT INTO matches(sport_id,competition_id,season_id,match_date,kickoff_time,
           home_team_id,away_team_id,home_score,away_score,status,venue,referee,
           tournament_stage,source_key,created_at,updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (a.sport_id(), competition_id, season_id, date_only, kickoff, home_id, away_id,
         home_score, away_score, status, venue, referee, stage,
         f"{provider}:{provider_id}", stamp, stamp),
    )
    match_id = int(cur.lastrowid)
    legacy.bind_provider_id(a, provider, "match", provider_id, match_id)
    return "INSERTED"


def parse_score(score: Any) -> tuple[int | None, int | None]:
    if isinstance(score, dict):
        value = score.get("ft") or score.get("fulltime") or score.get("fullTime")
    else:
        value = score
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        return legacy.as_int(value[0]), legacy.as_int(value[1])
    if isinstance(value, str):
        match = re.search(r"(\d+)\s*[-:]\s*(\d+)", value)
        if match:
            return int(match.group(1)), int(match.group(2))
    return None, None


def season_sort_key(label: str) -> tuple[int, str]:
    match = re.match(r"(\d{4})", label)
    return (int(match.group(1)) if match else 0, label)


def discover_openfootball_files(conf: dict[str, Any], mode: str, retries: int) -> list[str]:
    url = "https://api.github.com/repos/openfootball/football.json/git/trees/master?recursive=1"
    data, _, _ = request_bytes(url, retries=retries)
    assert data is not None
    payload = json.loads(data.decode("utf-8"))
    paths: list[str] = []
    for item in payload.get("tree") or []:
        path = str(item.get("path") or "")
        if item.get("type") != "blob" or not path.endswith(".json"):
            continue
        if not re.match(r"^\d{4}(?:-\d{2})?/[^/]+\.json$", path):
            continue
        if "/_" in path or path.endswith("/README.json"):
            continue
        paths.append(path)
    seasons = sorted({p.split("/", 1)[0] for p in paths}, key=season_sort_key, reverse=True)
    gs = conf["global_sources"]
    if mode == "quick":
        keep_seasons = set(seasons[:3])
        selected = [p for p in paths if p.split("/", 1)[0] in keep_seasons]
        maximum = int(gs.get("openfootball_max_files_quick", 160) or 0)
    else:
        history = int(gs.get("openfootball_history_seasons", 35) or 0)
        keep_seasons = set(seasons if history <= 0 else seasons[:history])
        selected = [p for p in paths if p.split("/", 1)[0] in keep_seasons]
        maximum = int(gs.get("openfootball_max_files_full", 0) or 0)
    selected.sort(key=lambda p: (season_sort_key(p.split("/", 1)[0]), p), reverse=True)
    return selected[:maximum] if maximum > 0 else selected


def openfootball(a: app.Archive, conf: dict[str, Any], mode: str, force: bool) -> dict[str, int]:
    provider = "OpenFootball JSON"
    stats = {"files_checked": 0, "files_changed": 0, "competitions": 0, "teams": 0,
             "inserted": 0, "updated": 0, "linked": 0, "unchanged": 0, "errors": 0}
    if not conf["global_sources"].get("enable_openfootball", True):
        app.log("OPENFOOTBALL DISABLED")
        return stats
    retries = int(conf["global_sources"].get("request_retries", 4))
    run_id = provider_run_start(a, provider, mode)
    try:
        paths = discover_openfootball_files(conf, mode, retries)
        app.log(f"OPENFOOTBALL DISCOVERED | files={len(paths)} | mode={mode}")
        for file_index, path in enumerate(paths, 1):
            stats["files_checked"] += 1
            url = "https://raw.githubusercontent.com/openfootball/football.json/master/" + urllib.parse.quote(path, safe="/-._")
            try:
                data, changed, status = cached_request(
                    a, provider, path, url, retries=retries, force=force, allow_not_found=True
                )
                if status == 404:
                    app.log(f"OPENFOOTBALL FILE MISSING | {path}", "WARN")
                    continue
                if data is None:
                    app.log(f"OPENFOOTBALL UNCHANGED FILE | {file_index}/{len(paths)} | {path}")
                    continue
                stats["files_changed"] += int(changed)
                payload = json.loads(data.decode("utf-8-sig"))
                matches = payload.get("matches") or []
                if not isinstance(matches, list):
                    continue
                season_label, filename = path.split("/", 1)
                code = filename[:-5]
                country = country_for_code(code)
                comp_name = canonical_competition_name(payload.get("name") or "", code, season_label)
                cid = legacy.competition(a, provider, code, comp_name, country, "league/cup")
                sid = legacy.season(a, provider, path, cid, season_label, None, None, path.split("/", 1)[0] in {dt.date.today().strftime('%Y'), f"{dt.date.today().year-1}-{str(dt.date.today().year)[-2:]}"})
                stats["competitions"] += 1
                imported_rows = 0
                for match_index, match in enumerate(matches, 1):
                    if not isinstance(match, dict):
                        continue
                    home_name = object_name(match.get("team1") or match.get("home"))
                    away_name = object_name(match.get("team2") or match.get("away"))
                    date = str(match.get("date") or "").strip()
                    if not home_name or not away_name or not re.match(r"^\d{4}-\d{2}-\d{2}", date):
                        continue
                    home_pid = stable_team_id(provider, country, home_name)
                    away_pid = stable_team_id(provider, country, away_name)
                    home_id = legacy.team(a, provider, home_pid, home_name, country)
                    away_id = legacy.team(a, provider, away_pid, away_name, country)
                    hs, aw = parse_score(match.get("score"))
                    status_name = "finished" if hs is not None and aw is not None else "scheduled"
                    identity = hashlib.sha1(f"{path}|{match_index}|{date}|{home_name}|{away_name}".encode("utf-8")).hexdigest()
                    result = improved_match(
                        a, provider, identity, cid, sid, date, home_id, away_id, hs, aw,
                        status_name, object_name(match.get("venue")) or None,
                        object_name(match.get("round") or match.get("stage")) or None,
                    )
                    key = result.lower()
                    if key in stats: stats[key] += 1
                    imported_rows += 1
                    if result != "UNCHANGED":
                        app.log(f"OPENFOOTBALL {result} | {season_label} | {comp_name} | {date[:10]} | {home_name} {hs if hs is not None else '-'}-{aw if aw is not None else '-'} {away_name}")
                    if match_index % 250 == 0:
                        a.conn.commit()
                finish_file(a, provider, path, imported_rows)
                a.conn.commit()
                app.log(f"OPENFOOTBALL FILE COMPLETE | {file_index}/{len(paths)} | {path} | rows={imported_rows}")
            except Exception as exc:
                stats["errors"] += 1
                app.log(f"OPENFOOTBALL FILE ERROR | {path} | {exc}", "ERROR")
        provider_run_finish(a, run_id, stats)
        return stats
    except Exception as exc:
        stats["errors"] += 1
        provider_run_finish(a, run_id, stats, "failed", str(exc))
        app.log(f"OPENFOOTBALL ERROR | {exc}", "ERROR")
        return stats


def football_season_codes(mode: str, history: int) -> list[str]:
    today = dt.date.today()
    current_start = today.year if today.month >= 7 else today.year - 1
    count = 2 if mode == "quick" else max(1, history)
    result = []
    for start in range(current_start, current_start - count, -1):
        result.append(f"{start % 100:02d}{(start + 1) % 100:02d}")
    return result


def parse_fd_date(value: str, season_code: str) -> str | None:
    text = (value or "").strip()
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%d/%m/%Y %H:%M", "%d/%m/%y %H:%M"):
        try:
            parsed = dt.datetime.strptime(text, fmt)
            return parsed.strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


def football_data_csv(a: app.Archive, conf: dict[str, Any], mode: str, force: bool) -> dict[str, int]:
    provider = "Football-Data.co.uk"
    stats = {"files_checked": 0, "files_changed": 0, "competitions": 0, "teams": 0,
             "inserted": 0, "updated": 0, "linked": 0, "unchanged": 0, "errors": 0}
    gs = conf["global_sources"]
    if not gs.get("enable_football_data_csv", True):
        app.log("FOOTBALL-DATA-CSV DISABLED")
        return stats
    retries = int(gs.get("request_retries", 4))
    seasons = football_season_codes(mode, int(gs.get("football_data_history_seasons", 12)))
    codes = [str(x).upper() for x in gs.get("football_data_league_codes", []) if str(x).upper() in FOOTBALL_DATA_LEAGUES]
    run_id = provider_run_start(a, provider, mode)
    try:
        for season_code in seasons:
            season_label = f"20{season_code[:2]}-20{season_code[2:]}"
            for code in codes:
                stats["files_checked"] += 1
                item_key = f"{season_code}/{code}.csv"
                url = f"https://www.football-data.co.uk/mmz4281/{season_code}/{code}.csv"
                try:
                    data, changed, status = cached_request(
                        a, provider, item_key, url, retries=retries, force=force, allow_not_found=True
                    )
                    if status == 404:
                        continue
                    if data is None:
                        continue
                    stats["files_changed"] += int(changed)
                    text = data.decode("utf-8-sig", errors="replace")
                    reader = csv.DictReader(io.StringIO(text))
                    league_name, country = FOOTBALL_DATA_LEAGUES[code]
                    cid = legacy.competition(a, provider, code, league_name, country, "league")
                    sid = legacy.season(a, provider, item_key, cid, season_label, None, None, season_code == seasons[0])
                    stats["competitions"] += 1
                    imported_rows = 0
                    for row_index, row in enumerate(reader, 1):
                        home_name = str(row.get("HomeTeam") or "").strip()
                        away_name = str(row.get("AwayTeam") or "").strip()
                        date = parse_fd_date(str(row.get("Date") or ""), season_code)
                        if not home_name or not away_name or not date:
                            continue
                        home_id = legacy.team(a, provider, stable_team_id(provider, country, home_name), home_name, country)
                        away_id = legacy.team(a, provider, stable_team_id(provider, country, away_name), away_name, country)
                        hs = legacy.as_int(row.get("FTHG")); aw = legacy.as_int(row.get("FTAG"))
                        status_name = "finished" if hs is not None and aw is not None else "scheduled"
                        identity = hashlib.sha1(f"{item_key}|{date}|{home_name}|{away_name}".encode("utf-8")).hexdigest()
                        result = improved_match(
                            a, provider, identity, cid, sid, date, home_id, away_id, hs, aw,
                            status_name, None, None, str(row.get("Referee") or "").strip() or None,
                        )
                        key = result.lower()
                        if key in stats: stats[key] += 1
                        imported_rows += 1
                        if result != "UNCHANGED":
                            app.log(f"FOOTBALL-DATA-CSV {result} | {season_label} | {league_name} | {date} | {home_name} {hs if hs is not None else '-'}-{aw if aw is not None else '-'} {away_name}")
                    finish_file(a, provider, item_key, imported_rows)
                    a.conn.commit()
                    app.log(f"FOOTBALL-DATA-CSV FILE COMPLETE | {item_key} | rows={imported_rows}")
                except Exception as exc:
                    stats["errors"] += 1
                    app.log(f"FOOTBALL-DATA-CSV FILE ERROR | {item_key} | {exc}", "WARN")
                time.sleep(float(gs.get("request_pause_seconds", 0.08)))
        provider_run_finish(a, run_id, stats)
        return stats
    except Exception as exc:
        stats["errors"] += 1
        provider_run_finish(a, run_id, stats, "failed", str(exc))
        app.log(f"FOOTBALL-DATA-CSV ERROR | {exc}", "ERROR")
        return stats


def openligadb_provider(a: app.Archive, conf: dict[str, Any]) -> dict[str, int]:
    base = legacy.openligadb(a, conf)
    return {
        "files_checked": 1, "files_changed": 1,
        "competitions": base.get("competitions", 0), "teams": base.get("teams", 0),
        "inserted": base.get("matches", 0), "updated": 0, "linked": 0,
        "unchanged": 0, "errors": base.get("errors", 0),
    }


def keyed_providers(a: app.Archive, conf: dict[str, Any], year: int) -> dict[str, int]:
    gs = conf["global_sources"]
    total = {"files_checked": 0, "files_changed": 0, "competitions": 0, "teams": 0,
             "inserted": 0, "updated": 0, "linked": 0, "unchanged": 0, "errors": 0}
    runners: list[tuple[str, Any]] = []
    if str(gs.get("football_data_token") or "").strip():
        runners.append(("football-data.org", lambda: legacy.football_data(a, conf)))
    else:
        app.log("OPTIONAL SOURCE INACTIVE | football-data.org | token not configured")
    if str(gs.get("api_football_key") or "").strip() and gs.get("api_football_league_ids"):
        runners.append(("API-Football", lambda: legacy.api_football(a, conf, year)))
    else:
        app.log("OPTIONAL SOURCE INACTIVE | API-Football | key/league IDs not configured")
    if str(gs.get("sportmonks_token") or "").strip() and gs.get("sportmonks_league_ids"):
        runners.append(("Sportmonks", lambda: legacy.sportmonks(a, conf)))
    else:
        app.log("OPTIONAL SOURCE INACTIVE | Sportmonks | token/league IDs not configured")
    for name, runner in runners:
        app.log(f"OPTIONAL PROVIDER START | {name}")
        result = runner()
        total["competitions"] += result.get("competitions", 0)
        total["teams"] += result.get("teams", 0)
        total["inserted"] += result.get("matches", 0)
        total["errors"] += result.get("errors", 0)
        app.log(f"OPTIONAL PROVIDER COMPLETE | {name} | {result}")
    return total


def add_totals(total: dict[str, int], part: dict[str, int]) -> None:
    for key in total:
        total[key] += int(part.get(key, 0))


def run(mode: str, providers: Iterable[str], force: bool = False) -> int:
    conf = config()
    a = app.Archive()
    ensure_schema(a)
    selected = {x.strip().lower() for x in providers if x.strip()}
    total = {"files_checked": 0, "files_changed": 0, "competitions": 0, "teams": 0,
             "inserted": 0, "updated": 0, "linked": 0, "unchanged": 0, "errors": 0}
    try:
        app.log("=" * 84)
        app.log(f"GLOBAL CLUB FOOTBALL SYNC v{VERSION} | mode={mode} | selected={','.join(sorted(selected))}")
        before = a.conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
        if "openfootball" in selected:
            app.log("PROVIDER START | openfootball | no API key required")
            result = openfootball(a, conf, mode, force)
            add_totals(total, result)
            app.log(f"PROVIDER COMPLETE | openfootball | {result}")
        if "football-data-csv" in selected:
            app.log("PROVIDER START | football-data-csv | no API key required")
            result = football_data_csv(a, conf, mode, force)
            add_totals(total, result)
            app.log(f"PROVIDER COMPLETE | football-data-csv | {result}")
        if "openligadb" in selected:
            app.log("PROVIDER START | openligadb | no API key required")
            result = openligadb_provider(a, conf)
            add_totals(total, result)
            app.log(f"PROVIDER COMPLETE | openligadb | {result}")
        if "keyed" in selected:
            result = keyed_providers(a, conf, dt.date.today().year)
            add_totals(total, result)
        after = a.conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
        app.database_report(a)
        app.log(f"GLOBAL CLUB SYNC COMPLETE | before_matches={before:,} | after_matches={after:,} | added={after-before:,} | totals={total}")
        no_data = total["inserted"] + total["linked"] + total["updated"] == 0
        if no_data and conf["global_sources"].get("fail_when_no_club_data", True):
            app.log("GLOBAL CLUB SYNC FAILED POLICY | no club match was inserted, linked or updated", "ERROR")
            return 3
        return 0 if total["errors"] == 0 else 2
    finally:
        a.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Automatic global club football synchronizer")
    parser.add_argument("--mode", choices=["quick", "full"], default="quick")
    parser.add_argument("--providers", default="openfootball,football-data-csv,openligadb,keyed")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    return run(args.mode, args.providers.split(","), args.force)


if __name__ == "__main__":
    raise SystemExit(main())
