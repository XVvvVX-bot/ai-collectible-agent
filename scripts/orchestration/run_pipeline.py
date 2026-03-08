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
    parser = argparse.ArgumentParser(description="Run end-to-end orchestration pipeline.")
    parser.add_argument("--db-path", default=cfg.database_path)
    parser.add_argument("--user-id", default=None)
    parser.add_argument("--report-date", default=None, help="YYYY-MM-DD in UTC.")
    parser.add_argument("--report-type", default="daily", choices=["daily", "immediate"])
    parser.add_argument("--max-stage-retries", type=int, default=2)
    parser.add_argument("--normalization-batch-size", type=int, default=1000000)
    parser.add_argument("--quality-batch-size", type=int, default=2000)
    parser.add_argument("--matching-min-score", type=float, default=30.0)
    parser.add_argument("--loose-name-match", action="store_true")
    parser.add_argument("--cooldown-hours", type=int, default=24)
    parser.add_argument("--freshness-hours", type=int, default=24)
    parser.add_argument("--price-move-threshold-pct", type=float, default=10.0)
    parser.add_argument("--metrics-window-days", type=int, default=30)
    parser.add_argument("--metrics-full-window-days", type=int, default=30)
    parser.add_argument("--max-report-items-per-section", type=int, default=50)
    parser.add_argument("--call-budget-per-run", type=int, default=30)
    parser.add_argument("--fresh-pages-per-status", type=int, default=2)
    parser.add_argument("--skip-ingestion", action="store_true")
    parser.add_argument("--skip-normalization", action="store_true")
    parser.add_argument("--skip-taxonomy-observability", action="store_true")
    parser.add_argument("--skip-quality-checks", action="store_true")
    parser.add_argument("--skip-matching", action="store_true")
    parser.add_argument("--skip-signals", action="store_true")
    parser.add_argument("--skip-alert-dispatch", action="store_true")
    parser.add_argument("--skip-market-metrics", action="store_true")
    parser.add_argument("--skip-reports", action="store_true")
    args = parser.parse_args()

    run_cfg = PipelineRunnerConfig(
        db_path=args.db_path,
        user_id=args.user_id,
        report_date=args.report_date,
        run_ingestion=not args.skip_ingestion,
        run_normalization=not args.skip_normalization,
        run_taxonomy_observability=not args.skip_taxonomy_observability,
        run_quality_checks=not args.skip_quality_checks,
        run_matching=not args.skip_matching,
        run_signals=not args.skip_signals,
        run_alert_dispatch=not args.skip_alert_dispatch,
        run_market_metrics=not args.skip_market_metrics,
        run_reports=not args.skip_reports,
        max_stage_retries=args.max_stage_retries,
        normalization_batch_size=args.normalization_batch_size,
        quality_batch_size=args.quality_batch_size,
        matching_min_score=args.matching_min_score,
        strict_name_match=not args.loose_name_match,
        cooldown_hours=args.cooldown_hours,
        freshness_hours=args.freshness_hours,
        price_move_threshold_pct=args.price_move_threshold_pct,
        metrics_window_days=args.metrics_window_days,
        metrics_full_window_days=args.metrics_full_window_days,
        report_type=args.report_type,
        max_report_items_per_section=args.max_report_items_per_section,
        call_budget_per_run=args.call_budget_per_run,
        fresh_pages_per_status=args.fresh_pages_per_status,
    )
    result = PipelineRunner(run_cfg).run()
    print(
        json.dumps(
            {
                "ok": result.status == "success",
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


if __name__ == "__main__":
    raise SystemExit(main())
