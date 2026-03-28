#!/usr/bin/env python3
"""Copy V1 user domain tables into the V2 DB."""

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
from ai_agent_v2.importers.user_domain_sync import sync_user_domain_to_v2


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Copy V1 user domain tables into the V2 DB.")
    parser.add_argument("--source-db-path", default=str(Path("data") / "agent.db"))
    parser.add_argument("--target-db-path", default=ZhaoV2Config.from_env().database_path)
    parser.add_argument("--user-id")
    args = parser.parse_args()

    result = sync_user_domain_to_v2(
        args.source_db_path,
        args.target_db_path,
        user_id=args.user_id,
    )
    print(
        json.dumps(
            {
                "ok": True,
                "source_db_path": args.source_db_path,
                "target_db_path": args.target_db_path,
                "user_id": args.user_id,
                "users_upserted": result.users_upserted,
                "items_upserted": result.items_upserted,
                "preferences_upserted": result.preferences_upserted,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
