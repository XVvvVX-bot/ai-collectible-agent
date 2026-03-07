from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ai_agent.clients.zhaoonline import now_utc_iso
from ai_agent.normalization.zhaoonline_norm import normalize_zhaoonline_raw
from ai_agent.storage.sqlite_raw_store import RawListingRecord, SqliteRawStore


def _insert_raw(
    store: SqliteRawStore,
    source_listing_id: str,
    fetch_status: str,
    payload: dict,
    payload_hash: str,
    fetched_at: str,
) -> None:
    store.insert_raw_records(
        [
            RawListingRecord(
                source_platform="zhaoonline",
                source_listing_id=source_listing_id,
                fetch_status=fetch_status,
                fetched_at=fetched_at,
                payload_json=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                payload_hash=payload_hash,
                request_meta_json="{}",
                created_at=now_utc_iso(),
            )
        ]
    )


def test_normalization_inserts_norm_row(tmp_path: Path):
    db_path = tmp_path / "agent.db"
    store = SqliteRawStore(str(db_path))
    store.ensure_schema()

    _insert_raw(
        store=store,
        source_listing_id="123",
        fetch_status="2",
        payload={
            "id": 123,
            "auctionNo": "A100",
            "name": "Test Lot",
            "status": "2",
            "auctionType": "1",
            "auctionCategoryId": 178,
            "auctionCharacterId": 3,
            "picPath": "https://img/a.jpg",
            "startAt": 1772415282000,
            "endAt": 1772871300000,
            "initialPrice": 100.0,
            "endPrice": 120.0,
        },
        payload_hash="h1",
        fetched_at="2026-03-07T00:00:00+00:00",
    )

    result = normalize_zhaoonline_raw(str(db_path), batch_size=100)
    assert result.processed == 1
    assert result.upserted == 1
    assert result.skipped == 0

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT
              source_listing_id, auction_no, title, status_norm, auction_type_norm,
              price_initial, price_current, price_end, is_active
            FROM market_listings_norm
            WHERE source_platform = 'zhaoonline' AND source_listing_id = '123'
            """
        ).fetchone()

    assert row is not None
    assert row[0] == "123"
    assert row[1] == "A100"
    assert row[2] == "Test Lot"
    assert row[3] == "live"
    assert row[4] == "auction"
    assert row[5] == 100.0
    assert row[6] == 120.0
    assert row[7] == 120.0
    assert row[8] == 1


def test_normalization_is_incremental_with_state(tmp_path: Path):
    db_path = tmp_path / "agent.db"
    store = SqliteRawStore(str(db_path))
    store.ensure_schema()

    _insert_raw(
        store=store,
        source_listing_id="200",
        fetch_status="1",
        payload={"id": 200, "name": "Preview Item", "status": "1"},
        payload_hash="ha",
        fetched_at="2026-03-07T00:00:00+00:00",
    )

    first = normalize_zhaoonline_raw(str(db_path), batch_size=100)
    second = normalize_zhaoonline_raw(str(db_path), batch_size=100)
    assert first.processed == 1
    assert second.processed == 0


def test_normalization_updates_existing_listing_and_seen_timestamps(tmp_path: Path):
    db_path = tmp_path / "agent.db"
    store = SqliteRawStore(str(db_path))
    store.ensure_schema()

    _insert_raw(
        store=store,
        source_listing_id="300",
        fetch_status="2",
        payload={"id": 300, "name": "Lot 300", "status": "2", "initialPrice": 100.0},
        payload_hash="h_old",
        fetched_at="2026-03-07T00:00:00+00:00",
    )
    normalize_zhaoonline_raw(str(db_path), batch_size=100)

    _insert_raw(
        store=store,
        source_listing_id="300",
        fetch_status="3",
        payload={"id": 300, "name": "Lot 300", "status": "3", "endPrice": 150.0},
        payload_hash="h_new",
        fetched_at="2026-03-07T01:00:00+00:00",
    )
    normalize_zhaoonline_raw(str(db_path), batch_size=100)

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT status_norm, price_current, first_seen_at, last_seen_at, is_active
            FROM market_listings_norm
            WHERE source_platform = 'zhaoonline' AND source_listing_id = '300'
            """
        ).fetchone()

    assert row is not None
    assert row[0] == "ended"
    assert row[1] == 150.0
    assert row[2] == "2026-03-07T00:00:00+00:00"
    assert row[3] == "2026-03-07T01:00:00+00:00"
    assert row[4] == 0

