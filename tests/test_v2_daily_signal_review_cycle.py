from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from ai_agent_v2.orchestration.daily_signal_review_cycle import run_daily_signal_review_cycle
from ai_agent_v2.storage.sqlite_store import SqliteV2Store


def test_daily_signal_review_cycle_runs_once_and_creates_index(tmp_path: Path):
    db_path = tmp_path / "agent_v2.db"
    reports_dir = tmp_path / "reports"
    state_dir = tmp_path / "state"
    SqliteV2Store(str(db_path)).ensure_schema()
    now = "2026-03-29T00:00:00+00:00"
    recent = "2026-03-29T11:00:00+00:00"

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO users (id, display_name, language, timezone, created_at, updated_at) VALUES ('u-review', 'Review User', 'zh-CN', 'Asia/Shanghai', ?, ?)",
            (now, now),
        )
        conn.execute(
            """
            INSERT INTO user_interests_v2 (
              id, user_id, interest_name, interest_kind, scope_kind, precision_mode,
              interest_priority, intent_confidence, allow_related_matches, allow_series_matches,
              allow_variant_matches, active_status, notes, created_at, updated_at
            ) VALUES
            ('interest-buy', 'u-review', '龙币抢拍', 'watch_buy', 'exact_item', 'exact', 'high', 1.0, 0, 0, 0, 'active', '', ?, ?)
            """,
            (now, now),
        )
        conn.execute(
            """
            INSERT INTO signals_v2 (
              id, run_id, user_id, interest_id, target_id, listing_id, signal_type,
              urgency, reason_code, signal_title, signal_summary, group_key,
              payload_json, created_at, last_seen_at, status
            ) VALUES
            ('sig-event', 'run-1', 'u-review', 'interest-buy', NULL, NULL, 'buy_went_live',
             'high', 'matched_item_went_live', 'Went live', 'buy event', 'evt-1', '{}', ?, ?, 'active')
            """,
            (recent, recent),
        )
        conn.commit()

    first = run_daily_signal_review_cycle(
        str(db_path),
        str(reports_dir),
        state_dir=str(state_dir),
        now_local=datetime.fromisoformat("2026-03-29T09:00:00-07:00"),
        lookback_hours=24,
    )
    second = run_daily_signal_review_cycle(
        str(db_path),
        str(reports_dir),
        state_dir=str(state_dir),
        now_local=datetime.fromisoformat("2026-03-29T18:00:00-07:00"),
        lookback_hours=24,
    )

    assert first.skipped is False
    assert first.index_report_path is not None
    assert first.user_count == 1
    assert first.total_signal_count == 1
    assert len(first.user_report_paths) == 1
    assert second.skipped is True
    assert second.skip_reason == "already_ran_today"
