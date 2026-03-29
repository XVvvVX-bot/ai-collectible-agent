from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from ai_agent_v2.clients.zhaoonline import now_utc_iso
from ai_agent_v2.storage.sqlite_store import SqliteV2Store

SOURCE_PLATFORM = "zhaoonline"

STATUS_MAP = {
    "1": "preview",
    "2": "live",
    "3": "ended",
}


@dataclass(frozen=True)
class NormalizationRunResult:
    source_listing_ids: tuple[str, ...]
    listing_ids: tuple[str, ...]
    processed_raw_snapshots: int
    listings_upserted: int
    media_deleted: int
    media_inserted: int
    events_inserted: int


def run_zhaoonline_norm_v2(
    db_path: str,
    *,
    source_listing_ids: Sequence[str] | None = None,
    sync_run_ids: Sequence[str] | None = None,
) -> NormalizationRunResult:
    SqliteV2Store(db_path).ensure_schema()
    with sqlite3.connect(Path(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        target_ids = _resolve_target_source_listing_ids(conn, source_listing_ids=source_listing_ids, sync_run_ids=sync_run_ids)
        if not target_ids:
            return NormalizationRunResult(
                source_listing_ids=(),
                listing_ids=(),
                processed_raw_snapshots=0,
                listings_upserted=0,
                media_deleted=0,
                media_inserted=0,
                events_inserted=0,
            )

        latest_raw_rows = _load_latest_raw_rows(conn, target_ids)
        existing_rows = _load_existing_norm_rows(conn, target_ids)
        upserts = []
        listing_ids: list[str] = []
        media_delete_count = 0
        media_insert_count = 0
        now = now_utc_iso()

        for source_listing_id in target_ids:
            raw_row = latest_raw_rows.get(source_listing_id)
            if raw_row is None:
                continue
            payload = json.loads(str(raw_row["payload_json"]))
            existing_row = existing_rows.get(source_listing_id)
            norm_row = _build_norm_row(
                payload=payload,
                raw_row=raw_row,
                existing_row=existing_row,
                now=now,
            )
            upserts.append(norm_row)
            listing_ids.append(str(norm_row["id"]))

        if upserts:
            conn.executemany(
                """
                INSERT INTO market_listings_norm_v2 (
                  id, source_platform, source_listing_id, auction_no, title, status_raw, status_norm,
                  old_status_raw, new_status_raw, change_time, category_id_raw, category_name_raw,
                  category_norm, character_id_raw, character_name_raw, character_norm, description,
                  description_character, rating_agency, rating_score, grade_remarks, auction_type_raw,
                  price_initial, price_end, buyer_fee_pct, preview_at, start_at, end_at, upload_at,
                  cancel_at, return_at, return_reason, return_remarks, settlement_status, settlement_at,
                  auction_size, auction_metal, auction_num, actual_num, is_delay, delay_time_sec,
                  exit_ban, primary_image_url, video_url, first_seen_at, last_seen_at, created_at, updated_at
                ) VALUES (
                  :id, :source_platform, :source_listing_id, :auction_no, :title, :status_raw, :status_norm,
                  :old_status_raw, :new_status_raw, :change_time, :category_id_raw, :category_name_raw,
                  :category_norm, :character_id_raw, :character_name_raw, :character_norm, :description,
                  :description_character, :rating_agency, :rating_score, :grade_remarks, :auction_type_raw,
                  :price_initial, :price_end, :buyer_fee_pct, :preview_at, :start_at, :end_at, :upload_at,
                  :cancel_at, :return_at, :return_reason, :return_remarks, :settlement_status, :settlement_at,
                  :auction_size, :auction_metal, :auction_num, :actual_num, :is_delay, :delay_time_sec,
                  :exit_ban, :primary_image_url, :video_url, :first_seen_at, :last_seen_at, :created_at, :updated_at
                )
                ON CONFLICT(source_platform, source_listing_id) DO UPDATE SET
                  auction_no = excluded.auction_no,
                  title = excluded.title,
                  status_raw = excluded.status_raw,
                  status_norm = excluded.status_norm,
                  old_status_raw = excluded.old_status_raw,
                  new_status_raw = excluded.new_status_raw,
                  change_time = excluded.change_time,
                  category_id_raw = excluded.category_id_raw,
                  category_name_raw = excluded.category_name_raw,
                  category_norm = excluded.category_norm,
                  character_id_raw = excluded.character_id_raw,
                  character_name_raw = excluded.character_name_raw,
                  character_norm = excluded.character_norm,
                  description = excluded.description,
                  description_character = excluded.description_character,
                  rating_agency = excluded.rating_agency,
                  rating_score = excluded.rating_score,
                  grade_remarks = excluded.grade_remarks,
                  auction_type_raw = excluded.auction_type_raw,
                  price_initial = excluded.price_initial,
                  price_end = excluded.price_end,
                  buyer_fee_pct = excluded.buyer_fee_pct,
                  preview_at = excluded.preview_at,
                  start_at = excluded.start_at,
                  end_at = excluded.end_at,
                  upload_at = excluded.upload_at,
                  cancel_at = excluded.cancel_at,
                  return_at = excluded.return_at,
                  return_reason = excluded.return_reason,
                  return_remarks = excluded.return_remarks,
                  settlement_status = excluded.settlement_status,
                  settlement_at = excluded.settlement_at,
                  auction_size = excluded.auction_size,
                  auction_metal = excluded.auction_metal,
                  auction_num = excluded.auction_num,
                  actual_num = excluded.actual_num,
                  is_delay = excluded.is_delay,
                  delay_time_sec = excluded.delay_time_sec,
                  exit_ban = excluded.exit_ban,
                  primary_image_url = excluded.primary_image_url,
                  video_url = excluded.video_url,
                  last_seen_at = excluded.last_seen_at,
                  updated_at = excluded.updated_at
                """,
                upserts,
            )

            media_delete_count = _delete_existing_media(conn, listing_ids)
            media_insert_count = _insert_media_rows(conn, upserts, latest_raw_rows)

        event_insert_count = _insert_event_rows(conn, source_listing_ids=target_ids, sync_run_ids=sync_run_ids)
        conn.commit()

    return NormalizationRunResult(
        source_listing_ids=tuple(target_ids),
        listing_ids=tuple(listing_ids),
        processed_raw_snapshots=len(latest_raw_rows),
        listings_upserted=len(upserts),
        media_deleted=media_delete_count,
        media_inserted=media_insert_count,
        events_inserted=event_insert_count,
    )


def _resolve_target_source_listing_ids(
    conn: sqlite3.Connection,
    *,
    source_listing_ids: Sequence[str] | None,
    sync_run_ids: Sequence[str] | None,
) -> list[str]:
    resolved: list[str] = []
    seen: set[str] = set()

    if source_listing_ids:
        for value in source_listing_ids:
            text = _text(value)
            if text and text not in seen:
                seen.add(text)
                resolved.append(text)

    if sync_run_ids:
        placeholders = ",".join("?" for _ in sync_run_ids)
        rows = conn.execute(
            f"""
            SELECT DISTINCT auction_id
            FROM zhao_v2_auction_raw
            WHERE source_platform = ?
              AND sync_run_id IN ({placeholders})
            ORDER BY auction_id
            """,
            (SOURCE_PLATFORM, *sync_run_ids),
        ).fetchall()
        for row in rows:
            text = _text(row["auction_id"])
            if text and text not in seen:
                seen.add(text)
                resolved.append(text)

    if not resolved and source_listing_ids is None and sync_run_ids is None:
        rows = conn.execute(
            """
            SELECT DISTINCT auction_id
            FROM zhao_v2_auction_raw
            WHERE source_platform = ?
            ORDER BY auction_id
            """,
            (SOURCE_PLATFORM,),
        ).fetchall()
        for row in rows:
            text = _text(row["auction_id"])
            if text and text not in seen:
                seen.add(text)
                resolved.append(text)

    return resolved


def _load_latest_raw_rows(conn: sqlite3.Connection, source_listing_ids: Sequence[str]) -> dict[str, sqlite3.Row]:
    latest: dict[str, tuple[tuple[int, str, str], sqlite3.Row]] = {}
    for chunk in _chunked(source_listing_ids, 500):
        placeholders = ",".join("?" for _ in chunk)
        rows = conn.execute(
            f"""
            SELECT auction_id, payload_json, fetched_at, created_at, change_time_raw
            FROM zhao_v2_auction_raw
            WHERE source_platform = ?
              AND auction_id IN ({placeholders})
            """,
            (SOURCE_PLATFORM, *chunk),
        ).fetchall()
        for row in rows:
            auction_id = str(row["auction_id"])
            rank = (
                _int_value(row["change_time_raw"]) or 0,
                _text(row["fetched_at"]) or "",
                _text(row["created_at"]) or "",
            )
            existing = latest.get(auction_id)
            if existing is None or rank > existing[0]:
                latest[auction_id] = (rank, row)
    return {key: value[1] for key, value in latest.items()}


def _load_existing_norm_rows(conn: sqlite3.Connection, source_listing_ids: Sequence[str]) -> dict[str, sqlite3.Row]:
    existing: dict[str, sqlite3.Row] = {}
    for chunk in _chunked(source_listing_ids, 500):
        placeholders = ",".join("?" for _ in chunk)
        rows = conn.execute(
            f"""
            SELECT *
            FROM market_listings_norm_v2
            WHERE source_platform = ?
              AND source_listing_id IN ({placeholders})
            """,
            (SOURCE_PLATFORM, *chunk),
        ).fetchall()
        for row in rows:
            existing[str(row["source_listing_id"])] = row
    return existing


def _build_norm_row(
    *,
    payload: dict[str, Any],
    raw_row: sqlite3.Row,
    existing_row: sqlite3.Row | None,
    now: str,
) -> dict[str, Any]:
    source_listing_id = _text(payload.get("auctionId")) or _text(raw_row["auction_id"])
    auction_no = _text(payload.get("auctionNo"))
    status_raw = _text(payload.get("status"))

    return {
        "id": str(existing_row["id"]) if existing_row is not None else str(uuid.uuid4()),
        "source_platform": SOURCE_PLATFORM,
        "source_listing_id": source_listing_id,
        "auction_no": auction_no,
        "title": _text(payload.get("name")),
        "status_raw": status_raw,
        "status_norm": STATUS_MAP.get(status_raw, f"raw_{status_raw}" if status_raw else None),
        "old_status_raw": _text(payload.get("oldStatus")),
        "new_status_raw": _text(payload.get("newStatus")) or status_raw,
        "change_time": _ms_to_iso(payload.get("changeTime")),
        "category_id_raw": _text(payload.get("auctionCategoryId")),
        "category_name_raw": _text(payload.get("categoryName")),
        "category_norm": _text(payload.get("categoryName")),
        "character_id_raw": _text(payload.get("auctionCharacterId")),
        "character_name_raw": _text(payload.get("characterName")),
        "character_norm": _text(payload.get("characterName")),
        "description": _text(payload.get("descr")),
        "description_character": _text(payload.get("descrCharacter")),
        "rating_agency": _text(payload.get("ratingAgency")),
        "rating_score": _text(payload.get("ratingScore")),
        "grade_remarks": _text(payload.get("gradeRemarks")),
        "auction_type_raw": _text(payload.get("auctionType")),
        "price_initial": _float_value(payload.get("initialPrice")),
        "price_end": _float_value(payload.get("endPrice")),
        "buyer_fee_pct": _float_value(payload.get("buyChargeFee")),
        "preview_at": _ms_to_iso(payload.get("previewAt")),
        "start_at": _ms_to_iso(payload.get("startAt")),
        "end_at": _ms_to_iso(payload.get("endAt")),
        "upload_at": _ms_to_iso(payload.get("uploadAt")),
        "cancel_at": _ms_to_iso(payload.get("cancelAt")),
        "return_at": _ms_to_iso(payload.get("returnAt")),
        "return_reason": _text(payload.get("returnReason")),
        "return_remarks": _text(payload.get("returnRemarks")),
        "settlement_status": _text(payload.get("settlementStatus")),
        "settlement_at": _ms_to_iso(payload.get("settlementAt")),
        "auction_size": _text(payload.get("auctionSize")),
        "auction_metal": _text(payload.get("auctionMetal")),
        "auction_num": _int_value(payload.get("auctionNum")),
        "actual_num": _int_value(payload.get("actualNum")),
        "is_delay": _bool_int_value(payload.get("isDelay")),
        "delay_time_sec": _int_value(payload.get("delayTime")),
        "exit_ban": _text(payload.get("exitBan")),
        "primary_image_url": _extract_primary_image_url(payload),
        "video_url": _text(payload.get("videoUrl")),
        "first_seen_at": str(existing_row["first_seen_at"]) if existing_row is not None else (_text(raw_row["created_at"]) or now),
        "last_seen_at": _text(raw_row["fetched_at"]) or now,
        "created_at": str(existing_row["created_at"]) if existing_row is not None else now,
        "updated_at": now,
    }


def _delete_existing_media(conn: sqlite3.Connection, listing_ids: Sequence[str]) -> int:
    deleted = 0
    for chunk in _chunked(listing_ids, 500):
        placeholders = ",".join("?" for _ in chunk)
        cursor = conn.execute(
            f"DELETE FROM market_listing_media_v2 WHERE listing_id IN ({placeholders})",
            tuple(chunk),
        )
        deleted += cursor.rowcount
    return deleted


def _insert_media_rows(
    conn: sqlite3.Connection,
    norm_rows: Sequence[dict[str, Any]],
    latest_raw_rows: dict[str, sqlite3.Row],
) -> int:
    now = now_utc_iso()
    inserted = 0
    for norm_row in norm_rows:
        raw_row = latest_raw_rows.get(str(norm_row["source_listing_id"]))
        if raw_row is None:
            continue
        payload = json.loads(str(raw_row["payload_json"]))
        for media_row in _extract_media_rows(norm_row=norm_row, payload=payload, created_at=now):
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO market_listing_media_v2 (
                  id, listing_id, source_platform, source_listing_id, media_type, media_url, sort_order, label, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    media_row["id"],
                    media_row["listing_id"],
                    media_row["source_platform"],
                    media_row["source_listing_id"],
                    media_row["media_type"],
                    media_row["media_url"],
                    media_row["sort_order"],
                    media_row["label"],
                    media_row["created_at"],
                ),
            )
            inserted += cursor.rowcount
    return inserted


def _extract_media_rows(*, norm_row: dict[str, Any], payload: dict[str, Any], created_at: str) -> list[dict[str, Any]]:
    listing_id = str(norm_row["id"])
    source_listing_id = str(norm_row["source_listing_id"])
    rows: list[dict[str, Any]] = []
    seen_urls: set[tuple[str, str]] = set()

    pictures = payload.get("pictures")
    if isinstance(pictures, list):
        sorted_pictures = sorted(
            [pic for pic in pictures if isinstance(pic, dict)],
            key=lambda pic: _picture_sort_key(pic),
        )
        for index, picture in enumerate(sorted_pictures, start=1):
            media_url = _extract_picture_url(picture)
            if not media_url:
                continue
            identity = ("image", media_url)
            if identity in seen_urls:
                continue
            seen_urls.add(identity)
            rows.append(
                {
                    "id": str(uuid.uuid4()),
                    "listing_id": listing_id,
                    "source_platform": SOURCE_PLATFORM,
                    "source_listing_id": source_listing_id,
                    "media_type": "image",
                    "media_url": media_url,
                    "sort_order": index,
                    "label": _text(picture.get("picOrder")),
                    "created_at": created_at,
                }
            )

    primary_image_url = _text(payload.get("picPath"))
    if primary_image_url:
        identity = ("image", primary_image_url)
        if identity not in seen_urls:
            rows.append(
                {
                    "id": str(uuid.uuid4()),
                    "listing_id": listing_id,
                    "source_platform": SOURCE_PLATFORM,
                    "source_listing_id": source_listing_id,
                    "media_type": "image",
                    "media_url": primary_image_url,
                    "sort_order": 1,
                    "label": "primary",
                    "created_at": created_at,
                }
            )
            seen_urls.add(identity)

    video_url = _text(payload.get("videoUrl"))
    if video_url:
        identity = ("video", video_url)
        if identity not in seen_urls:
            rows.append(
                {
                    "id": str(uuid.uuid4()),
                    "listing_id": listing_id,
                    "source_platform": SOURCE_PLATFORM,
                    "source_listing_id": source_listing_id,
                    "media_type": "video",
                    "media_url": video_url,
                    "sort_order": len(rows) + 1,
                    "label": "video",
                    "created_at": created_at,
                }
            )
    return rows


def _insert_event_rows(
    conn: sqlite3.Connection,
    *,
    source_listing_ids: Sequence[str],
    sync_run_ids: Sequence[str] | None,
) -> int:
    inserted = 0
    if sync_run_ids:
        for chunk in _chunked(sync_run_ids, 500):
            placeholders = ",".join("?" for _ in chunk)
            rows = conn.execute(
                f"""
                SELECT auction_id, change_time_raw, old_status_raw, new_status_raw, payload_json, created_at
                FROM zhao_v2_auction_change_raw
                WHERE source_platform = ?
                  AND sync_run_id IN ({placeholders})
                """,
                (SOURCE_PLATFORM, *chunk),
            ).fetchall()
            inserted += _insert_event_chunk(conn, rows)
        return inserted

    for chunk in _chunked(source_listing_ids, 500):
        placeholders = ",".join("?" for _ in chunk)
        rows = conn.execute(
            f"""
            SELECT auction_id, change_time_raw, old_status_raw, new_status_raw, payload_json, created_at
            FROM zhao_v2_auction_change_raw
            WHERE source_platform = ?
              AND auction_id IN ({placeholders})
            """,
            (SOURCE_PLATFORM, *chunk),
        ).fetchall()
        inserted += _insert_event_chunk(conn, rows)
    return inserted


def _insert_event_chunk(conn: sqlite3.Connection, rows: Iterable[sqlite3.Row]) -> int:
    inserted = 0
    for row in rows:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO market_listing_events_v2 (
              id, source_platform, source_listing_id, change_time, old_status_raw, new_status_raw, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                SOURCE_PLATFORM,
                str(row["auction_id"]),
                _ms_to_iso(row["change_time_raw"]),
                _text(row["old_status_raw"]),
                _text(row["new_status_raw"]),
                str(row["payload_json"]),
                _text(row["created_at"]) or now_utc_iso(),
            ),
        )
        inserted += cursor.rowcount
    return inserted


def _extract_primary_image_url(payload: dict[str, Any]) -> str | None:
    pic_path = _text(payload.get("picPath"))
    if pic_path:
        return pic_path
    pictures = payload.get("pictures")
    if isinstance(pictures, list):
        for picture in pictures:
            if not isinstance(picture, dict):
                continue
            media_url = _extract_picture_url(picture)
            if media_url:
                return media_url
    return None


def _extract_picture_url(picture: dict[str, Any]) -> str | None:
    pic_path = _text(picture.get("picPath"))
    if pic_path:
        return pic_path
    base_path = _text(picture.get("path"))
    name = _text(picture.get("name"))
    if base_path and name:
        return f"{base_path.rstrip('/')}/{name.lstrip('/')}"
    return None


def _picture_sort_key(picture: dict[str, Any]) -> tuple[int, str]:
    order = _text(picture.get("picOrder")) or ""
    if order.isdigit():
        return (int(order), order)
    if len(order) == 1 and order.isalpha():
        return (ord(order.upper()) - ord("A") + 1, order)
    return (9999, order)


def _ms_to_iso(value: Any) -> str | None:
    millis = _int_value(value)
    if millis is None:
        return None
    return datetime.fromtimestamp(millis / 1000, tz=timezone.utc).isoformat()


def _float_value(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_value(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _bool_int_value(value: Any) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return 1 if value else 0
    text = _text(value)
    if text is None:
        return None
    if text.lower() in {"true", "yes"}:
        return 1
    if text.lower() in {"false", "no"}:
        return 0
    return _int_value(text)


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _chunked(values: Sequence[str], size: int) -> Iterable[Sequence[str]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]
