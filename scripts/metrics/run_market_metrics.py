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

from ai_agent.metrics.market_metrics import run_market_metrics


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Run provisional market metrics baseline.")
    parser.add_argument("--db-path", default="data/agent.db")
    parser.add_argument("--window-days", type=int, default=30)
    parser.add_argument(
        "--full-window-days",
        type=int,
        default=30,
        help="Coverage day threshold to mark a metric as non-temporary.",
    )
    args = parser.parse_args()

    result = run_market_metrics(
        db_path=args.db_path,
        window_days=args.window_days,
        full_window_days=args.full_window_days,
    )
    print(
        json.dumps(
            {
                "ok": True,
                "rows_scanned": result.rows_scanned,
                "groups_built": result.groups_built,
                "upserted": result.upserted,
                "window_days": result.window_days,
                "provisional_groups": result.provisional_groups,
                "full_window_groups": result.full_window_groups,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
