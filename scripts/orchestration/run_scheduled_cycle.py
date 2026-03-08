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

from ai_agent.config import ZhaoConfig
from ai_agent.orchestration.pipeline import PipelineRunner, PipelineRunnerConfig


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    cfg = ZhaoConfig.from_env()
    parser = argparse.ArgumentParser(
        description="Run a scheduler-friendly pipeline cycle mode."
    )
    parser.add_argument("--mode", choices=["daily", "alerts"], required=True)
    parser.add_argument("--db-path", default=cfg.database_path)
    parser.add_argument("--user-id", default=None)
    parser.add_argument("--report-date", default=None, help="YYYY-MM-DD in UTC.")
    parser.add_argument("--max-stage-retries", type=int, default=2)
    parser.add_argument("--call-budget-per-run", type=int, default=None)
    parser.add_argument("--fresh-pages-per-status", type=int, default=None)
    parser.add_argument("--loose-name-match", action="store_true")
    parser.add_argument("--cooldown-hours", type=int, default=24)
    parser.add_argument("--freshness-hours", type=int, default=24)
    parser.add_argument("--price-move-threshold-pct", type=float, default=10.0)
    args = parser.parse_args()

    mode_defaults = _mode_defaults(args.mode)
    run_cfg = PipelineRunnerConfig(
        db_path=args.db_path,
        user_id=args.user_id,
        report_date=args.report_date,
        run_ingestion=mode_defaults["run_ingestion"],
        run_normalization=mode_defaults["run_normalization"],
        run_taxonomy_observability=mode_defaults["run_taxonomy_observability"],
        run_quality_checks=mode_defaults["run_quality_checks"],
        run_matching=mode_defaults["run_matching"],
        run_signals=mode_defaults["run_signals"],
        run_alert_dispatch=mode_defaults["run_alert_dispatch"],
        run_market_metrics=mode_defaults["run_market_metrics"],
        run_reports=mode_defaults["run_reports"],
        max_stage_retries=args.max_stage_retries,
        strict_name_match=not args.loose_name_match,
        cooldown_hours=args.cooldown_hours,
        freshness_hours=args.freshness_hours,
        price_move_threshold_pct=args.price_move_threshold_pct,
        report_type=mode_defaults["report_type"],
        call_budget_per_run=(
            args.call_budget_per_run
            if args.call_budget_per_run is not None
            else mode_defaults["call_budget_per_run"]
        ),
        fresh_pages_per_status=(
            args.fresh_pages_per_status
            if args.fresh_pages_per_status is not None
            else mode_defaults["fresh_pages_per_status"]
        ),
    )
    result = PipelineRunner(run_cfg).run()

    print(
        json.dumps(
            {
                "ok": result.status == "success",
                "mode": args.mode,
                "run_id": result.run_id,
                "status": result.status,
                "started_at": result.started_at,
                "finished_at": result.finished_at,
                "stages": [
                    {
                        "stage": stage.stage,
                        "status": stage.status,
                        "attempts": stage.attempts,
                        "metrics": stage.metrics,
                        "error": stage.error,
                    }
                    for stage in result.stage_results
                ],
            },
            ensure_ascii=False,
        )
    )
    return 0 if result.status == "success" else 1


def _mode_defaults(mode: str) -> dict[str, object]:
    if mode == "daily":
        return {
            "run_ingestion": True,
            "run_normalization": True,
            "run_taxonomy_observability": True,
            "run_quality_checks": True,
            "run_matching": True,
            "run_signals": True,
            "run_alert_dispatch": True,
            "run_market_metrics": True,
            "run_reports": True,
            "report_type": "daily",
            "call_budget_per_run": 30,
            "fresh_pages_per_status": 2,
        }
    return {
        "run_ingestion": True,
        "run_normalization": True,
        "run_taxonomy_observability": False,
        "run_quality_checks": False,
        "run_matching": True,
        "run_signals": True,
        "run_alert_dispatch": True,
        "run_market_metrics": False,
        "run_reports": False,
        "report_type": "immediate",
        "call_budget_per_run": 8,
        "fresh_pages_per_status": 1,
    }


if __name__ == "__main__":
    raise SystemExit(main())
