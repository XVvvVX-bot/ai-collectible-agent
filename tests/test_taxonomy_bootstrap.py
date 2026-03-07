from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

from ai_agent.taxonomy.zhaoonline_taxonomy import (
    apply_taxonomy_candidates,
    build_provisional_candidates,
    get_unmapped_report,
)
from ai_agent.storage.sqlite_raw_store import SqliteRawStore


def _insert_norm(
    conn: sqlite3.Connection,
    source_listing_id: str,
    *,
    category_raw: str | None = None,
    series_raw: str | None = None,
    status_raw: str | None = None,
    auction_type_raw: str | None = None,
    grade_raw: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO market_listings_norm (
          id,
          source_platform,
          source_listing_id,
          title,
          category_raw,
          series_raw,
          status_raw,
          auction_type_raw,
          grade_raw,
          currency,
          is_active,
          first_seen_at,
          last_seen_at,
          created_at,
          updated_at
        ) VALUES (?, 'zhaoonline', ?, 'x', ?, ?, ?, ?, ?, 'CNY', 1, ?, ?, ?, ?)
        """,
        (
            str(uuid.uuid4()),
            source_listing_id,
            category_raw,
            series_raw,
            status_raw,
            auction_type_raw,
            grade_raw,
            "2026-03-07T00:00:00+00:00",
            "2026-03-07T00:00:00+00:00",
            "2026-03-07T00:00:00+00:00",
            "2026-03-07T00:00:00+00:00",
        ),
    )


def test_taxonomy_bootstrap_and_unmapped_report(tmp_path: Path):
    db_path = tmp_path / "agent.db"
    store = SqliteRawStore(str(db_path))
    store.ensure_schema()

    with sqlite3.connect(db_path) as conn:
        _insert_norm(
            conn,
            "L-1",
            category_raw="178",
            series_raw="3",
            status_raw="2",
            auction_type_raw="1",
            grade_raw="PMG 63EPQ",
        )
        _insert_norm(
            conn,
            "L-2",
            category_raw="178",
            series_raw="3",
            status_raw="2",
            auction_type_raw="1",
            grade_raw="PMG 63EPQ",
        )
        _insert_norm(
            conn,
            "L-3",
            category_raw="184",
            series_raw="16",
            status_raw="1",
            auction_type_raw="9",
            grade_raw="NGC MS65",
        )
        conn.commit()

    before = get_unmapped_report(str(db_path), top_n_per_field=10, sample_size=2)
    assert before["category"][0]["raw_value"] == "178"
    assert before["category"][0]["observed_count"] == 2
    assert before["status"][0]["raw_value"] == "2"
    assert before["status"][0]["sample_listing_ids"] == ["L-1", "L-2"]

    candidates = build_provisional_candidates(str(db_path), top_n_per_field=10)
    mapped = {(x.field_name, x.raw_value): x.norm_value for x in candidates}
    assert mapped[("status", "2")] == "live"
    assert mapped[("status", "1")] == "preview"
    assert mapped[("auction_type", "1")] == "auction"
    assert mapped[("auction_type", "9")] == "auction_type_9"
    assert mapped[("category", "178")] == "category_178"
    assert mapped[("series", "3")] == "series_3"
    assert mapped[("grade", "PMG 63EPQ")] == "PMG 63EPQ"

    changes = apply_taxonomy_candidates(str(db_path), candidates)
    assert changes > 0

    after = get_unmapped_report(str(db_path), top_n_per_field=10, sample_size=2)
    assert after["category"] == []
    assert after["series"] == []
    assert after["status"] == []
    assert after["auction_type"] == []
    assert after["grade"] == []

