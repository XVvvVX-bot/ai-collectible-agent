#!/usr/bin/env python3
"""Run the V2 daily per-user interest digest batch at most once per local day."""

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
from ai_agent_v2.orchestration.daily_interest_digest_cycle import run_daily_interest_digest_cycle


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Run the V2 daily per-user interest digest batch at most once per local day.")
    parser.add_argument("--db-path", default=ZhaoV2Config.from_env().database_path)
    parser.add_argument("--output-dir", default=str(Path("reports_v2")))
    parser.add_argument("--state-dir", default=str(Path("data") / "state"))
    parser.add_argument("--lookback-hours", type=int, default=24)
    args = parser.parse_args()

    result = run_daily_interest_digest_cycle(
        args.db_path,
        args.output_dir,
        state_dir=args.state_dir,
        lookback_hours=args.lookback_hours,
    )
    print(
        json.dumps(
            {
                "ok": result.ok,
                "skipped": result.skipped,
                "skip_reason": result.skip_reason,
                "local_date": result.local_date,
                "index_report_path": result.index_report_path,
                "user_count": result.user_count,
                "total_active_matches": result.total_active_matches,
                "total_recent_activity_count": result.total_recent_activity_count,
                "user_report_paths": result.user_report_paths,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
