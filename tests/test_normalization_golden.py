from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path

from ai_agent.clients.zhaoonline import now_utc_iso
from ai_agent.normalization.zhaoonline_norm import normalize_zhaoonline_raw
from ai_agent.storage.sqlite_raw_store import RawListingRecord, SqliteRawStore


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "zhaoonline_norm_golden_cases.json"


def _insert_raw(store: SqliteRawStore, case: dict) -> None:
    store.insert_raw_records(
        [
            RawListingRecord(
                source_platform="zhaoonline",
                source_listing_id=case["source_listing_id"],
                fetch_status=case["fetch_status"],
                fetched_at=case["fetched_at"],
                payload_json=json.dumps(case["payload"], ensure_ascii=False, separators=(",", ":")),
                payload_hash=case["payload_hash"],
                request_meta_json="{}",
                created_at=now_utc_iso(),
            )
        ]
    )


def _insert_taxonomy(conn: sqlite3.Connection, rows: list[dict]) -> None:
    for row in rows:
        conn.execute(
            """
            INSERT INTO market_taxonomy_map (
              id, source_platform, field_name, raw_value, norm_value, created_at, updated_at
            ) VALUES (?, 'zhaoonline', ?, ?, ?, datetime('now'), datetime('now'))
            """,
            (
                str(uuid.uuid4()),
                row["field_name"],
                row["raw_value"],
                row["norm_value"],
            ),
        )


def test_normalization_golden_cases(tmp_path: Path):
    db_path = tmp_path / "agent.db"
    store = SqliteRawStore(str(db_path))
    store.ensure_schema()
    cases = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    for case in cases:
        _insert_raw(store, case)
        with sqlite3.connect(db_path) as conn:
            if case.get("taxonomy"):
                _insert_taxonomy(conn, case["taxonomy"])
                conn.commit()

        result = normalize_zhaoonline_raw(str(db_path), batch_size=100)
        assert result.processed == 1, case["name"]

        if case.get("expected_skip"):
            assert result.skipped == 1, case["name"]
            assert result.upserted == 0, case["name"]
            with sqlite3.connect(db_path) as conn:
                row = conn.execute(
                    """
                    SELECT 1
                    FROM market_listings_norm
                    WHERE source_platform='zhaoonline' AND source_listing_id=?
                    """,
                    (case["source_listing_id"],),
                ).fetchone()
            assert row is None, case["name"]
            continue

        assert result.skipped == 0, case["name"]
        assert result.upserted == 1, case["name"]
        expected = case["expected"]

        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT
                  source_listing_id,
                  auction_no,
                  title,
                  status_raw,
                  status_norm,
                  auction_type_norm,
                  category_raw,
                  category_norm,
                  series_raw,
                  series_norm,
                  description,
                  image_url,
                  start_at,
                  end_at,
                  price_initial,
                  price_end,
                  price_current,
                  currency,
                  is_active
                FROM market_listings_norm
                WHERE source_platform='zhaoonline' AND source_listing_id=?
                """,
                (case["source_listing_id"],),
            ).fetchone()

        assert row is not None, case["name"]
        for key, expected_value in expected.items():
            assert row[key] == expected_value, f"{case['name']}::{key}"

