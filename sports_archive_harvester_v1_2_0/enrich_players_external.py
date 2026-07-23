#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Player enrichment for v1.2.1 external-media storage."""
from __future__ import annotations

import argparse
import time
import urllib.parse

from sports_harvester_external_media import (
    Archive,
    MAX_PLAYER_PHOTO_BYTES,
    PLAYER_PHOTO_DIR,
    download_media,
    load_config,
    log,
    now_iso,
    thesportsdb_json,
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


def enrich(limit: int) -> int:
    config = load_config()
    archive = Archive()
    saved = photos = memberships = not_found = errors = 0
    try:
        rows = archive.conn.execute(
            "SELECT id,full_name FROM players WHERE source_key IS NULL ORDER BY updated_at DESC,id DESC LIMIT ?",
            (max(0, limit),),
        ).fetchall()
        log(f"PLAYER ENRICH START | selected={len(rows)} | limit={limit}")
        for index, row in enumerate(rows, 1):
            name = row["full_name"]
            try:
                query = urllib.parse.urlencode({"p": name})
                payload = thesportsdb_json(f"searchplayers.php?{query}", config)
                candidates = payload.get("player") or []
                if not candidates:
                    archive.conn.execute(
                        "UPDATE players SET source_key='not-found',updated_at=? WHERE id=?",
                        (now_iso(), row["id"]),
                    )
                    not_found += 1
                    log(f"PLAYER NOT FOUND | {index}/{len(rows)} | {name}")
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
                    f"birth={birth or '?'} | nationality={nationality or '?'} | "
                    f"position={position or '?'}"
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
                if index % 25 == 0:
                    archive.conn.commit()
                time.sleep(0.20)
            except Exception as exc:
                errors += 1
                log(f"PLAYER ENRICH ERROR | {name} | {exc}", "WARN")
        archive.conn.commit()
        log(
            f"PLAYER ENRICH COMPLETE | profiles={saved} | photos={photos} | "
            f"memberships={memberships} | not_found={not_found} | errors={errors}"
        )
        return 0 if errors == 0 else 2
    finally:
        archive.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    return enrich(args.limit)


if __name__ == "__main__":
    raise SystemExit(main())
