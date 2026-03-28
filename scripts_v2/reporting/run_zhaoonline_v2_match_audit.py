#!/usr/bin/env python3
"""Build a V2 matching audit report."""

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
from ai_agent_v2.reporting.match_audit import build_match_audit_report


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Build a V2 matching audit report.")
    parser.add_argument("--db-path", default=ZhaoV2Config.from_env().database_path)
    parser.add_argument("--output-dir", default=str(Path("reports_v2")))
    args = parser.parse_args()

    result = build_match_audit_report(args.db_path, args.output_dir)
    print(
        json.dumps(
            {
                "ok": True,
                "db_path": args.db_path,
                "report_path": result.report_path,
                "active_match_count": result.active_match_count,
                "relationship_counts": result.relationship_counts,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
