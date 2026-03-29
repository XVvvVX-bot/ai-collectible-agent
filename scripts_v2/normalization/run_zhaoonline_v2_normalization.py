#!/usr/bin/env python3
"""Run V2 normalization for Zhao listings."""

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
from ai_agent_v2.normalization.zhaoonline_norm import run_zhaoonline_norm_v2


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Run V2 normalization for Zhao listings.")
    parser.add_argument("--db-path", default=ZhaoV2Config.from_env().database_path)
    parser.add_argument("--source-listing-id", action="append", default=[])
    parser.add_argument("--sync-run-id", action="append", default=[])
    args = parser.parse_args()

    result = run_zhaoonline_norm_v2(
        args.db_path,
        source_listing_ids=args.source_listing_id or None,
        sync_run_ids=args.sync_run_id or None,
    )
    print(json.dumps(result.__dict__, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
