#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ai_agent.matching.v1_matcher import run_v1_matching


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Run V1 listing-to-user-item matching.")
    parser.add_argument("--db-path", default="data/agent.db")
    parser.add_argument("--user-id", default=None)
    parser.add_argument("--min-score", type=float, default=30.0)
    parser.add_argument(
        "--loose-name-match",
        action="store_true",
        help="Disable strict exact name match requirement.",
    )
    parser.add_argument(
        "--include-inactive-listings",
        action="store_true",
        help="Include inactive/ended listings in matching.",
    )
    args = parser.parse_args()

    result = run_v1_matching(
        db_path=args.db_path,
        user_id=args.user_id,
        min_score=args.min_score,
        only_active_listings=not args.include_inactive_listings,
        strict_name_match=not args.loose_name_match,
    )
    print(
        json.dumps(
            {
                "ok": True,
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
