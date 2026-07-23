#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v1.3.2 global sync entrypoint with resilient media downloading enabled."""
from __future__ import annotations

# Import first: patches every old media download entrypoint before providers load.
import media_download_fix  # noqa: F401
import global_football_sync_v2 as collector


def main() -> int:
    return collector.main()


if __name__ == "__main__":
    raise SystemExit(main())
