from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

from ai_agent_v2.reporting.daily_user_base_review import build_daily_user_base_review_report
from ai_agent_v2.storage.sqlite_store import SqliteV2Store


REFERENCE_NOW = datetime.fromisoformat("2026-03-29T12:00:00+00:00")


def test_daily_user_base_review_summarizes_active_v2_users(tmp_path: Path):
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
            ('interest-buy', 'u-review', '龙币抢拍', 'watch_buy', 'exact_item', 'exact', 'high', 1.0, 0, 0, 0, 'active', '', ?, ?),
            ('interest-sell', 'u-review', '红楼梦卖点', 'watch_sell', 'exact_item', 'exact', 'high', 1.0, 0, 0, 0, 'active', '', ?, ?)
            """,
            (now, now, now, now),
        )
        listing_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO market_listings_norm_v2 (
              id, source_platform, source_listing_id, title, status_raw, status_norm,
              category_name_raw, price_initial, first_seen_at, last_seen_at, created_at, updated_at
            ) VALUES (?, 'zhaoonline', 'L-1', '2026年中国龙31.104克普制银币', '1', 'preview', '纪念币-银', 1, ?, ?, ?, ?)
            """,
            (listing_id, recent, recent, recent, recent),
        )
        conn.execute(
            """
            INSERT INTO listing_matches_v2 (
              id, user_id, listing_id, user_item_id, item_type, relationship_type,
              match_score, identity_score, series_score, variant_score, condition_score,
              matcher_version, match_reasons_json, status, matched_at, updated_at
            ) VALUES
            (?, 'u-review', ?, 'target-buy', 'watch', 'exact_identity', 110, 80, 20, 5, 5, 'v2_test', '[]', 'active', ?, ?)
            """,
            (str(uuid.uuid4()), listing_id, recent, recent),
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

    result = build_daily_user_base_review_report(
        str(db_path),
        str(reports_dir),
        lookback_hours=24,
        now_utc=REFERENCE_NOW,
    )
    content = Path(result.report_path).read_text(encoding="utf-8")

    assert result.user_count == 1
    assert result.total_active_matches == 1
    assert result.total_active_signals == 2
    assert "# V2 Daily User-Base Review" in content
    assert "## User Summary" in content
    assert "## User Breakdown" in content
    assert "### Review User" in content
    assert "`u-review` | `Review User` | `2` interests | `1` active matches | `2` active signals" in content
    assert "`1` event-driven, `1` standing" in content
    assert "`龙币抢拍` | `watch_buy` | `1` active signals" in content
    assert "`high` | `龙币抢拍` | `buy_went_live` | Went live" in content
