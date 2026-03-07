from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_agent.clients.zhaoonline import now_utc_iso
from ai_agent.ingestion.raw_ingest import SOURCE_PLATFORM
from ai_agent.storage.sqlite_raw_store import SqliteRawStore


DEFAULT_STATUS_MAP = {
    "1": "preview",
    "2": "live",
    "3": "ended",
}


@dataclass(frozen=True)
class NormalizationResult:
    processed: int
    upserted: int
    skipped: int
    last_raw_rowid: int


def normalize_zhaoonline_raw(
    db_path: str,
    batch_size: int = 500,
) -> NormalizationResult:
    if batch_size < 1:
        raise ValueError("batch_size must be >= 1.")

    store = SqliteRawStore(db_path)
    store.ensure_schema()
    db_file = Path(db_path)

    with sqlite3.connect(db_file) as conn:
        conn.row_factory = sqlite3.Row
        last_rowid = _get_last_rowid(conn, SOURCE_PLATFORM)
        taxonomy_map = _load_taxonomy_map(conn, SOURCE_PLATFORM)

        rows = conn.execute(
            """
            SELECT
              rowid,
              source_listing_id,
              fetch_status,
              fetched_at,
              payload_json
            FROM market_listings_raw
            WHERE source_platform = ?
              AND rowid > ?
            ORDER BY rowid
            LIMIT ?
            """,
            (SOURCE_PLATFORM, last_rowid, batch_size),
        ).fetchall()

        if not rows:
            return NormalizationResult(
                processed=0,
                upserted=0,
                skipped=0,
                last_raw_rowid=last_rowid,
            )

        processed = 0
        upserted = 0
        skipped = 0
        newest_rowid = last_rowid
        for row in rows:
            processed += 1
            newest_rowid = max(newest_rowid, int(row["rowid"]))
            payload_json = row["payload_json"]
            try:
                payload = json.loads(payload_json)
            except json.JSONDecodeError:
                skipped += 1
                continue
            if not isinstance(payload, dict):
                skipped += 1
                continue

            norm = _normalize_payload(
                payload=payload,
                source_listing_id=str(row["source_listing_id"]),
                fetch_status=str(row["fetch_status"] or ""),
                fetched_at=str(row["fetched_at"]),
                taxonomy_map=taxonomy_map,
            )
            if norm is None:
                skipped += 1
                continue

            conn.execute(
                """
                INSERT INTO market_listings_norm (
                  id,
                  source_platform,
                  source_listing_id,
                  source_url,
                  auction_no,
                  title,
                  category_raw,
                  category_norm,
                  series_raw,
                  series_norm,
                  status_raw,
                  status_norm,
                  auction_type_raw,
                  auction_type_norm,
                  grade_raw,
                  grade_norm,
                  description,
                  image_url,
                  start_at,
                  end_at,
                  preview_at,
                  price_initial,
                  price_current,
                  price_end,
                  currency,
                  is_active,
                  first_seen_at,
                  last_seen_at,
                  created_at,
                  updated_at
                ) VALUES (
                  ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                ON CONFLICT(source_platform, source_listing_id)
                DO UPDATE SET
                  source_url = excluded.source_url,
                  auction_no = excluded.auction_no,
                  title = excluded.title,
                  category_raw = excluded.category_raw,
                  category_norm = excluded.category_norm,
                  series_raw = excluded.series_raw,
                  series_norm = excluded.series_norm,
                  status_raw = excluded.status_raw,
                  status_norm = excluded.status_norm,
                  auction_type_raw = excluded.auction_type_raw,
                  auction_type_norm = excluded.auction_type_norm,
                  grade_raw = excluded.grade_raw,
                  grade_norm = excluded.grade_norm,
                  description = excluded.description,
                  image_url = excluded.image_url,
                  start_at = excluded.start_at,
                  end_at = excluded.end_at,
                  preview_at = excluded.preview_at,
                  price_initial = excluded.price_initial,
                  price_current = excluded.price_current,
                  price_end = excluded.price_end,
                  currency = excluded.currency,
                  is_active = excluded.is_active,
                  first_seen_at = min(market_listings_norm.first_seen_at, excluded.first_seen_at),
                  last_seen_at = max(market_listings_norm.last_seen_at, excluded.last_seen_at),
                  updated_at = excluded.updated_at
                """,
                norm,
            )
            upserted += 1

        _set_last_rowid(conn, SOURCE_PLATFORM, newest_rowid)
        conn.commit()

    return NormalizationResult(
        processed=processed,
        upserted=upserted,
        skipped=skipped,
        last_raw_rowid=newest_rowid,
    )


def _normalize_payload(
    payload: dict[str, Any],
    source_listing_id: str,
    fetch_status: str,
    fetched_at: str,
    taxonomy_map: dict[tuple[str, str], str],
) -> tuple[Any, ...] | None:
    title = _to_text(payload.get("name")) or _to_text(payload.get("title"))
    if not title:
        return None

    status_raw = _to_text(payload.get("status")) or fetch_status
    status_norm = _map_taxonomy(
        taxonomy_map=taxonomy_map,
        field_name="status",
        raw_value=status_raw,
        fallback=DEFAULT_STATUS_MAP.get(status_raw, "unknown"),
    )
    category_raw = _to_text(payload.get("auctionCategoryId"))
    category_norm = _map_taxonomy(
        taxonomy_map=taxonomy_map,
        field_name="category",
        raw_value=category_raw,
        fallback=None,
    )
    series_raw = _to_text(payload.get("auctionCharacterId"))
    series_norm = _map_taxonomy(
        taxonomy_map=taxonomy_map,
        field_name="series",
        raw_value=series_raw,
        fallback=None,
    )
    auction_type_raw = _to_text(payload.get("auctionType"))
    auction_type_norm = _map_taxonomy(
        taxonomy_map=taxonomy_map,
        field_name="auction_type",
        raw_value=auction_type_raw,
        fallback="auction" if auction_type_raw == "1" else None,
    )
    grade_raw = _grade_raw(payload.get("ratingAgency"), payload.get("ratingScore"))
    grade_norm = _map_taxonomy(
        taxonomy_map=taxonomy_map,
        field_name="grade",
        raw_value=grade_raw,
        fallback=grade_raw,
    )
    price_initial = _to_float(payload.get("initialPrice"))
    price_end = _to_float(payload.get("endPrice"))
    price_current = price_end if price_end is not None else price_initial
    now = now_utc_iso()

    return (
        str(uuid.uuid4()),
        SOURCE_PLATFORM,
        source_listing_id,
        _to_text(payload.get("url")),
        _to_text(payload.get("auctionNo")),
        title,
        category_raw,
        category_norm,
        series_raw,
        series_norm,
        status_raw,
        status_norm,
        auction_type_raw,
        auction_type_norm,
        grade_raw,
        grade_norm,
        _to_text(payload.get("descr")) or _to_text(payload.get("descrCharacter")),
        _pick_image_url(payload),
        _epoch_ms_to_iso(payload.get("startAt")),
        _epoch_ms_to_iso(payload.get("endAt")),
        _epoch_ms_to_iso(payload.get("previewAt")),
        price_initial,
        price_current,
        price_end,
        "CNY",
        1 if status_norm in {"preview", "live"} else 0,
        fetched_at,
        fetched_at,
        now,
        now,
    )


def _load_taxonomy_map(conn: sqlite3.Connection, source_platform: str) -> dict[tuple[str, str], str]:
    rows = conn.execute(
        """
        SELECT field_name, raw_value, norm_value
        FROM market_taxonomy_map
        WHERE source_platform = ?
        """,
        (source_platform,),
    ).fetchall()
    return {(str(r[0]), str(r[1])): str(r[2]) for r in rows}


def _map_taxonomy(
    taxonomy_map: dict[tuple[str, str], str],
    field_name: str,
    raw_value: str | None,
    fallback: str | None,
) -> str | None:
    if raw_value is None or raw_value == "":
        return fallback
    return taxonomy_map.get((field_name, raw_value), fallback)


def _pick_image_url(payload: dict[str, Any]) -> str | None:
    primary = _to_text(payload.get("picPath"))
    if primary:
        return primary
    images = payload.get("images")
    if isinstance(images, list):
        for item in images:
            if isinstance(item, dict):
                url = _to_text(item.get("url"))
                if url:
                    return url
    return None


def _grade_raw(rating_agency: Any, rating_score: Any) -> str | None:
    agency = _to_text(rating_agency)
    score = _to_text(rating_score)
    if agency and score:
        return f"{agency} {score}"
    return agency or score


def _epoch_ms_to_iso(value: Any) -> str | None:
    if value in (None, ""):
        return None
    try:
        ms = int(value)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).isoformat()


def _to_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _get_last_rowid(conn: sqlite3.Connection, source_platform: str) -> int:
    row = conn.execute(
        """
        SELECT last_raw_rowid
        FROM normalization_state
        WHERE source_platform = ?
        """,
        (source_platform,),
    ).fetchone()
    if row is None:
        conn.execute(
            """
            INSERT INTO normalization_state (source_platform, last_raw_rowid, updated_at)
            VALUES (?, 0, datetime('now'))
            """,
            (source_platform,),
        )
        return 0
    return int(row[0])


def _set_last_rowid(conn: sqlite3.Connection, source_platform: str, last_rowid: int) -> None:
    conn.execute(
        """
        UPDATE normalization_state
        SET last_raw_rowid = ?, updated_at = datetime('now')
        WHERE source_platform = ?
        """,
        (int(last_rowid), source_platform),
    )

