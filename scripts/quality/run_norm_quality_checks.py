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

from ai_agent.quality.norm_quality import run_norm_quality_checks


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(
        description="Run quality checks on market_listings_norm rows."
    )
    parser.add_argument("--db-path", default="data/agent.db")
    parser.add_argument("--batch-size", type=int, default=2000)
    parser.add_argument(
        "--full-scan",
        action="store_true",
        help="Ignore incremental state and scan from rowid=0.",
    )
    args = parser.parse_args()

    result = run_norm_quality_checks(
        db_path=args.db_path,
        batch_size=args.batch_size,
        since_last_run=not args.full_scan,
    )
    print(
        json.dumps(
            {
                "ok": True,
                "run_id": result.run_id,
                "source_platform": result.source_platform,
                "since_last_run": result.since_last_run,
                "rowid_start": result.rowid_start,
                "rowid_end": result.rowid_end,
                "rows_evaluated": result.rows_evaluated,
                "pass_count": result.pass_count,
                "warning_count": result.warning_count,
                "fail_count": result.fail_count,
                "issue_counts": result.issue_counts,
                "sample_listing_ids": result.sample_listing_ids,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

