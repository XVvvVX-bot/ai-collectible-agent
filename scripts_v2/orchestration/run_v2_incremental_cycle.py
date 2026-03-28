#!/usr/bin/env python3
"""Run one forward-looking V2 incremental sync window for live scheduling."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ai_agent_v2.config import ZhaoV2Config
from ai_agent_v2.ingestion.live_incremental import DEFAULT_STATE_SOURCE_KEY, FileLock, run_live_incremental_cycle


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Run one forward-looking V2 incremental sync window.")
    parser.add_argument("--db-path", default=ZhaoV2Config.from_env().database_path)
    parser.add_argument("--base-url", default=os.getenv("ZHAO_V2_BASE_URL") or os.getenv("ZHAO_BASE_URL") or "http://zhaoonline.hk:8888")
    parser.add_argument("--secret", default=os.getenv("ZHAO_V2_SECRET") or os.getenv("ZHAO_SECRET"))
    parser.add_argument("--secret-file", default="data/secrets/zhaoonline_secret.txt")
    parser.add_argument("--state-source-key", default=DEFAULT_STATE_SOURCE_KEY)
    parser.add_argument("--window-hours", type=int, default=1)
    parser.add_argument("--page-size", type=int, default=int(os.getenv("ZHAO_V2_PAGE_SIZE", "500")))
    parser.add_argument("--min-interval-sec", type=int, default=int(os.getenv("ZHAO_V2_MIN_INTERVAL_SEC", "60")))
    parser.add_argument("--timeout-sec", type=int, default=int(os.getenv("ZHAO_V2_REQUEST_TIMEOUT_SEC", "60")))
    parser.add_argument("--rate-limit-state-path", default=os.getenv("ZHAO_V2_RATE_LIMIT_STATE_PATH", "data/zhaoonline_v2_rate_limit_live.json"))
    parser.add_argument("--lock-path", default="data/locks/zhaoonline_v2_incremental_live.lock")
    args = parser.parse_args()

    secret = args.secret or _read_secret_file(args.secret_file)
    if not secret:
        print(
            json.dumps(
                {
                    "ok": True,
                    "skipped": True,
                    "reason": "missing_secret",
                    "secret_file": args.secret_file,
                },
                ensure_ascii=False,
            )
        )
        return 0

    lock = FileLock(args.lock_path)
    if not lock.acquire():
        print(json.dumps({"ok": True, "skipped": True, "reason": "lock_held", "lock_path": args.lock_path}, ensure_ascii=False))
        return 0

    try:
        result = run_live_incremental_cycle(
            db_path=args.db_path,
            base_url=args.base_url,
            secret=secret,
            state_source_key=args.state_source_key,
            window_hours=args.window_hours,
            page_size=args.page_size,
            min_interval_sec=args.min_interval_sec,
            request_timeout_sec=args.timeout_sec,
            rate_limit_state_path=args.rate_limit_state_path,
        )
    finally:
        lock.release()

    print(
        json.dumps(
            {
                "ok": True,
                "db_path": args.db_path,
                "state_source_key": result.state_source_key,
                "skipped": result.skipped,
                "skip_reason": result.skip_reason,
                "final_from_time_ms": result.final_from_time_ms,
                "target_to_time_ms": result.target_to_time_ms,
                "results": [row.__dict__ for row in result.results],
            },
            ensure_ascii=False,
        )
    )
    return 0


def _read_secret_file(path: str) -> str | None:
    secret_path = Path(path)
    if not secret_path.is_absolute():
        secret_path = ROOT_DIR / secret_path
    if not secret_path.exists():
        return None
    text = secret_path.read_text(encoding="utf-8").strip()
    return text or None


if __name__ == "__main__":
    raise SystemExit(main())
