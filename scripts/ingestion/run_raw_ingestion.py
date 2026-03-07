#!/usr/bin/env python3
"""Run one raw-ingestion cycle for Zhaoonline status=1 and status=2."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ai_agent.clients.zhaoonline import ZhaoClient
from ai_agent.config import ZhaoConfig
from ai_agent.ingestion.raw_ingest import FileRateLimiter, RawIngestionJob
from ai_agent.normalization.zhaoonline_norm import normalize_zhaoonline_raw
from ai_agent.storage.sqlite_raw_store import SqliteRawStore


def main() -> int:
    cfg = ZhaoConfig.from_env()

    parser = argparse.ArgumentParser(description="Run raw ingestion for Zhaoonline.")
    parser.add_argument("--db-path", default=cfg.database_path)
    parser.add_argument("--base-url", default=cfg.base_url)
    parser.add_argument("--search-path", default=cfg.search_path)
    parser.add_argument("--secret", default=cfg.secret)
    parser.add_argument("--page-size", type=int, default=cfg.default_page_size)
    parser.add_argument("--timeout-sec", type=int, default=cfg.timeout_sec)
    parser.add_argument("--max-calls-per-hour", type=int, default=cfg.max_calls_per_hour)
    parser.add_argument("--rate-limit-state-path", default=cfg.rate_limit_state_path)
    parser.add_argument("--call-budget-per-run", type=int, default=30)
    parser.add_argument("--fresh-pages-per-status", type=int, default=2)
    parser.add_argument("--normalization-batch-size", type=int, default=1000000)
    parser.add_argument(
        "--skip-normalization",
        action="store_true",
        help="Skip raw-to-norm normalization after ingestion.",
    )
    args = parser.parse_args()

    client = ZhaoClient(
        base_url=args.base_url,
        search_path=args.search_path,
        secret=args.secret,
        timeout_sec=args.timeout_sec,
    )
    store = SqliteRawStore(db_path=args.db_path)
    rate_limiter = FileRateLimiter(
        state_path=args.rate_limit_state_path,
        max_calls=args.max_calls_per_hour,
    )
    job = RawIngestionJob(
        client=client,
        store=store,
        rate_limiter=rate_limiter,
        page_size=args.page_size,
        statuses=(2, 1),
        call_budget_per_run=args.call_budget_per_run,
        fresh_pages_per_status=args.fresh_pages_per_status,
    )
    result = job.run_once()
    normalization = None
    if not args.skip_normalization:
        normalization = normalize_zhaoonline_raw(
            db_path=args.db_path,
            batch_size=args.normalization_batch_size,
        )
    print(
        json.dumps(
            {
                "ok": True,
                "db_path": str(args.db_path),
                "total_inserted": result.total_inserted,
                "calls_used": result.calls_used,
                "inserted_by_status": result.inserted_by_status,
                "pages_fetched_by_status": result.pages_fetched_by_status,
                "completed_by_status": result.completed_by_status,
                "next_page_by_status": result.next_page_by_status,
                "normalization": (
                    None
                    if normalization is None
                    else {
                        "processed": normalization.processed,
                        "upserted": normalization.upserted,
                        "skipped": normalization.skipped,
                        "last_raw_rowid": normalization.last_raw_rowid,
                    }
                ),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
