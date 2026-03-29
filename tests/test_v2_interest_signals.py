from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path

from ai_agent_v2.parsing.listing_parser import run_listing_parse_v2
from ai_agent_v2.signals.interest_signals import run_interest_signal_generation
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
    updated_at: str = "2026-03-29T00:00:00+00:00",
) -> str:
    listing_id = str(uuid.uuid4())
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
            updated_at,
            updated_at,
            updated_at,
            updated_at,
        ),
    )
    return listing_id


def test_interest_signals_generate_buy_and_sell_candidates(tmp_path: Path):
    db_path = tmp_path / "agent_v2.db"
    SqliteV2Store(str(db_path)).ensure_schema()
    now = "2026-03-29T00:00:00+00:00"
    recent = "2026-03-29T11:00:00+00:00"

    with sqlite3.connect(db_path) as conn:
        buy_listing = _insert_listing(
            conn,
            "BUY-1",
            title="2026年中国龙31.104克普制银币",
            status_raw="2",
            status_norm="live",
            category_name_raw="纪念币-银",
            character_name_raw="评级币",
            updated_at=recent,
        )
        _insert_listing(
            conn,
            "SELL-1",
            title="T69M红楼梦型张新",
            status_raw="3",
            status_norm="ended",
            category_name_raw="小型（版）张",
            price_end=580.0,
            end_at=recent,
            character_name_raw="全品",
            updated_at=recent,
        )
        _insert_listing(
            conn,
            "BUY-END-1",
            title="2026年中国龙31.104克普制银币",
            status_raw="3",
            status_norm="ended",
            category_name_raw="纪念币-银",
            price_end=1560.0,
            end_at=recent,
            character_name_raw="评级币",
            updated_at=recent,
        )
        _insert_listing(
            conn,
            "BUY-END-2",
            title="2026年中国龙31.104克普制银币",
            status_raw="3",
            status_norm="ended",
            category_name_raw="纪念币-银",
            price_end=1540.0,
            end_at=recent,
            character_name_raw="评级币",
            updated_at=recent,
        )
        sell_live_listing = _insert_listing(
            conn,
            "SELL-2",
            title="T69M红楼梦型张新",
            status_raw="2",
            status_norm="live",
            category_name_raw="小型（版）张",
            character_name_raw="全品",
            updated_at=recent,
        )

        conn.execute(
            "INSERT INTO users (id, display_name, language, timezone, created_at, updated_at) VALUES ('u-signal', 'Signal User', 'zh-CN', 'Asia/Shanghai', ?, ?)",
            (now, now),
        )
        conn.execute(
            """
            INSERT INTO user_profile_defaults_v2 (
              user_id, default_currency, default_precision_mode, default_condition_mode,
              default_delivery_mode, default_min_match_score, default_cooldown_hours,
              default_allow_related_matches, default_allow_series_matches, default_allow_variant_matches,
              notes, created_at, updated_at
            ) VALUES (
              'u-signal', 'CNY', 'balanced', 'ignore', 'daily_digest', 70, 24, 0, 0, 1,
              'signal defaults', ?, ?
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
            ) VALUES
            ('interest-buy', 'u-signal', '龙币买点', 'watch_buy', 'exact_item', 'exact', 'high', 0.95, 0, 0, 0, 'active', 'buy', ?, ?),
            ('interest-sell', 'u-signal', '红楼梦卖点', 'watch_sell', 'exact_item', 'exact', 'high', 0.95, 0, 0, 0, 'active', 'sell', ?, ?)
            """,
            (now, now, now, now),
        )
        conn.execute(
            """
            INSERT INTO user_interest_targets_v2 (
              id, interest_id, target_label, target_kind, parse_family, raw_input,
              normalized_name, issue_code_norm, issue_part_token, series_key, theme_name,
              asset_type, variant_tokens_json, quantity_tokens_json, condition_tokens_json,
              year_value, budget_min, budget_max, strictness_override, priority_override,
              is_active, created_at, updated_at, condition_mode
            ) VALUES
            ('target-buy', 'interest-buy', '2026年中国龙31.104克普制银币', 'listing_identity', 'coin_like',
              '2026年中国龙31.104克普制银币', '中国龙31.104克普制银币', NULL, NULL, '中国龙|银币', '中国龙', '银币',
              '["普制"]', '[]', '["评级币"]', 2026, NULL, 1850, 'exact', 'high', 1, ?, ?, 'require'),
            ('target-sell', 'interest-sell', 'T69M红楼梦型张新', 'listing_identity', 'stamp_like',
              'T69M红楼梦型张新', '红楼梦型张', 'T69M', NULL, 'T69M', '红楼梦', NULL,
              '["型张","M"]', '[]', '["新","全品"]', NULL, NULL, NULL, 'exact', 'high', 1, ?, ?, 'require')
            """,
            (now, now, now, now),
        )
        conn.execute(
            """
            INSERT INTO user_holdings_v2 (
              id, user_id, linked_interest_id, raw_input, parse_family, normalized_name,
              issue_code_norm, issue_part_token, series_key, theme_name, asset_type,
              variant_tokens_json, quantity_tokens_json, condition_tokens_json, year_value,
              holding_quantity, cost_basis_total, cost_basis_unit, notes, is_active, created_at, updated_at
            ) VALUES (
              'holding-sell', 'u-signal', 'interest-sell', 'T69M红楼梦型张新', 'stamp_like', '红楼梦型张',
              'T69M', NULL, 'T69M', '红楼梦', NULL,
              '["型张","M"]', '[]', '["新","全品"]', NULL,
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
            ) VALUES
            ('policy-buy', 'interest-buy', 1, 1, 0, 1, 0, 0, 1, 0, 90, 24, 'immediate', 2, ?, ?),
            ('policy-sell', 'interest-sell', 0, 0, 1, 0, 0, 0, 0, 1, 88, 24, 'immediate', 2, ?, ?)
            """,
            (now, now, now, now),
        )
        conn.execute(
            """
            INSERT INTO listing_matches_v2 (
              id, user_id, listing_id, user_item_id, item_type, relationship_type,
              match_score, identity_score, series_score, variant_score, condition_score,
              matcher_version, match_reasons_json, status, matched_at, updated_at
            ) VALUES
            (?, 'u-signal', ?, 'target-buy', 'watch', 'exact_identity', 120, 90, 20, 5, 5, 'v2_test', '[]', 'active', ?, ?),
            (?, 'u-signal', ?, 'target-sell', 'watch', 'exact_identity', 187, 150, 20, 8, 9, 'v2_test', '[]', 'active', ?, ?)
            """,
            (
                str(uuid.uuid4()),
                buy_listing,
                recent,
                recent,
                str(uuid.uuid4()),
                sell_live_listing,
                recent,
                recent,
            ),
        )
        conn.commit()

    run_listing_parse_v2(str(db_path))
    result = run_interest_signal_generation(str(db_path), user_id="u-signal", lookback_hours=24)

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT signal_type, reason_code FROM signals_v2 WHERE user_id = 'u-signal' ORDER BY signal_type"
        ).fetchall()
        buy_budget_payload = json.loads(
            conn.execute(
                "SELECT payload_json FROM signals_v2 WHERE user_id = 'u-signal' AND signal_type = 'buy_budget_feasible_by_comps' LIMIT 1"
            ).fetchone()[0]
        )

    assert result.inserted >= 2
    signal_types = [row[0] for row in rows]
    assert "buy_active_opportunity" in signal_types
    assert "buy_budget_feasible_by_comps" in signal_types
    assert "sell_comp_above_cost" in signal_types
    assert buy_budget_payload["comp_trend"]["pricing_basis"] == "exact_same_condition"


def test_interest_signals_refresh_existing_rows_and_deactivate_stale_rows(tmp_path: Path):
    db_path = tmp_path / "agent_v2.db"
    SqliteV2Store(str(db_path)).ensure_schema()
    now = "2026-03-29T00:00:00+00:00"
    recent = "2026-03-29T11:00:00+00:00"

    with sqlite3.connect(db_path) as conn:
        live_listing = _insert_listing(
            conn,
            "BUY-1",
            title="2026年中国龙31.104克普制银币",
            status_raw="2",
            status_norm="live",
            category_name_raw="纪念币-银",
            character_name_raw="评级币",
            updated_at=recent,
        )
        _insert_listing(
            conn,
            "BUY-END-1",
            title="2026年中国龙31.104克普制银币",
            status_raw="3",
            status_norm="ended",
            category_name_raw="纪念币-银",
            price_end=1560.0,
            end_at=recent,
            character_name_raw="评级币",
            updated_at=recent,
        )
        conn.execute(
            "INSERT INTO users (id, display_name, language, timezone, created_at, updated_at) VALUES ('u-refresh', 'Refresh User', 'zh-CN', 'Asia/Shanghai', ?, ?)",
            (now, now),
        )
        conn.execute(
            """
            INSERT INTO user_profile_defaults_v2 (
              user_id, default_currency, default_precision_mode, default_condition_mode,
              default_delivery_mode, default_min_match_score, default_cooldown_hours,
              default_allow_related_matches, default_allow_series_matches, default_allow_variant_matches,
              notes, created_at, updated_at
            ) VALUES (
              'u-refresh', 'CNY', 'balanced', 'ignore', 'daily_digest', 70, 24, 0, 0, 1,
              'refresh defaults', ?, ?
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
              'interest-buy', 'u-refresh', '龙币买点', 'watch_buy', 'exact_item', 'exact',
              'high', 0.95, 0, 0, 0, 'active', 'buy', ?, ?
            )
            """,
            (now, now),
        )
        conn.execute(
            """
            INSERT INTO user_interest_targets_v2 (
              id, interest_id, target_label, target_kind, parse_family, raw_input,
              normalized_name, issue_code_norm, issue_part_token, series_key, theme_name,
              asset_type, variant_tokens_json, quantity_tokens_json, condition_tokens_json,
              year_value, budget_min, budget_max, strictness_override, priority_override,
              is_active, created_at, updated_at, condition_mode
            ) VALUES (
              'target-buy', 'interest-buy', '2026年中国龙31.104克普制银币', 'listing_identity', 'coin_like',
              '2026年中国龙31.104克普制银币', '中国龙31.104克普制银币', NULL, NULL, '中国龙|银币', '中国龙', '银币',
              '["普制"]', '[]', '["评级币"]', 2026, NULL, 1850, 'exact', 'high', 1, ?, ?, 'require'
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
              'policy-buy', 'interest-buy', 1, 1, 0, 1, 0, 0, 1, 0, 90, 24, 'immediate', 3, ?, ?
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
            (?, 'u-refresh', ?, 'target-buy', 'watch', 'exact_identity', 120, 90, 20, 5, 5, 'v2_test', '[]', 'active', ?, ?)
            """,
            (str(uuid.uuid4()), live_listing, recent, recent),
        )
        conn.execute(
            """
            INSERT INTO signals_v2 (
              id, run_id, user_id, interest_id, target_id, listing_id, signal_type,
              urgency, reason_code, signal_title, signal_summary, group_key,
              payload_json, created_at, last_seen_at, status
            ) VALUES (
              ?, 'old-run', 'u-refresh', 'interest-buy', 'target-buy', NULL, 'legacy_signal',
              'low', 'legacy_reason', 'old', 'old', 'old-key', '{}', ?, ?, 'active'
            )
            """,
            (str(uuid.uuid4()), recent, recent),
        )
        conn.commit()

    run_listing_parse_v2(str(db_path))
    result = run_interest_signal_generation(str(db_path), user_id="u-refresh", lookback_hours=24)

    with sqlite3.connect(db_path) as conn:
        active_types = [row[0] for row in conn.execute("SELECT signal_type FROM signals_v2 WHERE user_id='u-refresh' AND status='active'")]
        inactive_types = [row[0] for row in conn.execute("SELECT signal_type FROM signals_v2 WHERE user_id='u-refresh' AND status='inactive'")]

    assert result.deactivated >= 1
    assert "legacy_signal" in inactive_types
    assert "buy_active_opportunity" in active_types


def test_required_condition_treats_new_vs_used_as_hard_conflict(tmp_path: Path):
    db_path = tmp_path / "agent_v2.db"
    SqliteV2Store(str(db_path)).ensure_schema()
    now = "2026-03-29T00:00:00+00:00"
    recent = "2026-03-29T11:00:00+00:00"

    with sqlite3.connect(db_path) as conn:
        _insert_listing(
            conn,
            "STAMP-END-1",
            title="T89M仕女图型张盖",
            status_raw="3",
            status_norm="ended",
            category_name_raw="小型（版）张",
            price_end=250.0,
            end_at=recent,
            character_name_raw="全品",
            updated_at=recent,
        )
        _insert_listing(
            conn,
            "STAMP-END-2",
            title="T89M仕女图型张新",
            status_raw="3",
            status_norm="ended",
            category_name_raw="小型（版）张",
            price_end=420.0,
            end_at=recent,
            character_name_raw="全品",
            updated_at=recent,
        )
        conn.execute(
            "INSERT INTO users (id, display_name, language, timezone, created_at, updated_at) VALUES ('u-cond', 'Condition User', 'zh-CN', 'Asia/Shanghai', ?, ?)",
            (now, now),
        )
        conn.execute(
            """
            INSERT INTO user_profile_defaults_v2 (
              user_id, default_currency, default_precision_mode, default_condition_mode,
              default_delivery_mode, default_min_match_score, default_cooldown_hours,
              default_allow_related_matches, default_allow_series_matches, default_allow_variant_matches,
              notes, created_at, updated_at
            ) VALUES (
              'u-cond', 'CNY', 'balanced', 'ignore', 'daily_digest', 70, 24, 0, 0, 1,
              'condition defaults', ?, ?
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
              'interest-cond', 'u-cond', '仕女图条件', 'watch_buy', 'exact_item', 'exact',
              'high', 1.0, 0, 0, 0, 'active', 'condition-sensitive', ?, ?
            )
            """,
            (now, now),
        )
        conn.execute(
            """
            INSERT INTO user_interest_targets_v2 (
              id, interest_id, target_label, target_kind, parse_family, raw_input,
              normalized_name, issue_code_norm, issue_part_token, series_key, theme_name,
              asset_type, variant_tokens_json, quantity_tokens_json, condition_tokens_json,
              year_value, budget_min, budget_max, strictness_override, priority_override,
              is_active, created_at, updated_at, condition_mode
            ) VALUES (
              'target-cond', 'interest-cond', 'T89M仕女图型张新', 'listing_identity', 'stamp_like',
              'T89M仕女图型张新', '仕女图型张', 'T89M', NULL, 'T89M', '仕女图',
              NULL, '["型张","M"]', '[]', '["新","全品"]',
              NULL, NULL, 420, 'exact', 'high', 1, ?, ?, 'require'
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
              'policy-cond', 'interest-cond', 1, 1, 0, 1, 0, 0, 1, 0, 90, 24, 'immediate', 3, ?, ?
            )
            """,
            (now, now),
        )
        conn.commit()

    run_listing_parse_v2(str(db_path))
    result = run_interest_signal_generation(str(db_path), user_id="u-cond", lookback_hours=24)

    with sqlite3.connect(db_path) as conn:
        payload = json.loads(
            conn.execute(
                "SELECT payload_json FROM signals_v2 WHERE user_id = 'u-cond' AND signal_type = 'buy_budget_feasible_by_comps' LIMIT 1"
            ).fetchone()[0]
        )

    assert result.inserted >= 1
    comp_trend = payload["comp_trend"]
    assert comp_trend["pricing_basis"] == "full_fallback"
    assert comp_trend["same_condition_count"] == 1
    assert comp_trend["fallback_condition_count"] >= 1


def test_interest_signals_emit_event_driven_buy_and_sell_signals(tmp_path: Path):
    db_path = tmp_path / "agent_v2.db"
    SqliteV2Store(str(db_path)).ensure_schema()
    now = "2026-03-29T00:00:00+00:00"
    recent = "2026-03-29T11:00:00+00:00"

    with sqlite3.connect(db_path) as conn:
        buy_listing = _insert_listing(
            conn,
            "BUY-EVT-1",
            title="2026年中国龙31.104克普制银币",
            status_raw="2",
            status_norm="live",
            category_name_raw="纪念币-银",
            character_name_raw="评级币",
            updated_at=recent,
        )
        sell_listing = _insert_listing(
            conn,
            "SELL-EVT-1",
            title="T69M红楼梦型张新",
            status_raw="3",
            status_norm="ended",
            category_name_raw="小型（版）张",
            character_name_raw="全品",
            updated_at=recent,
            end_at=recent,
            price_end=580.0,
        )
        conn.execute(
            "INSERT INTO users (id, display_name, language, timezone, created_at, updated_at) VALUES ('u-evt', 'Event User', 'zh-CN', 'Asia/Shanghai', ?, ?)",
            (now, now),
        )
        conn.execute(
            """
            INSERT INTO user_profile_defaults_v2 (
              user_id, default_currency, default_precision_mode, default_condition_mode,
              default_delivery_mode, default_min_match_score, default_cooldown_hours,
              default_allow_related_matches, default_allow_series_matches, default_allow_variant_matches,
              notes, created_at, updated_at
            ) VALUES (
              'u-evt', 'CNY', 'balanced', 'ignore', 'daily_digest', 70, 24, 0, 0, 1,
              'event defaults', ?, ?
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
            ) VALUES
            ('interest-buy', 'u-evt', '龙币买点', 'watch_buy', 'exact_item', 'exact', 'high', 1.0, 0, 0, 0, 'active', '', ?, ?),
            ('interest-sell', 'u-evt', '红楼梦卖点', 'watch_sell', 'exact_item', 'exact', 'high', 1.0, 0, 0, 0, 'active', '', ?, ?)
            """,
            (now, now, now, now),
        )
        conn.execute(
            """
            INSERT INTO user_interest_targets_v2 (
              id, interest_id, target_label, target_kind, parse_family, raw_input,
              normalized_name, issue_code_norm, issue_part_token, series_key, theme_name,
              asset_type, variant_tokens_json, quantity_tokens_json, condition_tokens_json,
              year_value, budget_min, budget_max, strictness_override, priority_override,
              is_active, created_at, updated_at, condition_mode
            ) VALUES
            ('target-buy', 'interest-buy', '2026年中国龙31.104克普制银币', 'listing_identity', 'coin_like',
              '2026年中国龙31.104克普制银币', '中国龙31.104克普制银币', NULL, NULL, '中国龙|银币', '中国龙', '银币',
              '["普制"]', '[]', '["评级币"]', 2026, NULL, 1850, 'exact', 'high', 1, ?, ?, 'require'),
            ('target-sell', 'interest-sell', 'T69M红楼梦型张新', 'listing_identity', 'stamp_like',
              'T69M红楼梦型张新', '红楼梦型张', 'T69M', NULL, 'T69M', '红楼梦', NULL,
              '["型张","M"]', '[]', '["新","全品"]', NULL, NULL, NULL, 'exact', 'high', 1, ?, ?, 'require')
            """,
            (now, now, now, now),
        )
        conn.execute(
            """
            INSERT INTO user_holdings_v2 (
              id, user_id, linked_interest_id, raw_input, parse_family, normalized_name,
              issue_code_norm, issue_part_token, series_key, theme_name, asset_type,
              variant_tokens_json, quantity_tokens_json, condition_tokens_json, year_value,
              holding_quantity, cost_basis_total, cost_basis_unit, notes, is_active, created_at, updated_at
            ) VALUES (
              'holding-sell', 'u-evt', 'interest-sell', 'T69M红楼梦型张新', 'stamp_like', '红楼梦型张',
              'T69M', NULL, 'T69M', '红楼梦', NULL,
              '["型张","M"]', '[]', '["新","全品"]', NULL,
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
            ) VALUES
            ('policy-buy', 'interest-buy', 1, 1, 0, 1, 0, 0, 1, 0, 90, 24, 'immediate', 5, ?, ?),
            ('policy-sell', 'interest-sell', 0, 0, 1, 0, 0, 0, 0, 1, 88, 24, 'immediate', 5, ?, ?)
            """,
            (now, now, now, now),
        )
        conn.execute(
            """
            INSERT INTO listing_matches_v2 (
              id, user_id, listing_id, user_item_id, item_type, relationship_type,
              match_score, identity_score, series_score, variant_score, condition_score,
              matcher_version, match_reasons_json, status, matched_at, updated_at
            ) VALUES
            (?, 'u-evt', ?, 'target-buy', 'watch', 'exact_identity', 120, 90, 20, 5, 5, 'v2_test', '[]', 'active', ?, ?),
            (?, 'u-evt', ?, 'target-sell', 'watch', 'exact_identity', 187, 150, 20, 8, 9, 'v2_test', '[]', 'active', ?, ?)
            """,
            (str(uuid.uuid4()), buy_listing, recent, recent, str(uuid.uuid4()), sell_listing, recent, recent),
        )
        conn.execute(
            """
            INSERT INTO market_listing_events_v2 (
              id, source_platform, source_listing_id, change_time, old_status_raw, new_status_raw, payload_json, created_at
            ) VALUES
            (?, 'zhaoonline', 'BUY-EVT-1', ?, '1', '2', '{}', ?),
            (?, 'zhaoonline', 'SELL-EVT-1', ?, '2', '3', '{}', ?)
            """,
            (str(uuid.uuid4()), recent, recent, str(uuid.uuid4()), recent, recent),
        )
        conn.commit()

    run_listing_parse_v2(str(db_path))
    result = run_interest_signal_generation(str(db_path), user_id="u-evt", lookback_hours=24)

    with sqlite3.connect(db_path) as conn:
        signal_types = [row[0] for row in conn.execute("SELECT signal_type FROM signals_v2 WHERE user_id='u-evt' ORDER BY signal_type")]

    assert result.inserted >= 2
    assert "buy_went_live" in signal_types
    assert "sell_new_ended_comp" in signal_types
