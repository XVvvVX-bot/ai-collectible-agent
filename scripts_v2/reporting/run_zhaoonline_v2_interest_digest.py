#!/usr/bin/env python3
"""Build a V2 daily digest report for one user's interests."""

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
from ai_agent_v2.reporting.interest_digest import build_interest_digest_report


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Build a V2 daily digest report for one user's interests.")
    parser.add_argument("--db-path", default=ZhaoV2Config.from_env().database_path)
    parser.add_argument("--output-dir", default=str(Path("reports_v2")))
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--lookback-hours", type=int, default=24)
    args = parser.parse_args()

    result = build_interest_digest_report(
        args.db_path,
        args.output_dir,
        user_id=args.user_id,
        lookback_hours=args.lookback_hours,
    )
    print(
        json.dumps(
            {
                "ok": True,
                "db_path": args.db_path,
                "user_id": result.user_id,
                "report_path": result.report_path,
                "interest_count": result.interest_count,
                "active_match_count": result.active_match_count,
                "recent_activity_count": result.recent_activity_count,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
