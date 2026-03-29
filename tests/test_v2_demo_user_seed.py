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
                "2026å¹´ä¸­å›½é¾™31.104å…‹æ™®åˆ¶é“¶å¸",
                "3",
                "ended",
                "è¯„çº§å¸",
                "é¦–æ—¥å‘è¡Œ",
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
                "2026å¹´ä¸­å›½é¾™31.104å…‹æ™®åˆ¶é“¶å¸",
                "2",
                "live",
                "è¯„çº§å¸",
                "é¦–æ—¥å‘è¡Œ",
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
                "T69Mçº¢æ¥¼æ¢¦åž‹å¼ æ–°",
                "3",
                "ended",
                "å…¨å“",
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
                "2026å¹´ä¸­å›½é¾™31.104å…‹æ™®åˆ¶é“¶å¸",
                "2026å¹´ä¸­å›½é¾™31.104å…‹æ™®åˆ¶é“¶å¸",
                "2026|ä¸­å›½é¾™|é“¶å¸",
                "ä¸­å›½é¾™|é“¶å¸",
                "æ™®åˆ¶|31.104å…‹",
                "è¯„çº§å¸|é¦–æ—¥å‘è¡Œ",
                None,
                None,
                None,
                None,
                None,
                None,
                2026,
                "ä¸­å›½é¾™",
                "é“¶å¸",
                "æ™®åˆ¶",
                "31.104å…‹",
                None,
                "è¯„çº§å¸",
                "[]",
                "[\"è¯„çº§å¸\"]",
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
                "2026å¹´ä¸­å›½é¾™31.104å…‹æ™®åˆ¶é“¶å¸",
                "2026å¹´ä¸­å›½é¾™31.104å…‹æ™®åˆ¶é“¶å¸",
                "2026|ä¸­å›½é¾™|é“¶å¸",
                "ä¸­å›½é¾™|é“¶å¸",
                "æ™®åˆ¶|31.104å…‹",
                "è¯„çº§å¸|é¦–æ—¥å‘è¡Œ",
                None,
                None,
                None,
                None,
                None,
                None,
                2026,
                "ä¸­å›½é¾™",
                "é“¶å¸",
                "æ™®åˆ¶",
                "31.104å…‹",
                None,
                "è¯„çº§å¸",
                "[]",
                "[\"è¯„çº§å¸\"]",
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
                "T69Mçº¢æ¥¼æ¢¦åž‹å¼ æ–°",
                "T69Mçº¢æ¥¼æ¢¦åž‹å¼ æ–°",
                "T69M|çº¢æ¥¼æ¢¦",
                "T69M",
                "M|åž‹å¼ ",
                "æ–°|å…¨å“",
                "T",
                "T",
                "69",
                "M",
                "T69M",
                "çº¢æ¥¼æ¢¦",
                None,
                "çº¢æ¥¼æ¢¦",
                None,
                None,
                None,
                None,
                "å…¨å“",
                "[\"åž‹å¼ \",\"M\"]",
                "[\"æ–°\"]",
                "[]",
                now,
                now,
            ),
        )
        conn.commit()

    specs = (
        DemoInterestSpec(
            seed_title="2026å¹´ä¸­å›½é¾™31.104å…‹æ™®åˆ¶é“¶å¸",
            interest_name="ä¸­å›½é¾™æŠ¢æ‹",
            interest_kind="watch_buy",
            scope_kind="exact_item",
            precision_mode="exact",
            interest_priority="high",
            allow_related_matches=0,
            allow_series_matches=0,
            allow_variant_matches=0,
            target_label="2026å¹´ä¸­å›½é¾™31.104å…‹æ™®åˆ¶é“¶å¸",
            target_kind="listing_identity",
            normalized_name="ä¸­å›½é¾™æ™®åˆ¶é“¶å¸",
            use_issue_code_norm=False,
            use_issue_part_token=False,
            use_series_key=True,
            use_theme_name=True,
            use_asset_type=True,
            use_year_value=True,
            variant_tokens=("æ™®åˆ¶", "31.104å…‹"),
            quantity_tokens=(),
            condition_tokens=("è¯„çº§å¸",),
            condition_mode="require",
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
            seed_title="T69Mçº¢æ¥¼æ¢¦åž‹å¼ æ–°",
            interest_name="çº¢æ¥¼æ¢¦å–ç‚¹",
            interest_kind="watch_sell",
            scope_kind="exact_item",
            precision_mode="exact",
            interest_priority="high",
            allow_related_matches=0,
            allow_series_matches=0,
            allow_variant_matches=0,
            target_label="T69Mçº¢æ¥¼æ¢¦åž‹å¼ æ–°",
            target_kind="listing_identity",
            normalized_name="çº¢æ¥¼æ¢¦åž‹å¼ ",
            use_issue_code_norm=True,
            use_issue_part_token=False,
            use_series_key=True,
            use_theme_name=True,
            use_asset_type=False,
            use_year_value=False,
            variant_tokens=("åž‹å¼ ", "M"),
            quantity_tokens=(),
            condition_tokens=("æ–°", "å…¨å“"),
            condition_mode="require",
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
            "SELECT target_label, series_key, theme_name, asset_type, year_value FROM user_interest_targets_v2 WHERE target_label = '2026å¹´ä¸­å›½é¾™31.104å…‹æ™®åˆ¶é“¶å¸'"
        ).fetchone()

    assert defaults_count == 1
    assert interests == [
        ("ä¸­å›½é¾™æŠ¢æ‹", "watch_buy", "exact_item"),
        ("çº¢æ¥¼æ¢¦å–ç‚¹", "watch_sell", "exact_item"),
    ]
    assert holdings == [("T69Mçº¢æ¥¼æ¢¦åž‹å¼ æ–°", 480.0, 480.0)]
    assert target == ("2026å¹´ä¸­å›½é¾™31.104å…‹æ™®åˆ¶é“¶å¸", "ä¸­å›½é¾™|é“¶å¸", "ä¸­å›½é¾™", "é“¶å¸", 2026)
