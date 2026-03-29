from __future__ import annotations

import json
import re
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ai_agent_v2.clients.zhaoonline import now_utc_iso
from ai_agent_v2.parsing.listing_parser import (
    _classify_parse_family,
    _parse_coin_title,
    _parse_stamp_title,
)
from ai_agent_v2.storage.sqlite_store import SqliteV2Store

MATCHER_VERSION = "v2_matcher_003"
SUPPORTED_PARSE_FAMILIES = {"stamp_like", "coin_like"}
STAMP_HARD_VARIANT_TOKENS = {"小型张", "型张", "版张", "带厂铭", "直角边", "色标", "双连", "四连", "方连", "折版", "再版", "一版", "二版", "三版", "四版", "M"}
TRUSTED_STAMP_MIN_CONFIDENCE = 0.80
TRUSTED_COIN_MIN_CONFIDENCE = 0.90
STAMP_CODE_SCAN_RE = re.compile(r"(?:特|纪|普|文|编|J|T|N)\s*\d+[A-Z]?")
CONDITION_RANKS = {
    "全品": 100,
    "未使用": 95,
    "完全未使用品": 95,
    "评级票": 95,
    "评级币": 95,
    "上品": 85,
    "中上品": 75,
    "中品": 65,
    "九五品": 95,
    "九品": 90,
    "八五品": 85,
    "八品": 80,
    "七品": 70,
    "六品": 60,
    "五品": 50,
    "差品": 20,
    "修补品": 10,
}


@dataclass(frozen=True)
class ListingMatchRecord:
    user_id: str
    listing_id: str
    user_item_id: str
    item_type: str
    relationship_type: str
    match_score: float
    identity_score: float
    series_score: float
    variant_score: float
    condition_score: float
    reasons: list[str]


@dataclass(frozen=True)
class MatchingRunResult:
    run_id: str
    users_processed: int
    listings_scanned: int
    items_scanned: int
    evaluated_pairs: int
    matched_pairs: int
    inserted: int
    updated: int
    deactivated: int


@dataclass(frozen=True)
class ParsedUserItem:
    id: str
    user_id: str
    item_type: str
    category: str | None
    series_raw: str | None
    item_name: str
    grade_condition: str | None
    year_value: int | None
    parse_family: str
    issue_code_norm: str | None
    issue_name: str | None
    theme_name: str | None
    asset_type: str | None
    finish_type: str | None
    weight_text: str | None
    denomination_text: str | None
    identity_core: str | None
    series_key: str | None
    variant_tokens: list[str]
    quantity_tokens: list[str]
    condition_tokens: list[str]
    condition_mode: str
    issue_part_token: str | None
    subject_label: str | None
    precision_mode: str
    allow_series_matches: bool
    allow_variant_matches: bool


def run_v2_matching(
    db_path: str,
    *,
    user_id: str | None = None,
    only_active_listings: bool = True,
) -> MatchingRunResult:
    store = SqliteV2Store(db_path)
    store.ensure_schema()

    run_id = str(uuid.uuid4())
    started_at = now_utc_iso()

    users_processed = 0
    listings_scanned = 0
    items_scanned = 0
    evaluated_pairs = 0
    matched_pairs = 0
    inserted = 0
    updated = 0
    deactivated = 0

    with sqlite3.connect(Path(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        _insert_match_run(conn, run_id=run_id, user_id=user_id, started_at=started_at, only_active_listings=only_active_listings)
        try:
            user_rows = _load_users(conn, user_id=user_id)
            listing_rows = _load_listing_candidates(conn, only_active=only_active_listings)
            listing_groups = _group_listing_candidates(listing_rows)

            users_processed = len(user_rows)
            listings_scanned = len(listing_rows)

            for user_row in user_rows:
                uid = str(user_row["id"])
                parsed_items = [_parse_user_item(row) for row in _load_match_subjects(conn, uid)]
                items_scanned += len(parsed_items)
                run_keys: set[tuple[str, str]] = set()

                for item in parsed_items:
                    candidate_rows = _candidate_rows(listing_groups, item)
                    evaluated_pairs += len(candidate_rows)
                    for listing in candidate_rows:
                        match = _build_match(item=item, listing=listing)
                        if match is None:
                            continue
                        matched_pairs += 1
                        run_keys.add((match.listing_id, match.user_item_id))
                        changed = _upsert_match(conn, match=match, now=started_at)
                        if changed == "inserted":
                            inserted += 1
                        elif changed == "updated":
                            updated += 1

                deactivated += _deactivate_stale_matches(conn, user_id=uid, run_keys=run_keys, now=started_at)

            _finish_match_run(
                conn,
                run_id=run_id,
                finished_at=now_utc_iso(),
                status="success",
                users_processed=users_processed,
                items_scanned=items_scanned,
                listings_scanned=listings_scanned,
                evaluated_pairs=evaluated_pairs,
                matched_pairs=matched_pairs,
                inserted=inserted,
                updated=updated,
                deactivated=deactivated,
                error_message=None,
            )
            conn.commit()
        except Exception as exc:
            _finish_match_run(
                conn,
                run_id=run_id,
                finished_at=now_utc_iso(),
                status="failed",
                users_processed=users_processed,
                items_scanned=items_scanned,
                listings_scanned=listings_scanned,
                evaluated_pairs=evaluated_pairs,
                matched_pairs=matched_pairs,
                inserted=inserted,
                updated=updated,
                deactivated=deactivated,
                error_message=str(exc),
            )
            conn.commit()
            raise

    return MatchingRunResult(
        run_id=run_id,
        users_processed=users_processed,
        listings_scanned=listings_scanned,
        items_scanned=items_scanned,
        evaluated_pairs=evaluated_pairs,
        matched_pairs=matched_pairs,
        inserted=inserted,
        updated=updated,
        deactivated=deactivated,
    )


def _build_match(*, item: ParsedUserItem, listing: sqlite3.Row) -> ListingMatchRecord | None:
    if item.parse_family not in SUPPORTED_PARSE_FAMILIES:
        return None
    if item.parse_family != _clean_text(listing["parse_family"]):
        return None
    if not _is_trusted_match_pair(item=item, listing=listing):
        return None
    if item.parse_family == "stamp_like":
        return _build_stamp_match(item=item, listing=listing)
    if item.parse_family == "coin_like":
        return _build_coin_match(item=item, listing=listing)
    return None


def _build_stamp_match(*, item: ParsedUserItem, listing: sqlite3.Row) -> ListingMatchRecord | None:
    reasons: list[str] = []
    identity_score = 0.0
    series_score = 0.0
    variant_score = 0.0
    condition_score = 0.0

    item_code = _clean_text(item.issue_code_norm)
    listing_code = _clean_text(listing["issue_code_norm"])
    item_name = _normalize_key(item.issue_name)
    listing_name = _normalize_key(listing["issue_name"])
    item_series = _normalize_key(item.series_key)
    listing_series = _normalize_key(listing["series_key"])
    item_part = _normalize_key(item.issue_part_token)
    listing_part = _normalize_key(_extract_issue_part_token(listing["raw_title"]))

    if item_name and listing_name and item_name != listing_name:
        return None

    if item_code and listing_code and item_code == listing_code:
        identity_score += 75.0
        reasons.append("issue_code_exact")
    if item_name and listing_name and item_name == listing_name:
        identity_score += 70.0
        reasons.append("issue_name_exact")
    if item_series and listing_series and item_series == listing_series:
        series_score += 20.0
        reasons.append("series_key_exact")
    if item_part and listing_part and item_part == listing_part:
        identity_score += 20.0
        reasons.append("issue_part_exact")

    if item_part and item_part != listing_part:
        return None

    listing_variant_tokens = _json_list(listing["variant_tokens_json"])
    listing_quantity_tokens = _json_list(listing["quantity_tokens_json"])
    listing_condition_tokens = _listing_condition_tokens(listing)

    if item.quantity_tokens and not _has_token_overlap(item.quantity_tokens, listing_quantity_tokens):
        return None
    required_variant_tokens = [token for token in item.variant_tokens if token in STAMP_HARD_VARIANT_TOKENS]
    if required_variant_tokens and not _has_token_overlap(required_variant_tokens, listing_variant_tokens):
        return None
    if item.condition_mode == "require" and _has_hard_condition_conflict(item.condition_tokens, listing_condition_tokens):
        return None
    if item.condition_mode == "require" and not _condition_requirement_satisfied(item.condition_tokens, listing_condition_tokens):
        return None

    variant_overlap = _overlap_count(item.variant_tokens, listing_variant_tokens)
    if variant_overlap:
        variant_score += min(variant_overlap * 6.0, 12.0)
        reasons.append("variant_overlap")

    condition_overlap = _overlap_count(item.condition_tokens, listing_condition_tokens)
    if condition_overlap:
        condition_score += min(condition_overlap * 4.0, 8.0)
        reasons.append("condition_overlap")
    if item.condition_tokens and _condition_requirement_satisfied(item.condition_tokens, listing_condition_tokens):
        condition_score += 6.0
        reasons.append("condition_compatible")
    elif item.condition_tokens and item.condition_mode == "prefer" and _has_hard_condition_conflict(item.condition_tokens, listing_condition_tokens):
        condition_score -= 6.0
        reasons.append("condition_mismatch")

    has_variant_conflict = _has_token_conflict(item.variant_tokens, listing_variant_tokens)
    has_quantity_conflict = _has_token_conflict(item.quantity_tokens, listing_quantity_tokens)
    has_code_conflict = bool(item_code and listing_code and item_code != listing_code)

    relationship_type: str | None = None
    if (
        not has_variant_conflict
        and not has_quantity_conflict
        and not has_code_conflict
        and ("issue_code_exact" in reasons or "issue_name_exact" in reasons)
        and ("issue_name_exact" in reasons or not (item_name and listing_name))
        and ((item_part and listing_part and "issue_part_exact" in reasons) or not (item_part or listing_part))
    ):
        relationship_type = "exact_identity"
    elif "issue_code_exact" in reasons or "issue_name_exact" in reasons:
        relationship_type = "variant_related"
    elif "series_key_exact" in reasons:
        relationship_type = "series_related"

    total_score = identity_score + series_score + variant_score + condition_score
    single_anchor_exact = relationship_type == "exact_identity" and (("issue_code_exact" in reasons) ^ ("issue_name_exact" in reasons))
    if relationship_type is None:
        return None
    if not _relationship_allowed(item, relationship_type):
        return None
    if relationship_type == "exact_identity" and not single_anchor_exact and total_score < 85.0:
        return None
    if relationship_type == "exact_identity" and single_anchor_exact and total_score < 70.0:
        return None
    if relationship_type == "variant_related" and total_score < 55.0:
        return None
    if relationship_type == "series_related" and total_score < 45.0:
        return None

    return ListingMatchRecord(
        user_id=item.user_id,
        listing_id=str(listing["listing_id"]),
        user_item_id=item.id,
        item_type=item.item_type,
        relationship_type=relationship_type,
        match_score=total_score,
        identity_score=identity_score,
        series_score=series_score,
        variant_score=variant_score,
        condition_score=condition_score,
        reasons=reasons,
    )


def _build_coin_match(*, item: ParsedUserItem, listing: sqlite3.Row) -> ListingMatchRecord | None:
    reasons: list[str] = []
    identity_score = 0.0
    series_score = 0.0
    variant_score = 0.0
    condition_score = 0.0

    item_theme = _normalize_key(item.theme_name)
    listing_theme = _normalize_key(listing["theme_name"])
    item_asset = _normalize_key(item.asset_type)
    listing_asset = _normalize_key(listing["asset_type"])
    item_series = _normalize_key(item.series_key)
    listing_series = _normalize_key(listing["series_key"])
    item_year = item.year_value
    listing_year = _int_or_none(listing["year_value"])
    listing_variant_tokens = _json_list(listing["variant_tokens_json"])
    listing_quantity_tokens = _json_list(listing["quantity_tokens_json"])
    listing_condition_tokens = _listing_condition_tokens(listing)

    if item.precision_mode == "exact":
        if listing_quantity_tokens and not _has_token_overlap(item.quantity_tokens, listing_quantity_tokens):
            return None
        if listing_variant_tokens and not _has_token_overlap(item.variant_tokens, listing_variant_tokens):
            return None
        if item.condition_mode == "require" and _has_hard_condition_conflict(item.condition_tokens, listing_condition_tokens):
            return None
        if item.condition_mode == "require" and not _condition_requirement_satisfied(item.condition_tokens, listing_condition_tokens):
            return None

    if item_theme and listing_theme and item_theme == listing_theme:
        identity_score += 35.0
        reasons.append("theme_exact")
    if item_year is not None and listing_year is not None and item_year == listing_year:
        identity_score += 20.0
        reasons.append("year_exact")
    if item_asset and listing_asset and item_asset == listing_asset:
        identity_score += 20.0
        reasons.append("asset_type_exact")
    if item_series and listing_series and item_series == listing_series:
        series_score += 18.0
        reasons.append("series_key_exact")
    if _normalize_key(item.weight_text) and _normalize_key(item.weight_text) == _normalize_key(listing["weight_text"]):
        variant_score += 10.0
        reasons.append("weight_exact")
    if _normalize_key(item.denomination_text) and _normalize_key(item.denomination_text) == _normalize_key(listing["denomination_text"]):
        variant_score += 8.0
        reasons.append("denomination_exact")
    if _normalize_key(item.finish_type) and _normalize_key(item.finish_type) == _normalize_key(listing["finish_type"]):
        variant_score += 7.0
        reasons.append("finish_exact")

    condition_overlap = _overlap_count(item.condition_tokens, listing_condition_tokens)
    if condition_overlap:
        condition_score += min(condition_overlap * 4.0, 8.0)
        reasons.append("condition_overlap")
    if item.condition_tokens and _condition_requirement_satisfied(item.condition_tokens, listing_condition_tokens):
        condition_score += 6.0
        reasons.append("condition_compatible")
    elif item.condition_tokens and item.condition_mode == "prefer" and _has_hard_condition_conflict(item.condition_tokens, listing_condition_tokens):
        condition_score -= 6.0
        reasons.append("condition_mismatch")

    reason_set = set(reasons)
    relationship_type: str | None = None
    if {"theme_exact", "year_exact", "asset_type_exact"}.issubset(reason_set):
        relationship_type = "exact_identity"
    elif {"theme_exact", "year_exact"}.issubset(reason_set):
        relationship_type = "variant_related"
    elif {"theme_exact", "asset_type_exact"}.issubset(reason_set) or "series_key_exact" in reason_set:
        relationship_type = "series_related"

    total_score = identity_score + series_score + variant_score + condition_score
    if relationship_type is None:
        return None
    if not _relationship_allowed(item, relationship_type):
        return None
    if relationship_type == "exact_identity" and total_score < 75.0:
        return None
    if relationship_type == "variant_related" and total_score < 55.0:
        return None
    if relationship_type == "series_related" and total_score < 45.0:
        return None

    return ListingMatchRecord(
        user_id=item.user_id,
        listing_id=str(listing["listing_id"]),
        user_item_id=item.id,
        item_type=item.item_type,
        relationship_type=relationship_type,
        match_score=total_score,
        identity_score=identity_score,
        series_score=series_score,
        variant_score=variant_score,
        condition_score=condition_score,
        reasons=reasons,
    )


def _parse_user_item(row: sqlite3.Row) -> ParsedUserItem:
    item_name = _clean_text(row["item_name"]) or ""
    category = _clean_text(row["category"])
    series_raw = _clean_text(row["series"])
    grade_condition = _clean_text(row["grade_condition"])
    year_value = _int_or_none(row["year"])
    subject_label = _clean_text(row["subject_label"]) or item_name
    precision_mode = _clean_text(row["precision_mode"])
    explicit_condition_mode = _clean_text(row["condition_mode"]) if "condition_mode" in row.keys() else None
    allow_series_matches = _bool_or_default(row["allow_series_matches"], default=False)
    allow_variant_matches = _bool_or_default(row["allow_variant_matches"], default=True)
    explicit_parse_family = _clean_text(row["parse_family"]) if "parse_family" in row.keys() else None
    parse_family = explicit_parse_family if explicit_parse_family in SUPPORTED_PARSE_FAMILIES else _classify_parse_family(item_name, category)

    if parse_family == "stamp_like":
        parsed = _parse_stamp_title(raw_title=item_name, character_condition=grade_condition, description_character=None)
        series_issue_code = None
        if series_raw:
            series_parsed = _parse_stamp_title(raw_title=series_raw, character_condition=None, description_character=None)
            series_issue_code = _clean_text(series_parsed["issue_code_norm"])
        issue_code_norm = _clean_text(parsed["issue_code_norm"]) or series_issue_code
        issue_name = _clean_text(parsed["issue_name"])
        series_key = issue_code_norm or issue_name or series_raw
        theme_name = issue_name
    elif parse_family == "coin_like":
        parsed = _parse_coin_title(raw_title=item_name, character_condition=grade_condition, description_character=None)
        issue_code_norm = None
        issue_name = None
        theme_name = _clean_text(parsed["theme_name"]) or _non_numeric_text(series_raw)
        asset_type = _clean_text(parsed["asset_type"])
        if asset_type is None and category and any(marker in category.lower() for marker in ("coin", "币", "钞")):
            asset_type = "币类"
        series_key = "|".join(part for part in [theme_name, asset_type or _clean_text(parsed["asset_type"])] if part) or theme_name
        parsed = dict(parsed)
        parsed["theme_name"] = theme_name
        parsed["asset_type"] = asset_type or _clean_text(parsed["asset_type"])
        if parsed["year_value"] is None and year_value is not None:
            parsed["year_value"] = year_value
    else:
        parsed = {
            "asset_type": None,
            "finish_type": None,
            "weight_text": None,
            "denomination_text": None,
            "identity_core": None,
            "variant_tokens": [],
            "quantity_tokens": [],
            "condition_tokens": [grade_condition] if grade_condition else [],
        }
        issue_code_norm = None
        issue_name = None
        theme_name = None
        series_key = None

    return ParsedUserItem(
        id=str(row["id"]),
        user_id=str(row["user_id"]),
        item_type=str(row["item_type"]),
        category=category,
        series_raw=series_raw,
        item_name=item_name,
        grade_condition=grade_condition,
        year_value=_int_or_none(parsed.get("year_value")) if parse_family == "coin_like" else year_value,
        parse_family=parse_family,
        issue_code_norm=issue_code_norm,
        issue_name=issue_name,
        theme_name=theme_name,
        asset_type=_clean_text(parsed.get("asset_type")),
        finish_type=_clean_text(parsed.get("finish_type")),
        weight_text=_clean_text(parsed.get("weight_text")),
        denomination_text=_clean_text(parsed.get("denomination_text")),
        identity_core=_clean_text(parsed.get("identity_core")),
        series_key=series_key,
        variant_tokens=_token_values(parsed, "variant_tokens"),
        quantity_tokens=_token_values(parsed, "quantity_tokens"),
        condition_tokens=_condition_tokens(_token_values(parsed, "condition_tokens"), grade_condition),
        condition_mode=_resolve_condition_mode(explicit_condition_mode, _token_values(parsed, "condition_tokens"), grade_condition, precision_mode),
        issue_part_token=_extract_issue_part_token(item_name),
        subject_label=subject_label,
        precision_mode=precision_mode or _default_precision_mode(item_name, issue_code_norm, _token_values(parsed, "variant_tokens"), _token_values(parsed, "quantity_tokens")),
        allow_series_matches=allow_series_matches,
        allow_variant_matches=allow_variant_matches,
    )


def _load_users(conn: sqlite3.Connection, *, user_id: str | None) -> list[sqlite3.Row]:
    if user_id:
        row = conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            raise ValueError(f"user not found: {user_id}")
        return [row]
    return conn.execute("SELECT id FROM users ORDER BY id").fetchall()


def _load_match_subjects(conn: sqlite3.Connection, user_id: str) -> list[sqlite3.Row]:
    rows = conn.execute(
        """
        SELECT
          t.id AS id,
          i.user_id AS user_id,
          CASE WHEN i.interest_kind = 'watch_sell' THEN 'holding' ELSE 'watch' END AS item_type,
          t.parse_family AS parse_family,
          NULL AS category,
          t.series_key AS series,
          t.raw_input AS item_name,
          t.year_value AS year,
          (
            SELECT GROUP_CONCAT(value, ' ')
            FROM json_each(t.condition_tokens_json)
          ) AS grade_condition,
          t.target_label AS subject_label,
          COALESCE(t.strictness_override, i.precision_mode) AS precision_mode,
          t.condition_mode AS condition_mode,
          i.allow_series_matches AS allow_series_matches,
          i.allow_variant_matches AS allow_variant_matches
        FROM user_interest_targets_v2 t
        JOIN user_interests_v2 i ON i.id = t.interest_id
        WHERE i.user_id = ? AND i.active_status = 'active' AND t.is_active = 1
        ORDER BY i.interest_priority DESC, i.updated_at DESC, t.updated_at DESC, t.id
        """,
        (user_id,),
    ).fetchall()
    if rows:
        return rows
    return conn.execute(
        """
        SELECT
          id,
          user_id,
          item_type,
          NULL AS parse_family,
          category,
          series,
          item_name,
          year,
          grade_condition,
          item_name AS subject_label,
          NULL AS precision_mode,
          NULL AS condition_mode,
          0 AS allow_series_matches,
          1 AS allow_variant_matches
        FROM user_items
        WHERE user_id = ? AND is_active = 1
        ORDER BY item_type, updated_at DESC, id
        """,
        (user_id,),
    ).fetchall()


def _load_listing_candidates(conn: sqlite3.Connection, *, only_active: bool) -> list[sqlite3.Row]:
    where_sql = "WHERE n.status_norm IN ('preview', 'live')" if only_active else ""
    return conn.execute(
        f"""
        SELECT
          p.listing_id,
          p.parse_family,
          p.series_key,
          p.issue_code_norm,
          p.issue_name,
          p.theme_name,
          p.asset_type,
          p.finish_type,
          p.weight_text,
          p.denomination_text,
          p.variant_tokens_json,
          p.quantity_tokens_json,
          p.condition_tokens_json,
          p.character_condition,
          p.identity_core,
          p.year_value,
          p.raw_title,
          p.parse_confidence
        FROM listing_parse_v2 p
        JOIN market_listings_norm_v2 n ON n.id = p.listing_id
        {where_sql}
        ORDER BY p.listing_id
        """
    ).fetchall()


def _group_listing_candidates(rows: list[sqlite3.Row]) -> dict[str, dict[str, list[sqlite3.Row]]]:
    groups = {"stamp_code": {}, "stamp_name": {}, "stamp_series": {}, "coin_identity": {}, "coin_series": {}, "coin_theme": {}}
    for row in rows:
        family = _clean_text(row["parse_family"])
        if family == "stamp_like":
            _append_group(groups["stamp_code"], _clean_text(row["issue_code_norm"]), row)
            _append_group(groups["stamp_name"], _normalize_key(row["issue_name"]), row)
            _append_group(groups["stamp_series"], _normalize_key(row["series_key"]), row)
        elif family == "coin_like":
            _append_group(groups["coin_identity"], _normalize_key(row["identity_core"]), row)
            _append_group(groups["coin_series"], _normalize_key(row["series_key"]), row)
            _append_group(groups["coin_theme"], _normalize_key(row["theme_name"]), row)
    return groups


def _candidate_rows(groups: dict[str, dict[str, list[sqlite3.Row]]], item: ParsedUserItem) -> list[sqlite3.Row]:
    candidates: dict[str, sqlite3.Row] = {}
    if item.parse_family == "stamp_like":
        keys = [("stamp_code", _clean_text(item.issue_code_norm)), ("stamp_name", _normalize_key(item.issue_name)), ("stamp_series", _normalize_key(item.series_key))]
    elif item.parse_family == "coin_like":
        keys = [("coin_identity", _normalize_key(item.identity_core)), ("coin_series", _normalize_key(item.series_key)), ("coin_theme", _normalize_key(item.theme_name))]
    else:
        return []

    for group_name, key in keys:
        if not key:
            continue
        for row in groups[group_name].get(key, []):
            candidates[str(row["listing_id"])] = row
    return list(candidates.values())


def _is_trusted_match_pair(*, item: ParsedUserItem, listing: sqlite3.Row) -> bool:
    if item.parse_family == "stamp_like":
        return _is_trusted_stamp_item(item) and _is_trusted_stamp_listing(listing)
    if item.parse_family == "coin_like":
        return _is_trusted_coin_item(item) and _is_trusted_coin_listing(listing)
    return False


def _is_trusted_stamp_item(item: ParsedUserItem) -> bool:
    if _is_composite_stamp_title(item.item_name):
        return False
    return bool(_clean_text(item.issue_code_norm) or _clean_text(item.issue_name))


def _is_trusted_stamp_listing(listing: sqlite3.Row) -> bool:
    if _float_or_default(listing["parse_confidence"], 0.0) < TRUSTED_STAMP_MIN_CONFIDENCE:
        return False
    if _is_composite_stamp_title(listing["raw_title"]):
        return False
    return bool(_clean_text(listing["issue_code_norm"]) or _clean_text(listing["issue_name"]))


def _is_trusted_coin_item(item: ParsedUserItem) -> bool:
    return bool(item.year_value is not None and _clean_text(item.theme_name) and _clean_text(item.asset_type))


def _is_trusted_coin_listing(listing: sqlite3.Row) -> bool:
    if _float_or_default(listing["parse_confidence"], 0.0) < TRUSTED_COIN_MIN_CONFIDENCE:
        return False
    return bool(_int_or_none(listing["year_value"]) is not None and _clean_text(listing["theme_name"]) and _clean_text(listing["asset_type"]))


def _is_composite_stamp_title(value: Any) -> bool:
    text = _clean_text(value)
    if not text:
        return False
    normalized = text.replace("（", "(").replace("）", ")")
    if len(STAMP_CODE_SCAN_RE.findall(normalized)) >= 2:
        return True
    return any(marker in normalized for marker in ("、", "，", ",", "；", ";", "各一", "混", "邮折"))


def _listing_condition_tokens(listing: sqlite3.Row) -> list[str]:
    tokens = _json_list(listing["condition_tokens_json"])
    character_condition = _clean_text(listing["character_condition"])
    if character_condition and character_condition not in tokens:
        tokens.append(character_condition)
    return tokens


def _upsert_match(conn: sqlite3.Connection, *, match: ListingMatchRecord, now: str) -> str:
    reasons_json = json.dumps(match.reasons, ensure_ascii=False, separators=(",", ":"))
    existing = conn.execute(
        """
        SELECT id, relationship_type, match_score, identity_score, series_score, variant_score, condition_score, match_reasons_json, status
        FROM listing_matches_v2
        WHERE user_id = ? AND listing_id = ? AND user_item_id = ?
        """,
        (match.user_id, match.listing_id, match.user_item_id),
    ).fetchone()
    if existing is None:
        conn.execute(
            """
            INSERT INTO listing_matches_v2 (
              id, user_id, listing_id, user_item_id, item_type, relationship_type,
              match_score, identity_score, series_score, variant_score, condition_score,
              matcher_version, match_reasons_json, status, matched_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
            """,
            (
                str(uuid.uuid4()),
                match.user_id,
                match.listing_id,
                match.user_item_id,
                match.item_type,
                match.relationship_type,
                match.match_score,
                match.identity_score,
                match.series_score,
                match.variant_score,
                match.condition_score,
                MATCHER_VERSION,
                reasons_json,
                now,
                now,
            ),
        )
        return "inserted"

    changed = (
        str(existing["relationship_type"]) != match.relationship_type
        or float(existing["match_score"]) != float(match.match_score)
        or float(existing["identity_score"]) != float(match.identity_score)
        or float(existing["series_score"]) != float(match.series_score)
        or float(existing["variant_score"]) != float(match.variant_score)
        or float(existing["condition_score"]) != float(match.condition_score)
        or str(existing["match_reasons_json"]) != reasons_json
        or str(existing["status"]) != "active"
    )
    if not changed:
        return "unchanged"

    conn.execute(
        """
        UPDATE listing_matches_v2
        SET item_type = ?, relationship_type = ?, match_score = ?, identity_score = ?, series_score = ?,
            variant_score = ?, condition_score = ?, matcher_version = ?, match_reasons_json = ?,
            status = 'active', matched_at = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            match.item_type,
            match.relationship_type,
            match.match_score,
            match.identity_score,
            match.series_score,
            match.variant_score,
            match.condition_score,
            MATCHER_VERSION,
            reasons_json,
            now,
            now,
            str(existing["id"]),
        ),
    )
    return "updated"


def _deactivate_stale_matches(conn: sqlite3.Connection, *, user_id: str, run_keys: set[tuple[str, str]], now: str) -> int:
    rows = conn.execute(
        "SELECT listing_id, user_item_id FROM listing_matches_v2 WHERE user_id = ? AND status = 'active'",
        (user_id,),
    ).fetchall()
    stale_keys = [(str(row["listing_id"]), str(row["user_item_id"])) for row in rows if (str(row["listing_id"]), str(row["user_item_id"])) not in run_keys]
    if not stale_keys:
        return 0
    conn.executemany(
        """
        UPDATE listing_matches_v2
        SET status = 'inactive', updated_at = ?
        WHERE user_id = ? AND listing_id = ? AND user_item_id = ? AND status = 'active'
        """,
        [(now, user_id, listing_id, user_item_id) for listing_id, user_item_id in stale_keys],
    )
    return len(stale_keys)


def _insert_match_run(conn: sqlite3.Connection, *, run_id: str, user_id: str | None, started_at: str, only_active_listings: bool) -> None:
    conn.execute(
        """
        INSERT INTO listing_match_runs_v2 (id, user_id, matcher_version, only_active_listings, started_at, status)
        VALUES (?, ?, ?, ?, ?, 'running')
        """,
        (run_id, user_id, MATCHER_VERSION, 1 if only_active_listings else 0, started_at),
    )


def _finish_match_run(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    finished_at: str,
    status: str,
    users_processed: int,
    items_scanned: int,
    listings_scanned: int,
    evaluated_pairs: int,
    matched_pairs: int,
    inserted: int,
    updated: int,
    deactivated: int,
    error_message: str | None,
) -> None:
    conn.execute(
        """
        UPDATE listing_match_runs_v2
        SET finished_at = ?, status = ?, users_processed = ?, items_scanned = ?, listings_scanned = ?,
            evaluated_pairs = ?, matched_pairs = ?, inserted = ?, updated = ?, deactivated = ?, error_message = ?
        WHERE id = ?
        """,
        (
            finished_at,
            status,
            users_processed,
            items_scanned,
            listings_scanned,
            evaluated_pairs,
            matched_pairs,
            inserted,
            updated,
            deactivated,
            error_message,
            run_id,
        ),
    )


def _append_group(group: dict[str, list[sqlite3.Row]], key: str | None, row: sqlite3.Row) -> None:
    if key:
        group.setdefault(key, []).append(row)


def _json_list(value: Any) -> list[str]:
    if value is None:
        return []
    try:
        data = json.loads(str(value))
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [_clean_text(item) for item in data if _clean_text(item)]


def _overlap_count(left: list[str], right: list[str]) -> int:
    right_set = {_normalize_key(item) for item in right if _normalize_key(item)}
    return sum(1 for item in left if _normalize_key(item) and _normalize_key(item) in right_set)


def _has_token_overlap(left: list[str], right: list[str]) -> bool:
    return _overlap_count(left, right) > 0


def _has_token_conflict(left: list[str], right: list[str]) -> bool:
    left_set = {_normalize_key(item) for item in left if _normalize_key(item)}
    right_set = {_normalize_key(item) for item in right if _normalize_key(item)}
    return bool(left_set and right_set and left_set != right_set)


def _has_hard_condition_conflict(item_tokens: list[str], listing_tokens: list[str]) -> bool:
    item_profile = _condition_profile(item_tokens)
    listing_profile = _condition_profile(listing_tokens)
    item_state = item_profile["state"]
    listing_state = listing_profile["state"]
    if item_state and listing_state and item_state != listing_state:
        return True
    if item_profile["certified_required"] and not listing_profile["certified"]:
        return True
    if item_profile["min_rank"] is not None and listing_profile["max_rank"] is not None and listing_profile["max_rank"] < item_profile["min_rank"]:
        return True
    return False


def _condition_requirement_satisfied(item_tokens: list[str], listing_tokens: list[str]) -> bool:
    if not item_tokens:
        return True
    item_profile = _condition_profile(item_tokens)
    listing_profile = _condition_profile(listing_tokens)

    if item_profile["state"] and listing_profile["state"] and item_profile["state"] != listing_profile["state"]:
        return False
    if item_profile["certified_required"] and not listing_profile["certified"]:
        return False
    if item_profile["min_rank"] is not None:
        if listing_profile["max_rank"] is None:
            return False
        if listing_profile["max_rank"] < item_profile["min_rank"]:
            return False
    return True


def _condition_profile(tokens: list[str]) -> dict[str, Any]:
    profile = {
        "state": None,
        "certified": False,
        "certified_required": False,
        "min_rank": None,
        "max_rank": None,
    }
    for token in tokens:
        normalized = _clean_text(token)
        if not normalized:
            continue
        if any(marker in normalized for marker in ("新全", "新", "未使用")):
            profile["state"] = profile["state"] or "mint"
        elif any(marker in normalized for marker in ("旧全", "旧")):
            profile["state"] = profile["state"] or "used"
        elif any(marker in normalized for marker in ("盖全", "盖")):
            profile["state"] = profile["state"] or "cancelled"
        elif "实寄" in normalized:
            profile["state"] = profile["state"] or "mailed"

        if "评级" in normalized:
            profile["certified"] = True
            profile["certified_required"] = True

        rank = _condition_rank(normalized)
        if rank is not None:
            profile["min_rank"] = rank if profile["min_rank"] is None else max(profile["min_rank"], rank)
            profile["max_rank"] = rank if profile["max_rank"] is None else max(profile["max_rank"], rank)
    return profile


def _condition_rank(token: str) -> int | None:
    for label, rank in CONDITION_RANKS.items():
        if label in token:
            return rank
    return None


def _relationship_allowed(item: ParsedUserItem, relationship_type: str) -> bool:
    if relationship_type == "exact_identity":
        return True
    if relationship_type == "variant_related":
        return item.allow_variant_matches
    if relationship_type == "series_related":
        return item.allow_series_matches
    return False


def _condition_tokens(values: list[str], grade_condition: str | None) -> list[str]:
    tokens = [_clean_text(v) for v in values if _clean_text(v)]
    if grade_condition and grade_condition not in tokens:
        tokens.append(grade_condition)
    return tokens


def _resolve_condition_mode(
    explicit_mode: str | None,
    parsed_condition_tokens: list[str],
    grade_condition: str | None,
    precision_mode: str | None,
) -> str:
    if explicit_mode in {"ignore", "prefer", "require"}:
        return explicit_mode
    has_condition = bool(parsed_condition_tokens or _clean_text(grade_condition))
    if not has_condition:
        return "ignore"
    if _clean_text(precision_mode) == "exact":
        return "require"
    return "prefer"


def _token_values(parsed: dict[str, Any], field_name: str) -> list[str]:
    raw_values = parsed.get(field_name)
    if isinstance(raw_values, list):
        return [_clean_text(v) for v in raw_values if _clean_text(v)]
    json_field = parsed.get(f"{field_name}_json")
    if json_field is None:
        return []
    try:
        data = json.loads(str(json_field))
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [_clean_text(v) for v in data if _clean_text(v)]


def _normalize_key(value: Any) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    return "".join(ch for ch in text.lower() if ch.isalnum())


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _bool_or_default(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y"}:
        return True
    if text in {"0", "false", "no", "n"}:
        return False
    return default


def _int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_default(value: Any, default: float) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _non_numeric_text(value: str | None) -> str | None:
    text = _clean_text(value)
    if not text or text.isdigit():
        return None
    return text


def _default_precision_mode(
    item_name: str,
    issue_code_norm: str | None,
    variant_tokens: list[str],
    quantity_tokens: list[str],
) -> str:
    if _extract_issue_part_token(item_name) or variant_tokens or quantity_tokens:
        return "exact"
    if issue_code_norm:
        return "balanced"
    return "broad"


def _extract_issue_part_token(value: Any) -> str | None:
    text = _clean_text(value)
    if not text:
        return None
    normalized = text.replace("（", "(").replace("）", ")")
    start = normalized.find("(")
    end = normalized.find(")", start + 1) if start >= 0 else -1
    if start < 0 or end < 0:
        return None
    token = normalized[start + 1 : end].replace(" ", "")
    if "-" not in token:
        return None
    left, _, right = token.partition("-")
    if left.isdigit() and right.isdigit():
        return f"{left}-{right}"
    return None
