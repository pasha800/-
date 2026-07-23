#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Resilient external-media downloader for Sports Archive Harvester v1.3.2.

Fixes the root causes seen in production logs:
- repeated requests for the same broken logo on every match;
- Wikimedia SVG/GIF URLs that require a raster thumbnail URL;
- HTTP 400 thumbnail-size errors;
- HTTP 429 rate limiting;
- unsupported image payloads being retried forever.

Only JPEG/PNG/WebP files are saved. Images remain outside SQLite. SQLite stores
small metadata, local relative paths and compact retry state only.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import mimetypes
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import sports_harvester_external_media as base
import sports_harvester as core

APP_VERSION = "1.3.2"
core.APP_VERSION = APP_VERSION

MEDIA_STATE_SCHEMA = r"""
CREATE TABLE IF NOT EXISTS media_download_state (
  entity_type TEXT NOT NULL CHECK(entity_type IN ('team','player')),
  entity_id INTEGER NOT NULL,
  media_type TEXT NOT NULL CHECK(media_type IN ('logo','photo')),
  source_url_hash TEXT NOT NULL CHECK(length(source_url_hash)=64),
  status TEXT NOT NULL CHECK(status IN ('success','deferred','permanent_failure')),
  failure_count INTEGER NOT NULL DEFAULT 0,
  next_retry_at TEXT,
  last_http_status INTEGER,
  last_error TEXT,
  resolved_url TEXT,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(entity_type,entity_id,media_type,source_url_hash)
);
CREATE INDEX IF NOT EXISTS idx_media_retry
ON media_download_state(status,next_retry_at);
"""

# One attempt per entity during a process run, even when the same team appears in
# hundreds of fixtures.
_ATTEMPTED_THIS_RUN: set[tuple[str, int, str]] = set()
_HOST_NEXT_REQUEST: dict[str, float] = {}
_HOST_COOLDOWN_UNTIL: dict[str, float] = {}


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def _iso(value: dt.datetime) -> str:
    return value.isoformat()


def _ensure_state_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(MEDIA_STATE_SCHEMA)
    conn.commit()


def _url_hash(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8", errors="replace")).hexdigest()


def _safe_error(exc: Exception, limit: int = 280) -> str:
    text = re.sub(r"\s+", " ", str(exc)).strip()
    return text[:limit]


def _state_row(
    conn: sqlite3.Connection,
    entity_type: str,
    entity_id: int,
    media_type: str,
    source_hash: str,
) -> sqlite3.Row | None:
    return conn.execute(
        """SELECT status,failure_count,next_retry_at,last_http_status,last_error
           FROM media_download_state
           WHERE entity_type=? AND entity_id=? AND media_type=? AND source_url_hash=?""",
        (entity_type, entity_id, media_type, source_hash),
    ).fetchone()


def _retry_due(row: sqlite3.Row | None) -> bool:
    if row is None:
        return True
    status = str(row["status"])
    if status in {"success", "permanent_failure"}:
        return False
    retry_at = row["next_retry_at"]
    if not retry_at:
        return True
    try:
        return dt.datetime.fromisoformat(str(retry_at)) <= _now()
    except ValueError:
        return True


def _write_state(
    conn: sqlite3.Connection,
    *,
    entity_type: str,
    entity_id: int,
    media_type: str,
    source_hash: str,
    status: str,
    failure_count: int,
    next_retry_at: str | None,
    http_status: int | None,
    error: str | None,
    resolved_url: str | None,
) -> None:
    conn.execute(
        """INSERT INTO media_download_state(
             entity_type,entity_id,media_type,source_url_hash,status,failure_count,
             next_retry_at,last_http_status,last_error,resolved_url,updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(entity_type,entity_id,media_type,source_url_hash) DO UPDATE SET
             status=excluded.status,
             failure_count=excluded.failure_count,
             next_retry_at=excluded.next_retry_at,
             last_http_status=excluded.last_http_status,
             last_error=excluded.last_error,
             resolved_url=excluded.resolved_url,
             updated_at=excluded.updated_at""",
        (
            entity_type, entity_id, media_type, source_hash, status, failure_count,
            next_retry_at, http_status, error, resolved_url, _iso(_now()),
        ),
    )
    conn.commit()


def _existing_media(conn: sqlite3.Connection, entity_type: str, entity_id: int) -> sqlite3.Row | None:
    if entity_type == "team":
        return conn.execute(
            """SELECT f.id,f.relative_path,f.sha256
               FROM team_media m JOIN media_files f ON f.id=m.media_file_id
               WHERE m.team_id=?""",
            (entity_id,),
        ).fetchone()
    return conn.execute(
        """SELECT f.id,f.relative_path,f.sha256
           FROM player_media m JOIN media_files f ON f.id=m.media_file_id
           WHERE m.player_id=?""",
        (entity_id,),
    ).fetchone()


def _safe_local_path(relative_path: str) -> Path | None:
    text = (relative_path or "").strip().replace("\\", "/")
    if not text or text.lower().startswith(("http://", "https://", "data:")):
        return None
    try:
        root = core.ROOT.resolve()
        path = (core.ROOT / text).resolve()
        path.relative_to(root)
        return path
    except Exception:
        return None


def _wikimedia_filename(url: str) -> str | None:
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.casefold()
    if "wikimedia.org" not in host and "wikipedia.org" not in host:
        return None
    path = urllib.parse.unquote(parsed.path)
    # Handles /wikipedia/commons/a/ab/File.svg and /thumb/a/ab/File.svg/250px-...
    if "/thumb/" in path:
        path = path.split("/thumb/", 1)[1]
        parts = path.split("/")
        if len(parts) >= 3:
            return parts[2]
    name = path.rsplit("/", 1)[-1]
    return name or None


def _wikimedia_thumbnail_urls(url: str) -> list[str]:
    filename = _wikimedia_filename(url)
    if not filename:
        return []
    quoted = urllib.parse.quote(filename, safe="()!,'~-")
    # Special:Redirect asks Commons to select a valid thumbnail size, avoiding
    # the "Use thumbnail sizes listed" HTTP 400 response.
    return [
        f"https://commons.wikimedia.org/wiki/Special:Redirect/file/{quoted}?width=512",
        f"https://commons.wikimedia.org/wiki/Special:Redirect/file/{quoted}?width=256",
        f"https://commons.wikimedia.org/wiki/Special:Redirect/file/{quoted}?width=128",
    ]


def _candidate_urls(url: str) -> list[str]:
    candidates: list[str] = []
    lower = url.casefold()
    # For Wikimedia SVG/GIF, raster thumbnail candidates must be tried first.
    if _wikimedia_filename(url) and (".svg" in lower or ".gif" in lower or "/thumb/" in lower):
        candidates.extend(_wikimedia_thumbnail_urls(url))
    candidates.append(url)
    if _wikimedia_filename(url):
        candidates.extend(_wikimedia_thumbnail_urls(url))
    output: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        if item not in seen:
            seen.add(item)
            output.append(item)
    return output


def _sniff_image_mime(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _host_wait(url: str) -> None:
    host = urllib.parse.urlparse(url).netloc.casefold()
    now_mono = time.monotonic()
    cooldown = _HOST_COOLDOWN_UNTIL.get(host, 0.0)
    if cooldown > now_mono:
        raise RuntimeError(f"host cooldown active for {int(cooldown-now_mono)} seconds")
    next_request = _HOST_NEXT_REQUEST.get(host, 0.0)
    if next_request > now_mono:
        time.sleep(next_request - now_mono)
    # Wikimedia and public APIs are deliberately kept below burst limits.
    delay = 1.25 if "wikimedia" in host else 0.35
    _HOST_NEXT_REQUEST[host] = time.monotonic() + delay


def _request_image(url: str, timeout: int) -> tuple[bytes, dict[str, str], int, str]:
    _host_wait(url)
    headers = {
        "User-Agent": f"SportsArchiveHarvester/{APP_VERSION} (offline sports archive; contact via application owner)",
        "Accept": "image/avif,image/webp,image/png,image/jpeg,*/*;q=0.5",
        "Accept-Encoding": "identity",
        "Referer": "https://api.openligadb.de/",
    }
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        final_url = response.geturl()
        data = response.read()
        return data, {k.lower(): v for k, v in response.headers.items()}, int(response.status), final_url


def _insert_media_file(
    conn: sqlite3.Connection,
    relative_path: str,
    mime_type: str,
    byte_size: int,
    digest: str,
) -> int:
    conn.execute(
        """INSERT OR IGNORE INTO media_files(relative_path,mime_type,byte_size,sha256,created_at)
           VALUES(?,?,?,?,?)""",
        (relative_path, mime_type, byte_size, digest, core.now_iso()),
    )
    row = conn.execute("SELECT id FROM media_files WHERE sha256=?", (digest,)).fetchone()
    if not row:
        raise RuntimeError("media metadata could not be stored")
    return int(row[0])


def _link_media(conn: sqlite3.Connection, entity_type: str, entity_id: int, file_id: int) -> None:
    if entity_type == "team":
        conn.execute(
            """INSERT INTO team_media(team_id,media_file_id,linked_at) VALUES(?,?,?)
               ON CONFLICT(team_id) DO UPDATE SET media_file_id=excluded.media_file_id,
               linked_at=excluded.linked_at""",
            (entity_id, file_id, core.now_iso()),
        )
    else:
        conn.execute(
            """INSERT INTO player_media(player_id,media_file_id,linked_at) VALUES(?,?,?)
               ON CONFLICT(player_id) DO UPDATE SET media_file_id=excluded.media_file_id,
               linked_at=excluded.linked_at""",
            (entity_id, file_id, core.now_iso()),
        )


def download_media(
    archive: core.Archive,
    entity_type: str,
    entity_id: int,
    media_type: str,
    url: str,
    limit: int,
    destination: Path,
) -> bool:
    """Download one external image with persistent retry suppression."""
    _ensure_state_schema(archive.conn)
    expected = "logo" if entity_type == "team" else "photo"
    if media_type != expected:
        raise ValueError(f"invalid media type {media_type!r} for {entity_type!r}")
    if not url or not url.casefold().startswith(("http://", "https://")):
        return False

    existing = _existing_media(archive.conn, entity_type, entity_id)
    if existing:
        local = _safe_local_path(str(existing["relative_path"]))
        if local is not None and local.is_file():
            return False

    run_key = (entity_type, int(entity_id), media_type)
    if run_key in _ATTEMPTED_THIS_RUN:
        return False
    _ATTEMPTED_THIS_RUN.add(run_key)

    source_hash = _url_hash(url)
    old = _state_row(archive.conn, entity_type, entity_id, media_type, source_hash)
    if not _retry_due(old):
        return False
    failure_count = int(old["failure_count"]) if old else 0
    timeout = int(core.load_config().get("request_timeout_seconds", 30))
    last_error: Exception | None = None
    last_status: int | None = None

    for candidate in _candidate_urls(url):
        try:
            data, headers, status, resolved_url = _request_image(candidate, timeout)
            last_status = status
            if not data:
                raise RuntimeError("empty media response")
            if len(data) > int(limit):
                raise ValueError(
                    f"file size {core.human_bytes(len(data))} exceeds {core.human_bytes(int(limit))}"
                )
            sniffed = _sniff_image_mime(data)
            declared = (headers.get("content-type") or mimetypes.guess_type(resolved_url)[0] or "").split(";", 1)[0].casefold()
            if sniffed not in core.ALLOWED_IMAGE_MIME:
                # SVG/GIF/HTML are not stored. A Wikimedia raster candidate is
                # attempted before this path is marked permanently unsupported.
                raise ValueError(f"unsupported image payload MIME={declared or '?'}")

            digest = hashlib.sha256(data).hexdigest()
            found = archive.conn.execute(
                "SELECT id,relative_path FROM media_files WHERE sha256=?", (digest,)
            ).fetchone()
            if found:
                path = _safe_local_path(str(found["relative_path"]))
                if path is None or not path.is_file():
                    raise RuntimeError("media metadata exists but file is missing")
                file_id = int(found["id"])
                relative = str(found["relative_path"])
            else:
                extension = core.ALLOWED_IMAGE_MIME[sniffed]
                folder = destination / digest[:2]
                folder.mkdir(parents=True, exist_ok=True)
                final_path = folder / f"{digest}{extension}"
                temporary = final_path.with_suffix(final_path.suffix + ".tmp")
                temporary.write_bytes(data)
                if hashlib.sha256(temporary.read_bytes()).hexdigest() != digest:
                    temporary.unlink(missing_ok=True)
                    raise RuntimeError("SHA-256 verification failed")
                temporary.replace(final_path)
                relative = final_path.relative_to(core.ROOT).as_posix()
                file_id = _insert_media_file(
                    archive.conn, relative, sniffed, len(data), digest
                )
            _link_media(archive.conn, entity_type, entity_id, file_id)
            _write_state(
                archive.conn,
                entity_type=entity_type,
                entity_id=entity_id,
                media_type=media_type,
                source_hash=source_hash,
                status="success",
                failure_count=failure_count,
                next_retry_at=None,
                http_status=status,
                error=None,
                resolved_url=resolved_url,
            )
            archive.conn.commit()
            core.log(
                f"MEDIA FILE SAVED | {entity_type}={entity_id} | {media_type} | "
                f"{core.human_bytes(len(data))} | local_link={relative} | source={urllib.parse.urlparse(resolved_url).netloc}"
            )
            return True
        except urllib.error.HTTPError as exc:
            last_error = exc
            last_status = int(exc.code)
            host = urllib.parse.urlparse(candidate).netloc.casefold()
            if exc.code == 429:
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                seconds = int(retry_after) if retry_after and retry_after.isdigit() else 900
                _HOST_COOLDOWN_UNTIL[host] = time.monotonic() + min(seconds, 3600)
                break
            # 400/403/404 on one candidate may still be resolved by another
            # Wikimedia thumbnail candidate.
            if exc.code in {400, 403, 404, 410}:
                continue
            if 500 <= exc.code < 600:
                break
            continue
        except Exception as exc:
            last_error = exc
            # Unsupported SVG/GIF candidate can be followed by a raster candidate.
            continue

    failure_count += 1
    message = _safe_error(last_error or RuntimeError("all media candidates failed"))
    if last_status == 429:
        # Exponential persistent backoff: 15m, 30m, 1h ... max 24h.
        minutes = min(1440, 15 * (2 ** min(failure_count - 1, 6)))
        retry_at = _iso(_now() + dt.timedelta(minutes=minutes))
        state = "deferred"
        level = "WARN"
        core.log(
            f"MEDIA DEFERRED | {entity_type}={entity_id} | HTTP 429 | retry_after={retry_at}",
            level,
        )
    elif last_status in {500, 502, 503, 504}:
        minutes = min(360, 10 * (2 ** min(failure_count - 1, 5)))
        retry_at = _iso(_now() + dt.timedelta(minutes=minutes))
        state = "deferred"
        core.log(
            f"MEDIA DEFERRED | {entity_type}={entity_id} | HTTP {last_status} | retry_after={retry_at}",
            "WARN",
        )
    else:
        # Invalid SVG/GIF/HTML, missing files and bad Wikimedia URLs are not
        # hammered again on every fixture. A future changed URL gets a new hash
        # and is attempted normally.
        retry_at = None
        state = "permanent_failure"
        core.log(
            f"MEDIA PERMANENTLY SKIPPED | {entity_type}={entity_id} | status={last_status or '?'} | {message}",
            "WARN",
        )
    _write_state(
        archive.conn,
        entity_type=entity_type,
        entity_id=entity_id,
        media_type=media_type,
        source_hash=source_hash,
        status=state,
        failure_count=failure_count,
        next_retry_at=retry_at,
        http_status=last_status,
        error=message,
        resolved_url=None,
    )
    return False


# Patch every import path used by old and new collectors.
base.download_media = download_media
core.download_media = download_media

Archive = base.Archive
MAX_PLAYER_PHOTO_BYTES = base.MAX_PLAYER_PHOTO_BYTES
PLAYER_PHOTO_DIR = base.PLAYER_PHOTO_DIR
MAX_TEAM_LOGO_BYTES = base.MAX_TEAM_LOGO_BYTES
TEAM_LOGO_DIR = base.TEAM_LOGO_DIR
load_config = base.load_config
log = base.log
now_iso = base.now_iso
thesportsdb_json = base.thesportsdb_json
to_int = base.to_int
database_report = base.database_report
compact = base.compact
reset_database = base.reset_database


def main() -> int:
    return core.main()


if __name__ == "__main__":
    raise SystemExit(main())
