#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v1.3.2 player enrichment entrypoint with resilient media downloading."""
from __future__ import annotations

import media_download_fix  # noqa: F401
import enrich_players_external as enrichment


def main() -> int:
    return enrichment.main()


if __name__ == "__main__":
    raise SystemExit(main())
