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
              asset_type, variant_tokens_json, quantity_tokens_json, condition_tokens_json, condition_mode,
              year_value, budget_min, budget_max, strictness_override, priority_override,
              is_active, created_at, updated_at
            ) VALUES (
              'target-1', 'interest-1', 'T43西游记', 'issue_family', 'stamp_like', 'T43西游记新全',
              '西游记', 'T43', NULL, 'T43', '西游记',
              NULL, '[]', '[]', '[\"新全\"]', 'prefer',
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
            "UPDATE market_listings_norm_v2 SET character_name_raw = '评级币' WHERE id = ?",
            (plain_coin_id,),
        )

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
              asset_type, variant_tokens_json, quantity_tokens_json, condition_tokens_json, condition_mode,
              year_value, budget_min, budget_max, strictness_override, priority_override,
              is_active, created_at, updated_at
            ) VALUES
            (
              'target-coin', 'interest-coin', '2026年中国龙31.104克普制银币', 'listing_identity', 'coin_like',
              '2026年中国龙31.104克普制银币', '中国龙普制银币', NULL, NULL, '中国龙|银币', '中国龙',
              '银币', '[\"普制\",\"31.104克\"]', '[]', '[\"评级币\"]', 'require',
              2026, NULL, 1850, 'exact', 'high', 1, ?, ?
            ),
            (
              'target-stamp', 'interest-stamp', 'T43西游记', 'issue_family', 'stamp_like',
              'T43西游记新全', '西游记', 'T43', NULL, 'T43', '西游记',
              NULL, '[]', '[]', '[\"新全\"]', 'prefer',
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


def test_stamp_interest_can_match_by_issue_name_only_when_target_parse_family_is_explicit(tmp_path: Path):
    db_path = tmp_path / "agent_v2.db"
    SqliteV2Store(str(db_path)).ensure_schema()
    now = "2026-03-27T00:00:00+00:00"

    with sqlite3.connect(db_path) as conn:
        listing_id = _insert_listing(conn, "L-1", title="T43西游记新全", category_name_raw="JT邮票")
        _insert_listing(conn, "L-2", title="T44齐白石新全", category_name_raw="JT邮票")
        conn.execute(
            """
            INSERT INTO users (id, display_name, language, timezone, created_at, updated_at)
            VALUES ('u-name-only', 'Name Only User', 'zh-CN', 'Asia/Shanghai', ?, ?)
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
              'interest-name-only', 'u-name-only', '西游记', 'watch_buy', 'issue_family', 'balanced',
              'high', 0.9, 0, 0, 1, 'active', ?, ?
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
              'target-name-only', 'interest-name-only', '西游记', 'issue_family', 'stamp_like',
              '西游记', '西游记', NULL, NULL, '西游记', '西游记',
              NULL, '[]', '[]', '[]', 'ignore',
              NULL, NULL, NULL, 'balanced', 'high', 1, ?, ?
            )
            """,
            (now, now),
        )
        conn.commit()

    run_listing_parse_v2(str(db_path))
    result = run_v2_matching(str(db_path), user_id="u-name-only")

    assert result.matched_pairs == 1

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT user_item_id, listing_id, relationship_type
            FROM listing_matches_v2
            WHERE user_id = 'u-name-only'
            """
        ).fetchone()

    assert row == ("target-name-only", listing_id, "exact_identity")


def test_trusted_stamp_scope_excludes_composite_bundle_titles(tmp_path: Path):
    db_path = tmp_path / "agent_v2.db"
    SqliteV2Store(str(db_path)).ensure_schema()
    now = "2026-03-27T00:00:00+00:00"

    with sqlite3.connect(db_path) as conn:
        listing_id = _insert_listing(conn, "L-1", title="T43西游记新全", category_name_raw="JT邮票")
        _insert_listing(conn, "L-2", title="J13、J19、J21总公司邮折各一件", category_name_raw="中国邮票-其他")
        conn.execute(
            """
            INSERT INTO users (id, display_name, language, timezone, created_at, updated_at)
            VALUES ('u-trusted', 'Trusted User', 'zh-CN', 'Asia/Shanghai', ?, ?)
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
              'interest-trusted', 'u-trusted', '西游记补全', 'watch_buy', 'issue_family', 'balanced',
              'high', 0.9, 0, 0, 1, 'active', ?, ?
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
              'target-trusted', 'interest-trusted', 'T43西游记', 'issue_family', 'stamp_like',
              'T43西游记新全', '西游记', 'T43', NULL, 'T43', '西游记',
              NULL, '[]', '[]', '[\"新全\"]', 'prefer',
              NULL, NULL, NULL, 'balanced', 'high', 1, ?, ?
            )
            """,
            (now, now),
        )
        conn.commit()

    run_listing_parse_v2(str(db_path))
    result = run_v2_matching(str(db_path), user_id="u-trusted")

    assert result.matched_pairs == 1

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT listing_id
            FROM listing_matches_v2
            WHERE user_id = 'u-trusted'
            ORDER BY listing_id
            """
        ).fetchall()

    assert rows == [(listing_id,)]


def test_stamp_interest_can_match_by_issue_code_only(tmp_path: Path):
    db_path = tmp_path / "agent_v2.db"
    SqliteV2Store(str(db_path)).ensure_schema()
    now = "2026-03-27T00:00:00+00:00"

    with sqlite3.connect(db_path) as conn:
        listing_id = _insert_listing(conn, "L-1", title="纪43中国陶瓷新全", category_name_raw="纪特邮票")
        _insert_listing(conn, "L-2", title="纪44新全", category_name_raw="纪特邮票")
        conn.execute(
            """
            INSERT INTO users (id, display_name, language, timezone, created_at, updated_at)
            VALUES ('u-code-only', 'Code Only User', 'zh-CN', 'Asia/Shanghai', ?, ?)
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
              'interest-code-only', 'u-code-only', '纪43', 'watch_buy', 'issue_family', 'balanced',
              'high', 0.9, 0, 0, 1, 'active', ?, ?
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
              'target-code-only', 'interest-code-only', '纪43', 'issue_family', 'stamp_like',
              '纪43', NULL, 'J43', NULL, 'J43', NULL,
              NULL, '[]', '[]', '[]', 'ignore',
              NULL, NULL, NULL, 'balanced', 'high', 1, ?, ?
            )
            """,
            (now, now),
        )
        conn.commit()

    run_listing_parse_v2(str(db_path))
    result = run_v2_matching(str(db_path), user_id="u-code-only")

    assert result.matched_pairs == 1

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT user_item_id, listing_id, relationship_type
            FROM listing_matches_v2
            WHERE user_id = 'u-code-only'
            """
        ).fetchone()

    assert row == ("target-code-only", listing_id, "exact_identity")


def test_exact_stamp_interest_respects_condition_requirements(tmp_path: Path):
    db_path = tmp_path / "agent_v2.db"
    SqliteV2Store(str(db_path)).ensure_schema()
    now = "2026-03-27T00:00:00+00:00"

    with sqlite3.connect(db_path) as conn:
        full_quality_id = _insert_listing(conn, "L-1", title="T89M仕女图型张新", category_name_raw="小型（版）张")
        lower_quality_id = _insert_listing(conn, "L-2", title="T89M仕女图型张新", category_name_raw="小型（版）张")
        cancelled_id = _insert_listing(conn, "L-3", title="T89M仕女图型张盖", category_name_raw="小型（版）张")
        conn.execute(
            "UPDATE market_listings_norm_v2 SET character_name_raw = '全品' WHERE id = ?",
            (full_quality_id,),
        )
        conn.execute(
            "UPDATE market_listings_norm_v2 SET character_name_raw = '上品' WHERE id = ?",
            (lower_quality_id,),
        )
        conn.execute(
            "UPDATE market_listings_norm_v2 SET character_name_raw = '全品' WHERE id = ?",
            (cancelled_id,),
        )
        conn.execute(
            """
            INSERT INTO users (id, display_name, language, timezone, created_at, updated_at)
            VALUES ('u-condition', 'Condition User', 'zh-CN', 'Asia/Shanghai', ?, ?)
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
              'interest-condition', 'u-condition', '仕女图型张只收全品', 'watch_buy', 'exact_item', 'exact',
              'high', 0.95, 0, 0, 0, 'active', ?, ?
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
              'target-condition', 'interest-condition', 'T89M仕女图型张新', 'listing_identity', 'stamp_like',
              'T89M仕女图型张新', '仕女图型张', 'T89M', NULL, 'T89M', '仕女图',
              NULL, '[\"型张\",\"M\"]', '[]', '[\"新\",\"全品\"]', 'require',
              NULL, NULL, 420, 'exact', 'high', 1, ?, ?
            )
            """,
            (now, now),
        )
        conn.commit()

    run_listing_parse_v2(str(db_path))
    result = run_v2_matching(str(db_path), user_id="u-condition")

    assert result.matched_pairs == 1

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT listing_id, relationship_type
            FROM listing_matches_v2
            WHERE user_id = 'u-condition'
            ORDER BY listing_id
            """
        ).fetchall()

    assert rows == [(full_quality_id, "exact_identity")]
