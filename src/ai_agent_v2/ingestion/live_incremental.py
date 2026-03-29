from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ai_agent_v2.clients.zhaoonline import ZhaoV2Client, now_utc_iso
from ai_agent_v2.storage.sqlite_store import SqliteV2Store

RAW_SOURCE_PLATFORM = "zhaoonline"
DEFAULT_STATE_SOURCE_KEY = "zhaoonline_live"


@dataclass(frozen=True)
class LiveIncrementalWindowResult:
    sync_run_id: str
    from_time_ms: int
    to_time_ms: int
    pages_fetched: int
    items_seen: int
    auctions_inserted: int
    change_events_inserted: int
    last_page_num: int
    rate_limit_hit: bool
    retry_after_sec: int


@dataclass(frozen=True)
class LiveIncrementalCycleResult:
    skipped: bool
    skip_reason: str | None
    state_source_key: str
    final_from_time_ms: int | None
    target_to_time_ms: int | None
    results: tuple[LiveIncrementalWindowResult, ...]


class RequestPacer:
    def __init__(self, state_path: str, min_interval_sec: int, sleep_fn: Callable[[float], None] = time.sleep):
        self.state_path = Path(state_path)
        self.min_interval_sec = max(0, int(min_interval_sec))
        self.sleep_fn = sleep_fn

    def wait_for_turn(self) -> None:
        if self.min_interval_sec <= 0:
            return
        state = self._read_state()
        now_ts = time.time()
        last_request_at = float(state.get("last_request_at", 0.0) or 0.0)
        remaining = self.min_interval_sec - (now_ts - last_request_at)
        if remaining > 0:
            self.sleep_fn(remaining)
        self._write_state({"last_request_at": time.time()})

    def _read_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {}
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {}

    def _write_state(self, payload: dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.state_path.with_suffix(f"{self.state_path.suffix}.tmp")
        temp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        temp_path.replace(self.state_path)


def run_live_incremental_cycle(
    *,
    db_path: str,
    base_url: str,
    secret: str,
    state_source_key: str = DEFAULT_STATE_SOURCE_KEY,
    raw_source_platform: str = RAW_SOURCE_PLATFORM,
    window_hours: int = 1,
    page_size: int = 500,
    max_windows_per_run: int = 4,
    min_interval_sec: int = 60,
    request_timeout_sec: int = 60,
    rate_limit_state_path: str = "data/zhaoonline_v2_rate_limit_live.json",
    client: ZhaoV2Client | None = None,
    pacer: RequestPacer | None = None,
    now_ms: int | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> LiveIncrementalCycleResult:
    SqliteV2Store(db_path).ensure_schema()
    window_ms = max(1, int(window_hours)) * 60 * 60 * 1000
    max_windows = max(1, int(max_windows_per_run))
    pacer = pacer or RequestPacer(rate_limit_state_path, min_interval_sec, sleep_fn=sleep_fn)
    client = client or ZhaoV2Client(base_url=base_url, secret=secret, timeout_sec=request_timeout_sec)

    completed_hour_end_ms = _completed_hour_end_ms(now_ms)
    with sqlite3.connect(Path(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        results: list[LiveIncrementalWindowResult] = []
        first_from_time_ms: int | None = None
        last_to_time_ms: int | None = None

        for _ in range(max_windows):
            from_time_ms, to_time_ms = _choose_next_window(
                conn,
                state_source_key=state_source_key,
                completed_hour_end_ms=completed_hour_end_ms,
                window_ms=window_ms,
            )
            if from_time_ms is None or to_time_ms is None:
                break

            if first_from_time_ms is None:
                first_from_time_ms = from_time_ms

            result = _run_single_window(
                conn,
                client=client,
                pacer=pacer,
                raw_source_platform=raw_source_platform,
                state_source_key=state_source_key,
                from_time_ms=from_time_ms,
                to_time_ms=to_time_ms,
                page_size=page_size,
                sleep_fn=sleep_fn,
            )
            conn.commit()
            results.append(result)
            last_to_time_ms = to_time_ms

        if not results:
            return LiveIncrementalCycleResult(
                skipped=True,
                skip_reason="no_completed_window",
                state_source_key=state_source_key,
                final_from_time_ms=None,
                target_to_time_ms=None,
                results=(),
            )

    return LiveIncrementalCycleResult(
        skipped=False,
        skip_reason=None,
        state_source_key=state_source_key,
        final_from_time_ms=first_from_time_ms,
        target_to_time_ms=last_to_time_ms,
        results=tuple(results),
    )


def _run_single_window(
    conn: sqlite3.Connection,
    *,
    client: ZhaoV2Client,
    pacer: RequestPacer,
    raw_source_platform: str,
    state_source_key: str,
    from_time_ms: int,
    to_time_ms: int,
    page_size: int,
    sleep_fn: Callable[[float], None],
) -> LiveIncrementalWindowResult:
    started_at = now_utc_iso()
    sync_run_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO zhao_v2_sync_runs (
          id, source_platform, sync_type, status_filter, window_from_ms, window_to_ms,
          started_at, finished_at, status, error_message, pages_fetched, items_seen, items_inserted
        ) VALUES (?, ?, 'incremental', NULL, ?, ?, ?, NULL, 'running', NULL, 0, 0, 0)
        """,
        (sync_run_id, state_source_key, from_time_ms, to_time_ms, started_at),
    )

    page_num = 1
    pages_fetched = 0
    items_seen = 0
    auctions_inserted = 0
    change_events_inserted = 0
    last_page_num = 0
    rate_limit_hit = False
    retry_after_sec = 0

    try:
        while True:
            ctx, response, error = _fetch_page_with_single_retry(
                client=client,
                pacer=pacer,
                from_time_ms=from_time_ms,
                to_time_ms=to_time_ms,
                page_num=page_num,
                page_size=page_size,
                sleep_fn=sleep_fn,
                min_retry_sec=pacer.min_interval_sec,
            )

            if error is not None:
                raise RuntimeError(
                    f"HTTP {error.status_code} for incremental window {from_time_ms}->{to_time_ms}, page {page_num}: {error.body_text[:300]}"
                )
            if response is None or response.body_json is None:
                raise RuntimeError(f"Missing JSON response for incremental window {from_time_ms}->{to_time_ms}, page {page_num}.")

            page_info = _extract_page_info(response.body_json)
            items = page_info["items"]
            page_inserted_auctions = 0
            page_inserted_changes = 0
            fetched_at = now_utc_iso()

            for item in items:
                if not _is_meaningful_change(item):
                    continue
                auction_inserted, change_inserted = _insert_meaningful_incremental_item(
                    conn,
                    sync_run_id=sync_run_id,
                    source_platform=raw_source_platform,
                    item=item,
                    page_num=page_num,
                    page_size=page_size,
                    fetched_at=fetched_at,
                )
                page_inserted_auctions += auction_inserted
                page_inserted_changes += change_inserted

            page_meta_json = json.dumps(
                {
                    "url": ctx.url,
                    "http_status": response.status_code,
                    "elapsed_ms": response.elapsed_ms,
                    "total": page_info["total"],
                    "pages": page_info["pages"],
                    "has_next_page": page_info["has_next_page"],
                    "next_page": page_info["next_page"],
                    "from_time_ms": from_time_ms,
                    "to_time_ms": to_time_ms,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
            conn.execute(
                """
                INSERT INTO zhao_v2_sync_run_pages (
                  id, sync_run_id, page_num, page_size, items_seen, inserted_count, page_meta_json, fetched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (str(uuid.uuid4()), sync_run_id, page_num, page_size, len(items), page_inserted_changes, page_meta_json, fetched_at),
            )

            pages_fetched += 1
            items_seen += len(items)
            auctions_inserted += page_inserted_auctions
            change_events_inserted += page_inserted_changes
            last_page_num = page_num

            if not page_info["has_next_page"]:
                break
            page_num = page_info["next_page"] or (page_num + 1)

        finished_at = now_utc_iso()
        conn.execute(
            """
            UPDATE zhao_v2_sync_runs
            SET finished_at = ?, status = 'success', error_message = NULL,
                pages_fetched = ?, items_seen = ?, items_inserted = ?
            WHERE id = ?
            """,
            (finished_at, pages_fetched, items_seen, change_events_inserted, sync_run_id),
        )
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
            ) VALUES (?, NULL, NULL, NULL, ?, ?, ?)
            ON CONFLICT(source_platform) DO UPDATE SET
              last_incremental_from_ms = excluded.last_incremental_from_ms,
              last_incremental_to_ms = excluded.last_incremental_to_ms,
              updated_at = excluded.updated_at
            """,
            (state_source_key, from_time_ms, to_time_ms, finished_at),
        )
    except Exception as exc:
        finished_at = now_utc_iso()
        conn.execute(
            """
            UPDATE zhao_v2_sync_runs
            SET finished_at = ?, status = 'failed', error_message = ?,
                pages_fetched = ?, items_seen = ?, items_inserted = ?
            WHERE id = ?
            """,
            (finished_at, str(exc), pages_fetched, items_seen, change_events_inserted, sync_run_id),
        )
        raise

    return LiveIncrementalWindowResult(
        sync_run_id=sync_run_id,
        from_time_ms=from_time_ms,
        to_time_ms=to_time_ms,
        pages_fetched=pages_fetched,
        items_seen=items_seen,
        auctions_inserted=auctions_inserted,
        change_events_inserted=change_events_inserted,
        last_page_num=last_page_num,
        rate_limit_hit=rate_limit_hit,
        retry_after_sec=retry_after_sec,
    )


def _fetch_page_with_single_retry(
    *,
    client: ZhaoV2Client,
    pacer: RequestPacer,
    from_time_ms: int,
    to_time_ms: int,
    page_num: int,
    page_size: int,
    sleep_fn: Callable[[float], None],
    min_retry_sec: int,
):
    pacer.wait_for_turn()
    ctx, response, error = client.search_incremental(
        from_time_ms=from_time_ms,
        to_time_ms=to_time_ms,
        page=page_num,
        page_size=page_size,
    )
    if error is None or error.status_code != 429:
        return ctx, response, error
    retry_after_sec = max(60, int(min_retry_sec or 0))
    sleep_fn(retry_after_sec)
    pacer.wait_for_turn()
    return client.search_incremental(
        from_time_ms=from_time_ms,
        to_time_ms=to_time_ms,
        page=page_num,
        page_size=page_size,
    )


def _insert_meaningful_incremental_item(
    conn: sqlite3.Connection,
    *,
    sync_run_id: str,
    source_platform: str,
    item: dict[str, Any],
    page_num: int,
    page_size: int,
    fetched_at: str,
) -> tuple[int, int]:
    payload_json = json.dumps(item, ensure_ascii=False, separators=(",", ":"))
    payload_hash = hashlib.sha1(payload_json.encode("utf-8")).hexdigest()
    created_at = now_utc_iso()
    auction_id = _text(item.get("auctionId")) or _text(item.get("id")) or payload_hash
    auction_no = _text(item.get("auctionNo"))
    status_raw = _text(item.get("status"))
    change_time_raw = _text(item.get("changeTime"))
    old_status_raw = _text(item.get("oldStatus"))
    new_status_raw = _text(item.get("newStatus"))

    raw_cursor = conn.execute(
        """
        INSERT OR IGNORE INTO zhao_v2_auction_raw (
          id, sync_run_id, sync_type, source_platform, auction_id, auction_no, status_raw,
          change_time_raw, payload_json, payload_hash, page_num, page_size, fetched_at, created_at
        ) VALUES (?, ?, 'incremental', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(uuid.uuid4()),
            sync_run_id,
            source_platform,
            auction_id,
            auction_no,
            status_raw,
            change_time_raw,
            payload_json,
            payload_hash,
            page_num,
            page_size,
            fetched_at,
            created_at,
        ),
    )
    change_cursor = conn.execute(
        """
        INSERT OR IGNORE INTO zhao_v2_auction_change_raw (
          id, sync_run_id, source_platform, auction_id, auction_no, old_status_raw,
          new_status_raw, change_time_raw, payload_json, payload_hash, fetched_at, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(uuid.uuid4()),
            sync_run_id,
            source_platform,
            auction_id,
            auction_no,
            old_status_raw,
            new_status_raw,
            change_time_raw,
            payload_json,
            payload_hash,
            fetched_at,
            created_at,
        ),
    )
    return raw_cursor.rowcount, change_cursor.rowcount


def _choose_next_window(
    conn: sqlite3.Connection,
    *,
    state_source_key: str,
    completed_hour_end_ms: int,
    window_ms: int,
) -> tuple[int | None, int | None]:
    row = conn.execute(
        """
        SELECT last_incremental_to_ms
        FROM zhao_v2_sync_state
        WHERE source_platform = ?
        """,
        (state_source_key,),
    ).fetchone()
    if row is None or row["last_incremental_to_ms"] is None:
        from_time_ms = completed_hour_end_ms - window_ms
        to_time_ms = completed_hour_end_ms
    else:
        from_time_ms = int(row["last_incremental_to_ms"])
        to_time_ms = min(from_time_ms + window_ms, completed_hour_end_ms)
    if to_time_ms <= from_time_ms:
        return None, None
    return from_time_ms, to_time_ms


def _completed_hour_end_ms(now_ms: int | None) -> int:
    current_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    return current_ms - (current_ms % 3600000)


def _extract_page_info(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        items = payload.get("list")
        total = payload.get("total")
        pages = payload.get("pages")
        page_num = payload.get("pageNum")
        next_page = payload.get("nextPage")
        has_next_page = payload.get("hasNextPage")
        if isinstance(items, list):
            inferred_pages = int(pages) if pages is not None else (
                int(total // len(items)) + (1 if total and len(items) and total % len(items) else 0) if total is not None and len(items) > 0 else 1
            )
            return {
                "items": [item for item in items if isinstance(item, dict)],
                "total": int(total) if total is not None else None,
                "pages": inferred_pages,
                "page_num": int(page_num) if page_num is not None else None,
                "has_next_page": bool(has_next_page) if has_next_page is not None else bool(next_page),
                "next_page": int(next_page) if next_page not in (None, "", 0) else None,
            }
        for key in ("data", "result"):
            nested = payload.get(key)
            if isinstance(nested, dict):
                return _extract_page_info(nested)
    if isinstance(payload, list):
        return {
            "items": [item for item in payload if isinstance(item, dict)],
            "total": len(payload),
            "pages": 1,
            "page_num": 1,
            "has_next_page": False,
            "next_page": None,
        }
    raise RuntimeError("Unable to extract incremental page info from response payload.")


def _is_meaningful_change(item: dict[str, Any]) -> bool:
    return _text(item.get("oldStatus")) != _text(item.get("newStatus"))


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


class FileLock:
    def __init__(self, path: str):
        self.path = Path(path)
        self.fd: int | None = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return False
        os.write(self.fd, str(os.getpid()).encode("utf-8"))
        return True

    def release(self) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass
