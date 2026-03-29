from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ai_agent_v2.clients.zhaoonline import now_utc_iso
from ai_agent_v2.storage.sqlite_store import SqliteV2Store


@dataclass(frozen=True)
class InterestReviewReportResult:
    report_path: str
    user_id: str
    interest_count: int
    active_match_count: int


def build_interest_review_report(db_path: str, output_dir: str, *, user_id: str) -> InterestReviewReportResult:
    SqliteV2Store(db_path).ensure_schema()
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

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
                   default_cooldown_hours, default_allow_series_matches, default_allow_variant_matches
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
              i.intent_confidence,
              i.allow_related_matches,
              i.allow_series_matches,
              i.allow_variant_matches,
              i.notes,
              t.id AS target_id,
              t.target_label,
              t.target_kind,
              t.parse_family,
              t.raw_input,
              t.normalized_name,
              t.issue_code_norm,
              t.series_key,
              t.theme_name,
              t.asset_type,
              t.variant_tokens_json,
              t.quantity_tokens_json,
              t.condition_tokens_json,
              t.condition_mode,
              t.year_value,
              t.budget_max,
              h.raw_input AS holding_raw_input,
              h.holding_quantity,
              h.cost_basis_total,
              h.cost_basis_unit,
              p.notify_on_preview,
              p.notify_on_live,
              p.notify_on_ended,
              p.notify_on_exact_match,
              p.notify_on_variant_match,
              p.notify_on_series_match,
              p.notify_on_price_opportunity,
              p.notify_on_sell_opportunity,
              p.min_match_score,
              p.cooldown_hours,
              p.delivery_mode,
              p.max_signals_per_day
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

        interest_sections = [
            _build_interest_section(conn, row)
            for row in interests
        ]

    timestamp = now_utc_iso().replace(":", "").replace("-", "").replace("+00:00", "Z")
    report_path = out_dir / f"v2_interest_review_{user_id}_{timestamp}.md"
    report_path.write_text(
        _render_report(
            user=dict(user_row),
            defaults=dict(defaults_row) if defaults_row is not None else None,
            interest_sections=interest_sections,
            active_match_count=active_match_count,
        ),
        encoding="utf-8",
    )
    return InterestReviewReportResult(
        report_path=str(report_path),
        user_id=user_id,
        interest_count=len(interests),
        active_match_count=active_match_count,
    )


def _build_interest_section(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    target_id = row["target_id"]
    active_relationship_counts: dict[str, int] = {}
    grouped_matches: list[dict[str, Any]] = []
    representative_matches: list[dict[str, Any]] = []
    if target_id:
        active_relationship_counts = {
            str(r["relationship_type"]): int(r["cnt"])
            for r in conn.execute(
                """
                SELECT relationship_type, COUNT(*) AS cnt
                FROM listing_matches_v2
                WHERE status = 'active' AND user_item_id = ?
                GROUP BY relationship_type
                ORDER BY relationship_type
                """,
                (target_id,),
            ).fetchall()
        }
        grouped_matches = [
            dict(r)
            for r in conn.execute(
                """
                SELECT
                  n.title,
                  lm.relationship_type,
                  n.status_norm,
                  COUNT(*) AS listing_count,
                  MIN(n.price_initial) AS min_start_price,
                  MAX(n.price_initial) AS max_start_price,
                  MIN(NULLIF(n.price_end, 0)) AS min_end_price,
                  MAX(NULLIF(n.price_end, 0)) AS max_end_price,
                  MAX(lm.match_score) AS top_match_score,
                  MAX(n.end_at) AS latest_end_at
                FROM listing_matches_v2 lm
                JOIN market_listings_norm_v2 n ON n.id = lm.listing_id
                WHERE lm.status = 'active' AND lm.user_item_id = ?
                GROUP BY n.title, lm.relationship_type, n.status_norm
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
                LIMIT 8
                """,
                (target_id,),
            ).fetchall()
        ]
        representative_matches = [
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
                  n.end_at,
                  lm.relationship_type,
                  lm.match_score
                FROM listing_matches_v2 lm
                JOIN market_listings_norm_v2 n ON n.id = lm.listing_id
                WHERE lm.status = 'active' AND lm.user_item_id = ?
                ORDER BY
                  CASE lm.relationship_type
                    WHEN 'exact_identity' THEN 1
                    WHEN 'variant_related' THEN 2
                    WHEN 'series_related' THEN 3
                    ELSE 4
                  END,
                  lm.match_score DESC,
                  n.updated_at DESC,
                  n.source_listing_id DESC
                LIMIT 5
                """,
                (target_id,),
            ).fetchall()
        ]

    ended_comps = _load_recent_ended_comps(conn, row)
    return {
        "interest": dict(row),
        "active_relationship_counts": active_relationship_counts,
        "grouped_matches": grouped_matches,
        "representative_matches": representative_matches,
        "ended_comps": ended_comps,
    }


def _load_recent_ended_comps(conn: sqlite3.Connection, row: sqlite3.Row) -> list[dict[str, Any]]:
    parse_family = _text(row["parse_family"])
    if not parse_family:
        return []
    if parse_family == "stamp_like":
        return _load_recent_ended_stamp_comps(conn, row)
    if parse_family == "coin_like":
        return _load_recent_ended_coin_comps(conn, row)
    return []


def _load_recent_ended_stamp_comps(conn: sqlite3.Connection, row: sqlite3.Row) -> list[dict[str, Any]]:
    issue_code = _text(row["issue_code_norm"])
    issue_name = _text(row["theme_name"]) or _text(row["normalized_name"])
    raw_input = _text(row["raw_input"]) or ""
    where_clauses = ["n.status_raw = '3'"]
    params: list[Any] = []
    if issue_code and issue_name:
        where_clauses.append("(p.issue_code_norm = ? OR p.issue_name = ?)")
        params.extend([issue_code, issue_name])
    elif issue_code:
        where_clauses.append("p.issue_code_norm = ?")
        params.append(issue_code)
    elif issue_name:
        where_clauses.append("p.issue_name = ?")
        params.append(issue_name)
    else:
        return []
    query = f"""
        SELECT
          n.source_listing_id,
          n.title,
          n.status_norm,
          n.price_initial,
          n.price_end,
          n.character_name_raw,
          n.end_at,
          p.issue_code_norm,
          p.issue_name
        FROM market_listings_norm_v2 n
        JOIN listing_parse_v2 p ON p.listing_id = n.id
        WHERE {' AND '.join(where_clauses)}
        ORDER BY n.end_at DESC, n.source_listing_id DESC
        LIMIT 5
    """
    rows = [dict(r) for r in conn.execute(query, params).fetchall()]
    if _is_exact_stamp_interest(row):
        return [r for r in rows if _text(r["title"]) == raw_input or _text(r["issue_code_norm"]) == issue_code][:5]
    return rows


def _load_recent_ended_coin_comps(conn: sqlite3.Connection, row: sqlite3.Row) -> list[dict[str, Any]]:
    theme_name = _text(row["theme_name"])
    asset_type = _text(row["asset_type"])
    series_key = _text(row["series_key"])
    year_value = row["year_value"]
    if not theme_name or not asset_type:
        return []

    where_clauses = ["n.status_raw = '3'", "p.theme_name = ?", "p.asset_type = ?"]
    params: list[Any] = [theme_name, asset_type]
    if _is_exact_coin_interest(row) and year_value is not None:
        where_clauses.append("p.year_value = ?")
        params.append(year_value)
    elif series_key:
        where_clauses.append("p.series_key = ?")
        params.append(series_key)

    query = f"""
        SELECT
          n.source_listing_id,
          n.title,
          n.status_norm,
          n.price_initial,
          n.price_end,
          n.character_name_raw,
          n.end_at,
          p.year_value,
          p.theme_name,
          p.asset_type
        FROM market_listings_norm_v2 n
        JOIN listing_parse_v2 p ON p.listing_id = n.id
        WHERE {' AND '.join(where_clauses)}
        ORDER BY n.end_at DESC, n.source_listing_id DESC
        LIMIT 5
    """
    return [dict(r) for r in conn.execute(query, params).fetchall()]


def _is_exact_stamp_interest(row: sqlite3.Row) -> bool:
    return _text(row["precision_mode"]) == "exact" or _text(row["scope_kind"]) == "exact_item"


def _is_exact_coin_interest(row: sqlite3.Row) -> bool:
    return _text(row["precision_mode"]) == "exact" or _text(row["scope_kind"]) == "exact_item"


def _render_report(*, user: dict[str, Any], defaults: dict[str, Any] | None, interest_sections: list[dict[str, Any]], active_match_count: int) -> str:
    lines = [
        "# V2 Interest Review",
        "",
        f"- User: `{user['id']}` | `{user.get('display_name') or user['id']}`",
        f"- Language / timezone: `{user.get('language')}` / `{user.get('timezone')}`",
        f"- Active interest count: `{len(interest_sections)}`",
        f"- Active match count: `{active_match_count}`",
    ]
    if defaults is not None:
        lines.extend(
            [
                f"- Default precision / delivery: `{defaults['default_precision_mode']}` / `{defaults['default_delivery_mode']}`",
                f"- Default min score / cooldown: `{defaults['default_min_match_score']}` / `{defaults['default_cooldown_hours']}h`",
            ]
        )
    lines.extend(["", "## Interest Summary", ""])

    for section in interest_sections:
        interest = section["interest"]
        target_label = _text(interest["target_label"]) or _text(interest["interest_name"]) or _text(interest["raw_input"]) or "-"
        lines.append(f"### {interest['interest_name']}")
        lines.append("")
        lines.append(
            f"- Kind / scope / precision: `{interest['interest_kind']}` / `{interest['scope_kind']}` / `{interest['precision_mode']}`"
        )
        lines.append(f"- Condition mode: `{interest['condition_mode'] or 'ignore'}`")
        lines.append(f"- Target: `{target_label}`")
        if _text(interest["raw_input"]) and _text(interest["raw_input"]) != target_label:
            lines.append(f"- Raw input: `{interest['raw_input']}`")
        if interest["budget_max"] is not None:
            lines.append(f"- Budget max: `{interest['budget_max']}`")
        if interest["holding_raw_input"]:
            lines.append(
                f"- Holding: `{interest['holding_raw_input']}` | qty `{interest['holding_quantity']}` | cost basis `{interest['cost_basis_unit']}`"
            )
        lines.append(
            f"- Policy: delivery `{interest['delivery_mode']}` | min score `{interest['min_match_score']}` | cooldown `{interest['cooldown_hours']}h`"
        )
        lines.append(
            f"- Match permissions: variant `{_bool_label(interest['allow_variant_matches'])}` | series `{_bool_label(interest['allow_series_matches'])}`"
        )
        if interest["notes"]:
            lines.append(f"- Notes: {interest['notes']}")

        rel_counts = section["active_relationship_counts"]
        rel_counts_text = json.dumps(rel_counts, ensure_ascii=False, separators=(",", ":")) if rel_counts else "{}"
        lines.append(f"- Active relationship counts: `{rel_counts_text}`")
        lines.append("")

        lines.append("Active grouped opportunities:")
        if section["grouped_matches"]:
            for group in section["grouped_matches"]:
                start_range = _range_label(group["min_start_price"], group["max_start_price"])
                end_range = _range_label(group["min_end_price"], group["max_end_price"])
                extras = []
                if start_range:
                    extras.append(f"start {start_range}")
                if end_range:
                    extras.append(f"ended {end_range}")
                extras_text = f" | {' | '.join(extras)}" if extras else ""
                lines.append(
                    f"- `{group['relationship_type']}` | `{group['status_norm']}` | `{group['title']}` | "
                    f"`{group['listing_count']}` listings | top score `{group['top_match_score']}`{extras_text}"
                )
        else:
            lines.append("- none")
        lines.append("")

        lines.append("Representative active matches:")
        if section["representative_matches"]:
            for match in section["representative_matches"]:
                price_text = _price_text(match["price_initial"], match["price_end"])
                condition = _text(match["character_name_raw"])
                condition_text = f" | condition `{condition}`" if condition else ""
                lines.append(
                    f"- `{match['source_listing_id']}` | `{match['relationship_type']}` | `{match['status_norm']}` | "
                    f"`{match['title']}` | {price_text}{condition_text}"
                )
        else:
            lines.append("- none")
        lines.append("")

        lines.append("Recent ended comparable listings:")
        if section["ended_comps"]:
            for comp in section["ended_comps"]:
                lines.append(
                    f"- `{comp['source_listing_id']}` | `{comp['title']}` | ended `{comp['price_end']}` | "
                    f"`{comp['character_name_raw'] or '-'}` | `{comp['end_at'] or '-'} `"
                )
        else:
            lines.append("- none found in current normalized catalog")
        lines.extend(["", "---", ""])

    return "\n".join(lines).rstrip() + "\n"


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _bool_label(value: Any) -> str:
    return "yes" if int(value or 0) else "no"


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
