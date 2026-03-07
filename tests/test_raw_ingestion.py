from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ai_agent.clients.zhaoonline import ZhaoRequestContext, ZhaoResponse
from ai_agent.ingestion.raw_ingest import FileRateLimiter, RawIngestionJob, _extract_listing_id
from ai_agent.storage.sqlite_raw_store import SqliteRawStore


class FakeClient:
    def __init__(self):
        self.calls: list[tuple[int, int]] = []

    def search(self, status: int, page: int = 1, page_size: int = 50):
        self.calls.append((status, page))
        if page == 1:
            items = [
                {"listingId": f"{status}-{idx}", "name": "alpha"}
                for idx in range(page_size)
            ]
        else:
            items = []
        body = {"code": 200, "data": items}
        return (
            ZhaoRequestContext(
                url=f"http://example.local/api/search?status={status}&page={page}",
                headers={},
                timestamp_ms="1",
                token="token",
            ),
            ZhaoResponse(
                status_code=200,
                headers={"Content-Type": "application/json"},
                body_text=json.dumps(body, ensure_ascii=False),
                body_json=body,
                elapsed_ms=10,
            ),
            None,
        )


class FakePagedClient:
    def __init__(self):
        self.calls: list[tuple[int, int]] = []

    def search(self, status: int, page: int = 1, page_size: int = 50):
        self.calls.append((status, page))
        if page <= 3:
            items = [{"listingId": f"{status}-{page}-{idx}"} for idx in range(page_size)]
        else:
            items = []
        body = {"code": 200, "data": items}
        return (
            ZhaoRequestContext(
                url=f"http://example.local/api/search?status={status}&page={page}",
                headers={},
                timestamp_ms="1",
                token="token",
            ),
            ZhaoResponse(
                status_code=200,
                headers={"Content-Type": "application/json"},
                body_text=json.dumps(body, ensure_ascii=False),
                body_json=body,
                elapsed_ms=10,
            ),
            None,
        )


def test_file_rate_limiter_enforces_window(tmp_path: Path):
    now = 1_700_000_000.0

    def clock() -> float:
        return now

    limiter = FileRateLimiter(
        state_path=str(tmp_path / "rate.json"), max_calls=2, window_sec=3600, clock=clock
    )
    assert limiter.try_acquire() == (True, 0)
    assert limiter.try_acquire() == (True, 0)
    allowed, wait_sec = limiter.try_acquire()
    assert allowed is False
    assert wait_sec > 0


def test_extract_listing_id_has_hash_fallback():
    item = {"name": "x", "nested": {"a": 1}}
    listing_id = _extract_listing_id(item)
    assert listing_id.startswith("sha1:")


def test_raw_ingestion_job_persists_rows(tmp_path: Path):
    db_path = tmp_path / "agent.db"
    store = SqliteRawStore(str(db_path))
    limiter = FileRateLimiter(
        state_path=str(tmp_path / "rate.json"), max_calls=10, window_sec=3600
    )
    job = RawIngestionJob(
        client=FakeClient(),
        store=store,
        rate_limiter=limiter,
        page_size=50,
        statuses=(1, 2),
    )

    result = job.run_once()
    assert result.total_inserted == 100
    assert result.inserted_by_status == {1: 50, 2: 50}
    assert result.pages_fetched_by_status == {1: 2, 2: 2}
    assert result.completed_by_status == {1: True, 2: True}
    assert result.calls_used == 4
    assert result.next_page_by_status == {1: 1, 2: 1}

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT source_platform, source_listing_id, fetch_status, payload_json
            FROM market_listings_raw
            ORDER BY fetch_status, source_listing_id
            """
        ).fetchall()

    assert len(rows) == 100
    assert rows[0][0] == "zhaoonline"
    assert rows[0][2] in ("1", "2")


def test_raw_ingestion_job_skips_duplicates_on_repeat_run(tmp_path: Path):
    db_path = tmp_path / "agent.db"
    store = SqliteRawStore(str(db_path))
    limiter = FileRateLimiter(
        state_path=str(tmp_path / "rate.json"), max_calls=30, window_sec=3600
    )
    job = RawIngestionJob(
        client=FakeClient(),
        store=store,
        rate_limiter=limiter,
        page_size=50,
        statuses=(1, 2),
    )

    first = job.run_once()
    second = job.run_once()

    assert first.total_inserted == 100
    assert second.total_inserted == 0

    with sqlite3.connect(db_path) as conn:
        count = conn.execute("SELECT count(*) FROM market_listings_raw").fetchone()[0]

    assert count == 100


def test_raw_ingestion_job_resumes_deep_crawl_from_saved_cursor(tmp_path: Path):
    db_path = tmp_path / "agent.db"
    store = SqliteRawStore(str(db_path))
    limiter = FileRateLimiter(
        state_path=str(tmp_path / "rate.json"), max_calls=30, window_sec=3600
    )
    job = RawIngestionJob(
        client=FakePagedClient(),
        store=store,
        rate_limiter=limiter,
        page_size=50,
        statuses=(1,),
        call_budget_per_run=2,
        fresh_pages_per_status=0,
    )

    first = job.run_once()
    assert first.total_inserted == 100
    assert first.pages_fetched_by_status == {1: 2}
    assert first.completed_by_status == {1: False}
    assert first.next_page_by_status == {1: 3}

    second = job.run_once()
    assert second.total_inserted == 50
    assert second.pages_fetched_by_status == {1: 2}
    assert second.completed_by_status == {1: True}
    assert second.next_page_by_status == {1: 1}
