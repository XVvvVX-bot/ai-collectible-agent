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

from ai_agent.reporting.report_service import run_report_generation


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Generate and persist daily/immediate reports.")
    parser.add_argument("--db-path", default="data/agent.db")
    parser.add_argument("--user-id", default=None)
    parser.add_argument("--report-date", default=None, help="YYYY-MM-DD in UTC.")
    parser.add_argument("--report-type", default="daily", choices=["daily", "immediate"])
    parser.add_argument("--export-markdown", action="store_true")
    parser.add_argument("--reports-dir", default="reports")
    parser.add_argument("--max-items-per-section", type=int, default=50)
    parser.add_argument("--llm-humanize", action="store_true")
    parser.add_argument("--llm-model", default="gpt-4.1-mini")
    parser.add_argument("--openai-api-key", default=None)
    args = parser.parse_args()

    result = run_report_generation(
        db_path=args.db_path,
        user_id=args.user_id,
        report_date=args.report_date,
        report_type=args.report_type,
        export_markdown=args.export_markdown,
        reports_dir=args.reports_dir,
        max_items_per_section=args.max_items_per_section,
        llm_humanize=args.llm_humanize,
        llm_model=args.llm_model,
        openai_api_key=args.openai_api_key,
    )
    print(
        json.dumps(
            {
                "ok": True,
                "users_processed": result.users_processed,
                "generated_reports": result.generated_reports,
                "linked_signals": result.linked_signals,
                "report_type": result.report_type,
                "report_date": result.report_date,
                "exported_markdown_files": result.exported_markdown_files,
                "exported_humanized_files": result.exported_humanized_files,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
