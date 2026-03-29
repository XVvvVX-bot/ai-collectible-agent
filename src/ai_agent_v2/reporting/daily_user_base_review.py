from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ai_agent_v2.clients.zhaoonline import now_utc_iso
from ai_agent_v2.reporting.signal_review import EVENT_SIGNAL_TYPES
from ai_agent_v2.storage.sqlite_store import SqliteV2Store


@dataclass(frozen=True)
class DailyUserBaseReviewReportResult:
    report_path: str
    user_count: int
    total_active_matches: int
    total_active_signals: int


def build_daily_user_base_review_report(
    db_path: str,
    output_dir: str,
    *,
    lookback_hours: int = 24,
) -> DailyUserBaseReviewReportResult:
    SqliteV2Store(db_path).ensure_schema()
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    since_iso = (datetime.now(timezone.utc) - timedelta(hours=lookback_hours)).isoformat()

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        user_rows = conn.execute(
            """
            SELECT DISTINCT u.id, u.display_name, u.language, u.timezone
            FROM users u
            JOIN user_interests_v2 i ON i.user_id = u.id
            WHERE i.active_status = 'active'
            ORDER BY u.id
            """
        ).fetchall()
        user_sections = [_build_user_section(conn, row, since_iso=since_iso) for row in user_rows]

    timestamp = now_utc_iso().replace(":", "").replace("-", "").replace("+00:00", "Z")
    report_path = out_dir / f"v2_daily_user_base_review_{timestamp}.md"
    report_path.write_text(
        _render_report(user_sections, lookback_hours=lookback_hours),
        encoding="utf-8",
    )
    return DailyUserBaseReviewReportResult(
        report_path=str(report_path),
        user_count=len(user_sections),
        total_active_matches=sum(section["active_match_count"] for section in user_sections),
        total_active_signals=sum(section["active_signal_count"] for section in user_sections),
    )


def _build_user_section(conn: sqlite3.Connection, user_row: sqlite3.Row, *, since_iso: str) -> dict[str, Any]:
    user_id = str(user_row["id"])
    interest_count = int(
        conn.execute(
            "SELECT COUNT(*) FROM user_interests_v2 WHERE user_id = ? AND active_status = 'active'",
            (user_id,),
        ).fetchone()[0]
    )
    active_match_count = int(
        conn.execute(
            "SELECT COUNT(*) FROM listing_matches_v2 WHERE user_id = ? AND status = 'active'",
            (user_id,),
        ).fetchone()[0]
    )
    recent_matched_listing_count = int(
        conn.execute(
            """
            SELECT COUNT(*)
            FROM listing_matches_v2 lm
            JOIN market_listings_norm_v2 n ON n.id = lm.listing_id
            WHERE lm.user_id = ? AND lm.status = 'active' AND n.updated_at >= ?
            """,
            (user_id, since_iso),
        ).fetchone()[0]
    )
    active_signals = conn.execute(
        """
        SELECT
          s.signal_type,
          s.urgency,
          s.signal_title,
          s.signal_summary,
          s.last_seen_at,
          i.interest_name
        FROM signals_v2 s
        JOIN user_interests_v2 i ON i.id = s.interest_id
        WHERE s.user_id = ? AND s.status = 'active' AND s.last_seen_at >= ?
        ORDER BY
          CASE s.urgency WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
          s.last_seen_at DESC,
          i.interest_name,
          s.signal_type
        """,
        (user_id, since_iso),
    ).fetchall()
    event_signal_count = sum(1 for row in active_signals if str(row["signal_type"]) in EVENT_SIGNAL_TYPES)
    standing_signal_count = len(active_signals) - event_signal_count
    top_signals = list(active_signals[:3])
    interest_mix = conn.execute(
        """
        SELECT i.interest_name, i.interest_kind, COUNT(s.id) AS signal_count
        FROM user_interests_v2 i
        LEFT JOIN signals_v2 s
          ON s.interest_id = i.id
         AND s.status = 'active'
         AND s.last_seen_at >= ?
        WHERE i.user_id = ? AND i.active_status = 'active'
        GROUP BY i.id, i.interest_name, i.interest_kind
        ORDER BY signal_count DESC, i.interest_name
        """,
        (since_iso, user_id),
    ).fetchall()

    return {
        "user": dict(user_row),
        "interest_count": interest_count,
        "active_match_count": active_match_count,
        "recent_matched_listing_count": recent_matched_listing_count,
        "active_signal_count": len(active_signals),
        "event_signal_count": event_signal_count,
        "standing_signal_count": standing_signal_count,
        "top_signals": top_signals,
        "interest_mix": interest_mix,
    }


def _render_report(user_sections: list[dict[str, Any]], *, lookback_hours: int) -> str:
    total_matches = sum(section["active_match_count"] for section in user_sections)
    total_signals = sum(section["active_signal_count"] for section in user_sections)
    total_events = sum(section["event_signal_count"] for section in user_sections)
    total_standing = sum(section["standing_signal_count"] for section in user_sections)
    total_recent_refreshes = sum(section["recent_matched_listing_count"] for section in user_sections)

    lines = [
        "# V2 Daily User-Base Review",
        "",
        f"- Lookback window: last `{lookback_hours}` hours",
        f"- Active V2 users: `{len(user_sections)}`",
        f"- Active matches: `{total_matches}`",
        f"- Active signals in window: `{total_signals}`",
        f"- Event-driven signals: `{total_events}`",
        f"- Standing signals: `{total_standing}`",
        f"- Recently refreshed matched listings: `{total_recent_refreshes}`",
        "",
        "## User Summary",
        "",
    ]
    if not user_sections:
        lines.append("No active V2 users found.")
        return "\n".join(lines).rstrip() + "\n"

    for section in user_sections:
        user = section["user"]
        lines.append(
            f"- `{user['id']}` | `{user.get('display_name') or user['id']}` | "
            f"`{section['interest_count']}` interests | `{section['active_match_count']}` active matches | "
            f"`{section['active_signal_count']}` active signals"
        )

    lines.extend(["", "## User Breakdown", ""])
    for section in user_sections:
        user = section["user"]
        lines.append(f"### {user.get('display_name') or user['id']}")
        lines.append("")
        lines.append(f"- User id: `{user['id']}`")
        lines.append(f"- Language / timezone: `{user.get('language')}` / `{user.get('timezone')}`")
        lines.append(f"- Active interests: `{section['interest_count']}`")
        lines.append(f"- Active matches: `{section['active_match_count']}`")
        lines.append(f"- Recently refreshed matched listings: `{section['recent_matched_listing_count']}`")
        lines.append(
            f"- Active signals: `{section['active_signal_count']}` "
            f"(`{section['event_signal_count']}` event-driven, `{section['standing_signal_count']}` standing)"
        )
        lines.append("")
        lines.append("Interest mix:")
        if section["interest_mix"]:
            for row in section["interest_mix"]:
                lines.append(
                    f"- `{row['interest_name']}` | `{row['interest_kind']}` | `{row['signal_count']}` active signals"
                )
        else:
            lines.append("- none")
        lines.append("")
        lines.append("Top current signals:")
        if section["top_signals"]:
            for row in section["top_signals"]:
                lines.append(
                    f"- `{row['urgency']}` | `{row['interest_name']}` | `{row['signal_type']}` | "
                    f"{row['signal_title']} | {row['signal_summary']} | last seen `{row['last_seen_at']}`"
                )
        else:
            lines.append("- none")
        lines.extend(["", "---", ""])

    return "\n".join(lines).rstrip() + "\n"
