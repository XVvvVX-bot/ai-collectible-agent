from __future__ import annotations

import sqlite3
from pathlib import Path

from ai_agent_v2.reporting.signal_review import build_signal_review_report
from ai_agent_v2.storage.sqlite_store import SqliteV2Store


def test_signal_review_report_separates_event_and_standing_signals(tmp_path: Path):
    db_path = tmp_path / "agent_v2.db"
    reports_dir = tmp_path / "reports"
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
            ('interest-buy', 'u-review', '龙币买点', 'watch_buy', 'exact_item', 'exact', 'high', 1.0, 0, 0, 0, 'active', '', ?, ?),
            ('interest-sell', 'u-review', '红楼梦卖点', 'watch_sell', 'exact_item', 'exact', 'high', 1.0, 0, 0, 0, 'active', '', ?, ?)
            """,
            (now, now, now, now),
        )
        conn.execute(
            """
            INSERT INTO signals_v2 (
              id, run_id, user_id, interest_id, target_id, listing_id, signal_type,
              urgency, reason_code, signal_title, signal_summary, group_key,
              payload_json, created_at, last_seen_at, status
            ) VALUES
            ('sig-event', 'run-1', 'u-review', 'interest-buy', NULL, NULL, 'buy_went_live',
             'high', 'matched_item_went_live', 'Went live', 'buy event', 'evt-1', '{}', ?, ?, 'active'),
            ('sig-stand', 'run-1', 'u-review', 'interest-sell', NULL, NULL, 'sell_comp_above_cost',
             'high', 'ended_comp_above_cost_basis', 'Above cost', 'sell standing', 'std-1', '{}', ?, ?, 'active')
            """,
            (recent, recent, recent, recent),
        )
        conn.commit()

    result = build_signal_review_report(str(db_path), str(reports_dir), user_id="u-review", lookback_hours=24)
    content = Path(result.report_path).read_text(encoding="utf-8")

    assert result.signal_count == 2
    assert "## New Event Signals" in content
    assert "## Standing Signals" in content
    assert "`buy_went_live`" in content
    assert "`sell_comp_above_cost`" in content
    assert "### 龙币买点" in content
    assert "### 红楼梦卖点" in content
