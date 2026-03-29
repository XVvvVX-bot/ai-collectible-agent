#!/usr/bin/env python3
"""Build a consolidated V2 daily review report for the active user base."""

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
from ai_agent_v2.reporting.daily_user_base_review import build_daily_user_base_review_report


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Build a consolidated V2 daily review report for the active user base.")
    parser.add_argument("--db-path", default=ZhaoV2Config.from_env().database_path)
    parser.add_argument("--output-dir", default=str(Path("reports_v2")))
    parser.add_argument("--lookback-hours", type=int, default=24)
    args = parser.parse_args()

    result = build_daily_user_base_review_report(
        args.db_path,
        args.output_dir,
        lookback_hours=args.lookback_hours,
    )
    print(
        json.dumps(
            {
                "ok": True,
                "db_path": args.db_path,
                "report_path": result.report_path,
                "user_count": result.user_count,
                "total_active_matches": result.total_active_matches,
                "total_active_signals": result.total_active_signals,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
