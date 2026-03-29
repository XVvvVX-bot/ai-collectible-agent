#!/usr/bin/env python3
"""Prune stale inactive V2 signal rows."""

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
from ai_agent_v2.signals.cleanup import prune_inactive_signals


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Prune stale inactive V2 signal rows.")
    parser.add_argument("--db-path", default=ZhaoV2Config.from_env().database_path)
    parser.add_argument("--retention-days", type=int, default=30)
    args = parser.parse_args()

    result = prune_inactive_signals(args.db_path, retention_days=args.retention_days)
    print(
        json.dumps(
            {
                "ok": True,
                "db_path": args.db_path,
                "retention_days": result.retention_days,
                "deleted_signals": result.deleted_signals,
                "deleted_runs": result.deleted_runs,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
