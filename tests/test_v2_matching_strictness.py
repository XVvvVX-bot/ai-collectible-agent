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


def test_part_specific_stamp_items_only_match_same_part(tmp_path: Path):
    db_path = tmp_path / "agent_v2.db"
    SqliteV2Store(str(db_path)).ensure_schema()

    with sqlite3.connect(db_path) as conn:
        same_part_id = _insert_listing(conn, "L-1", title="纪94（8-1）新", category_name_raw="邮票")
        _insert_listing(conn, "L-2", title="纪94（8-2）新", category_name_raw="邮票")
        _insert_listing(conn, "L-3", title="纪94梅兰芳新全", category_name_raw="邮票")
        conn.execute(
            """
            INSERT INTO users (id, display_name, language, timezone, created_at, updated_at)
            VALUES ('u-1', 'Tester', 'zh-CN', 'Asia/Shanghai', '2026-03-27T00:00:00+00:00', '2026-03-27T00:00:00+00:00')
            """
        )
        conn.execute(
            """
            INSERT INTO user_items (
              id, user_id, item_type, category, series, item_name, is_active, dedupe_key, created_at, updated_at
            ) VALUES ('item-1', 'u-1', 'watch', '邮票', 'J94', '纪94（8-1）新', 1, '邮票|j94|纪94（8-1）新||', '2026-03-27T00:00:00+00:00', '2026-03-27T00:00:00+00:00')
            """
        )
        conn.commit()

    run_listing_parse_v2(str(db_path))
    result = run_v2_matching(str(db_path), user_id="u-1")
    assert result.matched_pairs == 1

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT listing_id, relationship_type FROM listing_matches_v2 WHERE user_item_id = 'item-1'"
        ).fetchone()
    assert row == (same_part_id, "exact_identity")


def test_issue_level_stamp_items_require_compatible_quantity_and_edition_tokens(tmp_path: Path):
    db_path = tmp_path / "agent_v2.db"
    SqliteV2Store(str(db_path)).ensure_schema()

    with sqlite3.connect(db_path) as conn:
        exact_id = _insert_listing(conn, "L-1", title="T130泰山新28套（一版）", category_name_raw="邮票")
        _insert_listing(conn, "L-2", title="T130泰山新56套（二版）", category_name_raw="邮票")
        _insert_listing(conn, "L-3", title="T130泰山新全", category_name_raw="邮票")
        conn.execute(
            """
            INSERT INTO users (id, display_name, language, timezone, created_at, updated_at)
            VALUES ('u-1', 'Tester', 'zh-CN', 'Asia/Shanghai', '2026-03-27T00:00:00+00:00', '2026-03-27T00:00:00+00:00')
            """
        )
        conn.execute(
            """
            INSERT INTO user_items (
              id, user_id, item_type, category, series, item_name, is_active, dedupe_key, created_at, updated_at
            ) VALUES ('item-1', 'u-1', 'watch', '邮票', 'T130', 'T130泰山新28套（一版）', 1, '邮票|t130|T130泰山新28套（一版）||', '2026-03-27T00:00:00+00:00', '2026-03-27T00:00:00+00:00')
            """
        )
        conn.commit()

    run_listing_parse_v2(str(db_path))
    result = run_v2_matching(str(db_path), user_id="u-1")
    assert result.matched_pairs == 1

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT listing_id, relationship_type FROM listing_matches_v2 WHERE user_item_id = 'item-1'"
        ).fetchone()
    assert row == (exact_id, "exact_identity")
