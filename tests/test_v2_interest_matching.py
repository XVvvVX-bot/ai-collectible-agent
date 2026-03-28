from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

from ai_agent_v2.matching.v2_matcher import run_v2_matching
from ai_agent_v2.parsing.listing_parser import run_listing_parse_v2
from ai_agent_v2.storage.sqlite_store import SqliteV2Store


def _insert_listing(
    conn: sqlite3.Connection,
    source_listing_id: str,
    *,
    title: str,
    category_name_raw: str,
) -> str:
    listing_id = str(uuid.uuid4())
    now = "2026-03-27T00:00:00+00:00"
    conn.execute(
        """
        INSERT INTO market_listings_norm_v2 (
          id, source_platform, source_listing_id, title, status_raw, status_norm,
          category_name_raw, first_seen_at, last_seen_at, created_at, updated_at
        ) VALUES (?, 'zhaoonline', ?, ?, '2', 'live', ?, ?, ?, ?, ?)
        """,
        (listing_id, source_listing_id, title, category_name_raw, now, now, now, now),
    )
    return listing_id


def test_matching_reads_v2_interest_targets_without_legacy_user_items(tmp_path: Path):
    db_path = tmp_path / "agent_v2.db"
    SqliteV2Store(str(db_path)).ensure_schema()
    now = "2026-03-27T00:00:00+00:00"

    with sqlite3.connect(db_path) as conn:
        exact_listing_id = _insert_listing(conn, "L-1", title="T43西游记新全", category_name_raw="JT邮票")
        _insert_listing(conn, "L-2", title="T44齐白石新全", category_name_raw="JT邮票")

        conn.execute(
            """
            INSERT INTO users (id, display_name, language, timezone, created_at, updated_at)
            VALUES ('u-interest', 'Interest User', 'zh-CN', 'Asia/Shanghai', ?, ?)
            """,
            (now, now),
        )
        conn.execute(
            """
            INSERT INTO user_interests_v2 (
              id, user_id, interest_name, interest_kind, scope_kind, precision_mode,
              interest_priority, intent_confidence, allow_related_matches, allow_series_matches,
              allow_variant_matches, active_status, created_at, updated_at
            ) VALUES (
              'interest-1', 'u-interest', '西游记补全', 'collecting', 'issue_family', 'balanced',
              'high', 0.8, 0, 0, 1, 'active', ?, ?
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
              is_active, created_at, updated_at
            ) VALUES (
              'target-1', 'interest-1', 'T43西游记', 'issue_family', 'stamp_like', 'T43西游记新全',
              '西游记', 'T43', NULL, 'T43', '西游记',
              NULL, '[]', '[]', '[\"新全\"]',
              NULL, NULL, 260, 'balanced', 'high',
              1, ?, ?
            )
            """,
            (now, now),
        )
        conn.commit()

    run_listing_parse_v2(str(db_path))
    result = run_v2_matching(str(db_path), user_id="u-interest")

    assert result.users_processed == 1
    assert result.items_scanned == 1
    assert result.matched_pairs == 1

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT user_item_id, item_type, relationship_type, listing_id
            FROM listing_matches_v2
            WHERE user_id = 'u-interest'
            """
        ).fetchone()

    assert row == ("target-1", "watch", "exact_identity", exact_listing_id)


def test_exact_coin_interest_rejects_packaging_variants_and_stamp_code_name_collisions(tmp_path: Path):
    db_path = tmp_path / "agent_v2.db"
    SqliteV2Store(str(db_path)).ensure_schema()
    now = "2026-03-27T00:00:00+00:00"

    with sqlite3.connect(db_path) as conn:
        plain_coin_id = _insert_listing(conn, "C-1", title="2026年中国龙31.104克普制银币", category_name_raw="纪念币-银")
        _insert_listing(conn, "C-2", title="2026年中国龙31.104克普制银币（卡册）", category_name_raw="纪念币-银")
        _insert_listing(conn, "C-3", title="2026年中国龙31.104克普制银币十枚", category_name_raw="纪念币-银")
        exact_stamp_id = _insert_listing(conn, "S-1", title="T43西游记新全", category_name_raw="JT邮票")
        _insert_listing(conn, "S-2", title="特43卫生新全", category_name_raw="纪特邮票")

        conn.execute(
            """
            INSERT INTO users (id, display_name, language, timezone, created_at, updated_at)
            VALUES ('u-exact', 'Exact User', 'zh-CN', 'Asia/Shanghai', ?, ?)
            """,
            (now, now),
        )
        conn.execute(
            """
            INSERT INTO user_interests_v2 (
              id, user_id, interest_name, interest_kind, scope_kind, precision_mode,
              interest_priority, intent_confidence, allow_related_matches, allow_series_matches,
              allow_variant_matches, active_status, created_at, updated_at
            ) VALUES
            ('interest-coin', 'u-exact', '龙银币抢拍', 'watch_buy', 'exact_item', 'exact', 'high', 0.95, 0, 0, 0, 'active', ?, ?),
            ('interest-stamp', 'u-exact', '西游记标准套票', 'watch_buy', 'issue_family', 'balanced', 'high', 0.8, 0, 0, 1, 'active', ?, ?)
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
              is_active, created_at, updated_at
            ) VALUES
            (
              'target-coin', 'interest-coin', '2026年中国龙31.104克普制银币', 'listing_identity', 'coin_like',
              '2026年中国龙31.104克普制银币', '中国龙普制银币', NULL, NULL, '中国龙|银币', '中国龙',
              '银币', '[\"普制\",\"31.104克\"]', '[]', '[\"评级币\"]',
              2026, NULL, 1850, 'exact', 'high', 1, ?, ?
            ),
            (
              'target-stamp', 'interest-stamp', 'T43西游记', 'issue_family', 'stamp_like',
              'T43西游记新全', '西游记', 'T43', NULL, 'T43', '西游记',
              NULL, '[]', '[]', '[\"新全\"]',
              NULL, NULL, 260, 'balanced', 'high', 1, ?, ?
            )
            """,
            (now, now, now, now),
        )
        conn.commit()

    run_listing_parse_v2(str(db_path))
    result = run_v2_matching(str(db_path), user_id="u-exact")

    assert result.matched_pairs == 2

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT user_item_id, listing_id, relationship_type
            FROM listing_matches_v2
            WHERE user_id = 'u-exact'
            ORDER BY user_item_id, listing_id
            """
        ).fetchall()

    assert rows == [
        ("target-coin", plain_coin_id, "exact_identity"),
        ("target-stamp", exact_stamp_id, "exact_identity"),
    ]
