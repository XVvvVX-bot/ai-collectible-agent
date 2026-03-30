from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

from ai_agent_v2.parsing.listing_parser import _classify_parse_family, _parse_coin_title, _parse_stamp_title


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "+00:00")


def resolve_intent_confidence(interest_kind: str) -> float:
    return {
        "watch_buy": 0.9,
        "watch_sell": 0.9,
        "collecting": 0.82,
        "discovery": 0.7,
        "portfolio_monitor": 0.78,
    }.get(interest_kind, 0.75)


def resolve_match_flags(
    *,
    scope_kind: str,
    precision_mode: str,
    defaults: dict[str, object],
) -> tuple[bool, bool, bool]:
    default_related = bool(int(defaults.get("default_allow_related_matches") or 0))
    default_series = bool(int(defaults.get("default_allow_series_matches") or 0))
    default_variant = bool(int(defaults.get("default_allow_variant_matches") or 0))
    if precision_mode == "exact":
        return False, False, False
    if precision_mode == "broad":
        return True, True, True

    allow_variant = default_variant or scope_kind in {"issue_family", "series", "theme", "category", "keyword"}
    allow_series = default_series or scope_kind in {"series", "theme", "category", "keyword"}
    allow_related = default_related or scope_kind in {"theme", "category", "keyword"}
    return allow_related, allow_series, allow_variant


def resolve_signal_policy_defaults(
    *,
    interest_kind: str,
    delivery_mode: str,
    cooldown_hours: int,
    min_match_score: object,
    max_signals_per_day: int,
    allow_series_matches: bool,
    allow_variant_matches: bool,
) -> dict[str, object]:
    safe_min_match_score = float(min_match_score) if min_match_score is not None else 70.0
    if interest_kind == "watch_sell":
        return {
            "notify_on_preview": 0,
            "notify_on_live": 0,
            "notify_on_ended": 1,
            "notify_on_exact_match": 0,
            "notify_on_variant_match": 0,
            "notify_on_series_match": 0,
            "notify_on_price_opportunity": 0,
            "notify_on_sell_opportunity": 1,
            "min_match_score": safe_min_match_score,
            "cooldown_hours": cooldown_hours,
            "delivery_mode": delivery_mode,
            "max_signals_per_day": max_signals_per_day,
        }
    return {
        "notify_on_preview": 1,
        "notify_on_live": 1,
        "notify_on_ended": 1 if interest_kind == "discovery" else 0,
        "notify_on_exact_match": 1,
        "notify_on_variant_match": int(allow_variant_matches),
        "notify_on_series_match": int(allow_series_matches),
        "notify_on_price_opportunity": 1,
        "notify_on_sell_opportunity": 1 if interest_kind == "portfolio_monitor" else 0,
        "min_match_score": safe_min_match_score,
        "cooldown_hours": cooldown_hours,
        "delivery_mode": delivery_mode,
        "max_signals_per_day": max_signals_per_day,
    }


def map_scope_kind_to_target_kind(scope_kind: str) -> str:
    return {
        "exact_item": "listing_identity",
        "issue_part": "issue_part",
        "issue_family": "issue_family",
        "series": "series_key",
        "theme": "theme",
        "category": "category",
        "keyword": "keyword",
    }.get(scope_kind, "listing_identity")


def build_manual_interest_target(
    *,
    raw_input: str,
    scope_kind: str,
    precision_mode: str,
    interest_priority: str,
    condition_mode: str,
    budget_max: float | None,
) -> dict[str, object]:
    parse_family = _classify_parse_family(raw_input, None)
    parsed: dict[str, object]
    if parse_family == "stamp_like":
        parsed = _parse_stamp_title(raw_title=raw_input, character_condition=None, description_character=None)
    elif parse_family == "coin_like":
        parsed = _parse_coin_title(raw_title=raw_input, character_condition=None, description_character=None)
    else:
        parsed = {
            "title_normalized": raw_input,
            "issue_code_norm": None,
            "series_key": raw_input,
            "theme_name": raw_input,
            "asset_type": None,
            "variant_tokens_json": "[]",
            "quantity_tokens_json": "[]",
            "condition_tokens_json": "[]",
            "year_value": None,
            "issue_name": raw_input,
        }

    normalized_name = parsed.get("issue_name") or parsed.get("title_normalized") or parsed.get("theme_name") or raw_input
    return {
        "target_label": raw_input,
        "target_kind": map_scope_kind_to_target_kind(scope_kind),
        "parse_family": parse_family,
        "normalized_name": normalized_name,
        "issue_code_norm": parsed.get("issue_code_norm"),
        "issue_part_token": None,
        "series_key": parsed.get("series_key"),
        "theme_name": parsed.get("theme_name"),
        "asset_type": parsed.get("asset_type"),
        "variant_tokens_json": parsed.get("variant_tokens_json") or "[]",
        "quantity_tokens_json": parsed.get("quantity_tokens_json") or "[]",
        "condition_tokens_json": parsed.get("condition_tokens_json") or "[]",
        "year_value": parsed.get("year_value"),
        "strictness_override": precision_mode,
        "priority_override": interest_priority,
        "condition_mode": condition_mode,
        "budget_max": budget_max,
    }


def create_interest_record(
    *,
    db_path: Path,
    user_id: str,
    interest_name: str,
    raw_input: str,
    interest_kind: str,
    scope_kind: str,
    precision_mode: str,
    interest_priority: str,
    interest_notes: str,
    budget_max: float | None,
    condition_mode: str,
    delivery_mode: str,
    cooldown_hours: int,
    min_match_score: float | None,
    max_signals_per_day: int,
) -> dict[str, object]:
    valid_interest_kinds = {"collecting", "watch_buy", "watch_sell", "discovery", "portfolio_monitor"}
    valid_scope_kinds = {"exact_item", "issue_part", "issue_family", "series", "theme", "category", "keyword"}
    valid_precision_modes = {"exact", "balanced", "broad"}
    valid_priorities = {"high", "normal", "low"}
    valid_condition_modes = {"ignore", "prefer", "require"}
    valid_delivery_modes = {"immediate", "daily_digest", "silent_log"}

    interest_name = interest_name.strip()
    raw_input = raw_input.strip()
    interest_notes = interest_notes.strip()
    if not interest_name:
        raise ValueError("interest_name is required")
    if not raw_input:
        raise ValueError("raw_input is required")
    if interest_kind not in valid_interest_kinds:
        raise ValueError("invalid interest_kind")
    if scope_kind not in valid_scope_kinds:
        raise ValueError("invalid scope_kind")
    if precision_mode not in valid_precision_modes:
        raise ValueError("invalid precision_mode")
    if interest_priority not in valid_priorities:
        raise ValueError("invalid interest_priority")
    if condition_mode not in valid_condition_modes:
        raise ValueError("invalid condition_mode")
    if delivery_mode not in valid_delivery_modes:
        raise ValueError("invalid delivery_mode")

    now_iso = utc_now_iso()
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        user_row = conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
        if user_row is None:
            raise ValueError(f"user not found: {user_id}")

        defaults_row = conn.execute(
            """
            SELECT default_min_match_score, default_allow_related_matches, default_allow_series_matches,
                   default_allow_variant_matches
            FROM user_profile_defaults_v2
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()
        defaults = {key: defaults_row[key] for key in defaults_row.keys()} if defaults_row is not None else {}

        parsed_target = build_manual_interest_target(
            raw_input=raw_input,
            scope_kind=scope_kind,
            precision_mode=precision_mode,
            interest_priority=interest_priority,
            condition_mode=condition_mode,
            budget_max=budget_max,
        )
        allow_related_matches, allow_series_matches, allow_variant_matches = resolve_match_flags(
            scope_kind=scope_kind,
            precision_mode=precision_mode,
            defaults=defaults,
        )
        policy_values = resolve_signal_policy_defaults(
            interest_kind=interest_kind,
            delivery_mode=delivery_mode,
            cooldown_hours=cooldown_hours,
            min_match_score=min_match_score if min_match_score is not None else defaults.get("default_min_match_score"),
            max_signals_per_day=max_signals_per_day,
            allow_series_matches=allow_series_matches,
            allow_variant_matches=allow_variant_matches,
        )

        interest_id = str(uuid.uuid4())
        target_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO user_interests_v2 (
              id, user_id, legacy_user_item_id, interest_name, interest_kind, scope_kind, precision_mode,
              interest_priority, intent_confidence, allow_related_matches, allow_series_matches,
              allow_variant_matches, active_status, notes, created_at, updated_at
            ) VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)
            """,
            (
                interest_id,
                user_id,
                interest_name,
                interest_kind,
                scope_kind,
                precision_mode,
                interest_priority,
                resolve_intent_confidence(interest_kind),
                int(allow_related_matches),
                int(allow_series_matches),
                int(allow_variant_matches),
                interest_notes,
                now_iso,
                now_iso,
            ),
        )
        conn.execute(
            """
            INSERT INTO user_interest_targets_v2 (
              id, interest_id, target_label, target_kind, parse_family, raw_input, normalized_name,
              issue_code_norm, issue_part_token, series_key, theme_name, asset_type, variant_tokens_json,
              quantity_tokens_json, condition_tokens_json, condition_mode, year_value, budget_min,
              budget_max, strictness_override, priority_override, is_active, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (
                target_id,
                interest_id,
                str(parsed_target["target_label"]),
                str(parsed_target["target_kind"]),
                str(parsed_target["parse_family"]),
                raw_input,
                parsed_target["normalized_name"],
                parsed_target["issue_code_norm"],
                parsed_target["issue_part_token"],
                parsed_target["series_key"],
                parsed_target["theme_name"],
                parsed_target["asset_type"],
                str(parsed_target["variant_tokens_json"]),
                str(parsed_target["quantity_tokens_json"]),
                str(parsed_target["condition_tokens_json"]),
                condition_mode,
                parsed_target["year_value"],
                None,
                budget_max,
                precision_mode,
                interest_priority,
                now_iso,
                now_iso,
            ),
        )
        conn.execute(
            """
            INSERT INTO user_interest_signal_policies_v2 (
              id, interest_id, notify_on_preview, notify_on_live, notify_on_ended, notify_on_exact_match,
              notify_on_variant_match, notify_on_series_match, notify_on_price_opportunity, notify_on_sell_opportunity,
              min_match_score, cooldown_hours, delivery_mode, max_signals_per_day, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                interest_id,
                policy_values["notify_on_preview"],
                policy_values["notify_on_live"],
                policy_values["notify_on_ended"],
                policy_values["notify_on_exact_match"],
                policy_values["notify_on_variant_match"],
                policy_values["notify_on_series_match"],
                policy_values["notify_on_price_opportunity"],
                policy_values["notify_on_sell_opportunity"],
                policy_values["min_match_score"],
                policy_values["cooldown_hours"],
                policy_values["delivery_mode"],
                policy_values["max_signals_per_day"],
                now_iso,
                now_iso,
            ),
        )
        conn.commit()

    return {
        "ok": True,
        "created_at": now_iso,
        "interest_id": interest_id,
        "target_id": target_id,
    }


def delete_interest_record(
    *,
    db_path: Path,
    user_id: str,
    interest_id: str,
) -> dict[str, object]:
    now_iso = utc_now_iso()
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        interest_row = conn.execute(
            """
            SELECT id, interest_name
            FROM user_interests_v2
            WHERE id = ? AND user_id = ?
            """,
            (interest_id, user_id),
        ).fetchone()
        if interest_row is None:
            raise ValueError(f"interest not found: {interest_id}")

        target_ids = [str(row["id"]) for row in conn.execute("SELECT id FROM user_interest_targets_v2 WHERE interest_id = ?", (interest_id,)).fetchall()]
        holding_ids = [str(row["id"]) for row in conn.execute("SELECT id FROM user_holdings_v2 WHERE user_id = ? AND linked_interest_id = ?", (user_id, interest_id)).fetchall()]

        conn.execute(
            """
            UPDATE user_interests_v2
            SET active_status = 'inactive', updated_at = ?
            WHERE id = ? AND user_id = ?
            """,
            (now_iso, interest_id, user_id),
        )
        conn.execute(
            """
            UPDATE user_interest_targets_v2
            SET is_active = 0, updated_at = ?
            WHERE interest_id = ?
            """,
            (now_iso, interest_id),
        )
        conn.execute(
            """
            UPDATE signals_v2
            SET status = 'inactive', last_seen_at = ?
            WHERE user_id = ? AND interest_id = ? AND status = 'active'
            """,
            (now_iso, user_id, interest_id),
        )
        related_item_ids = target_ids + holding_ids
        if related_item_ids:
            placeholders = ",".join("?" for _ in related_item_ids)
            conn.execute(
                f"""
                UPDATE listing_matches_v2
                SET status = 'inactive', updated_at = ?
                WHERE user_id = ? AND status = 'active' AND user_item_id IN ({placeholders})
                """,
                (now_iso, user_id, *related_item_ids),
            )
        conn.commit()

    return {
        "ok": True,
        "deleted_at": now_iso,
        "interest": {
            "id": str(interest_row["id"]),
            "interest_name": str(interest_row["interest_name"] or interest_id),
        },
    }
