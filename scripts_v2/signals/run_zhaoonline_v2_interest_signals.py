#!/usr/bin/env python3
"""Generate grouped V2 interest signals."""

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
from ai_agent_v2.signals.interest_signals import run_interest_signal_generation


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Generate grouped V2 interest signals.")
    parser.add_argument("--db-path", default=ZhaoV2Config.from_env().database_path)
    parser.add_argument("--user-id")
    parser.add_argument("--lookback-hours", type=int, default=24)
    args = parser.parse_args()

    result = run_interest_signal_generation(
        args.db_path,
        user_id=args.user_id,
        lookback_hours=args.lookback_hours,
    )
    print(
        json.dumps(
            {
                "ok": True,
                "db_path": args.db_path,
                "run_id": result.run_id,
                "interests_processed": result.interests_processed,
                "candidates": result.candidates,
                "inserted": result.inserted,
                "updated": result.updated,
                "deactivated": result.deactivated,
                "skipped_cooldown": result.skipped_cooldown,
                "inserted_by_type": result.inserted_by_type,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
