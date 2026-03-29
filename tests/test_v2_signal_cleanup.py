from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

from ai_agent_v2.signals.cleanup import prune_inactive_signals
from ai_agent_v2.storage.sqlite_store import SqliteV2Store


def test_prune_inactive_signals_deletes_only_old_inactive_rows(tmp_path: Path):
    db_path = tmp_path / "agent_v2.db"
    SqliteV2Store(str(db_path)).ensure_schema()

    old_time = "2026-01-01T00:00:00+00:00"
    new_time = "2026-03-29T00:00:00+00:00"

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO users (id, display_name, language, timezone, created_at, updated_at) VALUES ('u-clean', 'Cleanup User', 'zh-CN', 'Asia/Shanghai', ?, ?)",
            (new_time, new_time),
        )
        conn.execute(
            "INSERT INTO user_interests_v2 (id, user_id, interest_name, interest_kind, scope_kind, precision_mode, interest_priority, intent_confidence, allow_related_matches, allow_series_matches, allow_variant_matches, active_status, notes, created_at, updated_at) VALUES ('interest-clean', 'u-clean', 'cleanup', 'watch_buy', 'exact_item', 'exact', 'high', 1.0, 0, 0, 0, 'active', '', ?, ?)",
            (new_time, new_time),
        )
        conn.execute(
            "INSERT INTO signal_runs_v2 (id, user_id, lookback_hours, started_at, finished_at, status, interests_processed, candidates, inserted, skipped_cooldown) VALUES ('run-old', 'u-clean', 24, ?, ?, 'success', 1, 1, 1, 0)",
            (old_time, old_time),
        )
        conn.execute(
            "INSERT INTO signal_runs_v2 (id, user_id, lookback_hours, started_at, finished_at, status, interests_processed, candidates, inserted, skipped_cooldown) VALUES ('run-new', 'u-clean', 24, ?, ?, 'success', 1, 1, 1, 0)",
            (new_time, new_time),
        )
        conn.execute(
            """
            INSERT INTO signals_v2 (
              id, run_id, user_id, interest_id, target_id, listing_id, signal_type, urgency, reason_code,
              signal_title, signal_summary, group_key, payload_json, created_at, last_seen_at, status
            ) VALUES
            (?, 'run-old', 'u-clean', 'interest-clean', NULL, NULL, 'old_signal', 'low', 'old_reason', 'old', 'old', 'old-key', '{}', ?, ?, 'inactive'),
            (?, 'run-new', 'u-clean', 'interest-clean', NULL, NULL, 'new_signal', 'low', 'new_reason', 'new', 'new', 'new-key', '{}', ?, ?, 'inactive'),
            (?, 'run-new', 'u-clean', 'interest-clean', NULL, NULL, 'active_signal', 'low', 'active_reason', 'active', 'active', 'active-key', '{}', ?, ?, 'active')
            """,
            (
                str(uuid.uuid4()),
                old_time,
                old_time,
                str(uuid.uuid4()),
                new_time,
                new_time,
                str(uuid.uuid4()),
                old_time,
                old_time,
            ),
        )
        conn.commit()

    result = prune_inactive_signals(str(db_path), retention_days=30)

    with sqlite3.connect(db_path) as conn:
        statuses = conn.execute("SELECT signal_type, status FROM signals_v2 ORDER BY signal_type").fetchall()
        run_ids = [row[0] for row in conn.execute("SELECT id FROM signal_runs_v2 ORDER BY id").fetchall()]

    assert result.deleted_signals == 1
    assert result.deleted_runs == 1
    assert ("active_signal", "active") in statuses
    assert ("new_signal", "inactive") in statuses
    assert not any(signal_type == "old_signal" for signal_type, _ in statuses)
    assert "run-new" in run_ids
    assert "run-old" not in run_ids
