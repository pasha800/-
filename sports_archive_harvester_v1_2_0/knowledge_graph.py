#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sports Archive Harvester v1.4.0 knowledge-graph maintenance engine.

Goals:
- connect competitions, seasons, teams, players, venues, matches and sources;
- retain source provenance without raw payloads;
- prevent duplicate entities and duplicate facts;
- calculate quality/completeness scores;
- merge only high-confidence duplicates automatically;
- queue ambiguous candidates for manual review;
- delete useless empty facts while preserving meaningful history.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Iterable

import sports_harvester_external_media as app

VERSION = "1.4.0"

GRAPH_SCHEMA = r"""
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS venues (
  id INTEGER PRIMARY KEY,
  canonical_name TEXT NOT NULL,
  normalized_name TEXT NOT NULL,
  city TEXT,
  country_id INTEGER REFERENCES countries(id),
  capacity INTEGER,
  latitude REAL,
  longitude REAL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(normalized_name,city,country_id)
);

CREATE TABLE IF NOT EXISTS team_venues (
  team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  venue_id INTEGER NOT NULL REFERENCES venues(id) ON DELETE CASCADE,
  start_date TEXT,
  end_date TEXT,
  is_primary INTEGER NOT NULL DEFAULT 1,
  source_confidence REAL NOT NULL DEFAULT 0.5,
  PRIMARY KEY(team_id,venue_id,start_date)
);

CREATE TABLE IF NOT EXISTS competition_seasons (
  competition_id INTEGER NOT NULL REFERENCES competitions(id) ON DELETE CASCADE,
  season_id INTEGER NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
  parent_competition_id INTEGER REFERENCES competitions(id),
  level INTEGER,
  group_name TEXT,
  PRIMARY KEY(competition_id,season_id)
);

CREATE TABLE IF NOT EXISTS season_teams (
  season_id INTEGER NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
  team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  joined_at TEXT,
  left_at TEXT,
  final_rank INTEGER,
  points INTEGER,
  promoted INTEGER,
  relegated INTEGER,
  PRIMARY KEY(season_id,team_id)
);

CREATE TABLE IF NOT EXISTS match_lineups (
  match_id INTEGER NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
  team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  player_id INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
  is_starting INTEGER NOT NULL DEFAULT 0,
  shirt_number INTEGER,
  position TEXT,
  formation_slot TEXT,
  captain INTEGER NOT NULL DEFAULT 0,
  minute_on INTEGER,
  minute_off INTEGER,
  PRIMARY KEY(match_id,team_id,player_id)
);

CREATE TABLE IF NOT EXISTS player_careers (
  player_id INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
  team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  start_date TEXT,
  end_date TEXT,
  shirt_number INTEGER,
  position TEXT,
  appearances INTEGER,
  starts INTEGER,
  minutes INTEGER,
  goals INTEGER,
  assists INTEGER,
  yellow_cards INTEGER,
  red_cards INTEGER,
  is_current INTEGER NOT NULL DEFAULT 0,
  source_confidence REAL NOT NULL DEFAULT 0.5,
  PRIMARY KEY(player_id,team_id,start_date)
);

CREATE TABLE IF NOT EXISTS entity_aliases (
  id INTEGER PRIMARY KEY,
  entity_type TEXT NOT NULL CHECK(entity_type IN ('competition','season','team','player','venue','match')),
  entity_id INTEGER NOT NULL,
  alias TEXT NOT NULL,
  normalized_alias TEXT NOT NULL,
  language_code TEXT,
  alias_type TEXT NOT NULL DEFAULT 'alternate',
  source_id INTEGER REFERENCES sources(id),
  UNIQUE(entity_type,normalized_alias,language_code,entity_id)
);

CREATE INDEX IF NOT EXISTS idx_alias_lookup
ON entity_aliases(entity_type,normalized_alias);

CREATE TABLE IF NOT EXISTS source_records (
  id INTEGER PRIMARY KEY,
  source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  entity_type TEXT NOT NULL CHECK(entity_type IN ('competition','season','team','player','venue','match','event','lineup','standing')),
  entity_id INTEGER NOT NULL,
  external_id TEXT NOT NULL,
  source_url TEXT,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  content_hash TEXT,
  is_active INTEGER NOT NULL DEFAULT 1,
  UNIQUE(source_id,entity_type,external_id)
);

CREATE INDEX IF NOT EXISTS idx_source_records_entity
ON source_records(entity_type,entity_id);

CREATE TABLE IF NOT EXISTS field_provenance (
  entity_type TEXT NOT NULL,
  entity_id INTEGER NOT NULL,
  field_name TEXT NOT NULL,
  source_id INTEGER NOT NULL REFERENCES sources(id),
  source_record_id INTEGER REFERENCES source_records(id) ON DELETE CASCADE,
  value_hash TEXT NOT NULL,
  confidence REAL NOT NULL DEFAULT 0.5,
  observed_at TEXT NOT NULL,
  PRIMARY KEY(entity_type,entity_id,field_name,source_id,value_hash)
);

CREATE TABLE IF NOT EXISTS entity_quality (
  entity_type TEXT NOT NULL,
  entity_id INTEGER NOT NULL,
  completeness_score REAL NOT NULL,
  confidence_score REAL NOT NULL,
  source_count INTEGER NOT NULL,
  warning_count INTEGER NOT NULL,
  last_calculated_at TEXT NOT NULL,
  PRIMARY KEY(entity_type,entity_id)
);

CREATE TABLE IF NOT EXISTS merge_candidates (
  id INTEGER PRIMARY KEY,
  entity_type TEXT NOT NULL CHECK(entity_type IN ('competition','team','player','venue','match')),
  left_id INTEGER NOT NULL,
  right_id INTEGER NOT NULL,
  similarity_score REAL NOT NULL,
  evidence_json TEXT NOT NULL,
  decision TEXT NOT NULL DEFAULT 'pending' CHECK(decision IN ('pending','merged','rejected','ignored')),
  created_at TEXT NOT NULL,
  reviewed_at TEXT,
  UNIQUE(entity_type,left_id,right_id)
);

CREATE TABLE IF NOT EXISTS graph_edges (
  subject_type TEXT NOT NULL,
  subject_id INTEGER NOT NULL,
  predicate TEXT NOT NULL,
  object_type TEXT NOT NULL,
  object_id INTEGER NOT NULL,
  valid_from TEXT,
  valid_to TEXT,
  confidence REAL NOT NULL DEFAULT 0.5,
  source_count INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY(subject_type,subject_id,predicate,object_type,object_id,valid_from)
);

CREATE INDEX IF NOT EXISTS idx_graph_edges_subject
ON graph_edges(subject_type,subject_id,predicate);
CREATE INDEX IF NOT EXISTS idx_graph_edges_object
ON graph_edges(object_type,object_id,predicate);

CREATE TABLE IF NOT EXISTS maintenance_runs (
  id INTEGER PRIMARY KEY,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  mode TEXT NOT NULL,
  aliases_added INTEGER NOT NULL DEFAULT 0,
  edges_rebuilt INTEGER NOT NULL DEFAULT 0,
  candidates_added INTEGER NOT NULL DEFAULT 0,
  entities_merged INTEGER NOT NULL DEFAULT 0,
  useless_rows_removed INTEGER NOT NULL DEFAULT 0,
  errors INTEGER NOT NULL DEFAULT 0,
  note TEXT
);
"""


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold()
    replacements = {
        "&": " and ", "fc": " ", "cf": " ", "afc": " ", "sc": " ",
        "club": " ", "football": " ", "fussball": " ", "soccer": " ",
    }
    text = re.sub(r"\b(?:fc|cf|afc|sc|fk|ac|club|football|fussball|soccer)\b", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def value_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(GRAPH_SCHEMA)
    columns = {r[1] for r in conn.execute("PRAGMA table_info(matches)")}
    if "venue_id" not in columns:
        conn.execute("ALTER TABLE matches ADD COLUMN venue_id INTEGER REFERENCES venues(id)")
    if "season_id" not in columns:
        conn.execute("ALTER TABLE matches ADD COLUMN season_id INTEGER REFERENCES seasons(id)")
    conn.commit()


def safe_source_id(conn: sqlite3.Connection, name: str) -> int:
    conn.execute(
        "INSERT OR IGNORE INTO sources(name,base_url,license_note) VALUES(?,?,?)",
        (name, None, "Imported from legacy normalized record"),
    )
    return int(conn.execute("SELECT id FROM sources WHERE name=?", (name,)).fetchone()[0])


def seed_aliases(conn: sqlite3.Connection) -> int:
    added = 0
    source_id = safe_source_id(conn, "Legacy normalized database")
    specs = [
        ("team", "teams", "id", "name"),
        ("player", "players", "id", "full_name"),
        ("competition", "competitions", "id", "name"),
        ("season", "seasons", "id", "name"),
        ("venue", "venues", "id", "canonical_name"),
    ]
    for entity_type, table, id_col, name_col in specs:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        if not exists:
            continue
        rows = conn.execute(f'SELECT "{id_col}","{name_col}" FROM "{table}" WHERE "{name_col}" IS NOT NULL').fetchall()
        for entity_id, name in rows:
            normalized = normalize_text(name)
            if not normalized:
                continue
            cur = conn.execute(
                """INSERT OR IGNORE INTO entity_aliases
                   (entity_type,entity_id,alias,normalized_alias,language_code,alias_type,source_id)
                   VALUES(?,?,?,?,NULL,'canonical',?)""",
                (entity_type, int(entity_id), str(name), normalized, source_id),
            )
            added += int(bool(cur.rowcount))
    return added


def link_legacy_venues(conn: sqlite3.Connection) -> int:
    linked = 0
    rows = conn.execute(
        """SELECT id,venue,city,country_id FROM matches
           WHERE venue IS NOT NULL AND trim(venue)<>'' AND venue_id IS NULL"""
    ).fetchall()
    for match_id, venue_name, city, country_id in rows:
        normalized = normalize_text(venue_name)
        if not normalized:
            continue
        stamp = now_iso()
        conn.execute(
            """INSERT OR IGNORE INTO venues
               (canonical_name,normalized_name,city,country_id,created_at,updated_at)
               VALUES(?,?,?,?,?,?)""",
            (str(venue_name).strip(), normalized, city, country_id, stamp, stamp),
        )
        row = conn.execute(
            """SELECT id FROM venues WHERE normalized_name=? AND city IS ? AND country_id IS ?""",
            (normalized, city, country_id),
        ).fetchone()
        if row:
            conn.execute("UPDATE matches SET venue_id=? WHERE id=?", (int(row[0]), int(match_id)))
            linked += 1
    return linked


def rebuild_edges(conn: sqlite3.Connection) -> int:
    conn.execute("DELETE FROM graph_edges")
    count = 0

    def insert_many(sql: str) -> None:
        nonlocal count
        before = conn.total_changes
        conn.execute(sql)
        count += conn.total_changes - before

    insert_many("""
        INSERT OR IGNORE INTO graph_edges
        (subject_type,subject_id,predicate,object_type,object_id,valid_from,valid_to,confidence,source_count)
        SELECT 'match',id,'home_team','team',home_team_id,match_date,match_date,1.0,1 FROM matches
    """)
    insert_many("""
        INSERT OR IGNORE INTO graph_edges
        SELECT 'match',id,'away_team','team',away_team_id,match_date,match_date,1.0,1 FROM matches
    """)
    insert_many("""
        INSERT OR IGNORE INTO graph_edges
        SELECT 'match',id,'competition','competition',competition_id,match_date,match_date,0.95,1
        FROM matches WHERE competition_id IS NOT NULL
    """)
    insert_many("""
        INSERT OR IGNORE INTO graph_edges
        SELECT 'match',id,'season','season',season_id,match_date,match_date,0.95,1
        FROM matches WHERE season_id IS NOT NULL
    """)
    insert_many("""
        INSERT OR IGNORE INTO graph_edges
        SELECT 'match',id,'venue','venue',venue_id,match_date,match_date,0.9,1
        FROM matches WHERE venue_id IS NOT NULL
    """)
    insert_many("""
        INSERT OR IGNORE INTO graph_edges
        SELECT 'player',player_id,'member_of','team',team_id,start_date,end_date,
               CASE WHEN is_current=1 THEN 0.9 ELSE 0.75 END,1
        FROM team_memberships
    """)
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='season_teams'").fetchone():
        insert_many("""
            INSERT OR IGNORE INTO graph_edges
            SELECT 'team',team_id,'participated_in','season',season_id,joined_at,left_at,0.9,1
            FROM season_teams
        """)
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='match_events'").fetchone():
        insert_many("""
            INSERT OR IGNORE INTO graph_edges
            SELECT 'event',id,'occurred_in','match',match_id,NULL,NULL,1.0,1 FROM match_events
        """)
        insert_many("""
            INSERT OR IGNORE INTO graph_edges
            SELECT 'event',id,'involved_player','player',player_id,NULL,NULL,0.95,1
            FROM match_events WHERE player_id IS NOT NULL
        """)
    return count


@dataclass
class Candidate:
    left_id: int
    right_id: int
    score: float
    evidence: dict[str, Any]


def similarity(a: str, b: str) -> float:
    na, nb = normalize_text(a), normalize_text(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    return SequenceMatcher(None, na, nb).ratio()


def team_candidates(conn: sqlite3.Connection) -> Iterable[Candidate]:
    rows = conn.execute(
        """SELECT id,name,country_id,founded_year,city FROM teams
           WHERE name IS NOT NULL ORDER BY country_id,id"""
    ).fetchall()
    buckets: dict[tuple[Any, str], list[sqlite3.Row]] = {}
    for row in rows:
        normalized = normalize_text(row[1])
        key = (row[2], normalized[:4])
        buckets.setdefault(key, []).append(row)
    for bucket in buckets.values():
        for i, left in enumerate(bucket):
            for right in bucket[i + 1:]:
                score = similarity(left[1], right[1])
                evidence: dict[str, Any] = {"name_similarity": round(score, 4)}
                if left[2] == right[2]:
                    score += 0.04
                    evidence["same_country"] = True
                if left[3] and right[3] and left[3] == right[3]:
                    score += 0.03
                    evidence["same_founded_year"] = True
                if left[4] and right[4] and normalize_text(left[4]) == normalize_text(right[4]):
                    score += 0.03
                    evidence["same_city"] = True
                score = min(score, 1.0)
                if score >= 0.84:
                    yield Candidate(int(left[0]), int(right[0]), score, evidence)


def player_candidates(conn: sqlite3.Connection) -> Iterable[Candidate]:
    rows = conn.execute(
        """SELECT id,full_name,date_of_birth,nationality FROM players
           WHERE full_name IS NOT NULL ORDER BY date_of_birth,nationality,id"""
    ).fetchall()
    buckets: dict[tuple[str, Any, Any], list[sqlite3.Row]] = {}
    for row in rows:
        normalized = normalize_text(row[1])
        key = (normalized[:5], row[2], row[3])
        buckets.setdefault(key, []).append(row)
    for bucket in buckets.values():
        for i, left in enumerate(bucket):
            for right in bucket[i + 1:]:
                score = similarity(left[1], right[1])
                evidence: dict[str, Any] = {"name_similarity": round(score, 4)}
                if left[2] and left[2] == right[2]:
                    score += 0.08
                    evidence["same_birth_date"] = True
                if left[3] and normalize_text(left[3]) == normalize_text(right[3]):
                    score += 0.04
                    evidence["same_nationality"] = True
                score = min(score, 1.0)
                if score >= 0.86:
                    yield Candidate(int(left[0]), int(right[0]), score, evidence)


def store_candidates(conn: sqlite3.Connection) -> int:
    added = 0
    for entity_type, generator in (("team", team_candidates(conn)), ("player", player_candidates(conn))):
        for item in generator:
            left_id, right_id = sorted((item.left_id, item.right_id))
            cur = conn.execute(
                """INSERT OR IGNORE INTO merge_candidates
                   (entity_type,left_id,right_id,similarity_score,evidence_json,created_at)
                   VALUES(?,?,?,?,?,?)""",
                (entity_type, left_id, right_id, item.score,
                 json.dumps(item.evidence, ensure_ascii=False, sort_keys=True), now_iso()),
            )
            added += int(bool(cur.rowcount))
    return added


def merge_team(conn: sqlite3.Connection, keep_id: int, drop_id: int) -> None:
    for table, column in [
        ("matches", "home_team_id"), ("matches", "away_team_id"),
        ("match_events", "team_id"), ("match_stats", "team_id"),
        ("team_memberships", "team_id"), ("team_media", "team_id"),
        ("season_teams", "team_id"), ("team_venues", "team_id"),
        ("player_careers", "team_id"), ("match_lineups", "team_id"),
    ]:
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
            try:
                conn.execute(f'UPDATE OR IGNORE "{table}" SET "{column}"=? WHERE "{column}"=?', (keep_id, drop_id))
                conn.execute(f'DELETE FROM "{table}" WHERE "{column}"=?', (drop_id,))
            except sqlite3.IntegrityError:
                pass
    conn.execute("UPDATE entity_aliases SET entity_id=? WHERE entity_type='team' AND entity_id=?", (keep_id, drop_id))
    conn.execute("UPDATE source_records SET entity_id=? WHERE entity_type='team' AND entity_id=?", (keep_id, drop_id))
    conn.execute("DELETE FROM teams WHERE id=?", (drop_id,))


def merge_player(conn: sqlite3.Connection, keep_id: int, drop_id: int) -> None:
    for table, column in [
        ("match_events", "player_id"), ("team_memberships", "player_id"),
        ("player_media", "player_id"), ("player_careers", "player_id"),
        ("match_lineups", "player_id"),
    ]:
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
            try:
                conn.execute(f'UPDATE OR IGNORE "{table}" SET "{column}"=? WHERE "{column}"=?', (keep_id, drop_id))
                conn.execute(f'DELETE FROM "{table}" WHERE "{column}"=?', (drop_id,))
            except sqlite3.IntegrityError:
                pass
    conn.execute("UPDATE entity_aliases SET entity_id=? WHERE entity_type='player' AND entity_id=?", (keep_id, drop_id))
    conn.execute("UPDATE source_records SET entity_id=? WHERE entity_type='player' AND entity_id=?", (keep_id, drop_id))
    conn.execute("DELETE FROM players WHERE id=?", (drop_id,))


def auto_merge(conn: sqlite3.Connection, threshold: float = 0.985) -> int:
    merged = 0
    rows = conn.execute(
        """SELECT id,entity_type,left_id,right_id,similarity_score,evidence_json
           FROM merge_candidates WHERE decision='pending' AND similarity_score>=?
           ORDER BY similarity_score DESC""",
        (threshold,),
    ).fetchall()
    for candidate_id, entity_type, left_id, right_id, score, evidence_json in rows:
        evidence = json.loads(evidence_json)
        safe = False
        if entity_type == "team":
            safe = bool(evidence.get("same_country")) and (
                evidence.get("same_founded_year") or evidence.get("same_city") or score >= 0.998
            )
        elif entity_type == "player":
            safe = bool(evidence.get("same_birth_date")) and (
                evidence.get("same_nationality") or score >= 0.998
            )
        if not safe:
            continue
        keep_id, drop_id = min(int(left_id), int(right_id)), max(int(left_id), int(right_id))
        if entity_type == "team":
            merge_team(conn, keep_id, drop_id)
        elif entity_type == "player":
            merge_player(conn, keep_id, drop_id)
        else:
            continue
        conn.execute(
            "UPDATE merge_candidates SET decision='merged',reviewed_at=? WHERE id=?",
            (now_iso(), int(candidate_id)),
        )
        merged += 1
    return merged


def remove_useless_rows(conn: sqlite3.Connection) -> int:
    removed = 0
    statements = [
        "DELETE FROM entity_aliases WHERE trim(alias)='' OR trim(normalized_alias)=''",
        "DELETE FROM field_provenance WHERE trim(field_name)='' OR trim(value_hash)=''",
        "DELETE FROM match_stats WHERE stat_value IS NULL",
        "DELETE FROM team_memberships WHERE team_id IS NULL OR player_id IS NULL",
        "DELETE FROM source_records WHERE trim(external_id)=''",
    ]
    for statement in statements:
        before = conn.total_changes
        try:
            conn.execute(statement)
        except sqlite3.OperationalError:
            continue
        removed += conn.total_changes - before
    return removed


def quality_score(values: list[Any], important_indexes: set[int] | None = None) -> float:
    if not values:
        return 0.0
    important_indexes = important_indexes or set()
    total = 0.0
    present = 0.0
    for index, value in enumerate(values):
        weight = 2.0 if index in important_indexes else 1.0
        total += weight
        if value is not None and str(value).strip() != "":
            present += weight
    return round(present / total, 4) if total else 0.0


def calculate_quality(conn: sqlite3.Connection) -> int:
    conn.execute("DELETE FROM entity_quality")
    calculated = 0
    specs = [
        ("team", "SELECT id,name,country_id,founded_year,city,stadium,short_name,gender FROM teams", {1, 2}),
        ("player", "SELECT id,full_name,date_of_birth,nationality,position,place_of_birth,height_cm,weight_kg FROM players", {1}),
        ("competition", "SELECT id,name,country_id,competition_type FROM competitions", {1}),
        ("match", "SELECT id,match_date,home_team_id,away_team_id,competition_id,home_score,away_score,status,venue_id,referee FROM matches", {1, 2, 3}),
    ]
    stamp = now_iso()
    for entity_type, sql, important in specs:
        for row in conn.execute(sql).fetchall():
            entity_id = int(row[0])
            completeness = quality_score(list(row[1:]), {i - 1 for i in important if i > 0})
            source_count = int(conn.execute(
                "SELECT COUNT(DISTINCT source_id) FROM source_records WHERE entity_type=? AND entity_id=?",
                (entity_type, entity_id),
            ).fetchone()[0])
            warning_count = int(conn.execute(
                """SELECT COUNT(*) FROM merge_candidates
                   WHERE entity_type=? AND decision='pending' AND (left_id=? OR right_id=?)""",
                (entity_type, entity_id, entity_id),
            ).fetchone()[0]) if entity_type in {"team", "player", "competition", "match"} else 0
            confidence = min(1.0, 0.45 + 0.12 * source_count + 0.35 * completeness - 0.05 * warning_count)
            conn.execute(
                """INSERT INTO entity_quality
                   (entity_type,entity_id,completeness_score,confidence_score,source_count,warning_count,last_calculated_at)
                   VALUES(?,?,?,?,?,?,?)""",
                (entity_type, entity_id, completeness, round(confidence, 4), source_count, warning_count, stamp),
            )
            calculated += 1
    return calculated


def report(conn: sqlite3.Connection) -> None:
    tables = [
        "venues", "team_venues", "competition_seasons", "season_teams",
        "match_lineups", "player_careers", "entity_aliases", "source_records",
        "field_provenance", "entity_quality", "merge_candidates", "graph_edges",
    ]
    app.log(f"KNOWLEDGE GRAPH REPORT v{VERSION}")
    for table in tables:
        count = int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
        app.log(f"  {table:24} {count:,}")
    pending = int(conn.execute("SELECT COUNT(*) FROM merge_candidates WHERE decision='pending'").fetchone()[0])
    low_quality = int(conn.execute("SELECT COUNT(*) FROM entity_quality WHERE completeness_score<0.35").fetchone()[0])
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    fk_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
    app.log(f"  pending_merge_candidates {pending:,}")
    app.log(f"  low_quality_entities      {low_quality:,}")
    app.log(f"  integrity_check           {integrity}")
    app.log(f"  foreign_key_errors        {len(fk_errors)}")
    if integrity != "ok" or fk_errors:
        raise RuntimeError("knowledge graph integrity failure")


def maintain(mode: str, merge_threshold: float, no_auto_merge: bool) -> int:
    archive = app.Archive()
    conn = archive.conn
    ensure_schema(conn)
    cur = conn.execute(
        "INSERT INTO maintenance_runs(started_at,mode) VALUES(?,?)",
        (now_iso(), mode),
    )
    run_id = int(cur.lastrowid)
    stats = {
        "aliases_added": 0,
        "edges_rebuilt": 0,
        "candidates_added": 0,
        "entities_merged": 0,
        "useless_rows_removed": 0,
        "errors": 0,
    }
    try:
        app.log("=" * 84)
        app.log(f"KNOWLEDGE GRAPH MAINTENANCE v{VERSION} | mode={mode}")
        stats["aliases_added"] = seed_aliases(conn)
        linked_venues = link_legacy_venues(conn)
        app.log(f"GRAPH NORMALIZE | aliases_added={stats['aliases_added']} | venues_linked={linked_venues}")
        stats["candidates_added"] = store_candidates(conn)
        app.log(f"DEDUP CANDIDATES | added={stats['candidates_added']}")
        if not no_auto_merge:
            stats["entities_merged"] = auto_merge(conn, merge_threshold)
            app.log(f"SAFE AUTO MERGE | merged={stats['entities_merged']} | threshold={merge_threshold}")
        stats["useless_rows_removed"] = remove_useless_rows(conn)
        quality_rows = calculate_quality(conn)
        stats["edges_rebuilt"] = rebuild_edges(conn)
        conn.execute("PRAGMA optimize")
        conn.commit()
        app.log(
            f"GRAPH BUILT | edges={stats['edges_rebuilt']:,} | quality_rows={quality_rows:,} | "
            f"useless_removed={stats['useless_rows_removed']:,}"
        )
        report(conn)
        conn.execute(
            """UPDATE maintenance_runs SET finished_at=?,aliases_added=?,edges_rebuilt=?,
               candidates_added=?,entities_merged=?,useless_rows_removed=?,errors=? WHERE id=?""",
            (now_iso(), stats["aliases_added"], stats["edges_rebuilt"], stats["candidates_added"],
             stats["entities_merged"], stats["useless_rows_removed"], stats["errors"], run_id),
        )
        conn.commit()
        app.log(f"KNOWLEDGE GRAPH COMPLETE | {stats}")
        return 0
    except Exception as exc:
        stats["errors"] += 1
        conn.execute(
            "UPDATE maintenance_runs SET finished_at=?,errors=?,note=? WHERE id=?",
            (now_iso(), stats["errors"], str(exc), run_id),
        )
        conn.commit()
        app.log(f"KNOWLEDGE GRAPH ERROR | {exc}", "ERROR")
        return 2
    finally:
        archive.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Football knowledge graph, deduplication and quality maintenance")
    parser.add_argument("--mode", choices=["quick", "full"], default="quick")
    parser.add_argument("--merge-threshold", type=float, default=0.985)
    parser.add_argument("--no-auto-merge", action="store_true")
    parser.add_argument("--report-only", action="store_true")
    args = parser.parse_args()
    if args.report_only:
        archive = app.Archive()
        try:
            ensure_schema(archive.conn)
            report(archive.conn)
            return 0
        finally:
            archive.close()
    return maintain(args.mode, max(0.90, min(args.merge_threshold, 1.0)), args.no_auto_merge)


if __name__ == "__main__":
    raise SystemExit(main())
