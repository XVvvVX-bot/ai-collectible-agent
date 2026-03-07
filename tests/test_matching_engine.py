from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path

from ai_agent.matching.v1_matcher import run_v1_matching
from ai_agent.storage.sqlite_raw_store import SqliteRawStore
from ai_agent.user_domain import UserDomainService


def _insert_norm_row(
    conn: sqlite3.Connection,
    source_listing_id: str,
    *,
    title: str,
    category_norm: str | None = None,
    category_raw: str | None = None,
    series_norm: str | None = None,
    series_raw: str | None = None,
    grade_norm: str | None = None,
    grade_raw: str | None = None,
    is_active: int = 1,
) -> str:
    listing_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO market_listings_norm (
          id,
          source_platform,
          source_listing_id,
          title,
          category_raw,
          category_norm,
          series_raw,
          series_norm,
          grade_raw,
          grade_norm,
          currency,
          is_active,
          first_seen_at,
          last_seen_at,
          created_at,
          updated_at
        ) VALUES (?, 'zhaoonline', ?, ?, ?, ?, ?, ?, ?, ?, 'CNY', ?, ?, ?, ?, ?)
        """,
        (
            listing_id,
            source_listing_id,
            title,
            category_raw,
            category_norm,
            series_raw,
            series_norm,
            grade_raw,
            grade_norm,
            is_active,
            "2026-03-07T00:00:00+00:00",
            "2026-03-07T00:00:00+00:00",
            "2026-03-07T00:00:00+00:00",
            "2026-03-07T00:00:00+00:00",
        ),
    )
    return listing_id


def test_matching_engine_generates_transparent_reasons_and_score(tmp_path: Path):
    db_path = tmp_path / "agent.db"
    SqliteRawStore(str(db_path)).ensure_schema()
    service = UserDomainService(str(db_path))
    service.upsert_user("u-1")
    item = service.upsert_user_item(
        "u-1",
        "watch",
        category="stamp",
        series="t46",
        item_name="Monkey Ticket",
        year=1980,
        grade_condition="vf",
        priority="high",
    )

    with sqlite3.connect(db_path) as conn:
        listing_id = _insert_norm_row(
            conn,
            "L-100",
            title="1980 Monkey Ticket VF",
            category_norm="stamp",
            series_norm="t46",
            grade_norm="vf",
            is_active=1,
        )
        conn.commit()

    result = run_v1_matching(str(db_path), user_id="u-1", min_score=30.0, strict_name_match=False)
    assert result.matched_pairs == 1
    assert result.inserted == 1
    assert result.updated == 0
    assert result.deactivated == 0

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT listing_id, user_item_id, match_score, match_reasons_json, status
            FROM listing_matches
            WHERE user_id = 'u-1'
            """
        ).fetchone()
    assert row is not None
    assert row[0] == listing_id
    assert row[1] == item.id
    assert float(row[2]) == 100.0
    assert json.loads(str(row[3])) == [
        "category_exact",
        "series_exact",
        "item_name_phrase",
        "grade_exact",
    ]
    assert row[4] == "active"


def test_matching_engine_is_deterministic_and_deactivates_stale(tmp_path: Path):
    db_path = tmp_path / "agent.db"
    SqliteRawStore(str(db_path)).ensure_schema()
    service = UserDomainService(str(db_path))
    service.upsert_user("u-1")
    service.upsert_user_item(
        "u-1",
        "holding",
        category="coin",
        series="panda",
        item_name="1983 Panda 1oz",
        year=1983,
        quantity=1,
    )

    with sqlite3.connect(db_path) as conn:
        _insert_norm_row(
            conn,
            "L-1",
            title="1983 Panda 1oz",
            category_norm="coin",
            series_norm="panda",
            is_active=1,
        )
        conn.commit()

    first = run_v1_matching(str(db_path), user_id="u-1", min_score=30.0, strict_name_match=False)
    second = run_v1_matching(str(db_path), user_id="u-1", min_score=30.0, strict_name_match=False)
    assert first.inserted == 1
    assert second.inserted == 0
    assert second.updated == 0
    assert second.deactivated == 0

    service.deactivate_missing_user_items("u-1", "holding", keep_dedupe_keys=[])
    third = run_v1_matching(str(db_path), user_id="u-1", min_score=30.0, strict_name_match=False)
    assert third.matched_pairs == 0
    assert third.deactivated == 1

    with sqlite3.connect(db_path) as conn:
        status = conn.execute(
            "SELECT status FROM listing_matches WHERE user_id = 'u-1'"
        ).fetchone()[0]
    assert status == "inactive"


def test_matching_engine_strict_name_match_requires_exact_normalized_name(tmp_path: Path):
    db_path = tmp_path / "agent.db"
    SqliteRawStore(str(db_path)).ensure_schema()
    service = UserDomainService(str(db_path))
    service.upsert_user("u-1")
    service.upsert_user_item(
        "u-1",
        "watch",
        category="stamp",
        series="t46",
        item_name="Monkey Ticket",
        priority="high",
    )

    with sqlite3.connect(db_path) as conn:
        _insert_norm_row(
            conn,
            "L-exact",
            title="Monkey Ticket",
            category_norm="stamp",
            series_norm="t46",
            is_active=1,
        )
        _insert_norm_row(
            conn,
            "L-phrase-only",
            title="1980 Monkey Ticket VF",
            category_norm="stamp",
            series_norm="t46",
            is_active=1,
        )
        conn.commit()

    strict_result = run_v1_matching(str(db_path), user_id="u-1", strict_name_match=True)
    assert strict_result.matched_pairs == 1

    with sqlite3.connect(db_path) as conn:
        ids = [
            row[0]
            for row in conn.execute(
                """
                SELECT n.source_listing_id
                FROM listing_matches lm
                JOIN market_listings_norm n ON n.id = lm.listing_id
                WHERE lm.user_id = 'u-1' AND lm.status = 'active'
                ORDER BY n.source_listing_id
                """
            ).fetchall()
        ]
    assert ids == ["L-exact"]
