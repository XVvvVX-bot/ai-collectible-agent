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

from ai_agent.taxonomy.zhaoonline_taxonomy import get_unmapped_report


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Report unmapped Zhaoonline taxonomy values from market_listings_norm."
    )
    parser.add_argument("--db-path", default="data/agent.db")
    parser.add_argument("--top-n-per-field", type=int, default=20)
    parser.add_argument("--sample-size", type=int, default=3)
    args = parser.parse_args()

    report = get_unmapped_report(
        db_path=args.db_path,
        top_n_per_field=args.top_n_per_field,
        sample_size=args.sample_size,
    )
    print(
        json.dumps(
            {
                "ok": True,
                "db_path": args.db_path,
                "top_n_per_field": args.top_n_per_field,
                "sample_size": args.sample_size,
                "unmapped": report,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
