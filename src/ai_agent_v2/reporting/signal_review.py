from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ai_agent_v2.storage.sqlite_store import SqliteV2Store

EVENT_SIGNAL_TYPES = {
    "buy_went_live",
    "buy_new_preview",
    "collection_went_live",
    "sell_new_ended_comp",
}


@dataclass(frozen=True)
class SignalReviewReportResult:
    report_path: str
    user_id: str
    signal_count: int


def build_signal_review_report(
    db_path: str,
    output_dir: str,
    *,
    user_id: str,
    lookback_hours: int = 24,
    now_utc: datetime | None = None,
) -> SignalReviewReportResult:
    SqliteV2Store(db_path).ensure_schema()
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    current_utc = now_utc or datetime.now(timezone.utc)
    since_iso = (current_utc - timedelta(hours=lookback_hours)).isoformat()

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        user_row = conn.execute(
            "SELECT id, display_name, language, timezone FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if user_row is None:
            raise ValueError(f"user not found: {user_id}")
        signal_rows = conn.execute(
            """
            WITH ranked AS (
              SELECT
                s.id, s.listing_id, s.signal_type, s.urgency, s.reason_code,
                s.signal_title, s.signal_summary, s.group_key,
                s.created_at, s.last_seen_at,
                i.interest_name,
                CASE
                  WHEN s.listing_id IS NULL THEN 1
                  ELSE ROW_NUMBER() OVER (
                    PARTITION BY s.listing_id, s.signal_type
                    ORDER BY
                      CASE s.urgency WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
                      s.created_at,
                      s.id
                  )
                END AS rn
              FROM signals_v2 s
              JOIN user_interests_v2 i ON i.id = s.interest_id
              WHERE s.user_id = ? AND s.status = 'active' AND s.last_seen_at >= ?
            )
            SELECT signal_type, urgency, reason_code, signal_title, signal_summary,
                   group_key, created_at, last_seen_at, interest_name, listing_id
            FROM ranked
            WHERE rn = 1
            ORDER BY
              CASE urgency WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
              last_seen_at DESC,
              interest_name,
              signal_type
            """,
            (user_id, since_iso),
        ).fetchall()
        dup_rows = conn.execute(
            """
            SELECT s.listing_id, s.signal_type,
                   GROUP_CONCAT(i.interest_name, '||') AS interest_names
            FROM signals_v2 s
            JOIN user_interests_v2 i ON i.id = s.interest_id
            WHERE s.user_id = ? AND s.status = 'active' AND s.last_seen_at >= ?
              AND s.listing_id IS NOT NULL
            GROUP BY s.listing_id, s.signal_type
            HAVING COUNT(*) > 1
            """,
            (user_id, since_iso),
        ).fetchall()
        dup_map: dict[tuple[str, str], list[str]] = {}
        for r in dup_rows:
            names_raw = str(r["interest_names"] or "")
            names = [n for n in names_raw.split("||") if n]
            dup_map[(str(r["listing_id"]), str(r["signal_type"]))] = names

    timestamp = current_utc.replace(microsecond=0).isoformat().replace(":", "").replace("-", "").replace("+00:00", "Z")
    report_path = out_dir / f"v2_signal_review_{user_id}_{timestamp}.md"
    report_path.write_text(
        _render_report(dict(user_row), signal_rows, lookback_hours=lookback_hours, dup_map=dup_map),
        encoding="utf-8",
    )
    return SignalReviewReportResult(report_path=str(report_path), user_id=user_id, signal_count=len(signal_rows))


def _render_report(
    user: dict[str, str],
    signal_rows: list[sqlite3.Row],
    *,
    lookback_hours: int,
    dup_map: dict[tuple[str, str], list[str]] | None = None,
) -> str:
    event_rows = [row for row in signal_rows if str(row["signal_type"]) in EVENT_SIGNAL_TYPES]
    standing_rows = [row for row in signal_rows if str(row["signal_type"]) not in EVENT_SIGNAL_TYPES]
    lines = [
        "# V2 Signal Review",
        "",
        f"- User: `{user['id']}` | `{user.get('display_name') or user['id']}`",
        f"- Language / timezone: `{user.get('language')}` / `{user.get('timezone')}`",
        f"- Lookback window: last `{lookback_hours}` hours",
        f"- Active signals in window: `{len(signal_rows)}`",
        f"- Event-driven signals: `{len(event_rows)}`",
        f"- Standing signals: `{len(standing_rows)}`",
        "",
    ]
    if not signal_rows:
        lines.append("No active signals in the current review window.")
        return "\n".join(lines).rstrip() + "\n"

    lines.extend(_render_signal_section("New Event Signals", event_rows, dup_map=dup_map or {}))
    lines.extend(_render_signal_section("Standing Signals", standing_rows, dup_map=dup_map or {}))
    return "\n".join(lines).rstrip() + "\n"


def _render_signal_section(
    title: str,
    signal_rows: list[sqlite3.Row],
    *,
    dup_map: dict[tuple[str, str], list[str]],
) -> list[str]:
    lines = [f"## {title}", ""]
    if not signal_rows:
        lines.append("- none")
        lines.extend(["", ""])
        return lines

    current_interest = None
    for row in signal_rows:
        if row["interest_name"] != current_interest:
            current_interest = row["interest_name"]
            if lines[-1] != "":
                lines.append("")
            lines.append(f"### {current_interest}")
            lines.append("")
        lines.append(
            f"- `{row['urgency']}` | `{row['signal_type']}` | {row['signal_title']} | "
            f"{row['signal_summary']} | first seen `{row['created_at']}` | last seen `{row['last_seen_at']}`"
        )
        listing_id = row["listing_id"] if "listing_id" in row.keys() else None
        if listing_id is not None:
            others = [
                name
                for name in dup_map.get((str(listing_id), str(row["signal_type"])), [])
                if name != row["interest_name"]
            ]
            if others:
                shown = others[:3]
                extra = len(others) - len(shown)
                names = ", ".join(f"\"{n}\"" for n in shown)
                if extra > 0:
                    names += f" and {extra} more"
                lines.append(f"  - _also from {names}_")
    lines.extend(["", ""])
    return lines
