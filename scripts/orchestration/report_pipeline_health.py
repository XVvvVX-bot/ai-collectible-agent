#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(
        description="Print orchestration run health and alert dispatch stats."
    )
    parser.add_argument("--db-path", default="data/agent.db")
    parser.add_argument("--recent-runs", type=int, default=10)
    parser.add_argument("--alert-window-hours", type=int, default=24)
    args = parser.parse_args()

    db_path = Path(args.db_path)
    if not db_path.exists():
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": f"DB not found: {db_path}",
                },
                ensure_ascii=False,
            )
        )
        return 1

    now = datetime.now(timezone.utc)
    alert_cutoff = (now - timedelta(hours=args.alert_window_hours)).isoformat()

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        run_rows = conn.execute(
            """
            SELECT id, trigger_source, user_id, report_date, report_type, started_at, finished_at, status, error_message
            FROM orchestration_runs
            ORDER BY started_at DESC
            LIMIT ?
            """,
            (args.recent_runs,),
        ).fetchall()

        failed_stage_rows = conn.execute(
            """
            SELECT orchestration_run_id, stage_name, attempt_no, started_at, error_message
            FROM orchestration_stage_runs
            WHERE status = 'failed'
            ORDER BY started_at DESC
            LIMIT 20
            """
        ).fetchall()

        alert_rows = conn.execute(
            """
            SELECT status, COUNT(*) AS cnt
            FROM alert_dispatch_log
            WHERE dispatched_at >= ?
            GROUP BY status
            """,
            (alert_cutoff,),
        ).fetchall()
        by_status = {str(r["status"]): int(r["cnt"]) for r in alert_rows}

    payload: dict[str, Any] = {
        "ok": True,
        "recent_run_count": len(run_rows),
        "recent_runs": [
            {
                "id": str(r["id"]),
                "trigger_source": str(r["trigger_source"]),
                "user_id": str(r["user_id"] or ""),
                "report_date": str(r["report_date"] or ""),
                "report_type": str(r["report_type"] or ""),
                "started_at": str(r["started_at"]),
                "finished_at": str(r["finished_at"] or ""),
                "status": str(r["status"]),
                "error_message": str(r["error_message"] or ""),
            }
            for r in run_rows
        ],
        "failed_stages_recent": [
            {
                "run_id": str(r["orchestration_run_id"]),
                "stage": str(r["stage_name"]),
                "attempt_no": int(r["attempt_no"]),
                "started_at": str(r["started_at"]),
                "error_message": str(r["error_message"] or ""),
            }
            for r in failed_stage_rows
        ],
        "alerts": {
            "window_hours": args.alert_window_hours,
            "cutoff_utc": alert_cutoff,
            "sent_count": by_status.get("sent", 0),
            "failed_count": by_status.get("failed", 0),
        },
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
