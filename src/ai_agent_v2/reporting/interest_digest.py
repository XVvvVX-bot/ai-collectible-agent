from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ai_agent_v2.clients.zhaoonline import now_utc_iso
from ai_agent_v2.reporting.interest_review import _load_recent_ended_comps
from ai_agent_v2.signals.interest_signals import _comp_summary_suffix, _estimate_comp_trend
from ai_agent_v2.storage.sqlite_store import SqliteV2Store


@dataclass(frozen=True)
class InterestDigestReportResult:
    report_path: str
    user_id: str
    interest_count: int
    active_match_count: int
    recent_activity_count: int


def build_interest_digest_report(
    db_path: str,
    output_dir: str,
    *,
    user_id: str,
    lookback_hours: int = 24,
    now_utc: datetime | None = None,
) -> InterestDigestReportResult:
    SqliteV2Store(db_path).ensure_schema()
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    since_iso = _since_iso(lookback_hours, now_utc=now_utc)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        user_row = conn.execute(
            "SELECT id, display_name, language, timezone FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if user_row is None:
            raise ValueError(f"user not found: {user_id}")

        defaults_row = conn.execute(
            """
            SELECT default_precision_mode, default_delivery_mode, default_min_match_score,
                   default_cooldown_hours
            FROM user_profile_defaults_v2
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()

        interests = conn.execute(
            """
            SELECT
              i.id,
              i.interest_name,
              i.interest_kind,
              i.scope_kind,
              i.precision_mode,
              i.interest_priority,
              i.notes,
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
              h.raw_input AS holding_raw_input,
              h.holding_quantity,
              h.cost_basis_unit,
              p.min_match_score,
              p.cooldown_hours,
              p.delivery_mode
            FROM user_interests_v2 i
            LEFT JOIN user_interest_targets_v2 t ON t.interest_id = i.id AND t.is_active = 1
            LEFT JOIN user_holdings_v2 h ON h.linked_interest_id = i.id AND h.is_active = 1
            LEFT JOIN user_interest_signal_policies_v2 p ON p.interest_id = i.id
            WHERE i.user_id = ? AND i.active_status = 'active'
            ORDER BY
              CASE i.interest_priority WHEN 'high' THEN 1 WHEN 'normal' THEN 2 ELSE 3 END,
              i.interest_name,
              t.target_label
            """,
            (user_id,),
        ).fetchall()

        active_match_count = int(
            conn.execute(
                "SELECT COUNT(*) FROM listing_matches_v2 WHERE user_id = ? AND status = 'active'",
                (user_id,),
            ).fetchone()[0]
        )

        sections = [_build_interest_digest_section(conn, row, since_iso=since_iso) for row in interests]
        recent_activity_count = sum(section["recent_listing_count"] for section in sections)

    timestamp = now_utc_iso().replace(":", "").replace("-", "").replace("+00:00", "Z")
    report_path = out_dir / f"v2_interest_digest_{user_id}_{timestamp}.md"
    report_path.write_text(
        _render_report(
            user=dict(user_row),
            defaults=dict(defaults_row) if defaults_row is not None else None,
            lookback_hours=lookback_hours,
            active_match_count=active_match_count,
            recent_activity_count=recent_activity_count,
            sections=sections,
        ),
        encoding="utf-8",
    )
    return InterestDigestReportResult(
        report_path=str(report_path),
        user_id=user_id,
        interest_count=len(sections),
        active_match_count=active_match_count,
        recent_activity_count=recent_activity_count,
    )


def _build_interest_digest_section(conn: sqlite3.Connection, row: sqlite3.Row, *, since_iso: str) -> dict[str, Any]:
    target_id = _text(row["target_id"])
    grouped_active: list[dict[str, Any]] = []
    recent_groups: list[dict[str, Any]] = []
    recent_examples: list[dict[str, Any]] = []
    relationship_counts: dict[str, int] = {}
    recent_listing_count = 0

    if target_id:
        relationship_counts = {
            str(r["relationship_type"]): int(r["cnt"])
            for r in conn.execute(
                """
                SELECT lm.relationship_type, COUNT(*) AS cnt
                FROM listing_matches_v2 lm
                WHERE lm.status = 'active' AND lm.user_item_id = ?
                GROUP BY lm.relationship_type
                ORDER BY lm.relationship_type
                """,
                (target_id,),
            ).fetchall()
        }
        grouped_active = [
            dict(r)
            for r in conn.execute(
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
                  listing_count DESC,
                  top_match_score DESC,
                  n.title
                LIMIT 6
                """,
                (target_id,),
            ).fetchall()
        ]
        recent_groups = [
            dict(r)
            for r in conn.execute(
                """
                SELECT
                  n.title,
                  n.status_norm,
                  lm.relationship_type,
                  COUNT(*) AS listing_count,
                  MIN(n.price_initial) AS min_start_price,
                  MAX(n.price_initial) AS max_start_price,
                  MAX(n.updated_at) AS latest_listing_update
                FROM listing_matches_v2 lm
                JOIN market_listings_norm_v2 n ON n.id = lm.listing_id
                WHERE lm.status = 'active'
                  AND lm.user_item_id = ?
                  AND n.updated_at >= ?
                GROUP BY n.title, n.status_norm, lm.relationship_type
                ORDER BY
                  CASE lm.relationship_type
                    WHEN 'exact_identity' THEN 1
                    WHEN 'variant_related' THEN 2
                    WHEN 'series_related' THEN 3
                    ELSE 4
                  END,
                  latest_listing_update DESC,
                  listing_count DESC,
                  n.title
                LIMIT 4
                """,
                (target_id, since_iso),
            ).fetchall()
        ]
        recent_examples = [
            dict(r)
            for r in conn.execute(
                """
                SELECT
                  n.source_listing_id,
                  n.title,
                  n.status_norm,
                  n.price_initial,
                  n.price_end,
                  n.character_name_raw,
                  n.updated_at,
                  lm.relationship_type,
                  lm.match_score
                FROM listing_matches_v2 lm
                JOIN market_listings_norm_v2 n ON n.id = lm.listing_id
                WHERE lm.status = 'active'
                  AND lm.user_item_id = ?
                  AND n.updated_at >= ?
                ORDER BY
                  CASE lm.relationship_type
                    WHEN 'exact_identity' THEN 1
                    WHEN 'variant_related' THEN 2
                    WHEN 'series_related' THEN 3
                    ELSE 4
                  END,
                  n.updated_at DESC,
                  lm.match_score DESC,
                  n.source_listing_id DESC
                LIMIT 5
                """,
                (target_id, since_iso),
            ).fetchall()
        ]
        recent_listing_count = int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM listing_matches_v2 lm
                JOIN market_listings_norm_v2 n ON n.id = lm.listing_id
                WHERE lm.status = 'active'
                  AND lm.user_item_id = ?
                  AND n.updated_at >= ?
                """,
                (target_id, since_iso),
            ).fetchone()[0]
        )

    ended_comps = _load_recent_ended_comps(conn, row)
    recent_ended_comps = [comp for comp in ended_comps if _is_at_or_after(comp.get("end_at"), since_iso)]
    comp_trend = _estimate_comp_trend(conn, row, since_iso=since_iso)
    highlight = _summarize_interest(
        row=row,
        relationship_counts=relationship_counts,
        recent_groups=recent_groups,
        recent_listing_count=recent_listing_count,
        recent_ended_comps=recent_ended_comps,
        comp_trend=comp_trend,
    )

    return {
        "interest": dict(row),
        "relationship_counts": relationship_counts,
        "grouped_active": grouped_active,
        "recent_groups": recent_groups,
        "recent_examples": recent_examples,
        "recent_listing_count": recent_listing_count,
        "ended_comps": ended_comps,
        "recent_ended_comps": recent_ended_comps,
        "comp_trend": comp_trend,
        "highlight": highlight,
    }


def _summarize_interest(
    *,
    row: sqlite3.Row,
    relationship_counts: dict[str, int],
    recent_groups: list[dict[str, Any]],
    recent_listing_count: int,
    recent_ended_comps: list[dict[str, Any]],
    comp_trend: dict[str, Any],
) -> str:
    kind = _text(row["interest_kind"]) or "interest"
    target = _text(row["target_label"]) or _text(row["interest_name"]) or "target"
    exact_count = relationship_counts.get("exact_identity", 0)
    series_count = relationship_counts.get("series_related", 0)
    variant_count = relationship_counts.get("variant_related", 0)

    if kind == "watch_sell":
        cost_basis = row["cost_basis_unit"]
        expected_end_mid = comp_trend.get("weighted_median_end_price")
        if expected_end_mid is not None and cost_basis not in (None, 0, 0.0):
            observed = _range_label(comp_trend.get("observed_min_end_price"), comp_trend.get("observed_max_end_price"))
            suffix = _comp_summary_suffix(comp_trend)
            if float(expected_end_mid) > float(cost_basis):
                return (
                    f"`{target}` has weighted ended trend `{expected_end_mid}` "
                    f"(observed `{observed}`) above held cost basis `{cost_basis}`{suffix}."
                )
            return (
                f"`{target}` has weighted ended trend `{expected_end_mid}` "
                f"(observed `{observed}`) still below or near held cost basis `{cost_basis}`{suffix}."
            )
        if recent_listing_count:
            return f"`{target}` has `{recent_listing_count}` recently refreshed active comparable listings for sell-side monitoring."
        return f"`{target}` has no fresh ended comps in the current lookback window."

    if kind == "watch_buy":
        expected_end_mid = comp_trend.get("weighted_median_end_price")
        budget_max = _to_float(row["budget_max"])
        if expected_end_mid is not None and budget_max is not None:
            observed = _range_label(comp_trend.get("observed_min_end_price"), comp_trend.get("observed_max_end_price"))
            suffix = _comp_summary_suffix(comp_trend)
            if expected_end_mid <= budget_max:
                return (
                    f"`{target}` has comp-trend estimate `{expected_end_mid}` "
                    f"(observed `{observed}`) within budget `{budget_max}`{suffix}."
                )
            return (
                f"`{target}` has comp-trend estimate `{expected_end_mid}` "
                f"(observed `{observed}`) above budget `{budget_max}`{suffix}."
            )
        if recent_groups:
            top = recent_groups[0]
            return (
                f"`{target}` has `{recent_listing_count}` refreshed matches; top opportunity is "
                f"`{top['title']}` as `{top['relationship_type']}` / `{top['status_norm']}`"
                + "."
            )
        if exact_count:
            return f"`{target}` still has `{exact_count}` active exact matches, but none refreshed inside the current lookback window."
        return f"`{target}` has no active buy-side opportunities right now."

    if kind == "collecting":
        if exact_count or variant_count:
            return (
                f"`{target}` currently has `{exact_count}` exact and `{variant_count}` variant matches; "
                f"`{recent_listing_count}` listings refreshed recently."
            )
        if series_count:
            return f"`{target}` currently only has broader series activity (`{series_count}` matches), with no exact family hits."
        return f"`{target}` has no current collecting opportunities."

    if kind == "discovery":
        if recent_groups:
            return f"`{target}` has `{series_count}` broader series matches and `{recent_listing_count}` recently refreshed candidates to review."
        return f"`{target}` has no fresh discovery candidates in the current lookback window."

    return f"`{target}` has `{recent_listing_count}` recently refreshed listings across `{sum(relationship_counts.values())}` active matches."


def _render_report(
    *,
    user: dict[str, Any],
    defaults: dict[str, Any] | None,
    lookback_hours: int,
    active_match_count: int,
    recent_activity_count: int,
    sections: list[dict[str, Any]],
) -> str:
    lines = [
        "# V2 Interest Daily Digest",
        "",
        f"- User: `{user['id']}` | `{user.get('display_name') or user['id']}`",
        f"- Language / timezone: `{user.get('language')}` / `{user.get('timezone')}`",
        f"- Lookback window: last `{lookback_hours}` hours",
        f"- Active interest count: `{len(sections)}`",
        f"- Active match count: `{active_match_count}`",
        f"- Recently refreshed matched listings: `{recent_activity_count}`",
    ]
    if defaults is not None:
        lines.extend(
            [
                f"- Default precision / delivery: `{defaults['default_precision_mode']}` / `{defaults['default_delivery_mode']}`",
                f"- Default min score / cooldown: `{defaults['default_min_match_score']}` / `{defaults['default_cooldown_hours']}h`",
            ]
        )
    lines.extend(["", "## Highlights", ""])
    for section in sections:
        lines.append(f"- **{section['interest']['interest_name']}**: {section['highlight']}")

    lines.extend(["", "## Interest Breakdown", ""])
    for section in sections:
        interest = section["interest"]
        target_label = _text(interest["target_label"]) or _text(interest["interest_name"]) or _text(interest["raw_input"]) or "-"
        lines.append(f"### {interest['interest_name']}")
        lines.append("")
        lines.append(
            f"- Kind / scope / precision: `{interest['interest_kind']}` / `{interest['scope_kind']}` / `{interest['precision_mode']}`"
        )
        lines.append(f"- Target: `{target_label}`")
        lines.append(f"- Condition mode: `{interest['condition_mode'] or 'ignore'}`")
        if interest["budget_max"] is not None:
            lines.append(f"- Budget max: `{interest['budget_max']}`")
        if interest["holding_raw_input"]:
            lines.append(
                f"- Holding: `{interest['holding_raw_input']}` | qty `{interest['holding_quantity']}` | cost basis `{interest['cost_basis_unit']}`"
            )
        lines.append(
            f"- Policy: delivery `{interest['delivery_mode']}` | min score `{interest['min_match_score']}` | cooldown `{interest['cooldown_hours']}h`"
        )
        if interest["notes"]:
            lines.append(f"- Notes: {interest['notes']}")
        lines.append(f"- Digest summary: {section['highlight']}")
        comp_trend = section["comp_trend"]
        if comp_trend.get("weighted_median_end_price") is not None:
            lines.append(
                f"- Comp trend: weighted `{comp_trend['weighted_median_end_price']}` | observed "
                f"`{_range_label(comp_trend['observed_min_end_price'], comp_trend['observed_max_end_price'])}` | "
                f"{_comp_summary_suffix(comp_trend)}"
            )
        lines.append("")

        rel_counts = section["relationship_counts"]
        if rel_counts:
            rel_text = ", ".join(f"`{key}`={value}" for key, value in sorted(rel_counts.items()))
        else:
            rel_text = "none"
        lines.append(f"Relationship mix: {rel_text}")
        lines.append("")

        lines.append("Recent activity in lookback window:")
        if section["recent_groups"]:
            for group in section["recent_groups"]:
                start_range = _range_label(group["min_start_price"], group["max_start_price"])
                suffix = f" | start `{start_range}`" if start_range else ""
                lines.append(
                    f"- `{group['relationship_type']}` | `{group['status_norm']}` | `{group['title']}` | "
                    f"`{group['listing_count']}` refreshed listings{suffix}"
                )
        else:
            lines.append("- none")
        lines.append("")

        lines.append("Representative recent listings:")
        if section["recent_examples"]:
            for match in section["recent_examples"]:
                condition = _text(match["character_name_raw"])
                condition_text = f" | condition `{condition}`" if condition else ""
                lines.append(
                    f"- `{match['source_listing_id']}` | `{match['relationship_type']}` | `{match['status_norm']}` | "
                    f"`{match['title']}` | {_price_text(match['price_initial'], match['price_end'])}{condition_text}"
                )
        else:
            lines.append("- none")
        lines.append("")

        lines.append("Top active opportunity groups:")
        if section["grouped_active"]:
            for group in section["grouped_active"]:
                start_range = _range_label(group["min_start_price"], group["max_start_price"])
                suffix = f" | start `{start_range}`" if start_range else ""
                lines.append(
                    f"- `{group['relationship_type']}` | `{group['status_norm']}` | `{group['title']}` | "
                    f"`{group['listing_count']}` listings | top score `{group['top_match_score']}`{suffix}"
                )
        else:
            lines.append("- none")
        lines.append("")

        lines.append("Recent ended comparable listings:")
        ended_comps = section["recent_ended_comps"] or section["ended_comps"]
        if ended_comps:
            for comp in ended_comps[:5]:
                lines.append(
                    f"- `{comp['source_listing_id']}` | `{comp['title']}` | ended `{comp['price_end']}` | "
                    f"`{comp['character_name_raw'] or '-'}` | `{comp['end_at'] or '-'} `"
                )
        else:
            lines.append("- none found in current normalized catalog")
        lines.extend(["", "---", ""])

    return "\n".join(lines).rstrip() + "\n"


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


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _range_label(min_value: Any, max_value: Any) -> str | None:
    if min_value is None and max_value is None:
        return None
    if min_value == max_value:
        return str(min_value)
    return f"{min_value}-{max_value}"


def _price_text(price_initial: Any, price_end: Any) -> str:
    if price_end not in (None, 0, 0.0):
        return f"start `{price_initial}` -> end `{price_end}`"
    return f"start `{price_initial}`"


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
