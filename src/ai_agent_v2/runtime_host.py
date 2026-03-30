from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event
from typing import Any, Callable
from zoneinfo import ZoneInfo

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


@dataclass(frozen=True)
class ServiceConfig:
    runtime_paths: RuntimePaths
    timezone_name: str
    base_url: str
    secret: str | None
    state_source_key: str
    window_hours: int
    max_windows_per_run: int
    page_size: int
    min_interval_sec: int
    timeout_sec: int
    incremental_check_minutes: int
    daily_check_minutes: int
    daily_lookback_hours: int
    loop_sleep_seconds: int


def build_service_config(
    *,
    runtime_root: str,
    timezone_name: str,
    db_path: str | None = None,
    output_dir: str | None = None,
    state_dir: str | None = None,
    secret_file: str | None = None,
    lock_path: str | None = None,
    rate_limit_state_path: str | None = None,
    base_url: str = DEFAULT_BASE_URL,
    secret: str | None = None,
    state_source_key: str = DEFAULT_STATE_SOURCE_KEY,
    window_hours: int = 1,
    max_windows_per_run: int = 4,
    page_size: int = 500,
    min_interval_sec: int = 60,
    timeout_sec: int = 60,
    incremental_check_minutes: int = 10,
    daily_check_minutes: int = 60,
    daily_lookback_hours: int = 24,
    loop_sleep_seconds: int = 60,
) -> ServiceConfig:
    return ServiceConfig(
        runtime_paths=resolve_runtime_paths(
            runtime_root=runtime_root,
            db_path=db_path,
            output_dir=output_dir,
            state_dir=state_dir,
            secret_file=secret_file,
            lock_path=lock_path,
            rate_limit_state_path=rate_limit_state_path,
        ),
        timezone_name=timezone_name,
        base_url=base_url,
        secret=secret,
        state_source_key=state_source_key,
        window_hours=window_hours,
        max_windows_per_run=max_windows_per_run,
        page_size=page_size,
        min_interval_sec=min_interval_sec,
        timeout_sec=timeout_sec,
        incremental_check_minutes=incremental_check_minutes,
        daily_check_minutes=daily_check_minutes,
        daily_lookback_hours=daily_lookback_hours,
        loop_sleep_seconds=loop_sleep_seconds,
    )


class BackgroundServiceRunner:
    def __init__(self, config: ServiceConfig, *, emit_fn: Callable[[str, Any], None] | None = None):
        self.config = config
        self.runtime_paths = config.runtime_paths
        self.app_tz = load_timezone(config.timezone_name)
        self.emit_fn = emit_fn or emit_json
        self.last_incremental_check_at: datetime | None = None
        self.last_daily_check_at: datetime | None = None

    def ensure_runtime(self) -> None:
        ensure_runtime_dirs(self.runtime_paths)

    def start_event(self) -> dict[str, Any]:
        return {
            "timezone": str(self.app_tz),
            "runtime": asdict(self.runtime_paths),
        }

    def run_forever(self, *, stop_event: Event | None = None) -> None:
        self.ensure_runtime()
        self.emit_fn("worker_started", **self.start_event())
        while stop_event is None or not stop_event.is_set():
            self.run_cycle()
            sleep_seconds = max(5, int(self.config.loop_sleep_seconds))
            if stop_event is None:
                time.sleep(sleep_seconds)
            else:
                stop_event.wait(timeout=sleep_seconds)

    def run_cycle(self) -> None:
        now_utc = datetime.now(timezone.utc)
        now_local = now_utc.astimezone(self.app_tz)

        if should_run(self.last_incremental_check_at, now_utc, minutes=self.config.incremental_check_minutes):
            result = run_incremental_once(
                db_path=self.runtime_paths.db_path,
                base_url=self.config.base_url,
                secret=self.config.secret,
                secret_file=self.runtime_paths.secret_file,
                state_source_key=self.config.state_source_key,
                window_hours=self.config.window_hours,
                max_windows_per_run=self.config.max_windows_per_run,
                page_size=self.config.page_size,
                min_interval_sec=self.config.min_interval_sec,
                timeout_sec=self.config.timeout_sec,
                rate_limit_state_path=self.runtime_paths.rate_limit_state_path,
                lock_path=self.runtime_paths.lock_path,
            )
            self.emit_fn("incremental_cycle", local_time=now_local.isoformat(), **result)
            self.last_incremental_check_at = now_utc

        if should_run(self.last_daily_check_at, now_utc, minutes=self.config.daily_check_minutes):
            result = run_daily_cycles(
                db_path=self.runtime_paths.db_path,
                output_dir=self.runtime_paths.output_dir,
                state_dir=self.runtime_paths.state_dir,
                now_local=now_local,
                lookback_hours=self.config.daily_lookback_hours,
            )
            self.emit_fn("daily_cycles", local_time=now_local.isoformat(), **result)
            self.last_daily_check_at = now_utc


def resolve_runtime_paths(
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


def ensure_runtime_dirs(paths: RuntimePaths) -> None:
    Path(paths.runtime_root).mkdir(parents=True, exist_ok=True)
    Path(paths.db_path).parent.mkdir(parents=True, exist_ok=True)
    Path(paths.output_dir).mkdir(parents=True, exist_ok=True)
    Path(paths.state_dir).mkdir(parents=True, exist_ok=True)
    Path(paths.secret_file).parent.mkdir(parents=True, exist_ok=True)
    Path(paths.lock_path).parent.mkdir(parents=True, exist_ok=True)
    Path(paths.rate_limit_state_path).parent.mkdir(parents=True, exist_ok=True)


def load_timezone(value: str) -> ZoneInfo:
    try:
        return ZoneInfo(value)
    except Exception as exc:
        raise ValueError(f"Invalid timezone: {value}") from exc


def should_run(last_run_at: datetime | None, now_utc: datetime, *, minutes: int) -> bool:
    if last_run_at is None:
        return True
    return now_utc >= last_run_at + timedelta(minutes=max(1, int(minutes)))


def run_incremental_once(
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
        resolved_secret = secret or read_secret_file(secret_file)
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


def run_daily_cycles(
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


def read_secret_file(path: str) -> str | None:
    secret_path = Path(path)
    if not secret_path.is_absolute():
        secret_path = Path.cwd() / secret_path
    if not secret_path.exists():
        return None
    text = secret_path.read_text(encoding="utf-8").strip()
    return text or None


def emit_json(event: str, **payload: Any) -> None:
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
