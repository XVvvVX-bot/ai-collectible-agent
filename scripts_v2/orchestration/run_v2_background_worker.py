#!/usr/bin/env python3
"""Run the V2 pipeline on a long-lived worker for simple cloud hosting."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT_DIR = Path(__file__).resolve().parents[2]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ai_agent_v2.ingestion.live_incremental import DEFAULT_STATE_SOURCE_KEY, FileLock, run_live_incremental_cycle
from ai_agent_v2.orchestration.daily_interest_digest_cycle import run_daily_interest_digest_cycle
from ai_agent_v2.orchestration.daily_review_cycle import run_daily_user_base_review_cycle
from ai_agent_v2.orchestration.daily_signal_review_cycle import run_daily_signal_review_cycle
from ai_agent_v2.orchestration.post_sync_refresh import run_post_sync_refresh


DEFAULT_BASE_URL = os.getenv("ZHAO_V2_BASE_URL") or os.getenv("ZHAO_BASE_URL") or "http://zhaoonline.hk:8888"


@dataclass(frozen=True)
class RuntimePaths:
    runtime_root: str
    db_path: str
    output_dir: str
    state_dir: str
    secret_file: str
    lock_path: str
    rate_limit_state_path: str


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

    runtime_paths = _resolve_runtime_paths(
        runtime_root=args.runtime_root,
        db_path=args.db_path,
        output_dir=args.output_dir,
        state_dir=args.state_dir,
        secret_file=args.secret_file,
        lock_path=args.lock_path,
        rate_limit_state_path=args.rate_limit_state_path,
    )
    _ensure_runtime_dirs(runtime_paths)
    app_tz = _load_timezone(args.timezone)

    _emit("worker_started", timezone=str(app_tz), runtime=asdict(runtime_paths))

    last_incremental_check_at: datetime | None = None
    last_daily_check_at: datetime | None = None

    while True:
        now_utc = datetime.now(timezone.utc)
        now_local = now_utc.astimezone(app_tz)

        if _should_run(last_incremental_check_at, now_utc, minutes=args.incremental_check_minutes):
            result = _run_incremental_once(
                db_path=runtime_paths.db_path,
                base_url=args.base_url,
                secret=args.secret,
                secret_file=runtime_paths.secret_file,
                state_source_key=args.state_source_key,
                window_hours=args.window_hours,
                max_windows_per_run=args.max_windows_per_run,
                page_size=args.page_size,
                min_interval_sec=args.min_interval_sec,
                timeout_sec=args.timeout_sec,
                rate_limit_state_path=runtime_paths.rate_limit_state_path,
                lock_path=runtime_paths.lock_path,
            )
            _emit("incremental_cycle", local_time=now_local.isoformat(), **result)
            last_incremental_check_at = now_utc

        if _should_run(last_daily_check_at, now_utc, minutes=args.daily_check_minutes):
            result = _run_daily_cycles(
                db_path=runtime_paths.db_path,
                output_dir=runtime_paths.output_dir,
                state_dir=runtime_paths.state_dir,
                now_local=now_local,
                lookback_hours=args.daily_lookback_hours,
            )
            _emit("daily_cycles", local_time=now_local.isoformat(), **result)
            last_daily_check_at = now_utc

        time.sleep(max(5, int(args.loop_sleep_seconds)))


def _resolve_runtime_paths(
    *,
    runtime_root: str,
    db_path: str | None,
    output_dir: str | None,
    state_dir: str | None,
    secret_file: str | None,
    lock_path: str | None,
    rate_limit_state_path: str | None,
) -> RuntimePaths:
    root = Path(runtime_root)
    return RuntimePaths(
        runtime_root=str(root),
        db_path=db_path or os.getenv("ZHAO_V2_DATABASE_PATH") or str(root / "data" / "agent_v2.db"),
        output_dir=output_dir or os.getenv("APP_REPORTS_DIR") or str(root / "reports_v2"),
        state_dir=state_dir or os.getenv("APP_STATE_DIR") or str(root / "data" / "state"),
        secret_file=secret_file or os.getenv("APP_SECRET_FILE") or str(root / "data" / "secrets" / "zhaoonline_secret.txt"),
        lock_path=lock_path or os.getenv("APP_LOCK_PATH") or str(root / "data" / "locks" / "zhaoonline_v2_incremental_live.lock"),
        rate_limit_state_path=rate_limit_state_path
        or os.getenv("ZHAO_V2_RATE_LIMIT_STATE_PATH")
        or str(root / "data" / "zhaoonline_v2_rate_limit_live.json"),
    )


def _ensure_runtime_dirs(paths: RuntimePaths) -> None:
    Path(paths.runtime_root).mkdir(parents=True, exist_ok=True)
    Path(paths.db_path).parent.mkdir(parents=True, exist_ok=True)
    Path(paths.output_dir).mkdir(parents=True, exist_ok=True)
    Path(paths.state_dir).mkdir(parents=True, exist_ok=True)
    Path(paths.secret_file).parent.mkdir(parents=True, exist_ok=True)
    Path(paths.lock_path).parent.mkdir(parents=True, exist_ok=True)
    Path(paths.rate_limit_state_path).parent.mkdir(parents=True, exist_ok=True)


def _load_timezone(value: str) -> ZoneInfo:
    try:
        return ZoneInfo(value)
    except Exception as exc:
        raise ValueError(f"Invalid timezone: {value}") from exc


def _should_run(last_run_at: datetime | None, now_utc: datetime, *, minutes: int) -> bool:
    if last_run_at is None:
        return True
    return now_utc >= last_run_at + timedelta(minutes=max(1, int(minutes)))


def _run_incremental_once(
    *,
    db_path: str,
    base_url: str,
    secret: str | None,
    secret_file: str,
    state_source_key: str,
    window_hours: int,
    max_windows_per_run: int,
    page_size: int,
    min_interval_sec: int,
    timeout_sec: int,
    rate_limit_state_path: str,
    lock_path: str,
) -> dict[str, Any]:
    try:
        resolved_secret = secret or _read_secret_file(secret_file)
        if not resolved_secret:
            return {"ok": True, "skipped": True, "reason": "missing_secret", "secret_file": secret_file}

        lock = FileLock(lock_path)
        if not lock.acquire():
            return {"ok": True, "skipped": True, "reason": "lock_held", "lock_path": lock_path}

        try:
            result = run_live_incremental_cycle(
                db_path=db_path,
                base_url=base_url,
                secret=resolved_secret,
                state_source_key=state_source_key,
                window_hours=window_hours,
                max_windows_per_run=max_windows_per_run,
                page_size=page_size,
                min_interval_sec=min_interval_sec,
                request_timeout_sec=timeout_sec,
                rate_limit_state_path=rate_limit_state_path,
            )
        finally:
            lock.release()

        total_inserted = sum(row.change_events_inserted for row in result.results)
        post_sync_payload: dict[str, Any] | None = None
        if result.results and total_inserted > 0:
            post_sync = run_post_sync_refresh(
                db_path,
                sync_run_ids=[row.sync_run_id for row in result.results],
            )
            post_sync_payload = {
                "sync_run_ids": list(post_sync.sync_run_ids),
                "normalization": asdict(post_sync.normalization),
                "parsing": {
                    "processed": post_sync.parsing.processed,
                    "upserted": post_sync.parsing.upserted,
                    "family_counts": post_sync.parsing.family_counts,
                },
            }

        return {
            "ok": True,
            "db_path": db_path,
            "state_source_key": result.state_source_key,
            "skipped": result.skipped,
            "skip_reason": result.skip_reason,
            "final_from_time_ms": result.final_from_time_ms,
            "target_to_time_ms": result.target_to_time_ms,
            "window_count": len(result.results),
            "results": [asdict(row) for row in result.results],
            "post_sync": post_sync_payload,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _run_daily_cycles(
    *,
    db_path: str,
    output_dir: str,
    state_dir: str,
    now_local: datetime,
    lookback_hours: int,
) -> dict[str, Any]:
    try:
        review = run_daily_user_base_review_cycle(
            db_path,
            output_dir,
            state_dir=state_dir,
            now_local=now_local,
            lookback_hours=lookback_hours,
        )
        signal = run_daily_signal_review_cycle(
            db_path,
            output_dir,
            state_dir=state_dir,
            now_local=now_local,
            lookback_hours=lookback_hours,
        )
        digest = run_daily_interest_digest_cycle(
            db_path,
            output_dir,
            state_dir=state_dir,
            now_local=now_local,
            lookback_hours=lookback_hours,
        )
        return {
            "ok": True,
            "review": asdict(review),
            "signal_review": asdict(signal),
            "interest_digest": asdict(digest),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _read_secret_file(path: str) -> str | None:
    secret_path = Path(path)
    if not secret_path.is_absolute():
        secret_path = ROOT_DIR / secret_path
    if not secret_path.exists():
        return None
    text = secret_path.read_text(encoding="utf-8").strip()
    return text or None


def _emit(event: str, **payload: Any) -> None:
    print(
        json.dumps(
            {
                "event": event,
                "time_utc": datetime.now(timezone.utc).isoformat(),
                **payload,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    raise SystemExit(main())
