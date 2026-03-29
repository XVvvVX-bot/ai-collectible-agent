from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ai_agent_v2.storage.sqlite_store import SqliteV2Store


@dataclass(frozen=True)
class SignalCleanupResult:
    retention_days: int
    deleted_signals: int
    deleted_runs: int


def prune_inactive_signals(db_path: str, *, retention_days: int = 30) -> SignalCleanupResult:
    if retention_days < 0:
        raise ValueError("retention_days must be >= 0")

    SqliteV2Store(db_path).ensure_schema()
    cutoff_iso = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()

    with sqlite3.connect(Path(db_path)) as conn:
        deleted_signals = conn.execute(
            """
            DELETE FROM signals_v2
            WHERE status = 'inactive'
              AND last_seen_at < ?
            """,
            (cutoff_iso,),
        ).rowcount

        deleted_runs = conn.execute(
            """
            DELETE FROM signal_runs_v2
            WHERE finished_at IS NOT NULL
              AND finished_at < ?
              AND id NOT IN (SELECT DISTINCT run_id FROM signals_v2 WHERE run_id IS NOT NULL)
            """,
            (cutoff_iso,),
        ).rowcount
        conn.commit()

    return SignalCleanupResult(
        retention_days=retention_days,
        deleted_signals=deleted_signals,
        deleted_runs=deleted_runs,
    )
