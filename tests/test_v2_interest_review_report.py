from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

from ai_agent_v2.parsing.listing_parser import run_listing_parse_v2
from ai_agent_v2.reporting.interest_review import build_interest_review_report
from ai_agent_v2.storage.sqlite_store import SqliteV2Store


def _insert_listing(
    conn: sqlite3.Connection,
    source_listing_id: str,
    *,
    title: str,
    status_raw: str,
    status_norm: str,
    category_name_raw: str,
    price_initial: float = 1.0,
    price_end: float = 0.0,
    end_at: str | None = None,
    character_name_raw: str | None = None,
) -> str:
    listing_id = str(uuid.uuid4())
    now = "2026-03-29T00:00:00+00:00"
    conn.execute(
        """
        INSERT INTO market_listings_norm_v2 (
          id, source_platform, source_listing_id, title, status_raw, status_norm,
          category_name_raw, character_name_raw, price_initial, price_end, end_at,
          first_seen_at, last_seen_at, created_at, updated_at
        ) VALUES (?, 'zhaoonline', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            listing_id,
            source_listing_id,
            title,
            status_raw,
            status_norm,
            category_name_raw,
            character_name_raw,
            price_initial,
            price_end,
            end_at,
            now,
            now,
            now,
            now,
        ),
    )
    return listing_id


def test_interest_review_report_groups_active_matches_and_shows_ended_comps(tmp_path: Path):
    db_path = tmp_path / "agent_v2.db"
    reports_dir = tmp_path / "reports"
    SqliteV2Store(str(db_path)).ensure_schema()
    now = "2026-03-29T00:00:00+00:00"

    with sqlite3.connect(db_path) as conn:
        active_listing_id = _insert_listing(
            conn,
            "L-1",
            title="T69M红楼梦型张新",
            status_raw="2",
            status_norm="live",
            category_name_raw="小型（版）张",
            character_name_raw="全品",
        )
        _insert_listing(
            conn,
            "L-2",
            title="T69M红楼梦型张新",
            status_raw="2",
            status_norm="preview",
            category_name_raw="小型（版）张",
            character_name_raw="上品",
        )
        _insert_listing(
            conn,
            "L-3",
            title="T69M红楼梦型张新",
            status_raw="3",
            status_norm="ended",
            category_name_raw="小型（版）张",
            price_end=580.0,
            end_at="2026-03-28T12:00:00+00:00",
            character_name_raw="全品",
        )

        conn.execute(
            """
            INSERT INTO users (id, display_name, language, timezone, created_at, updated_at)
            VALUES ('u-review', 'Review User', 'zh-CN', 'Asia/Shanghai', ?, ?)
            """,
            (now, now),
        )
        conn.execute(
            """
            INSERT INTO user_profile_defaults_v2 (
              user_id, default_currency, default_precision_mode, default_delivery_mode,
              default_min_match_score, default_cooldown_hours, default_allow_related_matches,
              default_allow_series_matches, default_allow_variant_matches, notes, created_at, updated_at
            ) VALUES (
              'u-review', 'CNY', 'balanced', 'daily_digest', 70, 24, 0, 0, 1,
              'review defaults', ?, ?
            )
            """,
            (now, now),
        )
        conn.execute(
            """
            INSERT INTO user_interests_v2 (
              id, user_id, interest_name, interest_kind, scope_kind, precision_mode,
              interest_priority, intent_confidence, allow_related_matches, allow_series_matches,
              allow_variant_matches, active_status, notes, created_at, updated_at
            ) VALUES (
              'interest-1', 'u-review', '红楼梦卖点', 'watch_sell', 'exact_item', 'exact',
              'high', 0.95, 0, 0, 0, 'active', 'sell monitor', ?, ?
            )
            """,
            (now, now),
        )
        conn.execute(
            """
            INSERT INTO user_interest_targets_v2 (
              id, interest_id, target_label, target_kind, parse_family, raw_input,
              normalized_name, issue_code_norm, issue_part_token, series_key, theme_name,
              asset_type, variant_tokens_json, quantity_tokens_json, condition_tokens_json, condition_mode,
              year_value, budget_min, budget_max, strictness_override, priority_override,
              is_active, created_at, updated_at
            ) VALUES (
              'target-1', 'interest-1', 'T69M红楼梦型张新', 'listing_identity', 'stamp_like',
              'T69M红楼梦型张新', '红楼梦型张', 'T69M', NULL, 'T69M', '红楼梦',
              NULL, '[\"型张\",\"M\"]', '[]', '[\"新\",\"全品\"]', 'require',
              NULL, NULL, NULL, 'exact', 'high', 1, ?, ?
            )
            """,
            (now, now),
        )
        conn.execute(
            """
            INSERT INTO user_holdings_v2 (
              id, user_id, linked_interest_id, raw_input, parse_family, normalized_name,
              issue_code_norm, issue_part_token, series_key, theme_name, asset_type,
              variant_tokens_json, quantity_tokens_json, condition_tokens_json, year_value,
              holding_quantity, cost_basis_total, cost_basis_unit, notes, is_active, created_at, updated_at
            ) VALUES (
              'holding-1', 'u-review', 'interest-1', 'T69M红楼梦型张新', 'stamp_like', '红楼梦型张',
              'T69M', NULL, 'T69M', '红楼梦', NULL,
              '[\"型张\",\"M\"]', '[]', '[\"新\",\"全品\"]', NULL,
              1, 480, 480, 'owned item', 1, ?, ?
            )
            """,
            (now, now),
        )
        conn.execute(
            """
            INSERT INTO user_interest_signal_policies_v2 (
              id, interest_id, notify_on_preview, notify_on_live, notify_on_ended,
              notify_on_exact_match, notify_on_variant_match, notify_on_series_match,
              notify_on_price_opportunity, notify_on_sell_opportunity, min_match_score,
              cooldown_hours, delivery_mode, max_signals_per_day, created_at, updated_at
            ) VALUES (
              'policy-1', 'interest-1', 0, 0, 1, 0, 0, 0, 0, 1, 88, 12, 'immediate', 4, ?, ?
            )
            """,
            (now, now),
        )
        conn.execute(
            """
            INSERT INTO listing_matches_v2 (
              id, user_id, listing_id, user_item_id, item_type, relationship_type,
              match_score, identity_score, series_score, variant_score, condition_score,
              matcher_version, match_reasons_json, status, matched_at, updated_at
            ) VALUES
            (?, 'u-review', ?, 'target-1', 'watch', 'exact_identity', 181, 145, 20, 8, 8, 'v2_test', '[]', 'active', ?, ?),
            (?, 'u-review', ?, 'target-1', 'watch', 'exact_identity', 181, 145, 20, 8, 8, 'v2_test', '[]', 'active', ?, ?)
            """,
            (str(uuid.uuid4()), active_listing_id, now, now, str(uuid.uuid4()), conn.execute("SELECT id FROM market_listings_norm_v2 WHERE source_listing_id = 'L-2'").fetchone()[0], now, now),
        )
        conn.commit()

    run_listing_parse_v2(str(db_path))
    result = build_interest_review_report(str(db_path), str(reports_dir), user_id="u-review")

    content = Path(result.report_path).read_text(encoding="utf-8")
    assert result.interest_count == 1
    assert result.active_match_count == 2
    assert "### 红楼梦卖点" in content
    assert "Active grouped opportunities:" in content
    assert "`exact_identity` | `live` | `T69M红楼梦型张新`" in content
    assert "Recent ended comparable listings:" in content
    assert "`L-3` | `T69M红楼梦型张新` | ended `580.0`" in content
