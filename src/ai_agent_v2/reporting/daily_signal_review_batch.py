from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ai_agent_v2.reporting.signal_review import build_signal_review_report
from ai_agent_v2.storage.sqlite_store import SqliteV2Store


@dataclass(frozen=True)
class DailySignalReviewBatchResult:
    index_report_path: str
    user_count: int
    total_signal_count: int
    user_report_paths: list[str]


def build_daily_signal_review_batch(
    db_path: str,
    output_dir: str,
    *,
    lookback_hours: int = 24,
    now_utc: datetime | None = None,
) -> DailySignalReviewBatchResult:
    SqliteV2Store(db_path).ensure_schema()
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    current_utc = now_utc or datetime.now(timezone.utc)

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
        build_signal_review_report(
            db_path,
            output_dir,
            user_id=str(row["id"]),
            lookback_hours=lookback_hours,
            now_utc=current_utc,
        )
        for row in user_rows
    ]
    timestamp = current_utc.replace(microsecond=0).isoformat().replace(":", "").replace("-", "").replace("+00:00", "Z")
    index_path = out_dir / f"v2_daily_signal_review_index_{timestamp}.md"
    index_path.write_text(
        _render_index(user_rows, per_user, lookback_hours=lookback_hours),
        encoding="utf-8",
    )
    return DailySignalReviewBatchResult(
        index_report_path=str(index_path),
        user_count=len(per_user),
        total_signal_count=sum(item.signal_count for item in per_user),
        user_report_paths=[item.report_path for item in per_user],
    )


def _render_index(
    user_rows: list[sqlite3.Row],
    per_user: list,
    *,
    lookback_hours: int,
) -> str:
    lines = [
        "# V2 Daily Signal Review Index",
        "",
        f"- Lookback window: last `{lookback_hours}` hours",
        f"- Active V2 users reviewed: `{len(per_user)}`",
        f"- Total active signals across reports: `{sum(item.signal_count for item in per_user)}`",
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
            f"`{item.signal_count}` active signals | `{item.report_path}`"
        )
    return "\n".join(lines).rstrip() + "\n"
