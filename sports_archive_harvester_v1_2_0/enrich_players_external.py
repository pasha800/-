#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rate-limit-aware player enrichment for external-media storage.

TheSportsDB's public API may return HTTP 429 after a small number of requests.
This worker therefore uses bounded retries, exponential backoff and a circuit
breaker. Unprocessed players remain eligible for a later run; they are not
marked as failed and hundreds of useless repeated requests are avoided.
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request

from sports_harvester_external_media import (
    Archive,
    MAX_PLAYER_PHOTO_BYTES,
    PLAYER_PHOTO_DIR,
    download_media,
    load_config,
    log,
    now_iso,
    to_int,
)


def number(value):
    if value is None:
        return None
    text = str(value).strip().lower().replace("cm", "").replace("kg", "")
    try:
        return float(text)
    except ValueError:
        return None


def request_player(name: str, config: dict, retries: int = 3) -> dict | None:
    key = str(config.get("thesportsdb_api_key") or "3")
    query = urllib.parse.urlencode({"p": name})
    url = f"https://www.thesportsdb.com/api/v1/json/{urllib.parse.quote(key)}/searchplayers.php?{query}"
    timeout = int(config.get("request_timeout_seconds", 30))
    for attempt in range(retries + 1):
        try:
            request = urllib.request.Request(
                url,
                headers={"User-Agent": "SportsArchiveHarvester/1.3.1"},
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                retry_after = exc.headers.get("Retry-After")
                delay = float(retry_after) if retry_after and retry_after.isdigit() else min(90.0, 10.0 * (attempt + 1))
                if attempt >= retries:
                    raise RuntimeError("RATE_LIMIT_429") from exc
                log(f"PLAYER API RATE LIMITED | {name} | retry={attempt + 1}/{retries} | wait={delay:.0f}s", "WARN")
                time.sleep(delay)
                continue
            if 500 <= exc.code < 600 and attempt < retries:
                delay = min(30.0, 2.0 ** attempt)
                log(f"PLAYER API RETRY | status={exc.code} | wait={delay:.0f}s | {name}", "WARN")
                time.sleep(delay)
                continue
            raise
        except urllib.error.URLError:
            if attempt >= retries:
                raise
            delay = min(20.0, 2.0 ** attempt)
            time.sleep(delay)
    return None


def enrich(limit: int) -> int:
    config = load_config()
    archive = Archive()
    saved = photos = memberships = not_found = errors = deferred = 0
    circuit_open = False
    try:
        rows = archive.conn.execute(
            """SELECT id,full_name FROM players
               WHERE source_key IS NULL
               ORDER BY updated_at DESC,id DESC LIMIT ?""",
            (max(0, limit),),
        ).fetchall()
        log(f"PLAYER ENRICH START | selected={len(rows)} | limit={limit} | rate-limit-aware=yes")
        for index, row in enumerate(rows, 1):
            if circuit_open:
                deferred += 1
                continue
            name = row["full_name"]
            try:
                payload = request_player(name, config)
                candidates = (payload or {}).get("player") or []
                if not candidates:
                    archive.conn.execute(
                        "UPDATE players SET source_key='not-found',updated_at=? WHERE id=?",
                        (now_iso(), row["id"]),
                    )
                    not_found += 1
                    log(f"PLAYER NOT FOUND | {index}/{len(rows)} | {name}")
                    time.sleep(0.75)
                    continue
                item = candidates[0]
                birth = item.get("dateBorn") or None
                death = item.get("dateDied") or None
                nationality = item.get("strNationality") or None
                birthplace = item.get("strBirthLocation") or None
                position = item.get("strPosition") or None
                height = number(item.get("strHeight"))
                weight = number(item.get("strWeight"))
                archive.conn.execute(
                    """UPDATE players SET date_of_birth=COALESCE(?,date_of_birth),
                       date_of_death=?,nationality=COALESCE(?,nationality),
                       place_of_birth=?,position=?,height_cm=?,weight_kg=?,gender=?,
                       source_key=?,updated_at=? WHERE id=?""",
                    (birth, death, nationality, birthplace, position, height, weight,
                     item.get("strGender"), item.get("idPlayer"), now_iso(), row["id"]),
                )
                saved += 1
                log(
                    f"PLAYER ENRICHED | {index}/{len(rows)} | {name} | "
                    f"birth={birth or '?'} | nationality={nationality or '?'} | position={position or '?'}"
                )
                team_name = (item.get("strTeam") or "").strip()
                if team_name:
                    team_row = archive.conn.execute(
                        "SELECT id FROM teams WHERE name=? ORDER BY id LIMIT 1", (team_name,)
                    ).fetchone()
                    if team_row:
                        cur = archive.conn.execute(
                            """INSERT OR IGNORE INTO team_memberships
                               (team_id,player_id,shirt_number,position,start_date,is_current)
                               VALUES(?,?,?,?,?,1)""",
                            (int(team_row[0]), int(row["id"]),
                             to_int(item.get("strNumber")), position, None),
                        )
                        memberships += int(bool(cur.rowcount))
                image_url = item.get("strCutout") or item.get("strThumb")
                if config.get("download_player_photos", True) and image_url:
                    max_bytes = int(
                        config.get("media_limits", {}).get(
                            "player_photo_bytes", MAX_PLAYER_PHOTO_BYTES
                        )
                    )
                    photos += int(
                        download_media(
                            archive, "player", int(row["id"]), "photo",
                            image_url, max_bytes, PLAYER_PHOTO_DIR,
                        )
                    )
                if index % 10 == 0:
                    archive.conn.commit()
                time.sleep(1.0)
            except RuntimeError as exc:
                if str(exc) == "RATE_LIMIT_429":
                    circuit_open = True
                    deferred += 1
                    log(
                        f"PLAYER ENRICH CIRCUIT OPEN | API rate limit persists; "
                        f"remaining players are deferred to a later run | first_deferred={name}",
                        "WARN",
                    )
                    continue
                errors += 1
                log(f"PLAYER ENRICH ERROR | {name} | {exc}", "WARN")
            except Exception as exc:
                errors += 1
                log(f"PLAYER ENRICH ERROR | {name} | {exc}", "WARN")
        archive.conn.commit()
        log(
            f"PLAYER ENRICH COMPLETE | profiles={saved} | photos={photos} | "
            f"memberships={memberships} | not_found={not_found} | deferred={deferred} | errors={errors}"
        )
        return 0 if errors == 0 else 2
    finally:
        archive.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    return enrich(args.limit)


if __name__ == "__main__":
    raise SystemExit(main())
