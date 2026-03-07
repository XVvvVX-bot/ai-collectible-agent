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

from ai_agent.taxonomy.zhaoonline_taxonomy import (
    apply_taxonomy_candidates,
    build_provisional_candidates,
)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Build provisional Zhaoonline taxonomy mappings from unmapped normalized values."
    )
    parser.add_argument("--db-path", default="data/agent.db")
    parser.add_argument("--top-n-per-field", type=int, default=100)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply generated mappings into market_taxonomy_map.",
    )
    args = parser.parse_args()

    candidates = build_provisional_candidates(
        db_path=args.db_path,
        top_n_per_field=args.top_n_per_field,
    )
    applied = 0
    if args.apply:
        applied = apply_taxonomy_candidates(args.db_path, candidates)

    print(
        json.dumps(
            {
                "ok": True,
                "db_path": args.db_path,
                "candidate_count": len(candidates),
                "applied_changes": applied,
                "candidates": [
                    {
                        "field_name": item.field_name,
                        "raw_value": item.raw_value,
                        "norm_value": item.norm_value,
                        "observed_count": item.observed_count,
                        "source": item.source,
                    }
                    for item in candidates
                ],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
