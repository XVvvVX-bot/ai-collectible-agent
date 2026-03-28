from __future__ import annotations

import sqlite3
from pathlib import Path

from ai_agent_v2.profile.demo_user_seed import DemoInterestSpec, DEMO_USER_ID, seed_curated_demo_user_v2
from ai_agent_v2.storage.sqlite_store import SqliteV2Store


def test_seed_curated_demo_user_resets_profile_layer_and_inserts_curated_interests(tmp_path: Path):
    db_path = tmp_path / "agent_v2.db"
    SqliteV2Store(str(db_path)).ensure_schema()
    now = "2026-03-27T00:00:00+00:00"

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO users (id, display_name, language, timezone, created_at, updated_at)
            VALUES ('legacy-u', 'Legacy', 'zh-CN', 'Asia/Shanghai', ?, ?)
            """,
            (now, now),
        )
        conn.execute(
            """
            INSERT INTO user_profile_defaults_v2 (
              user_id, created_at, updated_at
            ) VALUES ('legacy-u', ?, ?)
            """,
            (now, now),
        )
        conn.execute(
            """
            INSERT INTO market_listings_norm_v2 (
              id, source_platform, source_listing_id, title, status_raw, status_norm,
              character_name_raw, description_character, price_end, end_at,
              first_seen_at, last_seen_at, created_at, updated_at
            ) VALUES (?, 'zhaoonline', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "dragon-ended",
                "dragon-ended-src",
                "2026年中国龙31.104克普制银币",
                "3",
                "ended",
                "评级币",
                "首日发行",
                1740.0,
                now,
                now,
                now,
                now,
                now,
            ),
        )
        conn.execute(
            """
            INSERT INTO market_listings_norm_v2 (
              id, source_platform, source_listing_id, title, status_raw, status_norm,
              character_name_raw, description_character, price_end, end_at,
              first_seen_at, last_seen_at, created_at, updated_at
            ) VALUES (?, 'zhaoonline', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "dragon-live",
                "dragon-live-src",
                "2026年中国龙31.104克普制银币",
                "2",
                "live",
                "评级币",
                "首日发行",
                1600.0,
                None,
                now,
                now,
                now,
                now,
            ),
        )
        conn.execute(
            """
            INSERT INTO market_listings_norm_v2 (
              id, source_platform, source_listing_id, title, status_raw, status_norm,
              character_name_raw, description_character, price_end, end_at,
              first_seen_at, last_seen_at, created_at, updated_at
            ) VALUES (?, 'zhaoonline', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "red-ended",
                "red-ended-src",
                "T69M红楼梦型张新",
                "3",
                "ended",
                "全品",
                None,
                580.0,
                now,
                now,
                now,
                now,
                now,
            ),
        )
        conn.execute(
            """
            INSERT INTO listing_parse_v2 (
              listing_id, source_platform, source_listing_id, parser_version, parse_family, raw_title,
              title_normalized, identity_core, series_key, variant_key, condition_key, code_prefix_raw,
              code_prefix_norm, code_number, code_suffix, issue_code_norm, issue_name, year_value,
              theme_name, asset_type, finish_type, weight_text, denomination_text, character_condition,
              variant_tokens_json, condition_tokens_json, quantity_tokens_json, parse_confidence, parse_notes_json,
              created_at, updated_at
            ) VALUES (
              ?, 'zhaoonline', ?, 'test', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0.9, '[]', ?, ?
            )
            """,
            (
                "dragon-ended",
                "dragon-ended-src",
                "coin_like",
                "2026年中国龙31.104克普制银币",
                "2026年中国龙31.104克普制银币",
                "2026|中国龙|银币",
                "中国龙|银币",
                "普制|31.104克",
                "评级币|首日发行",
                None,
                None,
                None,
                None,
                None,
                None,
                2026,
                "中国龙",
                "银币",
                "普制",
                "31.104克",
                None,
                "评级币",
                "[]",
                "[\"评级币\"]",
                "[]",
                now,
                now,
            ),
        )
        conn.execute(
            """
            INSERT INTO listing_parse_v2 (
              listing_id, source_platform, source_listing_id, parser_version, parse_family, raw_title,
              title_normalized, identity_core, series_key, variant_key, condition_key, code_prefix_raw,
              code_prefix_norm, code_number, code_suffix, issue_code_norm, issue_name, year_value,
              theme_name, asset_type, finish_type, weight_text, denomination_text, character_condition,
              variant_tokens_json, condition_tokens_json, quantity_tokens_json, parse_confidence, parse_notes_json,
              created_at, updated_at
            ) VALUES (
              ?, 'zhaoonline', ?, 'test', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0.9, '[]', ?, ?
            )
            """,
            (
                "dragon-live",
                "dragon-live-src",
                "coin_like",
                "2026年中国龙31.104克普制银币",
                "2026年中国龙31.104克普制银币",
                "2026|中国龙|银币",
                "中国龙|银币",
                "普制|31.104克",
                "评级币|首日发行",
                None,
                None,
                None,
                None,
                None,
                None,
                2026,
                "中国龙",
                "银币",
                "普制",
                "31.104克",
                None,
                "评级币",
                "[]",
                "[\"评级币\"]",
                "[]",
                now,
                now,
            ),
        )
        conn.execute(
            """
            INSERT INTO listing_parse_v2 (
              listing_id, source_platform, source_listing_id, parser_version, parse_family, raw_title,
              title_normalized, identity_core, series_key, variant_key, condition_key, code_prefix_raw,
              code_prefix_norm, code_number, code_suffix, issue_code_norm, issue_name, year_value,
              theme_name, asset_type, finish_type, weight_text, denomination_text, character_condition,
              variant_tokens_json, condition_tokens_json, quantity_tokens_json, parse_confidence, parse_notes_json,
              created_at, updated_at
            ) VALUES (
              ?, 'zhaoonline', ?, 'test', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0.9, '[]', ?, ?
            )
            """,
            (
                "red-ended",
                "red-ended-src",
                "stamp_like",
                "T69M红楼梦型张新",
                "T69M红楼梦型张新",
                "T69M|红楼梦",
                "T69M",
                "M|型张",
                "新|全品",
                "T",
                "T",
                "69",
                "M",
                "T69M",
                "红楼梦",
                None,
                "红楼梦",
                None,
                None,
                None,
                None,
                "全品",
                "[\"型张\",\"M\"]",
                "[\"新\"]",
                "[]",
                now,
                now,
            ),
        )
        conn.commit()

    specs = (
        DemoInterestSpec(
            seed_title="2026年中国龙31.104克普制银币",
            interest_name="中国龙抢拍",
            interest_kind="watch_buy",
            scope_kind="exact_item",
            precision_mode="exact",
            interest_priority="high",
            allow_related_matches=0,
            allow_series_matches=0,
            allow_variant_matches=0,
            target_label="2026年中国龙31.104克普制银币",
            target_kind="listing_identity",
            normalized_name="中国龙普制银币",
            use_issue_code_norm=False,
            use_issue_part_token=False,
            use_series_key=True,
            use_theme_name=True,
            use_asset_type=True,
            use_year_value=True,
            variant_tokens=("普制", "31.104克"),
            quantity_tokens=(),
            condition_tokens=("评级币",),
            budget_min=None,
            budget_max=1800.0,
            strictness_override="exact",
            priority_override="high",
            intent_confidence=0.95,
            policy_notify_on_preview=1,
            policy_notify_on_live=1,
            policy_notify_on_ended=0,
            policy_notify_on_exact_match=1,
            policy_notify_on_variant_match=0,
            policy_notify_on_series_match=0,
            policy_notify_on_price_opportunity=1,
            policy_notify_on_sell_opportunity=0,
            policy_min_match_score=90.0,
            policy_cooldown_hours=6,
            policy_delivery_mode="immediate",
            policy_max_signals_per_day=5,
        ),
        DemoInterestSpec(
            seed_title="T69M红楼梦型张新",
            interest_name="红楼梦卖点",
            interest_kind="watch_sell",
            scope_kind="exact_item",
            precision_mode="exact",
            interest_priority="high",
            allow_related_matches=0,
            allow_series_matches=0,
            allow_variant_matches=0,
            target_label="T69M红楼梦型张新",
            target_kind="listing_identity",
            normalized_name="红楼梦型张",
            use_issue_code_norm=True,
            use_issue_part_token=False,
            use_series_key=True,
            use_theme_name=True,
            use_asset_type=False,
            use_year_value=False,
            variant_tokens=("型张", "M"),
            quantity_tokens=(),
            condition_tokens=("新", "全品"),
            budget_min=None,
            budget_max=None,
            strictness_override="exact",
            priority_override="high",
            intent_confidence=0.93,
            policy_notify_on_preview=0,
            policy_notify_on_live=0,
            policy_notify_on_ended=1,
            policy_notify_on_exact_match=0,
            policy_notify_on_variant_match=0,
            policy_notify_on_series_match=0,
            policy_notify_on_price_opportunity=0,
            policy_notify_on_sell_opportunity=1,
            policy_min_match_score=88.0,
            policy_cooldown_hours=12,
            policy_delivery_mode="immediate",
            policy_max_signals_per_day=3,
            holding_quantity=1.0,
            cost_basis_unit=480.0,
        ),
    )

    result = seed_curated_demo_user_v2(
        str(db_path),
        clear_existing_profile_layer=True,
        specs=specs,
    )

    assert result.user_id == DEMO_USER_ID
    assert result.profile_tables_cleared is True
    assert result.interests_upserted == 2
    assert result.targets_upserted == 2
    assert result.holdings_upserted == 1
    assert result.policies_upserted == 2
    assert result.selections[0].overall_count == 2
    assert result.selections[0].ended_count == 1

    with sqlite3.connect(db_path) as conn:
        defaults_count = conn.execute("SELECT COUNT(*) FROM user_profile_defaults_v2").fetchone()[0]
        interests = conn.execute(
            "SELECT interest_name, interest_kind, scope_kind FROM user_interests_v2 ORDER BY interest_name"
        ).fetchall()
        holdings = conn.execute(
            "SELECT raw_input, cost_basis_total, cost_basis_unit FROM user_holdings_v2"
        ).fetchall()
        target = conn.execute(
            "SELECT target_label, series_key, theme_name, asset_type, year_value FROM user_interest_targets_v2 WHERE target_label = '2026年中国龙31.104克普制银币'"
        ).fetchone()

    assert defaults_count == 1
    assert interests == [
        ("中国龙抢拍", "watch_buy", "exact_item"),
        ("红楼梦卖点", "watch_sell", "exact_item"),
    ]
    assert holdings == [("T69M红楼梦型张新", 480.0, 480.0)]
    assert target == ("2026年中国龙31.104克普制银币", "中国龙|银币", "中国龙", "银币", 2026)
