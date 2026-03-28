from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ai_agent.clients.zhaoonline import now_utc_iso
from ai_agent.storage.sqlite_raw_store import SqliteRawStore

REASON_WEIGHTS = {
    "item_name_exact": 80.0,
    "category_exact": 30.0,
    "series_exact": 25.0,
    "item_name_phrase": 35.0,
    "item_name_token_overlap": 20.0,
    "grade_exact": 10.0,
}
REASON_ORDER = [
    "item_name_exact",
    "category_exact",
    "series_exact",
    "item_name_phrase",
    "item_name_token_overlap",
    "grade_exact",
]


@dataclass(frozen=True)
class ListingMatchRecord:
    user_id: str
    listing_id: str
    user_item_id: str
    item_type: str
    match_score: float
    reasons: list[str]


@dataclass(frozen=True)
class MatchingRunResult:
    users_processed: int
    listings_scanned: int
    items_scanned: int
    evaluated_pairs: int
    matched_pairs: int
    inserted: int
    updated: int
    deactivated: int


def run_v1_matching(
    db_path: str,
    *,
    user_id: str | None = None,
    min_score: float = 30.0,
    only_active_listings: bool = True,
    strict_name_match: bool = True,
) -> MatchingRunResult:
    if min_score < 0:
        raise ValueError("min_score must be >= 0.")

    store = SqliteRawStore(db_path)
    store.ensure_schema()
    db_file = Path(db_path)
    now = now_utc_iso()

    with sqlite3.connect(db_file) as conn:
        conn.row_factory = sqlite3.Row
        user_rows = _load_users(conn, user_id=user_id)
        listing_rows = _load_listings(conn, only_active=only_active_listings)
        listings_scanned = len(listing_rows)
        users_processed = len(user_rows)
        items_scanned = 0
        evaluated_pairs = 0
        matched_pairs = 0
        inserted = 0
        updated = 0
        deactivated = 0

        for user in user_rows:
            uid = str(user["id"])
            item_rows = _load_user_items(conn, uid)
            items_scanned += len(item_rows)
            run_keys: set[tuple[str, str]] = set()
            for item in item_rows:
                for listing in listing_rows:
                    evaluated_pairs += 1
                    record = _build_match(
                        item=item,
                        listing=listing,
                        user_id=uid,
                        min_score=min_score,
                        strict_name_match=strict_name_match,
                    )
                    if record is None:
                        continue
                    matched_pairs += 1
                    run_keys.add((record.listing_id, record.user_item_id))
                    changed = _upsert_match(conn=conn, match=record, now=now)
                    if changed == "inserted":
                        inserted += 1
                    elif changed == "updated":
                        updated += 1

            deactivated += _deactivate_stale_matches(conn=conn, user_id=uid, run_keys=run_keys, now=now)

        conn.commit()

    return MatchingRunResult(
        users_processed=users_processed,
        listings_scanned=listings_scanned,
        items_scanned=items_scanned,
        evaluated_pairs=evaluated_pairs,
        matched_pairs=matched_pairs,
        inserted=inserted,
        updated=updated,
        deactivated=deactivated,
    )


def _build_match(
    *,
    item: sqlite3.Row,
    listing: sqlite3.Row,
    user_id: str,
    min_score: float,
    strict_name_match: bool,
) -> ListingMatchRecord | None:
    reasons: list[str] = []

    item_category = _canon(item["category"])
    item_series = _canon(item["series"])
    item_name = _canon(item["item_name"])
    item_grade = _canon(item["grade_condition"])

    listing_category = _canon(listing["category_norm"]) or _canon(listing["category_raw"])
    listing_series = _canon(listing["series_norm"]) or _canon(listing["series_raw"])
    title = _canon(listing["title"])
    description = _canon(listing["description"])
    listing_text = f"{title} {description}".strip()
    listing_grade = _canon(listing["grade_norm"]) or _canon(listing["grade_raw"])
    normalized_item_name = _normalize_name_for_exact(item_name)
    normalized_title = _normalize_name_for_exact(title)
    if normalized_item_name and normalized_title and normalized_item_name == normalized_title:
        reasons.append("item_name_exact")

    if item_category and listing_category and item_category == listing_category:
        reasons.append("category_exact")
    if item_series and listing_series and item_series == listing_series:
        reasons.append("series_exact")

    if item_name and listing_text:
        if item_name in listing_text:
            reasons.append("item_name_phrase")
        else:
            overlap_ratio = _token_overlap_ratio(item_name, listing_text)
            if overlap_ratio >= 0.7:
                reasons.append("item_name_token_overlap")

    if item_grade and listing_grade and item_grade in listing_grade:
        reasons.append("grade_exact")

    reason_set = set(reasons)
    ordered_reasons = [code for code in REASON_ORDER if code in reason_set]
    if strict_name_match and "item_name_exact" not in reason_set:
        return None
    score = sum(REASON_WEIGHTS[code] for code in ordered_reasons)
    if score < min_score:
        return None

    return ListingMatchRecord(
        user_id=user_id,
        listing_id=str(listing["id"]),
        user_item_id=str(item["id"]),
        item_type=str(item["item_type"]),
        match_score=score,
        reasons=ordered_reasons,
    )


def _upsert_match(conn: sqlite3.Connection, *, match: ListingMatchRecord, now: str) -> str:
    reasons_json = json.dumps(match.reasons, ensure_ascii=False, separators=(",", ":"))
    existing = conn.execute(
        """
        SELECT id, match_score, match_reasons_json, status
        FROM listing_matches
        WHERE user_id = ? AND listing_id = ? AND user_item_id = ?
        """,
        (match.user_id, match.listing_id, match.user_item_id),
    ).fetchone()
    if existing is None:
        conn.execute(
            """
            INSERT INTO listing_matches (
              id,
              user_id,
              listing_id,
              user_item_id,
              item_type,
              match_score,
              match_reasons_json,
              status,
              matched_at,
              updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
            """,
            (
                str(uuid.uuid4()),
                match.user_id,
                match.listing_id,
                match.user_item_id,
                match.item_type,
                match.match_score,
                reasons_json,
                now,
                now,
            ),
        )
        return "inserted"

    score_changed = float(existing[1]) != float(match.match_score)
    reasons_changed = str(existing[2]) != reasons_json
    status_changed = str(existing[3]) != "active"
    if score_changed or reasons_changed or status_changed:
        conn.execute(
            """
            UPDATE listing_matches
            SET item_type = ?,
                match_score = ?,
                match_reasons_json = ?,
                status = 'active',
                matched_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                match.item_type,
                match.match_score,
                reasons_json,
                now,
                now,
                str(existing[0]),
            ),
        )
        return "updated"
    return "unchanged"


def _deactivate_stale_matches(
    conn: sqlite3.Connection,
    *,
    user_id: str,
    run_keys: set[tuple[str, str]],
    now: str,
) -> int:
    rows = conn.execute(
        """
        SELECT listing_id, user_item_id
        FROM listing_matches
        WHERE user_id = ? AND status = 'active'
        """,
        (user_id,),
    ).fetchall()
    to_deactivate = [
        (str(row["listing_id"]), str(row["user_item_id"]))
        for row in rows
        if (str(row["listing_id"]), str(row["user_item_id"])) not in run_keys
    ]
    if not to_deactivate:
        return 0
    conn.executemany(
        """
        UPDATE listing_matches
        SET status = 'inactive', updated_at = ?
        WHERE user_id = ? AND listing_id = ? AND user_item_id = ? AND status = 'active'
        """,
        [(now, user_id, listing_id, user_item_id) for listing_id, user_item_id in to_deactivate],
    )
    return len(to_deactivate)


def _load_users(conn: sqlite3.Connection, *, user_id: str | None) -> list[sqlite3.Row]:
    if user_id:
        row = conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            raise ValueError(f"user not found: {user_id}")
        return [row]
    return conn.execute("SELECT id FROM users ORDER BY id").fetchall()


def _load_user_items(conn: sqlite3.Connection, user_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT id, item_type, category, series, item_name, grade_condition
        FROM user_items
        WHERE user_id = ? AND is_active = 1
        ORDER BY item_type, dedupe_key, id
        """,
        (user_id,),
    ).fetchall()


def _load_listings(conn: sqlite3.Connection, *, only_active: bool) -> list[sqlite3.Row]:
    if only_active:
        return conn.execute(
            """
            SELECT
              id,
              category_norm,
              category_raw,
              series_norm,
              series_raw,
              title,
              description,
              grade_norm,
              grade_raw
            FROM market_listings_norm
            WHERE is_active = 1
            ORDER BY source_platform, source_listing_id
            """
        ).fetchall()
    return conn.execute(
        """
        SELECT
          id,
          category_norm,
          category_raw,
          series_norm,
          series_raw,
          title,
          description,
          grade_norm,
          grade_raw
        FROM market_listings_norm
        ORDER BY source_platform, source_listing_id
        """
    ).fetchall()


def _canon(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def _token_overlap_ratio(query_text: str, target_text: str) -> float:
    query_tokens = _tokenize(query_text)
    if not query_tokens:
        return 0.0
    target_tokens = set(_tokenize(target_text))
    if not target_tokens:
        return 0.0
    hits = sum(1 for token in query_tokens if token in target_tokens)
    return hits / len(query_tokens)


def _tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for chunk in text.replace("/", " ").replace("-", " ").split():
        token = chunk.strip().lower()
        if not token:
            continue
        tokens.append(token)
    return tokens


def _normalize_name_for_exact(value: str) -> str:
    if not value:
        return ""
    lowered = value.lower().strip()
    chars: list[str] = []
    for ch in lowered:
        if ch.isalnum():
            chars.append(ch)
    return "".join(chars)
