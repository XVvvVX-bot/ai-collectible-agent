#!/usr/bin/env python3
"""Populate V2 interest-profile tables from current user tables."""

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
from ai_agent_v2.profile.user_profile_migration import migrate_interest_profile_v2


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Populate V2 interest-profile tables from current user tables.")
    parser.add_argument("--db-path", default=ZhaoV2Config.from_env().database_path)
    args = parser.parse_args()

    result = migrate_interest_profile_v2(args.db_path)
    print(
        json.dumps(
            {
                "ok": True,
                "db_path": args.db_path,
                "users_processed": result.users_processed,
                "defaults_upserted": result.defaults_upserted,
                "interests_upserted": result.interests_upserted,
                "targets_upserted": result.targets_upserted,
                "holdings_upserted": result.holdings_upserted,
                "policies_upserted": result.policies_upserted,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
