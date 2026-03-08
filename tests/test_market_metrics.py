from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

from ai_agent.metrics.market_metrics import run_market_metrics
from ai_agent.storage.sqlite_raw_store import SqliteRawStore


def _insert_listing(
    conn: sqlite3.Connection,
    source_listing_id: str,
    *,
    category_norm: str | None,
    series_norm: str | None,
    title: str,
    observed_at: str,
    price_current: float | None,
    price_end: float | None = None,
) -> None:
    listing_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO market_listings_norm (
          id,
          source_platform,
          source_listing_id,
          title,
          category_norm,
          series_norm,
          price_current,
          price_end,
          currency,
          is_active,
          first_seen_at,
          last_seen_at,
          created_at,
          updated_at
        ) VALUES (?, 'zhaoonline', ?, ?, ?, ?, ?, ?, 'CNY', 1, ?, ?, ?, ?)
        """,
        (
            listing_id,
            source_listing_id,
            title,
            category_norm,
            series_norm,
            price_current,
            price_end,
            observed_at,
            observed_at,
            observed_at,
            observed_at,
        ),
    )


def test_market_metrics_marks_limited_history_as_temporary(tmp_path: Path):
    db_path = tmp_path / "agent.db"
    SqliteRawStore(str(db_path)).ensure_schema()

    with sqlite3.connect(db_path) as conn:
        _insert_listing(
            conn,
            "L-1",
            category_norm="stamp",
            series_norm="t46",
            title="Monkey Ticket",
            observed_at="2026-03-06T00:00:00+00:00",
            price_current=100.0,
        )
        _insert_listing(
            conn,
            "L-2",
            category_norm="stamp",
            series_norm="t46",
            title="Monkey Ticket",
            observed_at="2026-03-07T00:00:00+00:00",
            price_current=120.0,
        )
        conn.commit()

    result = run_market_metrics(str(db_path), window_days=30, full_window_days=30)
    assert result.groups_built == 1
    assert result.provisional_groups == 1
    assert result.full_window_groups == 0

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT
              sample_count,
              price_avg,
              price_median,
              trend_direction,
              data_coverage_days,
              confidence_level,
              is_temporary
            FROM market_metrics
            WHERE source_platform = 'zhaoonline'
            """
        ).fetchone()
    assert row is not None
    assert int(row[0]) == 2
    assert float(row[1]) == 110.0
    assert float(row[2]) == 110.0
    assert str(row[3]) == "up"
    assert int(row[4]) == 2
    assert str(row[5]) == "low"
    assert int(row[6]) == 1


def test_market_metrics_upsert_is_idempotent(tmp_path: Path):
    db_path = tmp_path / "agent.db"
    SqliteRawStore(str(db_path)).ensure_schema()

    with sqlite3.connect(db_path) as conn:
        _insert_listing(
            conn,
            "L-3",
            category_norm="coin",
            series_norm="panda",
            title="1983 Panda 1oz",
            observed_at="2026-03-07T00:00:00+00:00",
            price_current=1000.0,
        )
        conn.commit()

    first = run_market_metrics(str(db_path), window_days=30, full_window_days=30)
    second = run_market_metrics(str(db_path), window_days=30, full_window_days=30)
    assert first.upserted == 1
    assert second.upserted == 1

    with sqlite3.connect(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM market_metrics").fetchone()[0]
    assert int(count) == 1
