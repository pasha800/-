#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sports Archive Harvester v1.2.0

Offline-first, storage-conscious SQLite sports archive.
- Full historical bootstrap for international football (1872+)
- Fast current-year incremental update
- Verbose terminal progress for every saved object
- Team/player metadata and local media enrichment
- No raw API payloads and no remote-display dependency
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import mimetypes
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterable, Optional

APP_VERSION = "1.2.0"
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "sports_archive.sqlite3"
CACHE_DIR = DATA_DIR / "cache"
MEDIA_DIR = DATA_DIR / "media"
TEAM_LOGO_DIR = MEDIA_DIR / "team_logos"
PLAYER_PHOTO_DIR = MEDIA_DIR / "player_photos"
LOG_DIR = ROOT / "logs"
LOG_FILE = LOG_DIR / "live_sync.log"
CONFIG_PATH = ROOT / "config.json"

HIST_RESULTS = "https://raw.githubusercontent.com/martj42/international_results/master/results.csv"
HIST_GOALS = "https://raw.githubusercontent.com/martj42/international_results/master/goalscorers.csv"
HIST_SHOOTOUTS = "https://raw.githubusercontent.com/martj42/international_results/master/shootouts.csv"

ALLOWED_IMAGE_MIME = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
MAX_TEAM_LOGO_BYTES = 600_000
MAX_PLAYER_PHOTO_BYTES = 900_000
USER_AGENT = f"SportsArchiveHarvester/{APP_VERSION}"


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def log(message: str, level: str = "INFO") -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    line = f"[{now_iso()}] [{level}] {message}"
    print(line, flush=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def human_bytes(value: int) -> str:
    units = ["B", "KB", "MB", "GB"]
    size = float(value)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{value} B"


def load_config() -> dict[str, Any]:
    default = {
        "thesportsdb_api_key": "3",
        "download_team_logos": True,
        "download_player_photos": True,
        "media_limits": {
            "team_logo_bytes": MAX_TEAM_LOGO_BYTES,
            "player_photo_bytes": MAX_PLAYER_PHOTO_BYTES
        },
        "incremental_overlap_days": 14,
        "enrich_new_teams": True,
        "enrich_new_players": True,
        "request_timeout_seconds": 30
    }
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(json.dumps(default, ensure_ascii=False, indent=2), encoding="utf-8")
        return default
    try:
        user = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        default.update(user)
    except Exception as exc:
        log(f"config.json could not be read; safe defaults are used: {exc}", "WARN")
    return default


SCHEMA = r"""
PRAGMA foreign_keys=ON;
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA temp_store=MEMORY;
PRAGMA cache_size=-65536;

CREATE TABLE IF NOT EXISTS sports (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS countries (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS competitions (
  id INTEGER PRIMARY KEY,
  sport_id INTEGER NOT NULL REFERENCES sports(id),
  name TEXT NOT NULL,
  country_id INTEGER REFERENCES countries(id),
  competition_type TEXT,
  UNIQUE(sport_id, name, country_id)
);

CREATE TABLE IF NOT EXISTS teams (
  id INTEGER PRIMARY KEY,
  sport_id INTEGER NOT NULL REFERENCES sports(id),
  name TEXT NOT NULL,
  short_name TEXT,
  country_id INTEGER REFERENCES countries(id),
  founded_year INTEGER,
  city TEXT,
  stadium TEXT,
  gender TEXT,
  source_key TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(sport_id, name, country_id)
);

CREATE TABLE IF NOT EXISTS players (
  id INTEGER PRIMARY KEY,
  sport_id INTEGER NOT NULL REFERENCES sports(id),
  full_name TEXT NOT NULL,
  date_of_birth TEXT,
  date_of_death TEXT,
  nationality TEXT,
  place_of_birth TEXT,
  position TEXT,
  height_cm REAL,
  weight_kg REAL,
  gender TEXT,
  source_key TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(sport_id, full_name, date_of_birth)
);

CREATE TABLE IF NOT EXISTS team_memberships (
  id INTEGER PRIMARY KEY,
  team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  player_id INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
  shirt_number INTEGER,
  position TEXT,
  start_date TEXT,
  end_date TEXT,
  is_current INTEGER NOT NULL DEFAULT 1,
  UNIQUE(team_id, player_id, start_date)
);

CREATE TABLE IF NOT EXISTS matches (
  id INTEGER PRIMARY KEY,
  sport_id INTEGER NOT NULL REFERENCES sports(id),
  competition_id INTEGER REFERENCES competitions(id),
  match_date TEXT NOT NULL,
  kickoff_time TEXT,
  home_team_id INTEGER NOT NULL REFERENCES teams(id),
  away_team_id INTEGER NOT NULL REFERENCES teams(id),
  home_score INTEGER,
  away_score INTEGER,
  status TEXT NOT NULL DEFAULT 'finished',
  venue TEXT,
  city TEXT,
  country_id INTEGER REFERENCES countries(id),
  neutral INTEGER NOT NULL DEFAULT 0,
  tournament_stage TEXT,
  referee TEXT,
  attendance INTEGER,
  source_key TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(sport_id, match_date, home_team_id, away_team_id, competition_id)
);

CREATE TABLE IF NOT EXISTS match_events (
  id INTEGER PRIMARY KEY,
  match_id INTEGER NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
  team_id INTEGER REFERENCES teams(id),
  player_id INTEGER REFERENCES players(id),
  event_type TEXT NOT NULL,
  minute INTEGER,
  minute_extra INTEGER,
  detail TEXT,
  UNIQUE(match_id, event_type, minute, player_id, detail)
);

CREATE TABLE IF NOT EXISTS match_stats (
  match_id INTEGER NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
  team_id INTEGER NOT NULL REFERENCES teams(id),
  stat_name TEXT NOT NULL,
  stat_value REAL,
  PRIMARY KEY(match_id, team_id, stat_name)
);

CREATE TABLE IF NOT EXISTS media (
  id INTEGER PRIMARY KEY,
  entity_type TEXT NOT NULL CHECK(entity_type IN ('team','player')),
  entity_id INTEGER NOT NULL,
  media_type TEXT NOT NULL CHECK(media_type IN ('logo','photo')),
  relative_path TEXT NOT NULL,
  mime_type TEXT NOT NULL,
  byte_size INTEGER NOT NULL,
  sha256 TEXT NOT NULL UNIQUE,
  source_url TEXT,
  created_at TEXT NOT NULL,
  UNIQUE(entity_type, entity_id, media_type)
);

CREATE TABLE IF NOT EXISTS sources (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  base_url TEXT,
  license_note TEXT,
  enabled INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS sync_state (
  source_name TEXT NOT NULL,
  state_key TEXT NOT NULL,
  state_value TEXT,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(source_name, state_key)
);

CREATE TABLE IF NOT EXISTS sync_runs (
  id INTEGER PRIMARY KEY,
  mode TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  status TEXT NOT NULL,
  inserted_matches INTEGER NOT NULL DEFAULT 0,
  updated_matches INTEGER NOT NULL DEFAULT 0,
  inserted_teams INTEGER NOT NULL DEFAULT 0,
  inserted_players INTEGER NOT NULL DEFAULT 0,
  downloaded_media INTEGER NOT NULL DEFAULT 0,
  skipped_duplicates INTEGER NOT NULL DEFAULT 0,
  errors INTEGER NOT NULL DEFAULT 0,
  note TEXT
);

CREATE INDEX IF NOT EXISTS idx_matches_date ON matches(match_date);
CREATE INDEX IF NOT EXISTS idx_matches_teams ON matches(home_team_id, away_team_id);
CREATE INDEX IF NOT EXISTS idx_players_name ON players(full_name);
CREATE INDEX IF NOT EXISTS idx_teams_name ON teams(name);
CREATE INDEX IF NOT EXISTS idx_events_match ON match_events(match_id);
"""


class Archive:
    def __init__(self, db_path: Path = DB_PATH):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        TEAM_LOGO_DIR.mkdir(parents=True, exist_ok=True)
        PLAYER_PHOTO_DIR.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.execute("INSERT OR IGNORE INTO sports(name) VALUES('Football')")
        self.conn.execute("INSERT OR IGNORE INTO sources(name,base_url,license_note) VALUES(?,?,?)",
                          ("international_results", "https://github.com/martj42/international_results", "CC0-1.0"))
        self.conn.execute("INSERT OR IGNORE INTO sources(name,base_url,license_note) VALUES(?,?,?)",
                          ("TheSportsDB", "https://www.thesportsdb.com", "Provider terms apply"))
        self.conn.commit()

    def close(self) -> None:
        self.conn.commit()
        self.conn.close()

    def sport_id(self, name: str = "Football") -> int:
        row = self.conn.execute("SELECT id FROM sports WHERE name=?", (name,)).fetchone()
        return int(row[0])

    def country_id(self, name: Optional[str]) -> Optional[int]:
        if not name:
            return None
        name = name.strip()
        if not name:
            return None
        self.conn.execute("INSERT OR IGNORE INTO countries(name) VALUES(?)", (name,))
        return int(self.conn.execute("SELECT id FROM countries WHERE name=?", (name,)).fetchone()[0])

    def competition_id(self, name: Optional[str], country: Optional[str] = None) -> Optional[int]:
        if not name:
            return None
        sid = self.sport_id()
        cid = self.country_id(country)
        self.conn.execute(
            "INSERT OR IGNORE INTO competitions(sport_id,name,country_id) VALUES(?,?,?)",
            (sid, name.strip(), cid),
        )
        row = self.conn.execute(
            "SELECT id FROM competitions WHERE sport_id=? AND name=? AND country_id IS ?",
            (sid, name.strip(), cid),
        ).fetchone()
        return int(row[0])

    def team_id(self, name: str, country: Optional[str] = None) -> tuple[int, bool]:
        sid = self.sport_id()
        cid = self.country_id(country)
        ts = now_iso()
        row = self.conn.execute(
            "SELECT id FROM teams WHERE sport_id=? AND name=? AND country_id IS ?",
            (sid, name.strip(), cid),
        ).fetchone()
        if row:
            return int(row[0]), False
        cur = self.conn.execute(
            "INSERT INTO teams(sport_id,name,country_id,created_at,updated_at) VALUES(?,?,?,?,?)",
            (sid, name.strip(), cid, ts, ts),
        )
        return int(cur.lastrowid), True

    def player_id(self, name: str, birth: Optional[str] = None, nationality: Optional[str] = None) -> tuple[int, bool]:
        sid = self.sport_id()
        name = name.strip()
        birth = birth or None
        row = self.conn.execute(
            "SELECT id FROM players WHERE sport_id=? AND full_name=? AND date_of_birth IS ?",
            (sid, name, birth),
        ).fetchone()
        if row:
            return int(row[0]), False
        ts = now_iso()
        cur = self.conn.execute(
            "INSERT INTO players(sport_id,full_name,date_of_birth,nationality,created_at,updated_at) VALUES(?,?,?,?,?,?)",
            (sid, name, birth, nationality, ts, ts),
        )
        return int(cur.lastrowid), True

    def upsert_match(self, row: dict[str, str]) -> tuple[int, str, int]:
        home = (row.get("home_team") or "").strip()
        away = (row.get("away_team") or "").strip()
        date = (row.get("date") or "").strip()
        if not home or not away or not date:
            raise ValueError("match misses date/home/away")
        country = (row.get("country") or "").strip() or None
        tournament = (row.get("tournament") or "International").strip()
        home_id, home_new = self.team_id(home)
        away_id, away_new = self.team_id(away)
        comp_id = self.competition_id(tournament, country)
        sid = self.sport_id()
        score_h = to_int(row.get("home_score"))
        score_a = to_int(row.get("away_score"))
        neutral = 1 if str(row.get("neutral", "")).lower() in {"true", "1", "yes"} else 0
        cid = self.country_id(country)
        existing = self.conn.execute(
            "SELECT id,home_score,away_score,venue,city,neutral FROM matches WHERE sport_id=? AND match_date=? AND home_team_id=? AND away_team_id=? AND competition_id IS ?",
            (sid, date, home_id, away_id, comp_id),
        ).fetchone()
        ts = now_iso()
        if existing:
            changed = (existing["home_score"] != score_h or existing["away_score"] != score_a or
                       existing["venue"] != (row.get("venue") or None) or existing["city"] != (row.get("city") or None) or
                       existing["neutral"] != neutral)
            if changed:
                self.conn.execute(
                    "UPDATE matches SET home_score=?,away_score=?,venue=?,city=?,country_id=?,neutral=?,updated_at=? WHERE id=?",
                    (score_h, score_a, row.get("venue") or None, row.get("city") or None, cid, neutral, ts, existing["id"]),
                )
                return int(existing["id"]), "updated", int(home_new) + int(away_new)
            return int(existing["id"]), "duplicate", int(home_new) + int(away_new)
        cur = self.conn.execute(
            """INSERT INTO matches(sport_id,competition_id,match_date,home_team_id,away_team_id,home_score,away_score,status,venue,city,country_id,neutral,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (sid, comp_id, date, home_id, away_id, score_h, score_a, "finished", row.get("venue") or None,
             row.get("city") or None, cid, neutral, ts, ts),
        )
        return int(cur.lastrowid), "inserted", int(home_new) + int(away_new)

    def set_state(self, source: str, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO sync_state(source_name,state_key,state_value,updated_at) VALUES(?,?,?,?) ON CONFLICT(source_name,state_key) DO UPDATE SET state_value=excluded.state_value,updated_at=excluded.updated_at",
            (source, key, value, now_iso()),
        )

    def get_state(self, source: str, key: str) -> Optional[str]:
        row = self.conn.execute("SELECT state_value FROM sync_state WHERE source_name=? AND state_key=?", (source, key)).fetchone()
        return str(row[0]) if row else None


def to_int(value: Any) -> Optional[int]:
    try:
        if value is None or str(value).strip() == "":
            return None
        return int(float(str(value)))
    except (ValueError, TypeError):
        return None


def request_bytes(url: str, timeout: int = 30, headers: Optional[dict[str, str]] = None) -> tuple[bytes, dict[str, str], int]:
    request_headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "identity"}
    if headers:
        request_headers.update(headers)
    req = urllib.request.Request(url, headers=request_headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read(), {k.lower(): v for k, v in resp.headers.items()}, int(resp.status)
    except urllib.error.HTTPError as exc:
        if exc.code == 304:
            return b"", {k.lower(): v for k, v in exc.headers.items()}, 304
        raise


def cached_csv(archive: Archive, source_name: str, url: str, filename: str, force: bool = False) -> tuple[Path, bool]:
    path = CACHE_DIR / filename
    headers: dict[str, str] = {}
    if not force:
        etag = archive.get_state(source_name, f"etag:{url}")
        modified = archive.get_state(source_name, f"modified:{url}")
        if etag:
            headers["If-None-Match"] = etag
        if modified:
            headers["If-Modified-Since"] = modified
    log(f"SOURCE CHECK | {source_name} | {url}")
    try:
        data, response_headers, status = request_bytes(url, headers=headers)
        if status == 304 and path.exists():
            log(f"SOURCE UNCHANGED | cache reused | {filename}")
            return path, False
        if not data:
            if path.exists():
                return path, False
            raise RuntimeError("empty source response and no cache")
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        if response_headers.get("etag"):
            archive.set_state(source_name, f"etag:{url}", response_headers["etag"])
        if response_headers.get("last-modified"):
            archive.set_state(source_name, f"modified:{url}", response_headers["last-modified"])
        archive.set_state(source_name, f"sha256:{url}", hashlib.sha256(data).hexdigest())
        log(f"SOURCE DOWNLOADED | {filename} | {human_bytes(len(data))}")
        return path, True
    except Exception:
        if path.exists():
            log(f"NETWORK FAILED | using existing local cache: {filename}", "WARN")
            return path, False
        raise


def iter_csv(path: Path) -> Iterable[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        yield from csv.DictReader(f)


def begin_run(a: Archive, mode: str) -> int:
    cur = a.conn.execute("INSERT INTO sync_runs(mode,started_at,status) VALUES(?,?,?)", (mode, now_iso(), "running"))
    a.conn.commit()
    return int(cur.lastrowid)


def finish_run(a: Archive, run_id: int, stats: dict[str, int], status: str = "completed", note: str = "") -> None:
    a.conn.execute(
        """UPDATE sync_runs SET finished_at=?,status=?,inserted_matches=?,updated_matches=?,inserted_teams=?,inserted_players=?,downloaded_media=?,skipped_duplicates=?,errors=?,note=? WHERE id=?""",
        (now_iso(), status, stats.get("inserted", 0), stats.get("updated", 0), stats.get("teams", 0),
         stats.get("players", 0), stats.get("media", 0), stats.get("duplicate", 0), stats.get("errors", 0), note, run_id),
    )
    a.conn.commit()


def sync_matches(a: Archive, current_year_only: bool, force_download: bool = False) -> dict[str, int]:
    path, changed = cached_csv(a, "international_results", HIST_RESULTS, "international_results.csv", force_download)
    year = dt.date.today().year
    stats = {"inserted": 0, "updated": 0, "duplicate": 0, "teams": 0, "players": 0, "media": 0, "errors": 0}
    processed = 0
    log(f"MATCH IMPORT START | mode={'CURRENT-YEAR' if current_year_only else 'FULL-HISTORY'} | source_changed={changed}")
    if current_year_only and not changed:
        log("FAST EXIT | source has not changed; no rows need reprocessing")
        return stats
    for row in iter_csv(path):
        date = row.get("date", "")
        if current_year_only and not date.startswith(str(year)):
            continue
        processed += 1
        try:
            match_id, action, new_teams = a.upsert_match(row)
            stats[action] += 1
            stats["teams"] += new_teams
            score = f"{row.get('home_score','?')}-{row.get('away_score','?')}"
            log(f"MATCH {action.upper():9} | {date} | {row.get('home_team')} {score} {row.get('away_team')} | id={match_id}")
        except Exception as exc:
            stats["errors"] += 1
            log(f"MATCH ERROR | row={processed} | {exc}", "ERROR")
        if processed % 500 == 0:
            a.conn.commit()
            db_size = DB_PATH.stat().st_size if DB_PATH.exists() else 0
            log(f"PROGRESS | rows={processed:,} | inserted={stats['inserted']:,} | updated={stats['updated']:,} | duplicate={stats['duplicate']:,} | db={human_bytes(db_size)}")
    a.conn.commit()
    a.set_state("international_results", "last_match_sync", now_iso())
    a.set_state("international_results", "last_match_year", str(year))
    a.conn.commit()
    return stats


def sync_goals(a: Archive, current_year_only: bool, force_download: bool = False) -> dict[str, int]:
    path, changed = cached_csv(a, "international_results", HIST_GOALS, "goalscorers.csv", force_download)
    year = dt.date.today().year
    stats = {"players": 0, "events": 0, "duplicate": 0, "errors": 0}
    if current_year_only and not changed:
        log("GOALS FAST EXIT | source unchanged")
        return stats
    for i, row in enumerate(iter_csv(path), 1):
        date = row.get("date", "")
        if current_year_only and not date.startswith(str(year)):
            continue
        try:
            home = (row.get("home_team") or "").strip()
            away = (row.get("away_team") or "").strip()
            scorer = (row.get("scorer") or "").strip()
            team = (row.get("team") or "").strip()
            if not scorer:
                continue
            match = a.conn.execute(
                """SELECT m.id FROM matches m JOIN teams h ON h.id=m.home_team_id JOIN teams v ON v.id=m.away_team_id
                   WHERE m.match_date=? AND h.name=? AND v.name=? ORDER BY m.id LIMIT 1""",
                (date, home, away),
            ).fetchone()
            if not match:
                continue
            player_id, is_new = a.player_id(scorer)
            team_row = a.conn.execute("SELECT id FROM teams WHERE name=? ORDER BY id LIMIT 1", (team,)).fetchone()
            team_id = int(team_row[0]) if team_row else None
            minute = to_int(row.get("minute"))
            detail = "own_goal" if str(row.get("own_goal", "")).lower() == "true" else ("penalty" if str(row.get("penalty", "")).lower() == "true" else None)
            cur = a.conn.execute(
                "INSERT OR IGNORE INTO match_events(match_id,team_id,player_id,event_type,minute,detail) VALUES(?,?,?,?,?,?)",
                (int(match[0]), team_id, player_id, "goal", minute, detail),
            )
            if cur.rowcount:
                stats["events"] += 1
                stats["players"] += int(is_new)
                log(f"GOAL INSERTED | {date} | {scorer} | minute={minute or '?'} | {home} vs {away}")
            else:
                stats["duplicate"] += 1
        except Exception as exc:
            stats["errors"] += 1
            log(f"GOAL ERROR | row={i} | {exc}", "ERROR")
        if i % 1000 == 0:
            a.conn.commit()
    a.conn.commit()
    return stats


def thesportsdb_json(endpoint: str, config: dict[str, Any]) -> dict[str, Any]:
    key = str(config.get("thesportsdb_api_key") or "3")
    url = f"https://www.thesportsdb.com/api/v1/json/{urllib.parse.quote(key)}/{endpoint}"
    data, _, _ = request_bytes(url, timeout=int(config.get("request_timeout_seconds", 30)))
    return json.loads(data.decode("utf-8"))


def download_media(a: Archive, entity_type: str, entity_id: int, media_type: str, url: str, limit: int, destination: Path) -> bool:
    if not url or not url.lower().startswith(("http://", "https://")):
        return False
    existing = a.conn.execute("SELECT relative_path FROM media WHERE entity_type=? AND entity_id=? AND media_type=?", (entity_type, entity_id, media_type)).fetchone()
    if existing and (ROOT / existing[0]).exists():
        return False
    try:
        data, headers, _ = request_bytes(url)
        mime = (headers.get("content-type") or mimetypes.guess_type(url)[0] or "").split(";")[0].lower()
        if mime not in ALLOWED_IMAGE_MIME:
            log(f"MEDIA SKIPPED | unsupported MIME {mime} | {url}", "WARN")
            return False
        if len(data) > limit:
            log(f"MEDIA SKIPPED | {human_bytes(len(data))} exceeds {human_bytes(limit)} | {url}", "WARN")
            return False
        digest = hashlib.sha256(data).hexdigest()
        dup = a.conn.execute("SELECT relative_path FROM media WHERE sha256=?", (digest,)).fetchone()
        if dup:
            relative = str(dup[0])
        else:
            destination.mkdir(parents=True, exist_ok=True)
            file_path = destination / f"{digest}{ALLOWED_IMAGE_MIME[mime]}"
            file_path.write_bytes(data)
            relative = file_path.relative_to(ROOT).as_posix()
        a.conn.execute(
            """INSERT INTO media(entity_type,entity_id,media_type,relative_path,mime_type,byte_size,sha256,source_url,created_at)
               VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(entity_type,entity_id,media_type) DO UPDATE SET relative_path=excluded.relative_path,mime_type=excluded.mime_type,byte_size=excluded.byte_size,sha256=excluded.sha256,source_url=excluded.source_url""",
            (entity_type, entity_id, media_type, relative, mime, len(data), digest, url, now_iso()),
        )
        log(f"MEDIA SAVED | {entity_type}={entity_id} | {media_type} | {human_bytes(len(data))} | offline={relative}")
        return True
    except Exception as exc:
        log(f"MEDIA ERROR | {entity_type}={entity_id} | {exc}", "WARN")
        return False


def enrich_new_entities(a: Archive, config: dict[str, Any], limit: int = 50) -> dict[str, int]:
    stats = {"teams": 0, "players": 0, "media": 0, "errors": 0}
    rows = a.conn.execute(
        "SELECT id,name FROM teams WHERE source_key IS NULL ORDER BY updated_at DESC,id DESC LIMIT ?", (limit,)
    ).fetchall()
    for row in rows:
        try:
            query = urllib.parse.urlencode({"t": row["name"]})
            payload = thesportsdb_json(f"searchteams.php?{query}", config)
            items = payload.get("teams") or []
            if not items:
                a.conn.execute("UPDATE teams SET source_key='not-found',updated_at=? WHERE id=?", (now_iso(), row["id"]))
                continue
            item = items[0]
            formed = to_int(item.get("intFormedYear"))
            a.conn.execute(
                """UPDATE teams SET short_name=?,founded_year=?,city=?,stadium=?,gender=?,source_key=?,updated_at=? WHERE id=?""",
                (item.get("strTeamShort"), formed, item.get("strStadiumLocation"), item.get("strStadium"), item.get("strGender"), item.get("idTeam"), now_iso(), row["id"]),
            )
            stats["teams"] += 1
            log(f"TEAM ENRICHED | {row['name']} | founded={formed or '?'} | stadium={item.get('strStadium') or '?'}")
            if config.get("download_team_logos", True) and item.get("strBadge"):
                max_bytes = int(config.get("media_limits", {}).get("team_logo_bytes", MAX_TEAM_LOGO_BYTES))
                stats["media"] += int(download_media(a, "team", int(row["id"]), "logo", item["strBadge"], max_bytes, TEAM_LOGO_DIR))
        except Exception as exc:
            stats["errors"] += 1
            log(f"TEAM ENRICH ERROR | {row['name']} | {exc}", "WARN")
        time.sleep(0.20)
    a.conn.commit()
    return stats


def database_report(a: Archive) -> None:
    tables = ["sports", "countries", "competitions", "teams", "players", "team_memberships", "matches", "match_events", "match_stats", "media", "sync_runs"]
    log("DATABASE REPORT")
    for table in tables:
        count = a.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        log(f"  {table:18} {count:,}")
    db_size = DB_PATH.stat().st_size if DB_PATH.exists() else 0
    media_size = sum(p.stat().st_size for p in MEDIA_DIR.rglob("*") if p.is_file()) if MEDIA_DIR.exists() else 0
    integrity = a.conn.execute("PRAGMA integrity_check").fetchone()[0]
    fk = a.conn.execute("PRAGMA foreign_key_check").fetchall()
    log(f"  sqlite_size        {human_bytes(db_size)}")
    log(f"  media_size         {human_bytes(media_size)}")
    log(f"  integrity_check    {integrity}")
    log(f"  foreign_key_errors {len(fk)}")


def compact(a: Archive) -> None:
    log("COMPACTION START | removing unused cache and optimizing SQLite")
    for file in CACHE_DIR.glob("*.tmp"):
        file.unlink(missing_ok=True)
    a.conn.execute("PRAGMA optimize")
    a.conn.commit()
    a.conn.execute("VACUUM")
    log("COMPACTION COMPLETE")


def reset_database() -> None:
    if DB_PATH.exists():
        stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = DATA_DIR / f"sports_archive_before_reset_{stamp}.sqlite3"
        DB_PATH.replace(backup)
        log(f"OLD DATABASE MOVED TO BACKUP | {backup.name}")
    for suffix in ("-wal", "-shm"):
        Path(str(DB_PATH) + suffix).unlink(missing_ok=True)
    log("EMPTY DATABASE WILL BE CREATED ON NEXT START")


def run_sync(mode: str, enrich_limit: int, force: bool) -> int:
    config = load_config()
    a = Archive()
    run_id = begin_run(a, mode)
    combined = {"inserted": 0, "updated": 0, "duplicate": 0, "teams": 0, "players": 0, "media": 0, "errors": 0}
    try:
        log("=" * 76)
        log(f"Sports Archive Harvester v{APP_VERSION} | mode={mode}")
        log("Policy: essential text + team logos + player photos only; no raw payload storage")
        current = mode == "quick"
        match_stats = sync_matches(a, current_year_only=current, force_download=force)
        for key in combined:
            combined[key] += match_stats.get(key, 0)
        goal_stats = sync_goals(a, current_year_only=current, force_download=force)
        combined["players"] += goal_stats.get("players", 0)
        combined["duplicate"] += goal_stats.get("duplicate", 0)
        combined["errors"] += goal_stats.get("errors", 0)
        if enrich_limit > 0 and config.get("enrich_new_teams", True):
            enrich = enrich_new_entities(a, config, enrich_limit)
            combined["teams"] += enrich.get("teams", 0)
            combined["media"] += enrich.get("media", 0)
            combined["errors"] += enrich.get("errors", 0)
        finish_run(a, run_id, combined)
        database_report(a)
        log(f"SYNC COMPLETE | new_matches={combined['inserted']} | updated={combined['updated']} | duplicates={combined['duplicate']} | new_players={combined['players']} | media={combined['media']} | errors={combined['errors']}")
        return 0
    except KeyboardInterrupt:
        combined["errors"] += 1
        finish_run(a, run_id, combined, "cancelled", "cancelled by user")
        log("SYNC CANCELLED BY USER", "WARN")
        return 130
    except Exception as exc:
        combined["errors"] += 1
        finish_run(a, run_id, combined, "failed", str(exc))
        log(f"SYNC FAILED | {exc}", "ERROR")
        return 1
    finally:
        a.close()


def menu() -> int:
    while True:
        print("\n" + "=" * 72)
        print(" Sports Archive Harvester v1.2.0 - Offline-first control panel")
        print("=" * 72)
        print("1) Quick update: current-year new matches only")
        print("2) Full historical collection from 1872")
        print("3) Database report and integrity check")
        print("4) Compact database and clean temporary files")
        print("5) Reset to a new empty database (old DB is backed up)")
        print("0) Exit")
        choice = input("Choose: ").strip()
        if choice == "1":
            run_sync("quick", 50, False)
        elif choice == "2":
            run_sync("full", 100, False)
        elif choice == "3":
            a = Archive(); database_report(a); a.close()
        elif choice == "4":
            a = Archive(); compact(a); a.close()
        elif choice == "5":
            confirm = input("Type RESET to confirm: ").strip()
            if confirm == "RESET":
                reset_database()
        elif choice == "0":
            return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Offline-first SQLite sports archive")
    p.add_argument("command", nargs="?", choices=["menu", "quick", "full", "report", "compact", "reset"], default="menu")
    p.add_argument("--enrich-limit", type=int, default=50, help="Maximum newly discovered teams to enrich this run")
    p.add_argument("--force-download", action="store_true", help="Ignore ETag/Last-Modified and redownload source")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "menu":
        return menu()
    if args.command in {"quick", "full"}:
        return run_sync(args.command, max(0, args.enrich_limit), args.force_download)
    if args.command == "reset":
        reset_database(); return 0
    a = Archive()
    try:
        if args.command == "report": database_report(a)
        elif args.command == "compact": compact(a)
    finally:
        a.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
