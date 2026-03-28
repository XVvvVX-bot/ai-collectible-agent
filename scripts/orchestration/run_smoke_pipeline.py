#!/usr/bin/env python3
from __future__ import annotations

import json
import sqlite3
import sys
import uuid
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ai_agent.clients.zhaoonline import now_utc_iso
from ai_agent.orchestration.pipeline import PipelineRunner, PipelineRunnerConfig
from ai_agent.storage.sqlite_raw_store import SqliteRawStore
from ai_agent.user_domain import UserDomainService


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    db_path = "data/smoke_pipeline.db"
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    if Path(db_path).exists():
        Path(db_path).unlink()

    _seed(db_path)
    report_date = now_utc_iso()[:10]
    result = PipelineRunner(
        PipelineRunnerConfig(
            db_path=db_path,
            user_id="smoke_u_1",
            report_date=report_date,
            run_ingestion=False,
            run_normalization=False,
            run_taxonomy_observability=False,
        )
    ).run()

    checks = _assert_outputs(db_path)
    ok = result.status == "success" and checks["ok"]
    print(
        json.dumps(
            {
                "ok": ok,
                "run_id": result.run_id,
                "status": result.status,
                "checks": checks,
            },
            ensure_ascii=False,
        )
    )
    return 0 if ok else 1


def _seed(db_path: str) -> None:
    SqliteRawStore(db_path).ensure_schema()
    service = UserDomainService(db_path)
    service.upsert_user("smoke_u_1")
    service.upsert_user_preferences("smoke_u_1", high_interest_flag=True, keywords=["monkey"])
    service.upsert_user_item(
        "smoke_u_1",
        "watch",
        category="stamp",
        series="t46",
        item_name="Monkey Ticket",
        priority="high",
        max_buy_price=100.0,
    )

    now_iso = now_utc_iso()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO market_listings_norm (
              id,
              source_platform,
              source_listing_id,
              title,
              category_norm,
              series_norm,
              status_norm,
              price_initial,
              price_current,
              currency,
              is_active,
              first_seen_at,
              last_seen_at,
              created_at,
              updated_at
            ) VALUES (?, 'zhaoonline', ?, ?, ?, ?, 'live', ?, ?, 'CNY', 1, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                "smoke-listing-1",
                "Monkey Ticket",
                "stamp",
                "t46",
                150.0,
                90.0,
                now_iso,
                now_iso,
                now_iso,
                now_iso,
            ),
        )
        conn.commit()


def _assert_outputs(db_path: str) -> dict[str, object]:
    with sqlite3.connect(db_path) as conn:
        counts = {
            "signals": int(conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]),
            "reports": int(conn.execute("SELECT COUNT(*) FROM reports").fetchone()[0]),
            "stage_runs": int(conn.execute("SELECT COUNT(*) FROM orchestration_stage_runs").fetchone()[0]),
            "alerts_dispatched": int(
                conn.execute("SELECT COUNT(*) FROM alert_dispatch_log WHERE status = 'sent'").fetchone()[0]
            ),
        }
    ok = (
        counts["signals"] >= 1
        and counts["reports"] >= 1
        and counts["stage_runs"] >= 1
        and counts["alerts_dispatched"] >= 1
    )
    return {"ok": ok, "counts": counts}


if __name__ == "__main__":
    raise SystemExit(main())
