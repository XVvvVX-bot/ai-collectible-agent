from __future__ import annotations

import json
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


@dataclass(frozen=True)
class InterestProfileMigrationResult:
    users_processed: int
    defaults_upserted: int
    interests_upserted: int
    targets_upserted: int
    holdings_upserted: int
    policies_upserted: int


def migrate_interest_profile_v2(db_path: str) -> InterestProfileMigrationResult:
    SqliteV2Store(db_path).ensure_schema()
    now = now_utc_iso()

    with sqlite3.connect(Path(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        user_rows = conn.execute("SELECT * FROM users ORDER BY id").fetchall()
        pref_rows = {
            str(row["user_id"]): row
            for row in conn.execute("SELECT * FROM user_preferences").fetchall()
        }
        item_rows = conn.execute(
            """
            SELECT *
            FROM user_items
            WHERE is_active = 1
            ORDER BY user_id, item_type, updated_at DESC, id
            """
        ).fetchall()

        defaults_upserted = 0
        interests_upserted = 0
        targets_upserted = 0
        holdings_upserted = 0
        policies_upserted = 0

        interest_lookup: dict[str, str] = {}

        for user in user_rows:
            pref = pref_rows.get(str(user["id"]))
            _upsert_profile_defaults(conn, user_id=str(user["id"]), pref_row=pref, now=now)
            defaults_upserted += 1

        for row in item_rows:
            parsed = _parse_user_item(row)
            if str(row["item_type"]) == "watch":
                interest_id = _upsert_interest(conn, row=row, parsed=parsed, now=now)
                interest_lookup[str(row["id"])] = interest_id
                interests_upserted += 1
                _upsert_target(conn, interest_id=interest_id, row=row, parsed=parsed, now=now)
                targets_upserted += 1
                _upsert_policy(conn, interest_id=interest_id, row=row, pref_row=pref_rows.get(str(row["user_id"])), parsed=parsed, now=now)
                policies_upserted += 1
            elif str(row["item_type"]) == "holding":
                linked_interest_id = interest_lookup.get(str(row["id"]))
                _upsert_holding(conn, linked_interest_id=linked_interest_id, row=row, parsed=parsed, now=now)
                holdings_upserted += 1

        conn.commit()

    return InterestProfileMigrationResult(
        users_processed=len(user_rows),
        defaults_upserted=defaults_upserted,
        interests_upserted=interests_upserted,
        targets_upserted=targets_upserted,
        holdings_upserted=holdings_upserted,
        policies_upserted=policies_upserted,
    )


def _upsert_profile_defaults(
    conn: sqlite3.Connection,
    *,
    user_id: str,
    pref_row: sqlite3.Row | None,
    now: str,
) -> None:
    allow_series = 1 if pref_row and int(pref_row["high_interest_flag"]) else 0
    conn.execute(
        """
        INSERT INTO user_profile_defaults_v2 (
          user_id,
          default_currency,
          default_precision_mode,
          default_delivery_mode,
          default_min_match_score,
          default_cooldown_hours,
          default_allow_related_matches,
          default_allow_series_matches,
          default_allow_variant_matches,
          notes,
          created_at,
          updated_at
        ) VALUES (?, 'CNY', 'balanced', 'daily_digest', 70, 24, 0, ?, 1, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
          default_allow_series_matches = excluded.default_allow_series_matches,
          notes = excluded.notes,
          updated_at = excluded.updated_at
        """,
        (
            user_id,
            allow_series,
            pref_row["buy_rule_text"] if pref_row else None,
            now,
            now,
        ),
    )


def _upsert_interest(
    conn: sqlite3.Connection,
    *,
    row: sqlite3.Row,
    parsed: dict[str, Any],
    now: str,
) -> str:
    existing = conn.execute(
        "SELECT id FROM user_interests_v2 WHERE legacy_user_item_id = ?",
        (str(row["id"]),),
    ).fetchone()
    interest_id = str(existing["id"]) if existing else str(uuid.uuid4())
    interest_kind = "watch_buy"
    scope_kind = _scope_kind(parsed)
    precision_mode = _precision_mode(parsed)
    allow_related = 1 if precision_mode == "broad" else 0
    allow_series = 1 if precision_mode == "broad" else 0
    allow_variant = 1 if precision_mode in {"exact", "balanced"} else 0
    conn.execute(
        """
        INSERT INTO user_interests_v2 (
          id,
          user_id,
          legacy_user_item_id,
          interest_name,
          interest_kind,
          scope_kind,
          precision_mode,
          interest_priority,
          intent_confidence,
          allow_related_matches,
          allow_series_matches,
          allow_variant_matches,
          active_status,
          notes,
          created_at,
          updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
          interest_name = excluded.interest_name,
          scope_kind = excluded.scope_kind,
          precision_mode = excluded.precision_mode,
          interest_priority = excluded.interest_priority,
          intent_confidence = excluded.intent_confidence,
          allow_related_matches = excluded.allow_related_matches,
          allow_series_matches = excluded.allow_series_matches,
          allow_variant_matches = excluded.allow_variant_matches,
          notes = excluded.notes,
          updated_at = excluded.updated_at
        """,
        (
            interest_id,
            str(row["user_id"]),
            str(row["id"]),
            str(row["item_name"]),
            interest_kind,
            scope_kind,
            precision_mode,
            str(row["priority"] or "normal"),
            _intent_confidence(parsed),
            allow_related,
            allow_series,
            allow_variant,
            row["notes"],
            now,
            now,
        ),
    )
    return interest_id


def _upsert_target(
    conn: sqlite3.Connection,
    *,
    interest_id: str,
    row: sqlite3.Row,
    parsed: dict[str, Any],
    now: str,
) -> None:
    existing = conn.execute(
        "SELECT id FROM user_interest_targets_v2 WHERE interest_id = ?",
        (interest_id,),
    ).fetchone()
    target_id = str(existing["id"]) if existing else str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO user_interest_targets_v2 (
          id,
          interest_id,
          target_label,
          target_kind,
          parse_family,
          raw_input,
          normalized_name,
          issue_code_norm,
          issue_part_token,
          series_key,
          theme_name,
          asset_type,
          variant_tokens_json,
          quantity_tokens_json,
          condition_tokens_json,
          year_value,
          budget_min,
          budget_max,
          strictness_override,
          priority_override,
          is_active,
          created_at,
          updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
          target_label = excluded.target_label,
          target_kind = excluded.target_kind,
          parse_family = excluded.parse_family,
          raw_input = excluded.raw_input,
          normalized_name = excluded.normalized_name,
          issue_code_norm = excluded.issue_code_norm,
          issue_part_token = excluded.issue_part_token,
          series_key = excluded.series_key,
          theme_name = excluded.theme_name,
          asset_type = excluded.asset_type,
          variant_tokens_json = excluded.variant_tokens_json,
          quantity_tokens_json = excluded.quantity_tokens_json,
          condition_tokens_json = excluded.condition_tokens_json,
          year_value = excluded.year_value,
          budget_max = excluded.budget_max,
          strictness_override = excluded.strictness_override,
          priority_override = excluded.priority_override,
          updated_at = excluded.updated_at
        """,
        (
            target_id,
            interest_id,
            str(row["item_name"]),
            _target_kind(parsed),
            parsed["parse_family"],
            str(row["item_name"]),
            parsed["normalized_name"],
            parsed["issue_code_norm"],
            parsed["issue_part_token"],
            parsed["series_key"],
            parsed["theme_name"],
            parsed["asset_type"],
            _json_text(parsed["variant_tokens"]),
            _json_text(parsed["quantity_tokens"]),
            _json_text(parsed["condition_tokens"]),
            parsed["year_value"],
            None,
            row["max_buy_price"],
            _precision_mode(parsed),
            row["priority"],
            now,
            now,
        ),
    )


def _upsert_holding(
    conn: sqlite3.Connection,
    *,
    linked_interest_id: str | None,
    row: sqlite3.Row,
    parsed: dict[str, Any],
    now: str,
) -> None:
    existing = conn.execute(
        "SELECT id FROM user_holdings_v2 WHERE legacy_user_item_id = ?",
        (str(row["id"]),),
    ).fetchone()
    holding_id = str(existing["id"]) if existing else str(uuid.uuid4())
    quantity = float(row["quantity"]) if row["quantity"] is not None else None
    total = float(row["cost_basis_total"]) if row["cost_basis_total"] is not None else None
    unit = (total / quantity) if total is not None and quantity not in (None, 0) else None
    conn.execute(
        """
        INSERT INTO user_holdings_v2 (
          id,
          user_id,
          legacy_user_item_id,
          linked_interest_id,
          raw_input,
          parse_family,
          normalized_name,
          issue_code_norm,
          issue_part_token,
          series_key,
          theme_name,
          asset_type,
          variant_tokens_json,
          quantity_tokens_json,
          condition_tokens_json,
          year_value,
          holding_quantity,
          cost_basis_total,
          cost_basis_unit,
          acquired_at,
          notes,
          is_active,
          created_at,
          updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, 1, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
          linked_interest_id = excluded.linked_interest_id,
          raw_input = excluded.raw_input,
          parse_family = excluded.parse_family,
          normalized_name = excluded.normalized_name,
          issue_code_norm = excluded.issue_code_norm,
          issue_part_token = excluded.issue_part_token,
          series_key = excluded.series_key,
          theme_name = excluded.theme_name,
          asset_type = excluded.asset_type,
          variant_tokens_json = excluded.variant_tokens_json,
          quantity_tokens_json = excluded.quantity_tokens_json,
          condition_tokens_json = excluded.condition_tokens_json,
          year_value = excluded.year_value,
          holding_quantity = excluded.holding_quantity,
          cost_basis_total = excluded.cost_basis_total,
          cost_basis_unit = excluded.cost_basis_unit,
          notes = excluded.notes,
          updated_at = excluded.updated_at
        """,
        (
            holding_id,
            str(row["user_id"]),
            str(row["id"]),
            linked_interest_id,
            str(row["item_name"]),
            parsed["parse_family"],
            parsed["normalized_name"],
            parsed["issue_code_norm"],
            parsed["issue_part_token"],
            parsed["series_key"],
            parsed["theme_name"],
            parsed["asset_type"],
            _json_text(parsed["variant_tokens"]),
            _json_text(parsed["quantity_tokens"]),
            _json_text(parsed["condition_tokens"]),
            parsed["year_value"],
            quantity,
            total,
            unit,
            row["notes"],
            now,
            now,
        ),
    )


def _upsert_policy(
    conn: sqlite3.Connection,
    *,
    interest_id: str,
    row: sqlite3.Row,
    pref_row: sqlite3.Row | None,
    parsed: dict[str, Any],
    now: str,
) -> None:
    existing = conn.execute(
        "SELECT id FROM user_interest_signal_policies_v2 WHERE interest_id = ?",
        (interest_id,),
    ).fetchone()
    policy_id = str(existing["id"]) if existing else str(uuid.uuid4())
    precision = _precision_mode(parsed)
    notify_series = 1 if precision == "broad" else 0
    notify_variant = 1 if precision in {"exact", "balanced"} else 0
    delivery_mode = "immediate" if str(row["priority"] or "normal") == "high" else "daily_digest"
    min_score = 85 if precision == "exact" else 70 if precision == "balanced" else 55
    conn.execute(
        """
        INSERT INTO user_interest_signal_policies_v2 (
          id,
          interest_id,
          notify_on_preview,
          notify_on_live,
          notify_on_ended,
          notify_on_exact_match,
          notify_on_variant_match,
          notify_on_series_match,
          notify_on_price_opportunity,
          notify_on_sell_opportunity,
          min_match_score,
          cooldown_hours,
          delivery_mode,
          max_signals_per_day,
          created_at,
          updated_at
        ) VALUES (?, ?, 1, 1, 0, 1, ?, ?, 1, 0, ?, ?, ?, 20, ?, ?)
        ON CONFLICT(interest_id) DO UPDATE SET
          notify_on_variant_match = excluded.notify_on_variant_match,
          notify_on_series_match = excluded.notify_on_series_match,
          min_match_score = excluded.min_match_score,
          cooldown_hours = excluded.cooldown_hours,
          delivery_mode = excluded.delivery_mode,
          updated_at = excluded.updated_at
        """,
        (
            policy_id,
            interest_id,
            notify_variant,
            notify_series,
            min_score,
            _cooldown_hours(pref_row),
            delivery_mode,
            now,
            now,
        ),
    )


def _parse_user_item(row: sqlite3.Row) -> dict[str, Any]:
    item_name = _text(row["item_name"]) or ""
    category = _text(row["category"])
    grade_condition = _text(row["grade_condition"])
    parse_family = _classify_parse_family(item_name, category)

    if parse_family == "stamp_like":
        parsed = _parse_stamp_title(raw_title=item_name, character_condition=grade_condition, description_character=None)
        normalized_name = _text(parsed["issue_name"]) or _text(item_name)
        series_key = _text(parsed["series_key"]) or _text(parsed["issue_code_norm"]) or normalized_name
        theme_name = _text(parsed["theme_name"])
        issue_code_norm = _text(parsed["issue_code_norm"])
    elif parse_family == "coin_like":
        parsed = _parse_coin_title(raw_title=item_name, character_condition=grade_condition, description_character=None)
        normalized_name = _text(parsed["theme_name"]) or _text(item_name)
        series_key = _text(parsed["series_key"]) or normalized_name
        theme_name = _text(parsed["theme_name"])
        issue_code_norm = None
    else:
        parsed = {
            "variant_tokens_json": "[]",
            "quantity_tokens_json": "[]",
            "condition_tokens_json": "[]",
            "year_value": None,
            "asset_type": None,
        }
        normalized_name = _text(item_name)
        series_key = _text(row["series"]) or normalized_name
        theme_name = None
        issue_code_norm = None

    return {
        "parse_family": parse_family,
        "normalized_name": normalized_name,
        "issue_code_norm": issue_code_norm,
        "issue_part_token": _extract_issue_part_token(item_name),
        "series_key": series_key,
        "theme_name": theme_name,
        "asset_type": _text(parsed.get("asset_type")),
        "variant_tokens": _token_values(parsed.get("variant_tokens_json")),
        "quantity_tokens": _token_values(parsed.get("quantity_tokens_json")),
        "condition_tokens": _condition_tokens(_token_values(parsed.get("condition_tokens_json")), grade_condition),
        "year_value": _int_or_none(parsed.get("year_value")) or _int_or_none(row["year"]),
    }


def _scope_kind(parsed: dict[str, Any]) -> str:
    if parsed["issue_part_token"]:
        return "issue_part"
    if parsed["issue_code_norm"] and (parsed["variant_tokens"] or parsed["quantity_tokens"]):
        return "exact_item"
    if parsed["issue_code_norm"]:
        return "issue_family"
    if parsed["series_key"]:
        return "series"
    if parsed["theme_name"]:
        return "theme"
    return "keyword"


def _target_kind(parsed: dict[str, Any]) -> str:
    if parsed["issue_part_token"]:
        return "issue_part"
    if parsed["issue_code_norm"] and (parsed["variant_tokens"] or parsed["quantity_tokens"]):
        return "listing_identity"
    if parsed["issue_code_norm"]:
        return "issue_family"
    if parsed["series_key"]:
        return "series_key"
    if parsed["theme_name"]:
        return "theme"
    return "keyword"


def _precision_mode(parsed: dict[str, Any]) -> str:
    if parsed["issue_part_token"] or parsed["variant_tokens"] or parsed["quantity_tokens"]:
        return "exact"
    if parsed["issue_code_norm"] or parsed["theme_name"] or parsed["series_key"]:
        return "balanced"
    return "broad"


def _intent_confidence(parsed: dict[str, Any]) -> float:
    if parsed["issue_part_token"]:
        return 0.95
    if parsed["issue_code_norm"] and (parsed["variant_tokens"] or parsed["quantity_tokens"]):
        return 0.9
    if parsed["issue_code_norm"] or parsed["theme_name"]:
        return 0.75
    return 0.55


def _cooldown_hours(pref_row: sqlite3.Row | None) -> int:
    if pref_row is None:
        return 24
    rules_json = _text(pref_row["rules_json"])
    if not rules_json:
        return 24
    try:
        rules = json.loads(rules_json)
    except json.JSONDecodeError:
        return 24
    value = rules.get("cooldown_hours")
    return _int_or_none(value) or 24


def _token_values(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [str(item).strip() for item in data if str(item).strip()]


def _condition_tokens(values: list[str], grade_condition: str | None) -> list[str]:
    tokens = [value for value in values if value]
    if grade_condition and grade_condition not in tokens:
        tokens.append(grade_condition)
    return tokens


def _extract_issue_part_token(value: Any) -> str | None:
    text = _text(value)
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


def _json_text(values: list[str]) -> str:
    return json.dumps(values, ensure_ascii=False, separators=(",", ":"))


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
