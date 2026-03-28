#!/usr/bin/env python3
"""Run V2 structured matching."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ai_agent_v2.config import ZhaoV2Config
from ai_agent_v2.matching.v2_matcher import run_v2_matching


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Run V2 structured matching.")
    parser.add_argument("--db-path", default=ZhaoV2Config.from_env().database_path)
    parser.add_argument("--user-id")
    parser.add_argument("--include-ended", action="store_true")
    args = parser.parse_args()

    result = run_v2_matching(
        args.db_path,
        user_id=args.user_id,
        only_active_listings=not args.include_ended,
    )
    print(
        json.dumps(
            {
                "ok": True,
                "db_path": args.db_path,
                "run_id": result.run_id,
                "users_processed": result.users_processed,
                "listings_scanned": result.listings_scanned,
                "items_scanned": result.items_scanned,
                "evaluated_pairs": result.evaluated_pairs,
                "matched_pairs": result.matched_pairs,
                "inserted": result.inserted,
                "updated": result.updated,
                "deactivated": result.deactivated,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
