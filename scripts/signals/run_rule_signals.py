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

from ai_agent.signals.rule_engine import run_rule_signal_generation


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Run V1 rule-based signal generation.")
    parser.add_argument("--db-path", default="data/agent.db")
    parser.add_argument("--user-id", default=None)
    parser.add_argument("--cooldown-hours", type=int, default=24)
    parser.add_argument("--freshness-hours", type=int, default=24)
    parser.add_argument("--price-move-threshold-pct", type=float, default=10.0)
    args = parser.parse_args()

    result = run_rule_signal_generation(
        db_path=args.db_path,
        user_id=args.user_id,
        cooldown_hours=args.cooldown_hours,
        freshness_hours=args.freshness_hours,
        price_move_threshold_pct=args.price_move_threshold_pct,
    )
    print(
        json.dumps(
            {
                "ok": True,
                "users_processed": result.users_processed,
                "matches_scanned": result.matches_scanned,
                "candidates": result.candidates,
                "inserted": result.inserted,
                "skipped_cooldown": result.skipped_cooldown,
                "skipped_duplicate_run": result.skipped_duplicate_run,
                "inserted_by_type": result.inserted_by_type,
                "inserted_by_urgency": result.inserted_by_urgency,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
