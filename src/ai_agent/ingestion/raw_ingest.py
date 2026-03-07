from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ai_agent.clients.zhaoonline import ZhaoClient, now_utc_iso
from ai_agent.storage.sqlite_raw_store import RawListingRecord, SqliteRawStore

SOURCE_PLATFORM = "zhaoonline"
LISTING_ID_CANDIDATE_KEYS = (
    "listingId",
    "listing_id",
    "auctionId",
    "auction_id",
    "itemId",
    "item_id",
    "goodsId",
    "goods_id",
    "id",
    "no",
    "auctionNo",
    "auction_no",
)


class FileRateLimiter:
    def __init__(
        self,
        state_path: str,
        max_calls: int,
        window_sec: int = 3600,
        clock: callable = time.time,
    ):
        self.state_path = Path(state_path)
        self.max_calls = max_calls
        self.window_sec = window_sec
        self.clock = clock

    def try_acquire(self, n: int = 1) -> tuple[bool, int]:
        now = self.clock()
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        timestamps = self._read_timestamps()
        window_start = now - self.window_sec
        kept = [t for t in timestamps if t >= window_start]
        available = self.max_calls - len(kept)
        if available < n:
            if kept:
                wait_sec = max(1, math.ceil(min(kept) + self.window_sec - now))
            else:
                wait_sec = self.window_sec
            self._write_timestamps(kept)
            return False, wait_sec
        kept.extend([now] * n)
        self._write_timestamps(kept)
        return True, 0

    def _read_timestamps(self) -> list[float]:
        if not self.state_path.exists():
            return []
        try:
            content = json.loads(self.state_path.read_text(encoding="utf-8"))
            if not isinstance(content, dict):
                return []
            values = content.get("timestamps", [])
            if not isinstance(values, list):
                return []
            return [float(v) for v in values]
        except (OSError, ValueError, TypeError):
            return []

    def _write_timestamps(self, timestamps: list[float]) -> None:
        temp_path = self.state_path.with_suffix(f"{self.state_path.suffix}.tmp")
        payload = {"timestamps": timestamps}
        temp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        temp_path.replace(self.state_path)


@dataclass(frozen=True)
class RawIngestionResult:
    total_inserted: int
    inserted_by_status: dict[int, int]
    pages_fetched_by_status: dict[int, int]
    completed_by_status: dict[int, bool]
    next_page_by_status: dict[int, int]
    calls_used: int


class RawIngestionJob:
    def __init__(
        self,
        client: ZhaoClient,
        store: SqliteRawStore,
        rate_limiter: FileRateLimiter,
        page_size: int = 50,
        statuses: tuple[int, ...] = (2, 1),
        call_budget_per_run: int | None = None,
        fresh_pages_per_status: int = 2,
    ):
        self.client = client
        self.store = store
        self.rate_limiter = rate_limiter
        self.page_size = page_size
        self.statuses = statuses
        self.call_budget_per_run = (
            call_budget_per_run if call_budget_per_run is not None else rate_limiter.max_calls
        )
        self.fresh_pages_per_status = max(0, fresh_pages_per_status)
        if self.call_budget_per_run < 1:
            raise ValueError("call_budget_per_run must be >= 1.")
        if self.call_budget_per_run > 30:
            raise ValueError("call_budget_per_run must be <= 30 for safe operation.")

    def run_once(self) -> RawIngestionResult:
        self.store.ensure_schema()
        self.store.ensure_crawl_state_rows(SOURCE_PLATFORM, self.statuses)
        inserted_by_status: dict[int, int] = {}
        pages_fetched_by_status: dict[int, int] = {}
        completed_by_status: dict[int, bool] = {}
        next_page_by_status: dict[int, int] = {}
        total_inserted = 0
        calls_used = 0

        for status in self.statuses:
            inserted_by_status[status] = 0
            pages_fetched_by_status[status] = 0
            completed_by_status[status] = False
            next_page_by_status[status] = self.store.get_next_page(SOURCE_PLATFORM, status)

        # Phase 1: refresh top pages each run.
        for status in self.statuses:
            for page in range(1, self.fresh_pages_per_status + 1):
                if calls_used >= self.call_budget_per_run:
                    break
                inserted, reached_end = self._fetch_and_store_page(status=status, page=page)
                calls_used += 1
                pages_fetched_by_status[status] += 1
                inserted_by_status[status] += inserted
                total_inserted += inserted
                if reached_end:
                    completed_by_status[status] = True
                    break

        # Phase 2: continue deep crawl from persisted page cursor.
        while calls_used < self.call_budget_per_run:
            made_progress = False
            for status in self.statuses:
                if calls_used >= self.call_budget_per_run:
                    break
                if completed_by_status[status]:
                    continue

                page = self.store.get_next_page(SOURCE_PLATFORM, status)
                inserted, reached_end = self._fetch_and_store_page(status=status, page=page)
                calls_used += 1
                pages_fetched_by_status[status] += 1
                inserted_by_status[status] += inserted
                total_inserted += inserted
                made_progress = True

                if reached_end:
                    completed_by_status[status] = True
                    self.store.set_next_page(SOURCE_PLATFORM, status, 1)
                else:
                    self.store.set_next_page(SOURCE_PLATFORM, status, page + 1)

            if not made_progress:
                break

        for status in self.statuses:
            next_page_by_status[status] = self.store.get_next_page(SOURCE_PLATFORM, status)

        return RawIngestionResult(
            total_inserted=total_inserted,
            inserted_by_status=inserted_by_status,
            pages_fetched_by_status=pages_fetched_by_status,
            completed_by_status=completed_by_status,
            next_page_by_status=next_page_by_status,
            calls_used=calls_used,
        )

    def _fetch_and_store_page(self, status: int, page: int) -> tuple[int, bool]:
        allowed, wait_sec = self.rate_limiter.try_acquire()
        if not allowed:
            raise RuntimeError(
                f"Rate limit reached before status={status}, page={page}. Retry in ~{wait_sec} seconds."
            )

        ctx, resp, err = self.client.search(status=status, page=page, page_size=self.page_size)
        if err is not None:
            raise RuntimeError(
                f"Zhaoonline returned HTTP {err.status_code} for status={status}, page={page}: {err.body_text[:300]}"
            )
        if resp is None:
            raise RuntimeError(f"Missing response for status={status}, page={page}.")
        if resp.body_json is None:
            raise RuntimeError(
                f"Response for status={status}, page={page} is not valid JSON: {resp.body_text[:300]}"
            )

        fetched_at = now_utc_iso()
        listings = _extract_listings(resp.body_json)
        if not listings:
            return 0, True

        records = _to_raw_records(
            listings=listings,
            fetched_at=fetched_at,
            fetch_status=str(status),
            request_meta={
                "status_param": status,
                "page_param": page,
                "page_size_param": self.page_size,
                "url": ctx.url,
                "http_status": resp.status_code,
                "elapsed_ms": resp.elapsed_ms,
                "response_headers": resp.headers,
            },
        )
        inserted = self.store.insert_raw_records(records)
        return inserted, len(listings) < self.page_size


def _extract_listings(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []

    for key in ("data", "list", "items", "rows", "records", "result"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            nested = _extract_listings(value)
            if nested:
                return nested
    return []


def _to_raw_records(
    listings: list[dict[str, Any]],
    fetched_at: str,
    fetch_status: str,
    request_meta: dict[str, Any],
) -> list[RawListingRecord]:
    created_at = now_utc_iso()
    request_meta_json = json.dumps(request_meta, ensure_ascii=False, separators=(",", ":"))
    records: list[RawListingRecord] = []
    for item in listings:
        source_listing_id = _extract_listing_id(item)
        payload_json = json.dumps(item, ensure_ascii=False, separators=(",", ":"))
        payload_hash = hashlib.sha1(payload_json.encode("utf-8")).hexdigest()
        records.append(
            RawListingRecord(
                source_platform=SOURCE_PLATFORM,
                source_listing_id=source_listing_id,
                fetch_status=fetch_status,
                fetched_at=fetched_at,
                payload_json=payload_json,
                payload_hash=payload_hash,
                request_meta_json=request_meta_json,
                created_at=created_at,
            )
        )
    return records


def _extract_listing_id(item: dict[str, Any]) -> str:
    for key in LISTING_ID_CANDIDATE_KEYS:
        value = item.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    canonical = json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha1:" + hashlib.sha1(canonical.encode("utf-8")).hexdigest()
