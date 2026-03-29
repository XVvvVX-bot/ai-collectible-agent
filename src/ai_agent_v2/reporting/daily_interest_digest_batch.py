from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from ai_agent_v2.clients.zhaoonline import now_utc_iso
from ai_agent_v2.reporting.interest_digest import build_interest_digest_report
from ai_agent_v2.storage.sqlite_store import SqliteV2Store


@dataclass(frozen=True)
class DailyInterestDigestBatchResult:
    index_report_path: str
    user_count: int
    total_active_matches: int
    total_recent_activity_count: int
    user_report_paths: list[str]


def build_daily_interest_digest_batch(
    db_path: str,
    output_dir: str,
    *,
    lookback_hours: int = 24,
) -> DailyInterestDigestBatchResult:
    SqliteV2Store(db_path).ensure_schema()
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

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

    per_user = [
        build_interest_digest_report(
            db_path,
            output_dir,
            user_id=str(row["id"]),
            lookback_hours=lookback_hours,
        )
        for row in user_rows
    ]
    timestamp = now_utc_iso().replace(":", "").replace("-", "").replace("+00:00", "Z")
    index_path = out_dir / f"v2_daily_interest_digest_index_{timestamp}.md"
    index_path.write_text(
        _render_index(user_rows, per_user, lookback_hours=lookback_hours),
        encoding="utf-8",
    )
    return DailyInterestDigestBatchResult(
        index_report_path=str(index_path),
        user_count=len(per_user),
        total_active_matches=sum(item.active_match_count for item in per_user),
        total_recent_activity_count=sum(item.recent_activity_count for item in per_user),
        user_report_paths=[item.report_path for item in per_user],
    )


def _render_index(
    user_rows: list[sqlite3.Row],
    per_user: list,
    *,
    lookback_hours: int,
) -> str:
    lines = [
        "# V2 Daily Interest Digest Index",
        "",
        f"- Lookback window: last `{lookback_hours}` hours",
        f"- Active V2 users reviewed: `{len(per_user)}`",
        f"- Total active matches across reports: `{sum(item.active_match_count for item in per_user)}`",
        f"- Total recently refreshed matched listings: `{sum(item.recent_activity_count for item in per_user)}`",
        "",
        "## Reports",
        "",
    ]
    if not per_user:
        lines.append("No active V2 users found.")
        return "\n".join(lines).rstrip() + "\n"

    user_map = {str(row["id"]): row for row in user_rows}
    for item in per_user:
        user_row = user_map[item.user_id]
        lines.append(
            f"- `{item.user_id}` | `{user_row['display_name'] or item.user_id}` | "
            f"`{item.interest_count}` interests | `{item.active_match_count}` active matches | "
            f"`{item.recent_activity_count}` recently refreshed matched listings | `{item.report_path}`"
        )
    return "\n".join(lines).rstrip() + "\n"
