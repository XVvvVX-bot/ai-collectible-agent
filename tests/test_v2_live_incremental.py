from __future__ import annotations

import sqlite3
from pathlib import Path

from ai_agent_v2.clients.zhaoonline import ZhaoV2RequestContext, ZhaoV2Response
from ai_agent_v2.ingestion.live_incremental import RequestPacer, run_live_incremental_cycle
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


def test_live_incremental_cycle_bootstraps_previous_hour_and_keeps_only_meaningful_changes(tmp_path: Path):
    db_path = tmp_path / "agent_v2.db"
    SqliteV2Store(str(db_path)).ensure_schema()
    client = _FakeClient()
    pacer = RequestPacer(str(tmp_path / "rate_limit.json"), min_interval_sec=0)

    result = run_live_incremental_cycle(
        db_path=str(db_path),
        base_url="http://example.test",
        secret="secret",
        client=client,
        pacer=pacer,
        state_source_key="zhaoonline_live_test",
        now_ms=7200000,
        sleep_fn=lambda _: None,
    )

    assert result.skipped is False
    assert result.final_from_time_ms == 3600000
    assert result.target_to_time_ms == 7200000
    assert len(result.results) == 1
    assert result.results[0].items_seen == 2
    assert result.results[0].auctions_inserted == 1
    assert result.results[0].change_events_inserted == 1
    assert client.calls == [(3600000, 7200000, 1, 500)]

    with sqlite3.connect(db_path) as conn:
        state = conn.execute(
            "SELECT last_incremental_from_ms, last_incremental_to_ms FROM zhao_v2_sync_state WHERE source_platform = 'zhaoonline_live_test'"
        ).fetchone()
        raw_count = conn.execute("SELECT COUNT(*) FROM zhao_v2_auction_raw WHERE sync_type = 'incremental'").fetchone()[0]
        change_count = conn.execute("SELECT COUNT(*) FROM zhao_v2_auction_change_raw").fetchone()[0]

    assert state == (3600000, 7200000)
    assert raw_count == 1
    assert change_count == 1


def test_live_incremental_cycle_processes_multiple_backlog_windows_per_run(tmp_path: Path):
    db_path = tmp_path / "agent_v2.db"
    SqliteV2Store(str(db_path)).ensure_schema()
    client = _FakeClient()
    pacer = RequestPacer(str(tmp_path / "rate_limit.json"), min_interval_sec=0)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO zhao_v2_sync_state (
              source_platform,
              baseline_status_filter,
              last_baseline_started_at,
              last_baseline_finished_at,
              last_incremental_from_ms,
              last_incremental_to_ms,
              updated_at
            ) VALUES (?, NULL, NULL, NULL, ?, ?, '2026-03-27T00:00:00+00:00')
            """,
            ("zhaoonline_live_test", 0, 3600000),
        )
        conn.commit()

    result = run_live_incremental_cycle(
        db_path=str(db_path),
        base_url="http://example.test",
        secret="secret",
        client=client,
        pacer=pacer,
        state_source_key="zhaoonline_live_test",
        now_ms=14400000,
        max_windows_per_run=3,
        sleep_fn=lambda _: None,
    )

    assert result.skipped is False
    assert result.final_from_time_ms == 3600000
    assert result.target_to_time_ms == 14400000
    assert len(result.results) == 3
    assert [row.from_time_ms for row in result.results] == [3600000, 7200000, 10800000]
    assert [row.to_time_ms for row in result.results] == [7200000, 10800000, 14400000]
    assert client.calls == [
        (3600000, 7200000, 1, 500),
        (7200000, 10800000, 1, 500),
        (10800000, 14400000, 1, 500),
    ]

    with sqlite3.connect(db_path) as conn:
        state = conn.execute(
            "SELECT last_incremental_from_ms, last_incremental_to_ms FROM zhao_v2_sync_state WHERE source_platform = 'zhaoonline_live_test'"
        ).fetchone()
        raw_count = conn.execute("SELECT COUNT(*) FROM zhao_v2_auction_raw WHERE sync_type = 'incremental'").fetchone()[0]
        change_count = conn.execute("SELECT COUNT(*) FROM zhao_v2_auction_change_raw").fetchone()[0]
        run_count = conn.execute(
            "SELECT COUNT(*) FROM zhao_v2_sync_runs WHERE source_platform = 'zhaoonline_live_test'"
        ).fetchone()[0]

    assert state == (10800000, 14400000)
    assert raw_count == 3
    assert change_count == 3
    assert run_count == 3
