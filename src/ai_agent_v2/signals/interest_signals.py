from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ai_agent_v2.reporting.interest_review import _load_recent_ended_comps
from ai_agent_v2.storage.sqlite_store import SqliteV2Store


@dataclass(frozen=True)
class SignalCandidate:
    user_id: str
    interest_id: str
    target_id: str | None
    listing_id: str | None
    signal_type: str
    urgency: str
    reason_code: str
    signal_title: str
    signal_summary: str
    group_key: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class InterestSignalRunResult:
    run_id: str
    interests_processed: int
    candidates: int
    inserted: int
    updated: int
    deactivated: int
    skipped_cooldown: int
    inserted_by_type: dict[str, int]


def run_interest_signal_generation(
    db_path: str,
    *,
    user_id: str | None = None,
    lookback_hours: int = 24,
    now_utc: datetime | None = None,
) -> InterestSignalRunResult:
    store = SqliteV2Store(db_path)
    store.ensure_schema()

    current_utc = now_utc or datetime.now(timezone.utc)
    run_id = str(uuid.uuid4())
    started_at = current_utc.replace(microsecond=0).isoformat()
    since_iso = _since_iso(lookback_hours, now_utc=current_utc)

    interests_processed = 0
    candidates = 0
    inserted = 0
    updated = 0
    deactivated = 0
    skipped_cooldown = 0
    inserted_by_type: dict[str, int] = {}

    with sqlite3.connect(Path(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        _insert_signal_run(conn, run_id=run_id, user_id=user_id, lookback_hours=lookback_hours, started_at=started_at)
        try:
            interest_rows = _load_interests(conn, user_id=user_id)
            interests_processed = len(interest_rows)
            for row in interest_rows:
                cooldown_hours = int(row["cooldown_hours"] or 24)
                interest_candidates = _build_interest_candidates(conn, row, since_iso=since_iso)
                current_keys: set[tuple[str, str, str]] = set()
                for candidate in interest_candidates:
                    candidates += 1
                    current_keys.add(_signal_key(candidate))
                    if _refresh_existing_signal(conn, candidate=candidate, now_iso=started_at):
                        updated += 1
                        continue
                    if _is_in_cooldown(conn, candidate, cooldown_hours=cooldown_hours, now_utc=current_utc):
                        skipped_cooldown += 1
                        continue
                    _insert_signal(conn, run_id=run_id, candidate=candidate, now_iso=started_at)
                    inserted += 1
                    inserted_by_type[candidate.signal_type] = inserted_by_type.get(candidate.signal_type, 0) + 1
                deactivated += _deactivate_stale_interest_signals(
                    conn,
                    interest_id=str(row["interest_id"]),
                    current_keys=current_keys,
                    now_iso=started_at,
                )
            _finish_signal_run(
                conn,
                run_id=run_id,
                finished_at=current_utc.replace(microsecond=0).isoformat(),
                status="success",
                interests_processed=interests_processed,
                candidates=candidates,
                inserted=inserted,
                updated=updated,
                deactivated=deactivated,
                skipped_cooldown=skipped_cooldown,
                error_message=None,
            )
            conn.commit()
        except Exception as exc:
            _finish_signal_run(
                conn,
                run_id=run_id,
                finished_at=current_utc.replace(microsecond=0).isoformat(),
                status="failed",
                interests_processed=interests_processed,
                candidates=candidates,
                inserted=inserted,
                updated=updated,
                deactivated=deactivated,
                skipped_cooldown=skipped_cooldown,
                error_message=str(exc),
            )
            conn.commit()
            raise

    return InterestSignalRunResult(
        run_id=run_id,
        interests_processed=interests_processed,
        candidates=candidates,
        inserted=inserted,
        updated=updated,
        deactivated=deactivated,
        skipped_cooldown=skipped_cooldown,
        inserted_by_type=inserted_by_type,
    )


def _build_interest_candidates(conn: sqlite3.Connection, row: sqlite3.Row, *, since_iso: str) -> list[SignalCandidate]:
    interest_id = str(row["interest_id"])
    user_id = str(row["user_id"])
    target_id = _text(row["target_id"])
    interest_kind = _text(row["interest_kind"]) or ""
    target_label = _text(row["target_label"]) or _text(row["interest_name"]) or "target"
    if target_id is None:
        return []

    active_groups = _load_active_groups(conn, target_id)
    ended_comps = _load_recent_ended_comps(conn, row)
    recent_ended = [comp for comp in ended_comps if _is_at_or_after(comp.get("end_at"), since_iso)]
    comp_trend = _estimate_comp_trend(conn, row, since_iso=since_iso)
    recent_events = _load_recent_interest_events(conn, row, since_iso=since_iso)
    candidates: list[SignalCandidate] = []

    if interest_kind == "watch_buy":
        for event in recent_events[:3]:
            event_key = f"{event['source_listing_id']}|{event['old_status_raw']}|{event['new_status_raw']}|{event['change_time']}"
            if event["old_status_raw"] == "1" and event["new_status_raw"] == "2":
                candidates.append(
                    SignalCandidate(
                        user_id=user_id,
                        interest_id=interest_id,
                        target_id=target_id,
                        listing_id=event["listing_id"],
                        signal_type="buy_went_live",
                        urgency="high",
                        reason_code="matched_item_went_live",
                        signal_title="Wanted item just went live",
                        signal_summary=f"`{target_label}` listing `{event['title']}` moved from preview to live.",
                        group_key=event_key,
                        payload={"target_label": target_label, "event": event},
                    )
                )
            elif event["old_status_raw"] == "0" and event["new_status_raw"] == "1":
                candidates.append(
                    SignalCandidate(
                        user_id=user_id,
                        interest_id=interest_id,
                        target_id=target_id,
                        listing_id=event["listing_id"],
                        signal_type="buy_new_preview",
                        urgency="medium",
                        reason_code="matched_item_entered_preview",
                        signal_title="Wanted item entered preview",
                        signal_summary=f"`{target_label}` listing `{event['title']}` newly entered preview.",
                        group_key=event_key,
                        payload={"target_label": target_label, "event": event},
                    )
                )
        top_groups = active_groups[:2]
        for group in top_groups:
            urgency = "high" if group["relationship_type"] == "exact_identity" and group["status_norm"] == "live" else "medium"
            group_key = f"{group['relationship_type']}|{group['status_norm']}|{group['title']}"
            candidates.append(
                SignalCandidate(
                    user_id=user_id,
                    interest_id=interest_id,
                    target_id=target_id,
                    listing_id=None,
                    signal_type="buy_active_opportunity",
                    urgency=urgency,
                    reason_code="grouped_active_match",
                    signal_title="Exact wanted item is active" if group["relationship_type"] == "exact_identity" else "Related wanted item is active",
                    signal_summary=(
                        f"`{target_label}` currently has `{group['listing_count']}` `{group['status_norm']}` listings for "
                        f"`{group['title']}`."
                    ),
                    group_key=group_key,
                    payload={"target_label": target_label, "group": group, "budget_max": row["budget_max"]},
                )
            )
        budget_max = _to_float(row["budget_max"])
        expected_end_mid = comp_trend["weighted_median_end_price"]
        if budget_max is not None and expected_end_mid is not None:
            comp_range = _range_label(comp_trend["observed_min_end_price"], comp_trend["observed_max_end_price"])
            summary_suffix = _comp_summary_suffix(comp_trend)
            if expected_end_mid <= budget_max:
                candidates.append(
                    SignalCandidate(
                        user_id=user_id,
                        interest_id=interest_id,
                        target_id=target_id,
                        listing_id=None,
                        signal_type="buy_budget_feasible_by_comps",
                        urgency="medium",
                        reason_code="ended_comp_trend_within_budget",
                        signal_title="Recent ended comps fit the buy budget",
                        signal_summary=(
                            f"`{target_label}` has recent ended comps around `{expected_end_mid}` "
                            f"(range `{comp_range}`), within budget `{budget_max}`{summary_suffix}."
                        ),
                        group_key=f"budget_fit|{budget_max}|{expected_end_mid}",
                        payload={
                            "target_label": target_label,
                            "budget_max": budget_max,
                            "expected_end_mid": expected_end_mid,
                            "ended_comp_range": comp_range,
                            "comp_trend": comp_trend,
                        },
                    )
                )
            else:
                candidates.append(
                    SignalCandidate(
                        user_id=user_id,
                        interest_id=interest_id,
                        target_id=target_id,
                        listing_id=None,
                        signal_type="buy_budget_risk_by_comps",
                        urgency="medium",
                        reason_code="ended_comp_trend_above_budget",
                        signal_title="Recent ended comps are above the buy budget",
                        signal_summary=(
                            f"`{target_label}` has recent ended comps around `{expected_end_mid}` "
                            f"(range `{comp_range}`), above budget `{budget_max}`{summary_suffix}."
                        ),
                        group_key=f"budget_risk|{budget_max}|{expected_end_mid}",
                        payload={
                            "target_label": target_label,
                            "budget_max": budget_max,
                            "expected_end_mid": expected_end_mid,
                            "ended_comp_range": comp_range,
                            "comp_trend": comp_trend,
                        },
                    )
                )

    elif interest_kind == "collecting":
        for event in recent_events[:3]:
            if event["old_status_raw"] == "1" and event["new_status_raw"] == "2":
                event_key = f"{event['source_listing_id']}|{event['old_status_raw']}|{event['new_status_raw']}|{event['change_time']}"
                candidates.append(
                    SignalCandidate(
                        user_id=user_id,
                        interest_id=interest_id,
                        target_id=target_id,
                        listing_id=event["listing_id"],
                        signal_type="collection_went_live",
                        urgency="medium",
                        reason_code="collection_item_went_live",
                        signal_title="Collection item went live",
                        signal_summary=f"`{target_label}` related listing `{event['title']}` just moved into live bidding.",
                        group_key=event_key,
                        payload={"target_label": target_label, "event": event},
                    )
                )
        top_groups = [group for group in active_groups if group["relationship_type"] in {"exact_identity", "variant_related"}][:2]
        for group in top_groups:
            group_key = f"{group['relationship_type']}|{group['status_norm']}|{group['title']}"
            candidates.append(
                SignalCandidate(
                    user_id=user_id,
                    interest_id=interest_id,
                    target_id=target_id,
                    listing_id=None,
                    signal_type="collection_opportunity",
                    urgency="medium" if group["relationship_type"] == "exact_identity" else "low",
                    reason_code="grouped_collection_match",
                    signal_title="Collection opportunity found",
                    signal_summary=(
                        f"`{target_label}` currently has `{group['listing_count']}` `{group['relationship_type']}` "
                        f"listings for `{group['title']}` in `{group['status_norm']}` status."
                    ),
                    group_key=group_key,
                    payload={"target_label": target_label, "group": group},
                )
            )

    elif interest_kind == "discovery":
        top_group = active_groups[0] if active_groups else None
        if top_group is not None:
            group_key = f"{top_group['relationship_type']}|{top_group['status_norm']}|{top_group['title']}"
            candidates.append(
                SignalCandidate(
                    user_id=user_id,
                    interest_id=interest_id,
                    target_id=target_id,
                    listing_id=None,
                    signal_type="discovery_digest",
                    urgency="low",
                    reason_code="series_activity_snapshot",
                    signal_title="Discovery track has active market depth",
                    signal_summary=(
                        f"`{target_label}` currently spans `{len(active_groups)}` grouped opportunities; "
                        f"top group is `{top_group['title']}` with `{top_group['listing_count']}` listings."
                    ),
                    group_key=group_key,
                    payload={"target_label": target_label, "top_group": top_group, "group_count": len(active_groups)},
                )
            )

    elif interest_kind == "watch_sell":
        for event in recent_events[:3]:
            if event["old_status_raw"] == "2" and event["new_status_raw"] == "3":
                event_key = f"{event['source_listing_id']}|{event['old_status_raw']}|{event['new_status_raw']}|{event['change_time']}"
                candidates.append(
                    SignalCandidate(
                        user_id=user_id,
                        interest_id=interest_id,
                        target_id=target_id,
                        listing_id=event["listing_id"],
                        signal_type="sell_new_ended_comp",
                        urgency="high",
                        reason_code="matched_comp_just_ended",
                        signal_title="Comparable listing just ended",
                        signal_summary=f"`{target_label}` comparable listing `{event['title']}` just ended and can refresh the exit view.",
                        group_key=event_key,
                        payload={"target_label": target_label, "event": event},
                    )
                )
        cost_basis = _to_float(row["cost_basis_unit"])
        expected_end_mid = comp_trend["weighted_median_end_price"]
        if cost_basis is not None and expected_end_mid is not None:
            max_price = comp_trend["observed_max_end_price"]
            min_price = comp_trend["observed_min_end_price"]
            if max_price is not None and max_price > cost_basis:
                summary_suffix = _comp_summary_suffix(comp_trend)
                candidates.append(
                    SignalCandidate(
                        user_id=user_id,
                        interest_id=interest_id,
                        target_id=target_id,
                        listing_id=None,
                        signal_type="sell_comp_above_cost",
                        urgency="high",
                        reason_code="ended_comp_above_cost_basis",
                        signal_title="Ended comps are above cost basis",
                        signal_summary=(
                            f"`{target_label}` has weighted ended trend around `{expected_end_mid}` "
                            f"(observed `{min_price}-{max_price}`) versus held cost basis `{cost_basis}`{summary_suffix}."
                        ),
                        group_key=f"ended_range|{min_price}|{max_price}|{expected_end_mid}",
                        payload={
                            "target_label": target_label,
                            "cost_basis_unit": cost_basis,
                            "comp_trend": comp_trend,
                            "min_price": min_price,
                            "max_price": max_price,
                            "expected_end_mid": expected_end_mid,
                        },
                    )
                )
        if active_groups:
            top_group = active_groups[0]
            candidates.append(
                SignalCandidate(
                    user_id=user_id,
                    interest_id=interest_id,
                    target_id=target_id,
                    listing_id=None,
                    signal_type="sell_market_depth",
                    urgency="medium",
                    reason_code="active_comparable_market_depth",
                    signal_title="Comparable active supply is present",
                    signal_summary=(
                        f"`{target_label}` currently has `{top_group['listing_count']}` comparable `{top_group['status_norm']}` listings "
                        f"for `{top_group['title']}`."
                    ),
                    group_key=f"{top_group['relationship_type']}|{top_group['status_norm']}|{top_group['title']}",
                    payload={"target_label": target_label, "group": top_group},
                )
            )

    return candidates[: int(row["max_signals_per_day"] or 3)]


def _load_interests(conn: sqlite3.Connection, *, user_id: str | None) -> list[sqlite3.Row]:
    where = ["i.active_status = 'active'"]
    params: list[Any] = []
    if user_id:
        where.append("i.user_id = ?")
        params.append(user_id)
    query = f"""
        SELECT
          i.id AS interest_id,
          i.user_id,
          i.interest_name,
          i.interest_kind,
          i.scope_kind,
          i.precision_mode,
          t.id AS target_id,
          t.target_label,
          t.parse_family,
          t.raw_input,
          t.normalized_name,
          t.issue_code_norm,
          t.series_key,
          t.theme_name,
          t.asset_type,
          t.year_value,
          t.condition_tokens_json,
          t.condition_mode,
          t.budget_max,
          h.cost_basis_unit,
          p.min_match_score,
          p.cooldown_hours,
          p.delivery_mode,
          p.max_signals_per_day
        FROM user_interests_v2 i
        LEFT JOIN user_interest_targets_v2 t ON t.interest_id = i.id AND t.is_active = 1
        LEFT JOIN user_holdings_v2 h ON h.linked_interest_id = i.id AND h.is_active = 1
        LEFT JOIN user_interest_signal_policies_v2 p ON p.interest_id = i.id
        WHERE {' AND '.join(where)}
        ORDER BY
          CASE i.interest_priority WHEN 'high' THEN 1 WHEN 'normal' THEN 2 ELSE 3 END,
          i.interest_name
    """
    return conn.execute(query, params).fetchall()


def _load_active_groups(conn: sqlite3.Connection, target_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
          n.title,
          n.status_norm,
          lm.relationship_type,
          COUNT(*) AS listing_count,
          MIN(n.price_initial) AS min_start_price,
          MAX(n.price_initial) AS max_start_price,
          MAX(lm.match_score) AS top_match_score,
          MAX(n.updated_at) AS latest_listing_update
        FROM listing_matches_v2 lm
        JOIN market_listings_norm_v2 n ON n.id = lm.listing_id
        WHERE lm.status = 'active' AND lm.user_item_id = ?
        GROUP BY n.title, n.status_norm, lm.relationship_type
        ORDER BY
          CASE lm.relationship_type
            WHEN 'exact_identity' THEN 1
            WHEN 'variant_related' THEN 2
            WHEN 'series_related' THEN 3
            ELSE 4
          END,
          CASE n.status_norm
            WHEN 'live' THEN 1
            WHEN 'preview' THEN 2
            WHEN 'ended' THEN 3
            ELSE 4
          END,
          listing_count DESC,
          top_match_score DESC,
          n.title
        """,
        (target_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def _load_recent_interest_events(conn: sqlite3.Connection, row: sqlite3.Row, *, since_iso: str) -> list[dict[str, Any]]:
    target = _target_profile(row)
    parse_family = target["parse_family"]
    params: list[Any] = [parse_family, since_iso]
    where = ["p.parse_family = ?", "e.change_time >= ?"]
    if parse_family == "stamp_like":
        clauses: list[str] = []
        if target["issue_code_norm"]:
            clauses.append("p.issue_code_norm = ?")
            params.append(target["issue_code_norm"])
        if target["issue_name"]:
            clauses.append("p.issue_name = ?")
            params.append(target["issue_name"])
        if target["series_key"]:
            clauses.append("p.series_key = ?")
            params.append(target["series_key"])
        if not clauses:
            return []
        where.append("(" + " OR ".join(clauses) + ")")
    elif parse_family == "coin_like":
        clauses = []
        if target["theme_name"] and target["asset_type"]:
            clauses.append("(p.theme_name = ? AND p.asset_type = ?)")
            params.extend([target["theme_name"], target["asset_type"]])
        if target["series_key"]:
            clauses.append("p.series_key = ?")
            params.append(target["series_key"])
        if not clauses:
            return []
        where.append("(" + " OR ".join(clauses) + ")")
    else:
        return []

    query = f"""
        SELECT
          n.id AS listing_id,
          n.source_listing_id,
          n.title,
          e.change_time,
          e.old_status_raw,
          e.new_status_raw
        FROM market_listing_events_v2 e
        JOIN market_listings_norm_v2 n
          ON n.source_platform = e.source_platform
         AND n.source_listing_id = e.source_listing_id
        JOIN listing_parse_v2 p ON p.listing_id = n.id
        WHERE {" AND ".join(where)}
        ORDER BY e.change_time DESC, n.source_listing_id DESC
        LIMIT 10
    """
    return [dict(row) for row in conn.execute(query, params).fetchall()]


def _estimate_comp_trend(conn: sqlite3.Connection, row: sqlite3.Row, *, since_iso: str) -> dict[str, Any]:
    target = _target_profile(row)
    comp_rows = _load_comp_candidates(conn, target)
    scored: list[dict[str, Any]] = []
    for comp in comp_rows:
        relation = _classify_comp_relationship(target, comp)
        if relation is None:
            continue
        price_end = _to_float(comp["price_end"])
        if price_end is None or price_end <= 0:
            continue
        recency_weight = _recency_weight(comp["end_at"], since_iso=since_iso)
        condition_weight = _condition_weight(target, comp)
        relation_weight = {"exact_identity": 1.0, "variant_related": 0.7, "series_related": 0.4}[relation]
        weight = relation_weight * recency_weight * condition_weight
        if weight <= 0:
            continue
        scored.append(
            {
                "source_listing_id": comp["source_listing_id"],
                "title": comp["title"],
                "price_end": price_end,
                "end_at": comp["end_at"],
                "relationship_type": relation,
                "condition_tier": _condition_tier(target, comp),
                "weight": round(weight, 4),
            }
        )
    if not scored:
        return {
            "sample_count": 0,
            "selected_sample_count": 0,
            "exact_count": 0,
            "variant_count": 0,
            "series_count": 0,
            "same_condition_count": 0,
            "acceptable_condition_count": 0,
            "fallback_condition_count": 0,
            "pricing_basis": "none",
            "weighted_median_end_price": None,
            "weighted_average_end_price": None,
            "observed_min_end_price": None,
            "observed_max_end_price": None,
            "top_comps": [],
        }
    selected_scored, pricing_basis = _select_pricing_subset(scored)
    exact_count = sum(1 for comp in scored if comp["relationship_type"] == "exact_identity")
    variant_count = sum(1 for comp in scored if comp["relationship_type"] == "variant_related")
    series_count = sum(1 for comp in scored if comp["relationship_type"] == "series_related")
    same_condition_count = sum(1 for comp in scored if comp["condition_tier"] == "same_condition")
    acceptable_condition_count = sum(1 for comp in scored if comp["condition_tier"] == "acceptable_condition")
    fallback_condition_count = sum(1 for comp in scored if comp["condition_tier"] == "fallback_condition")
    weighted_values = sorted((comp["price_end"], comp["weight"]) for comp in selected_scored)
    weighted_median = _weighted_median(weighted_values)
    weighted_average = round(
        sum(comp["price_end"] * comp["weight"] for comp in selected_scored) / sum(comp["weight"] for comp in selected_scored),
        2,
    )
    return {
        "sample_count": len(scored),
        "selected_sample_count": len(selected_scored),
        "exact_count": exact_count,
        "variant_count": variant_count,
        "series_count": series_count,
        "same_condition_count": same_condition_count,
        "acceptable_condition_count": acceptable_condition_count,
        "fallback_condition_count": fallback_condition_count,
        "pricing_basis": pricing_basis,
        "weighted_median_end_price": weighted_median,
        "weighted_average_end_price": weighted_average,
        "observed_min_end_price": min(comp["price_end"] for comp in selected_scored),
        "observed_max_end_price": max(comp["price_end"] for comp in selected_scored),
        "top_comps": sorted(selected_scored, key=lambda comp: (-comp["weight"], -(comp["price_end"]), comp["source_listing_id"]))[:5],
    }


def _load_comp_candidates(conn: sqlite3.Connection, target: dict[str, Any]) -> list[sqlite3.Row]:
    parse_family = target["parse_family"]
    params: list[Any] = [parse_family]
    where = ["n.status_raw = '3'", "p.parse_family = ?"]
    if parse_family == "stamp_like":
        clauses: list[str] = []
        if target["issue_code_norm"]:
            clauses.append("p.issue_code_norm = ?")
            params.append(target["issue_code_norm"])
        if target["issue_name"]:
            clauses.append("p.issue_name = ?")
            params.append(target["issue_name"])
        if target["series_key"]:
            clauses.append("p.series_key = ?")
            params.append(target["series_key"])
        if not clauses:
            return []
        where.append("(" + " OR ".join(clauses) + ")")
    elif parse_family == "coin_like":
        clauses = []
        if target["theme_name"] and target["asset_type"]:
            clauses.append("(p.theme_name = ? AND p.asset_type = ?)")
            params.extend([target["theme_name"], target["asset_type"]])
        if target["series_key"]:
            clauses.append("p.series_key = ?")
            params.append(target["series_key"])
        if not clauses:
            return []
        where.append("(" + " OR ".join(clauses) + ")")
    else:
        return []

    query = f"""
        SELECT
          n.source_listing_id,
          n.title,
          n.price_end,
          n.end_at,
          n.character_name_raw,
          p.raw_title,
          p.issue_code_norm,
          p.issue_name,
          p.series_key,
          p.theme_name,
          p.asset_type,
          p.year_value,
          p.variant_key,
          p.condition_key,
          p.variant_tokens_json,
          p.condition_tokens_json,
          p.character_condition
        FROM market_listings_norm_v2 n
        JOIN listing_parse_v2 p ON p.listing_id = n.id
        WHERE {" AND ".join(where)}
        ORDER BY n.end_at DESC, n.source_listing_id DESC
        LIMIT 80
    """
    return conn.execute(query, params).fetchall()


def _target_profile(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "parse_family": _text(row["parse_family"]),
        "raw_input": _text(row["raw_input"]),
        "issue_code_norm": _text(row["issue_code_norm"]),
        "issue_name": _text(row["theme_name"]) if _text(row["parse_family"]) == "stamp_like" else _text(row["normalized_name"]),
        "series_key": _text(row["series_key"]),
        "theme_name": _text(row["theme_name"]),
        "asset_type": _text(row["asset_type"]),
        "year_value": row["year_value"],
        "condition_mode": _text(row["condition_mode"]) or "ignore",
        "condition_tokens": _condition_tokens_from_target_row(row),
    }


def _classify_comp_relationship(target: dict[str, Any], comp: sqlite3.Row) -> str | None:
    if target["parse_family"] == "stamp_like":
        target_code = _normalize_key(target["issue_code_norm"])
        comp_code = _normalize_key(comp["issue_code_norm"])
        target_name = _normalize_key(target["issue_name"])
        comp_name = _normalize_key(comp["issue_name"])
        target_series = _normalize_key(target["series_key"])
        comp_series = _normalize_key(comp["series_key"])
        target_variant = _conditionless_target_variant(target)
        comp_variant = _json_list(comp["variant_tokens_json"])
        if ((target_code and comp_code and target_code == comp_code) or (target_name and comp_name and target_name == comp_name)):
            if _token_overlap(target_variant, comp_variant):
                return "exact_identity"
            return "variant_related"
        if target_series and comp_series and target_series == comp_series:
            return "series_related"
        return None
    if target["parse_family"] == "coin_like":
        target_theme = _normalize_key(target["theme_name"])
        comp_theme = _normalize_key(comp["theme_name"])
        target_asset = _normalize_key(target["asset_type"])
        comp_asset = _normalize_key(comp["asset_type"])
        target_year = target["year_value"]
        comp_year = comp["year_value"]
        target_series = _normalize_key(target["series_key"])
        comp_series = _normalize_key(comp["series_key"])
        if target_theme and comp_theme and target_theme == comp_theme and target_asset and comp_asset and target_asset == comp_asset:
            if target_year is not None and comp_year == target_year:
                return "exact_identity"
            if target_series and comp_series and target_series == comp_series:
                return "variant_related"
            return "series_related"
        return None
    return None


def _conditionless_target_variant(target: dict[str, Any]) -> list[str]:
    raw_input = _text(target["raw_input"]) or ""
    if not raw_input:
        return []
    if target["parse_family"] == "stamp_like":
        title = raw_input
        tokens: list[str] = []
        for token in ("小型张", "型张", "版张", "带厂铭", "直角边", "色标", "双连", "四连", "方连", "折版", "再版", "一版", "二版", "三版", "四版", "M"):
            if token in title:
                tokens.append(token)
        return tokens
    return []


def _condition_tokens_from_target_row(row: sqlite3.Row) -> list[str]:
    return _json_list(row["condition_tokens_json"]) if "condition_tokens_json" in row.keys() else []


def _condition_weight(target: dict[str, Any], comp: sqlite3.Row) -> float:
    tier = _condition_tier(target, comp)
    if tier == "same_condition":
        return 1.0
    if tier == "acceptable_condition":
        return 0.8
    return 0.5


def _condition_tier(target: dict[str, Any], comp: sqlite3.Row) -> str:
    mode = target["condition_mode"]
    if mode == "ignore":
        return "acceptable_condition"
    target_tokens = target["condition_tokens"]
    comp_tokens = _json_list(comp["condition_tokens_json"])
    character = _text(comp["character_condition"])
    if character and character not in comp_tokens:
        comp_tokens.append(character)
    if not target_tokens:
        return "acceptable_condition"
    if _has_hard_condition_conflict(target_tokens, comp_tokens):
        return "fallback_condition"
    if _token_overlap(target_tokens, comp_tokens):
        return "same_condition"
    if mode == "require":
        return "fallback_condition"
    return "acceptable_condition"


def _recency_weight(end_at: Any, *, since_iso: str) -> float:
    text = _text(end_at)
    if text is None:
        return 0.6
    try:
        end_dt = datetime.fromisoformat(text)
        since_dt = datetime.fromisoformat(since_iso)
    except ValueError:
        return 0.6
    if end_dt >= since_dt:
        return 1.0
    age_days = max((datetime.now(timezone.utc) - end_dt).total_seconds() / 86400.0, 0.0)
    if age_days <= 3:
        return 0.9
    if age_days <= 7:
        return 0.8
    if age_days <= 14:
        return 0.7
    return 0.55


def _comp_summary_suffix(comp_trend: dict[str, Any]) -> str:
    sample_count = comp_trend["sample_count"]
    selected_sample_count = comp_trend["selected_sample_count"]
    exact_count = comp_trend["exact_count"]
    variant_count = comp_trend["variant_count"]
    series_count = comp_trend["series_count"]
    same_condition_count = comp_trend["same_condition_count"]
    acceptable_condition_count = comp_trend["acceptable_condition_count"]
    fallback_condition_count = comp_trend["fallback_condition_count"]
    pricing_basis = _pricing_basis_label(comp_trend["pricing_basis"])
    return (
        f" using `{selected_sample_count}` of `{sample_count}` ended comps"
        f" on `{pricing_basis}` basis"
        f" (`{exact_count}` exact, `{variant_count}` variant, `{series_count}` series; "
        f"`{same_condition_count}` same-condition, `{acceptable_condition_count}` acceptable, `{fallback_condition_count}` fallback)"
    )


def _json_list(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item).strip() for item in parsed if str(item).strip()]


def _token_overlap(left: list[str], right: list[str]) -> bool:
    if not left or not right:
        return False
    return bool({_normalize_key(token) for token in left} & {_normalize_key(token) for token in right})


def _has_hard_condition_conflict(target_tokens: list[str], comp_tokens: list[str]) -> bool:
    target_tags = _condition_tags(target_tokens)
    comp_tags = _condition_tags(comp_tokens)
    if "mint" in target_tags and "used" in comp_tags:
        return True
    if "used" in target_tags and "mint" in comp_tags:
        return True
    if "graded" in target_tags and "graded" not in comp_tags:
        return True
    return False


def _condition_tags(tokens: list[str]) -> set[str]:
    tags: set[str] = set()
    normalized = {_normalize_key(token) for token in tokens if _normalize_key(token)}
    if normalized & {"新", "新全"}:
        tags.add("mint")
    if normalized & {"旧", "旧全", "盖", "盖全", "实寄"}:
        tags.add("used")
    if normalized & {"评级票", "评级币"}:
        tags.add("graded")
    return tags


def _normalize_key(value: Any) -> str | None:
    text = _text(value)
    if text is None:
        return None
    return "".join(text.lower().split())


def _insert_signal_run(conn: sqlite3.Connection, *, run_id: str, user_id: str | None, lookback_hours: int, started_at: str) -> None:
    conn.execute(
        """
        INSERT INTO signal_runs_v2 (
          id, user_id, lookback_hours, started_at, status
        ) VALUES (?, ?, ?, ?, 'running')
        """,
        (run_id, user_id, lookback_hours, started_at),
    )


def _finish_signal_run(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    finished_at: str,
    status: str,
    interests_processed: int,
    candidates: int,
    inserted: int,
    updated: int,
    deactivated: int,
    skipped_cooldown: int,
    error_message: str | None,
) -> None:
    conn.execute(
        """
        UPDATE signal_runs_v2
        SET finished_at = ?,
            status = ?,
            interests_processed = ?,
            candidates = ?,
            inserted = ?,
            updated = ?,
            deactivated = ?,
            skipped_cooldown = ?,
            error_message = ?
        WHERE id = ?
        """,
        (finished_at, status, interests_processed, candidates, inserted, updated, deactivated, skipped_cooldown, error_message, run_id),
    )


def _is_in_cooldown(
    conn: sqlite3.Connection,
    candidate: SignalCandidate,
    *,
    cooldown_hours: int,
    now_utc: datetime | None = None,
) -> bool:
    current = now_utc or datetime.now(timezone.utc)
    cutoff = (current - timedelta(hours=cooldown_hours)).isoformat()
    row = conn.execute(
        """
        SELECT 1
        FROM signals_v2
        WHERE user_id = ?
          AND interest_id = ?
          AND signal_type = ?
          AND reason_code = ?
          AND COALESCE(group_key, '') = COALESCE(?, '')
          AND created_at >= ?
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (
            candidate.user_id,
            candidate.interest_id,
            candidate.signal_type,
            candidate.reason_code,
            candidate.group_key,
            cutoff,
        ),
    ).fetchone()
    return row is not None


def _insert_signal(conn: sqlite3.Connection, *, run_id: str, candidate: SignalCandidate, now_iso: str) -> None:
    conn.execute(
        """
        INSERT INTO signals_v2 (
          id, run_id, user_id, interest_id, target_id, listing_id, signal_type,
          urgency, reason_code, signal_title, signal_summary, group_key,
          payload_json, created_at, last_seen_at, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
        """,
        (
            str(uuid.uuid4()),
            run_id,
            candidate.user_id,
            candidate.interest_id,
            candidate.target_id,
            candidate.listing_id,
            candidate.signal_type,
            candidate.urgency,
            candidate.reason_code,
            candidate.signal_title,
            candidate.signal_summary,
            candidate.group_key,
            json.dumps(candidate.payload, ensure_ascii=False, separators=(",", ":")),
            now_iso,
            now_iso,
        ),
    )


def _refresh_existing_signal(conn: sqlite3.Connection, *, candidate: SignalCandidate, now_iso: str) -> bool:
    row = conn.execute(
        """
        SELECT id
        FROM signals_v2
        WHERE user_id = ?
          AND interest_id = ?
          AND signal_type = ?
          AND reason_code = ?
          AND COALESCE(group_key, '') = COALESCE(?, '')
          AND status = 'active'
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (
            candidate.user_id,
            candidate.interest_id,
            candidate.signal_type,
            candidate.reason_code,
            candidate.group_key,
        ),
    ).fetchone()
    if row is None:
        return False
    conn.execute(
        """
        UPDATE signals_v2
        SET target_id = ?,
            listing_id = ?,
            urgency = ?,
            signal_title = ?,
            signal_summary = ?,
            payload_json = ?,
            last_seen_at = ?,
            status = 'active'
        WHERE id = ?
        """,
        (
            candidate.target_id,
            candidate.listing_id,
            candidate.urgency,
            candidate.signal_title,
            candidate.signal_summary,
            json.dumps(candidate.payload, ensure_ascii=False, separators=(",", ":")),
            now_iso,
            row["id"],
        ),
    )
    return True


def _deactivate_stale_interest_signals(
    conn: sqlite3.Connection,
    *,
    interest_id: str,
    current_keys: set[tuple[str, str, str]],
    now_iso: str,
) -> int:
    rows = conn.execute(
        """
        SELECT id, signal_type, reason_code, COALESCE(group_key, '') AS group_key
        FROM signals_v2
        WHERE interest_id = ? AND status = 'active'
        """,
        (interest_id,),
    ).fetchall()
    stale_ids = [
        row["id"]
        for row in rows
        if (str(row["signal_type"]), str(row["reason_code"]), str(row["group_key"])) not in current_keys
    ]
    if not stale_ids:
        return 0
    placeholders = ",".join("?" for _ in stale_ids)
    conn.execute(
        f"""
        UPDATE signals_v2
        SET status = 'inactive',
            last_seen_at = ?
        WHERE id IN ({placeholders})
        """,
        (now_iso, *stale_ids),
    )
    return len(stale_ids)


def _signal_key(candidate: SignalCandidate) -> tuple[str, str, str]:
    return (
        candidate.signal_type,
        candidate.reason_code,
        candidate.group_key or "",
    )


def _since_iso(hours: int, *, now_utc: datetime | None = None) -> str:
    current = now_utc or datetime.now(timezone.utc)
    return (current - timedelta(hours=hours)).isoformat()


def _is_at_or_after(value: Any, since_iso: str) -> bool:
    text = _text(value)
    if text is None:
        return False
    try:
        return datetime.fromisoformat(text) >= datetime.fromisoformat(since_iso)
    except ValueError:
        return False


def _range_label(min_value: Any, max_value: Any) -> str | None:
    if min_value is None and max_value is None:
        return None
    if min_value == max_value:
        return str(min_value)
    return f"{min_value}-{max_value}"


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    mid = len(values) // 2
    if len(values) % 2 == 1:
        return values[mid]
    return (values[mid - 1] + values[mid]) / 2.0


def _weighted_median(weighted_values: list[tuple[float, float]]) -> float | None:
    if not weighted_values:
        return None
    total_weight = sum(weight for _, weight in weighted_values)
    if total_weight <= 0:
        return None
    threshold = total_weight / 2.0
    running = 0.0
    for value, weight in weighted_values:
        running += weight
        if running >= threshold:
            return round(value, 2)
    return round(weighted_values[-1][0], 2)


def _select_pricing_subset(scored: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
    exactish = [comp for comp in scored if comp["relationship_type"] in {"exact_identity", "variant_related"}]
    same_exactish = [comp for comp in exactish if comp["condition_tier"] == "same_condition"]
    acceptable_exactish = [comp for comp in exactish if comp["condition_tier"] in {"same_condition", "acceptable_condition"}]
    same_any = [comp for comp in scored if comp["condition_tier"] == "same_condition"]
    acceptable_any = [comp for comp in scored if comp["condition_tier"] in {"same_condition", "acceptable_condition"}]

    if len(same_exactish) >= 2:
        return same_exactish, "exact_same_condition"
    if len(acceptable_exactish) >= 2:
        return acceptable_exactish, "exact_acceptable_condition"
    if len(same_any) >= 2:
        return same_any, "same_condition_fallback"
    if len(acceptable_any) >= 2:
        return acceptable_any, "acceptable_condition_fallback"
    return scored, "full_fallback"


def _pricing_basis_label(value: str) -> str:
    labels = {
        "exact_same_condition": "exact same-condition",
        "exact_acceptable_condition": "exact acceptable-condition",
        "same_condition_fallback": "same-condition fallback",
        "acceptable_condition_fallback": "acceptable-condition fallback",
        "full_fallback": "full fallback",
        "none": "no comp",
    }
    return labels.get(value, value)
