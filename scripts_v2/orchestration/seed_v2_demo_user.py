#!/usr/bin/env python3
"""Reset the V2 profile layer and seed one curated demo user."""

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
from ai_agent_v2.profile.demo_user_seed import seed_curated_demo_user_v2


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Reset the V2 profile layer and seed one curated demo user.")
    parser.add_argument("--db-path", default=ZhaoV2Config.from_env().database_path)
    parser.add_argument(
        "--no-clear",
        action="store_true",
        help="Keep existing V2 profile rows and append the curated demo user instead of clearing first.",
    )
    args = parser.parse_args()

    result = seed_curated_demo_user_v2(
        args.db_path,
        clear_existing_profile_layer=not args.no_clear,
    )
    print(
        json.dumps(
            {
                "ok": True,
                "db_path": args.db_path,
                "user_id": result.user_id,
                "profile_tables_cleared": result.profile_tables_cleared,
                "users_upserted": result.users_upserted,
                "defaults_upserted": result.defaults_upserted,
                "interests_upserted": result.interests_upserted,
                "targets_upserted": result.targets_upserted,
                "holdings_upserted": result.holdings_upserted,
                "policies_upserted": result.policies_upserted,
                "selections": [
                    {
                        "title": row.title,
                        "source_listing_id": row.source_listing_id,
                        "overall_count": row.overall_count,
                        "ended_count": row.ended_count,
                        "price_end": row.price_end,
                        "parse_family": row.parse_family,
                    }
                    for row in result.selections
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
