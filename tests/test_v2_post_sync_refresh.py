from __future__ import annotations

import sqlite3
from pathlib import Path

from ai_agent_v2.clients.zhaoonline import ZhaoV2RequestContext, ZhaoV2Response
from ai_agent_v2.ingestion.live_incremental import RequestPacer, run_live_incremental_cycle
from ai_agent_v2.orchestration.post_sync_refresh import run_post_sync_refresh
from ai_agent_v2.storage.sqlite_store import SqliteV2Store


class _FakeClient:
    def __init__(self):
        self.calls: list[tuple[int, int, int, int]] = []

    def search_incremental(self, *, from_time_ms: int, to_time_ms: int, page: int, page_size: int):
        self.calls.append((from_time_ms, to_time_ms, page, page_size))
        payload = {
            "total": 2,
            "pageNum": 1,
            "pageSize": page_size,
            "pages": 1,
            "hasNextPage": False,
            "nextPage": 0,
            "list": [
                {
                    "auctionId": 101,
                    "auctionNo": "A-101",
                    "name": "T43西游记新全",
                    "status": "2",
                    "oldStatus": "1",
                    "newStatus": "2",
                    "changeTime": from_time_ms + 1000,
                    "auctionCategoryId": 10,
                    "categoryName": "JT邮票",
                    "auctionCharacterId": 20,
                    "characterName": "新全",
                    "descrCharacter": "上品",
                    "initialPrice": 1.0,
                    "endPrice": 0.0,
                    "buyChargeFee": 8.0,
                    "previewAt": from_time_ms - 1000,
                    "startAt": from_time_ms + 500,
                    "endAt": to_time_ms,
                    "uploadAt": from_time_ms - 5000,
                    "picPath": "https://img.example.test/A.jpg",
                    "pictures": [
                        {"picPath": "https://img.example.test/A.jpg", "picOrder": "A"},
                        {"picPath": "https://img.example.test/B.jpg", "picOrder": "B"},
                    ],
                },
                {
                    "auctionId": 202,
                    "auctionNo": "A-202",
                    "name": "same-status noise",
                    "status": "2",
                    "oldStatus": "2",
                    "newStatus": "2",
                    "changeTime": from_time_ms + 2000,
                },
            ],
        }
        return (
            ZhaoV2RequestContext(url="http://example.test/incremental", headers={}, timestamp_ms="1", token="x"),
            ZhaoV2Response(status_code=200, headers={}, body_text="{}", body_json=payload, elapsed_ms=25),
            None,
        )


def test_post_sync_refresh_normalizes_and_parses_affected_incremental_rows(tmp_path: Path):
    db_path = tmp_path / "agent_v2.db"
    SqliteV2Store(str(db_path)).ensure_schema()
    client = _FakeClient()
    pacer = RequestPacer(str(tmp_path / "rate_limit.json"), min_interval_sec=0)

    cycle_result = run_live_incremental_cycle(
        db_path=str(db_path),
        base_url="http://example.test",
        secret="secret",
        client=client,
        pacer=pacer,
        state_source_key="zhaoonline_live_test",
        now_ms=7200000,
        sleep_fn=lambda _: None,
    )

    refresh_result = run_post_sync_refresh(
        str(db_path),
        sync_run_ids=[row.sync_run_id for row in cycle_result.results],
    )

    assert refresh_result.normalization.listings_upserted == 1
    assert refresh_result.normalization.media_inserted == 2
    assert refresh_result.normalization.events_inserted == 1
    assert refresh_result.parsing.processed == 1
    assert refresh_result.parsing.family_counts == {"stamp_like": 1}

    with sqlite3.connect(db_path) as conn:
        norm_row = conn.execute(
            """
            SELECT source_listing_id, title, status_norm, category_name_raw, character_name_raw, primary_image_url
            FROM market_listings_norm_v2
            """
        ).fetchone()
        event_count = conn.execute("SELECT COUNT(*) FROM market_listing_events_v2").fetchone()[0]
        media_count = conn.execute("SELECT COUNT(*) FROM market_listing_media_v2").fetchone()[0]
        parse_row = conn.execute(
            """
            SELECT parse_family, issue_code_norm, issue_name
            FROM listing_parse_v2
            """
        ).fetchone()

    assert norm_row == ("101", "T43西游记新全", "live", "JT邮票", "新全", "https://img.example.test/A.jpg")
    assert event_count == 1
    assert media_count == 2
    assert parse_row == ("stamp_like", "T43", "西游记")
