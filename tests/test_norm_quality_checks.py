from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

from ai_agent.quality.norm_quality import run_norm_quality_checks
from ai_agent.storage.sqlite_raw_store import SqliteRawStore


def _insert_norm_row(
    conn: sqlite3.Connection,
    source_listing_id: str,
    *,
    title: str = "ok",
    status_norm: str = "live",
    start_at: str | None = None,
    end_at: str | None = None,
    category_raw: str | None = None,
    category_norm: str | None = None,
    series_raw: str | None = None,
    series_norm: str | None = None,
    price_initial: float | None = None,
    price_current: float | None = None,
    price_end: float | None = None,
    is_active: int = 1,
) -> None:
    conn.execute(
        """
        INSERT INTO market_listings_norm (
          id,
          source_platform,
          source_listing_id,
          title,
          category_raw,
          category_norm,
          series_raw,
          series_norm,
          status_norm,
          start_at,
          end_at,
          price_initial,
          price_current,
          price_end,
          currency,
          is_active,
          first_seen_at,
          last_seen_at,
          created_at,
          updated_at
        ) VALUES (?, 'zhaoonline', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'CNY', ?, ?, ?, ?, ?)
        """,
        (
            str(uuid.uuid4()),
            source_listing_id,
            title,
            category_raw,
            category_norm,
            series_raw,
            series_norm,
            status_norm,
            start_at,
            end_at,
            price_initial,
            price_current,
            price_end,
            is_active,
            "2026-03-07T00:00:00+00:00",
            "2026-03-07T00:00:00+00:00",
            "2026-03-07T00:00:00+00:00",
            "2026-03-07T00:00:00+00:00",
        ),
    )


def test_norm_quality_detects_failures_and_warnings(tmp_path: Path):
    db_path = tmp_path / "agent.db"
    SqliteRawStore(str(db_path)).ensure_schema()

    with sqlite3.connect(db_path) as conn:
        _insert_norm_row(
            conn,
            "ok-1",
            title="Good Row",
            status_norm="live",
            start_at="2026-03-07T00:00:00+00:00",
            end_at="2026-03-08T00:00:00+00:00",
            category_raw="178",
            category_norm="category_178",
            series_raw="3",
            series_norm="series_3",
            price_initial=100.0,
            price_current=100.0,
            price_end=None,
            is_active=1,
        )
        _insert_norm_row(
            conn,
            "bad-1",
            title="Bad Row",
            status_norm="live",
            start_at="2026-03-09T00:00:00+00:00",
            end_at="2026-03-08T00:00:00+00:00",
            category_raw="999",
            category_norm=None,
            series_raw="7",
            series_norm=None,
            price_initial=-1.0,
            price_current=10.0,
            price_end=9.0,
            is_active=0,
        )
        conn.commit()

    result = run_norm_quality_checks(str(db_path), batch_size=100, since_last_run=True)
    assert result.rows_evaluated == 2
    assert result.pass_count == 1
    assert result.fail_count == 1
    assert result.warning_count == 0
    assert result.issue_counts["start_after_end"] == 1
    assert result.issue_counts["price_initial_negative"] == 1
    assert result.issue_counts["is_active_mismatch_status"] == 1
    assert result.issue_counts["unmapped_category"] == 1
    assert result.issue_counts["unmapped_series"] == 1
    assert result.issue_counts["price_current_not_equal_end"] == 1


def test_norm_quality_incremental_state(tmp_path: Path):
    db_path = tmp_path / "agent.db"
    SqliteRawStore(str(db_path)).ensure_schema()

    with sqlite3.connect(db_path) as conn:
        _insert_norm_row(conn, "first", title="First")
        conn.commit()

    first = run_norm_quality_checks(str(db_path), batch_size=100, since_last_run=True)
    second = run_norm_quality_checks(str(db_path), batch_size=100, since_last_run=True)
    assert first.rows_evaluated == 1
    assert second.rows_evaluated == 0

    with sqlite3.connect(db_path) as conn:
        _insert_norm_row(conn, "second", title="Second")
        conn.commit()

    third = run_norm_quality_checks(str(db_path), batch_size=100, since_last_run=True)
    assert third.rows_evaluated == 1
    assert third.rowid_start == first.rowid_end

