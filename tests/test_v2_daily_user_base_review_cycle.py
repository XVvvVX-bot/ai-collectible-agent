from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from ai_agent_v2.orchestration.daily_review_cycle import run_daily_user_base_review_cycle
from ai_agent_v2.storage.sqlite_store import SqliteV2Store


def test_daily_review_cycle_runs_once_per_local_day(tmp_path: Path):
    db_path = tmp_path / "agent_v2.db"
    reports_dir = tmp_path / "reports"
    state_dir = tmp_path / "state"
    SqliteV2Store(str(db_path)).ensure_schema()
    now = "2026-03-29T00:00:00+00:00"

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
        conn.commit()

    first = run_daily_user_base_review_cycle(
        str(db_path),
        str(reports_dir),
        state_dir=str(state_dir),
        now_local=datetime.fromisoformat("2026-03-29T09:00:00-07:00"),
        lookback_hours=24,
    )
    second = run_daily_user_base_review_cycle(
        str(db_path),
        str(reports_dir),
        state_dir=str(state_dir),
        now_local=datetime.fromisoformat("2026-03-29T18:00:00-07:00"),
        lookback_hours=24,
    )

    assert first.skipped is False
    assert first.report_path is not None
    assert second.skipped is True
    assert second.skip_reason == "already_ran_today"
