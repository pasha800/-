#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sports Archive Harvester v1.2.1 external-media layer.

All team logos and player photos are stored as ordinary files outside SQLite.
SQLite stores only small metadata and local relative paths linked by real foreign
keys. No image bytes, remote display URLs, base64 or BLOB values are stored.
"""
from __future__ import annotations

import hashlib
import mimetypes
import shutil
import sqlite3
from pathlib import Path
from typing import Any

import sports_harvester as core

APP_VERSION = "1.2.1"
core.APP_VERSION = APP_VERSION

EXTERNAL_MEDIA_SCHEMA = r"""
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS media_files (
  id INTEGER PRIMARY KEY,
  relative_path TEXT NOT NULL UNIQUE,
  mime_type TEXT NOT NULL CHECK(mime_type IN ('image/jpeg','image/png','image/webp')),
  byte_size INTEGER NOT NULL CHECK(byte_size > 0),
  sha256 TEXT NOT NULL UNIQUE CHECK(length(sha256) = 64),
  created_at TEXT NOT NULL,
  CHECK(relative_path NOT LIKE 'http://%'),
  CHECK(relative_path NOT LIKE 'https://%'),
  CHECK(relative_path NOT LIKE 'data:%')
);

CREATE TABLE IF NOT EXISTS team_media (
  team_id INTEGER PRIMARY KEY REFERENCES teams(id) ON DELETE CASCADE,
  media_file_id INTEGER NOT NULL REFERENCES media_files(id) ON DELETE RESTRICT,
  linked_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS player_media (
  player_id INTEGER PRIMARY KEY REFERENCES players(id) ON DELETE CASCADE,
  media_file_id INTEGER NOT NULL REFERENCES media_files(id) ON DELETE RESTRICT,
  linked_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_team_media_file ON team_media(media_file_id);
CREATE INDEX IF NOT EXISTS idx_player_media_file ON player_media(media_file_id);
"""


def _quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _safe_local_path(relative_path: str) -> Path | None:
    text = (relative_path or "").strip().replace("\\", "/")
    if not text or text.lower().startswith(("http://", "https://", "data:")):
        return None
    try:
        root = core.ROOT.resolve()
        candidate = (core.ROOT / text).resolve()
        candidate.relative_to(root)
        return candidate
    except Exception:
        return None


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def _insert_media_file(
    conn: sqlite3.Connection,
    relative_path: str,
    mime_type: str,
    byte_size: int,
    sha256: str,
    created_at: str,
) -> int:
    conn.execute(
        """INSERT OR IGNORE INTO media_files
           (relative_path,mime_type,byte_size,sha256,created_at)
           VALUES(?,?,?,?,?)""",
        (relative_path, mime_type, byte_size, sha256, created_at),
    )
    row = conn.execute(
        "SELECT id FROM media_files WHERE sha256=?", (sha256,)
    ).fetchone()
    if not row:
        raise RuntimeError("media file metadata could not be saved")
    return int(row[0])


def migrate_external_media(conn: sqlite3.Connection) -> None:
    """Migrate legacy path-only media rows and remove the polymorphic table."""
    conn.executescript(EXTERNAL_MEDIA_SCHEMA)
    if _table_exists(conn, "media"):
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(media)").fetchall()
        }
        required = {
            "entity_type", "entity_id", "relative_path", "mime_type",
            "byte_size", "sha256", "created_at"
        }
        if required.issubset(columns):
            rows = conn.execute(
                """SELECT entity_type,entity_id,relative_path,mime_type,
                          byte_size,sha256,created_at
                   FROM media"""
            ).fetchall()
            for row in rows:
                entity_type, entity_id, rel, mime, size, digest, created = row
                local = _safe_local_path(str(rel or ""))
                if local is None or not local.is_file():
                    continue
                if str(mime) not in core.ALLOWED_IMAGE_MIME:
                    continue
                actual_size = local.stat().st_size
                if actual_size <= 0:
                    continue
                actual_digest = hashlib.sha256(local.read_bytes()).hexdigest()
                file_id = _insert_media_file(
                    conn,
                    local.relative_to(core.ROOT.resolve()).as_posix(),
                    str(mime),
                    actual_size,
                    actual_digest,
                    str(created or core.now_iso()),
                )
                if entity_type == "team":
                    conn.execute(
                        """INSERT INTO team_media(team_id,media_file_id,linked_at)
                           VALUES(?,?,?)
                           ON CONFLICT(team_id) DO UPDATE SET
                           media_file_id=excluded.media_file_id,
                           linked_at=excluded.linked_at""",
                        (int(entity_id), file_id, core.now_iso()),
                    )
                elif entity_type == "player":
                    conn.execute(
                        """INSERT INTO player_media(player_id,media_file_id,linked_at)
                           VALUES(?,?,?)
                           ON CONFLICT(player_id) DO UPDATE SET
                           media_file_id=excluded.media_file_id,
                           linked_at=excluded.linked_at""",
                        (int(entity_id), file_id, core.now_iso()),
                    )
        conn.execute("DROP TABLE media")
    conn.commit()


def _sniff_image_mime(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _media_link(
    conn: sqlite3.Connection, entity_type: str, entity_id: int
) -> sqlite3.Row | None:
    if entity_type == "team":
        return conn.execute(
            """SELECT f.id,f.relative_path,f.sha256
               FROM team_media m JOIN media_files f ON f.id=m.media_file_id
               WHERE m.team_id=?""",
            (entity_id,),
        ).fetchone()
    if entity_type == "player":
        return conn.execute(
            """SELECT f.id,f.relative_path,f.sha256
               FROM player_media m JOIN media_files f ON f.id=m.media_file_id
               WHERE m.player_id=?""",
            (entity_id,),
        ).fetchone()
    raise ValueError(f"unsupported entity_type: {entity_type}")


def download_media(
    archive: core.Archive,
    entity_type: str,
    entity_id: int,
    media_type: str,
    url: str,
    limit: int,
    destination: Path,
) -> bool:
    """Download one image to disk and store only its local path in SQLite."""
    expected = "logo" if entity_type == "team" else "photo"
    if media_type != expected:
        raise ValueError(f"invalid media type {media_type!r} for {entity_type!r}")
    if not url or not url.lower().startswith(("http://", "https://")):
        return False

    existing = _media_link(archive.conn, entity_type, entity_id)
    if existing:
        local = _safe_local_path(str(existing["relative_path"]))
        if local is not None and local.is_file():
            return False

    try:
        data, headers, _ = core.request_bytes(url)
        if not data:
            return False
        if len(data) > int(limit):
            core.log(
                f"MEDIA SKIPPED | {core.human_bytes(len(data))} exceeds "
                f"{core.human_bytes(int(limit))} | {entity_type}={entity_id}",
                "WARN",
            )
            return False

        sniffed = _sniff_image_mime(data)
        declared = (
            (headers.get("content-type") or mimetypes.guess_type(url)[0] or "")
            .split(";")[0].lower()
        )
        mime = sniffed or declared
        if mime not in core.ALLOWED_IMAGE_MIME or sniffed is None:
            core.log(
                f"MEDIA SKIPPED | invalid image bytes/MIME={declared or '?'} | "
                f"{entity_type}={entity_id}",
                "WARN",
            )
            return False

        digest = hashlib.sha256(data).hexdigest()
        file_row = archive.conn.execute(
            "SELECT id,relative_path FROM media_files WHERE sha256=?", (digest,)
        ).fetchone()
        if file_row:
            local = _safe_local_path(str(file_row["relative_path"]))
            if local is None or not local.is_file():
                raise RuntimeError("media metadata exists but external file is missing")
            file_id = int(file_row["id"])
            relative = str(file_row["relative_path"])
        else:
            extension = core.ALLOWED_IMAGE_MIME[mime]
            folder = destination / digest[:2]
            folder.mkdir(parents=True, exist_ok=True)
            final_path = folder / f"{digest}{extension}"
            temporary = final_path.with_suffix(final_path.suffix + ".tmp")
            temporary.write_bytes(data)
            if hashlib.sha256(temporary.read_bytes()).hexdigest() != digest:
                temporary.unlink(missing_ok=True)
                raise RuntimeError("downloaded media failed SHA-256 verification")
            temporary.replace(final_path)
            relative = final_path.relative_to(core.ROOT).as_posix()
            file_id = _insert_media_file(
                archive.conn, relative, mime, len(data), digest, core.now_iso()
            )

        if entity_type == "team":
            archive.conn.execute(
                """INSERT INTO team_media(team_id,media_file_id,linked_at)
                   VALUES(?,?,?)
                   ON CONFLICT(team_id) DO UPDATE SET
                   media_file_id=excluded.media_file_id,
                   linked_at=excluded.linked_at""",
                (entity_id, file_id, core.now_iso()),
            )
        else:
            archive.conn.execute(
                """INSERT INTO player_media(player_id,media_file_id,linked_at)
                   VALUES(?,?,?)
                   ON CONFLICT(player_id) DO UPDATE SET
                   media_file_id=excluded.media_file_id,
                   linked_at=excluded.linked_at""",
                (entity_id, file_id, core.now_iso()),
            )
        archive.conn.commit()
        core.log(
            f"MEDIA FILE SAVED | {entity_type}={entity_id} | {media_type} | "
            f"{core.human_bytes(len(data))} | local_link={relative} | sqlite_bytes=0"
        )
        return True
    except Exception as exc:
        core.log(f"MEDIA ERROR | {entity_type}={entity_id} | {exc}", "WARN")
        return False


def _blob_cell_count(conn: sqlite3.Connection) -> int:
    total = 0
    tables = conn.execute(
        """SELECT name FROM sqlite_master
           WHERE type='table' AND name NOT LIKE 'sqlite_%'"""
    ).fetchall()
    for table_row in tables:
        table = str(table_row[0])
        for column in conn.execute(
            f"PRAGMA table_info({_quote_identifier(table)})"
        ).fetchall():
            column_name = str(column[1])
            sql = (
                f"SELECT COUNT(*) FROM {_quote_identifier(table)} "
                f"WHERE typeof({_quote_identifier(column_name)})='blob'"
            )
            total += int(conn.execute(sql).fetchone()[0])
    return total


def _referenced_media_paths(conn: sqlite3.Connection) -> set[str]:
    return {
        str(row[0]).replace("\\", "/")
        for row in conn.execute("SELECT relative_path FROM media_files").fetchall()
    }


def database_report(archive: core.Archive) -> None:
    tables = [
        "sports", "countries", "competitions", "teams", "players",
        "team_memberships", "matches", "match_events", "match_stats",
        "media_files", "team_media", "player_media", "sync_runs"
    ]
    core.log("DATABASE + EXTERNAL MEDIA REPORT")
    for table in tables:
        count = archive.conn.execute(
            f"SELECT COUNT(*) FROM {_quote_identifier(table)}"
        ).fetchone()[0]
        core.log(f"  {table:20} {count:,}")

    db_size = core.DB_PATH.stat().st_size if core.DB_PATH.exists() else 0
    media_files = [p for p in core.MEDIA_DIR.rglob("*") if p.is_file()]
    media_size = sum(p.stat().st_size for p in media_files)
    referenced = _referenced_media_paths(archive.conn)
    missing = 0
    remote_paths = 0
    for rel in referenced:
        if rel.lower().startswith(("http://", "https://", "data:")):
            remote_paths += 1
            continue
        local = _safe_local_path(rel)
        if local is None or not local.is_file():
            missing += 1
    disk_rel = {
        p.relative_to(core.ROOT).as_posix()
        for p in media_files
        if not p.name.endswith(".tmp")
    }
    orphan_files = len(disk_rel - referenced)
    blob_cells = _blob_cell_count(archive.conn)
    integrity = archive.conn.execute("PRAGMA integrity_check").fetchone()[0]
    fk_errors = archive.conn.execute("PRAGMA foreign_key_check").fetchall()

    core.log(f"  sqlite_size          {core.human_bytes(db_size)}")
    core.log(f"  external_media_size  {core.human_bytes(media_size)}")
    core.log(f"  image_blob_cells     {blob_cells} (must be 0)")
    core.log(f"  remote_media_paths   {remote_paths} (must be 0)")
    core.log(f"  missing_media_files  {missing}")
    core.log(f"  orphan_media_files   {orphan_files}")
    core.log(f"  integrity_check      {integrity}")
    core.log(f"  foreign_key_errors   {len(fk_errors)}")
    if blob_cells or remote_paths or integrity != "ok" or fk_errors:
        raise RuntimeError("external-media integrity policy failed")


def compact(archive: core.Archive) -> None:
    core.log("COMPACTION START | SQLite + external media cleanup")
    referenced = _referenced_media_paths(archive.conn)
    removed_files = 0
    removed_bytes = 0
    for path in list(core.MEDIA_DIR.rglob("*")) if core.MEDIA_DIR.exists() else []:
        if not path.is_file():
            continue
        rel = path.relative_to(core.ROOT).as_posix()
        if path.name.endswith(".tmp") or rel not in referenced:
            removed_bytes += path.stat().st_size
            path.unlink(missing_ok=True)
            removed_files += 1
    for folder in sorted(
        [p for p in core.MEDIA_DIR.rglob("*") if p.is_dir()],
        key=lambda p: len(p.parts),
        reverse=True,
    ) if core.MEDIA_DIR.exists() else []:
        try:
            folder.rmdir()
        except OSError:
            pass
    for file in core.CACHE_DIR.glob("*.tmp") if core.CACHE_DIR.exists() else []:
        file.unlink(missing_ok=True)
    archive.conn.execute(
        """DELETE FROM media_files
           WHERE id NOT IN (SELECT media_file_id FROM team_media)
             AND id NOT IN (SELECT media_file_id FROM player_media)"""
    )
    archive.conn.execute("PRAGMA optimize")
    archive.conn.commit()
    archive.conn.execute("VACUUM")
    core.log(
        f"COMPACTION COMPLETE | removed_files={removed_files} | "
        f"freed={core.human_bytes(removed_bytes)}"
    )


def reset_database() -> None:
    stamp = core.dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_root = core.DATA_DIR / "backups" / f"reset_{stamp}"
    backup_root.mkdir(parents=True, exist_ok=True)
    if core.DB_PATH.exists():
        shutil.move(str(core.DB_PATH), str(backup_root / core.DB_PATH.name))
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(core.DB_PATH) + suffix)
        if sidecar.exists():
            shutil.move(str(sidecar), str(backup_root / sidecar.name))
    if core.MEDIA_DIR.exists():
        shutil.move(str(core.MEDIA_DIR), str(backup_root / "media"))
    core.TEAM_LOGO_DIR.mkdir(parents=True, exist_ok=True)
    core.PLAYER_PHOTO_DIR.mkdir(parents=True, exist_ok=True)
    core.log(f"DATABASE AND EXTERNAL MEDIA MOVED TO BACKUP | {backup_root}")


def menu() -> int:
    while True:
        print("\n" + "=" * 74)
        print(" Sports Archive Harvester v1.2.1 - External media control panel")
        print(" Images stay outside SQLite; DB contains local path links only")
        print("=" * 74)
        print("1) Quick update: current-year new matches only")
        print("2) Full historical collection from 1872")
        print("3) Database + external media integrity report")
        print("4) Compact DB and delete unlinked media files")
        print("5) Reset DB and media safely into a timestamped backup")
        print("0) Exit")
        choice = input("Choose: ").strip()
        if choice == "1":
            core.run_sync("quick", 50, False)
        elif choice == "2":
            core.run_sync("full", 100, False)
        elif choice == "3":
            archive = core.Archive()
            try:
                database_report(archive)
            finally:
                archive.close()
        elif choice == "4":
            archive = core.Archive()
            try:
                compact(archive)
            finally:
                archive.close()
        elif choice == "5":
            if input("Type RESET to confirm: ").strip() == "RESET":
                reset_database()
        elif choice == "0":
            return 0


_original_archive_init = core.Archive.__init__


def _archive_init_with_external_media(self: core.Archive, *args: Any, **kwargs: Any) -> None:
    _original_archive_init(self, *args, **kwargs)
    migrate_external_media(self.conn)


core.Archive.__init__ = _archive_init_with_external_media
core.download_media = download_media
core.database_report = database_report
core.compact = compact
core.reset_database = reset_database
core.menu = menu

Archive = core.Archive
MAX_PLAYER_PHOTO_BYTES = core.MAX_PLAYER_PHOTO_BYTES
PLAYER_PHOTO_DIR = core.PLAYER_PHOTO_DIR
MAX_TEAM_LOGO_BYTES = core.MAX_TEAM_LOGO_BYTES
TEAM_LOGO_DIR = core.TEAM_LOGO_DIR
load_config = core.load_config
log = core.log
now_iso = core.now_iso
thesportsdb_json = core.thesportsdb_json
to_int = core.to_int


def main() -> int:
    return core.main()


if __name__ == "__main__":
    raise SystemExit(main())
