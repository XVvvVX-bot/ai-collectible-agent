from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from ai_agent_v2.orchestration.daily_interest_digest_cycle import run_daily_interest_digest_cycle
from ai_agent_v2.storage.sqlite_store import SqliteV2Store


def test_daily_interest_digest_cycle_runs_once_and_creates_index(tmp_path: Path):
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
        conn.execute(
            """
            INSERT INTO user_interest_targets_v2 (
              id, interest_id, target_label, target_kind, parse_family, raw_input,
              normalized_name, issue_code_norm, series_key, theme_name,
              variant_tokens_json, quantity_tokens_json, condition_tokens_json,
              is_active, created_at, updated_at, condition_mode
            ) VALUES (
              'target-buy', 'interest-buy', '2026年中国龙31.104克普制银币', 'listing_identity', 'coin_like',
              '2026年中国龙31.104克普制银币', '中国龙31.104克普制银币', NULL, '中国龙-银币', '中国龙',
              '[]', '[]', '[]', 1, ?, ?, 'ignore'
            )
            """,
            (now, now),
        )
        conn.commit()

    first = run_daily_interest_digest_cycle(
        str(db_path),
        str(reports_dir),
        state_dir=str(state_dir),
        now_local=datetime.fromisoformat("2026-03-29T09:00:00-07:00"),
        lookback_hours=24,
    )
    second = run_daily_interest_digest_cycle(
        str(db_path),
        str(reports_dir),
        state_dir=str(state_dir),
        now_local=datetime.fromisoformat("2026-03-29T18:00:00-07:00"),
        lookback_hours=24,
    )

    assert first.skipped is False
    assert first.index_report_path is not None
    assert first.user_count == 1
    assert len(first.user_report_paths) == 1
    assert second.skipped is True
    assert second.skip_reason == "already_ran_today"
