#!/usr/bin/env python3
"""Run the V2 pipeline on a long-lived worker for simple cloud hosting."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ai_agent_v2.ingestion.live_incremental import DEFAULT_STATE_SOURCE_KEY
from ai_agent_v2.runtime_host import BackgroundServiceRunner, DEFAULT_BASE_URL, build_service_config


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Run the V2 pipeline on a long-lived worker.")
    parser.add_argument("--runtime-root", default=os.getenv("APP_RUNTIME_ROOT") or "runtime")
    parser.add_argument("--db-path")
    parser.add_argument("--output-dir")
    parser.add_argument("--state-dir")
    parser.add_argument("--secret-file")
    parser.add_argument("--lock-path")
    parser.add_argument("--rate-limit-state-path")
    parser.add_argument("--timezone", default=os.getenv("APP_TIMEZONE") or "UTC")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--secret", default=os.getenv("ZHAO_V2_SECRET") or os.getenv("ZHAO_SECRET"))
    parser.add_argument("--state-source-key", default=os.getenv("ZHAO_V2_STATE_SOURCE_KEY") or DEFAULT_STATE_SOURCE_KEY)
    parser.add_argument("--window-hours", type=int, default=int(os.getenv("ZHAO_V2_WINDOW_HOURS", "1")))
    parser.add_argument("--max-windows-per-run", type=int, default=int(os.getenv("ZHAO_V2_MAX_WINDOWS_PER_RUN", "4")))
    parser.add_argument("--page-size", type=int, default=int(os.getenv("ZHAO_V2_PAGE_SIZE", "500")))
    parser.add_argument("--min-interval-sec", type=int, default=int(os.getenv("ZHAO_V2_MIN_INTERVAL_SEC", "60")))
    parser.add_argument("--timeout-sec", type=int, default=int(os.getenv("ZHAO_V2_REQUEST_TIMEOUT_SEC", "60")))
    parser.add_argument("--incremental-check-minutes", type=int, default=int(os.getenv("APP_INCREMENTAL_CHECK_MINUTES", "10")))
    parser.add_argument("--daily-check-minutes", type=int, default=int(os.getenv("APP_DAILY_CHECK_MINUTES", "60")))
    parser.add_argument("--daily-lookback-hours", type=int, default=int(os.getenv("APP_DAILY_LOOKBACK_HOURS", "24")))
    parser.add_argument("--loop-sleep-seconds", type=int, default=int(os.getenv("APP_LOOP_SLEEP_SECONDS", "60")))
    args = parser.parse_args()

    config = build_service_config(
        runtime_root=args.runtime_root,
        timezone_name=args.timezone,
        db_path=args.db_path,
        output_dir=args.output_dir,
        state_dir=args.state_dir,
        secret_file=args.secret_file,
        lock_path=args.lock_path,
        rate_limit_state_path=args.rate_limit_state_path,
        base_url=args.base_url,
        secret=args.secret,
        state_source_key=args.state_source_key,
        window_hours=args.window_hours,
        max_windows_per_run=args.max_windows_per_run,
        page_size=args.page_size,
        min_interval_sec=args.min_interval_sec,
        timeout_sec=args.timeout_sec,
        incremental_check_minutes=args.incremental_check_minutes,
        daily_check_minutes=args.daily_check_minutes,
        daily_lookback_hours=args.daily_lookback_hours,
        loop_sleep_seconds=args.loop_sleep_seconds,
    )
    runner = BackgroundServiceRunner(config)
    runner.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
