from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from ai_agent_v2.clients.zhaoonline import now_utc_iso
from ai_agent_v2.storage.sqlite_store import SqliteV2Store


@dataclass(frozen=True)
class MatchAuditResult:
    report_path: str
    active_match_count: int
    relationship_counts: dict[str, int]


def build_match_audit_report(db_path: str, output_dir: str) -> MatchAuditResult:
    SqliteV2Store(db_path).ensure_schema()
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        active_match_count = int(conn.execute("SELECT COUNT(*) FROM listing_matches_v2 WHERE status = 'active'").fetchone()[0])
        relationship_counts = {
            str(row["relationship_type"]): int(row["count"])
            for row in conn.execute(
                """
                SELECT relationship_type, COUNT(*) AS count
                FROM listing_matches_v2
                WHERE status = 'active'
                GROUP BY relationship_type
                ORDER BY relationship_type
                """
            ).fetchall()
        }
        top_items = conn.execute(
            """
            SELECT
              lm.user_id,
              COALESCE(t.target_label, ui.item_name, lm.user_item_id) AS subject_label,
              COUNT(*) AS count
            FROM listing_matches_v2 lm
            LEFT JOIN user_items ui ON ui.id = lm.user_item_id
            LEFT JOIN user_interest_targets_v2 t ON t.id = lm.user_item_id
            WHERE lm.status = 'active'
            GROUP BY lm.user_id, COALESCE(t.target_label, ui.item_name, lm.user_item_id)
            ORDER BY count DESC, lm.user_id, subject_label
            LIMIT 25
            """
        ).fetchall()
        samples = conn.execute(
            """
            SELECT
              lm.user_id,
              COALESCE(t.target_label, ui.item_name, lm.user_item_id) AS subject_label,
              n.title,
              lm.relationship_type,
              lm.match_score,
              lm.match_reasons_json
            FROM listing_matches_v2 lm
            LEFT JOIN user_items ui ON ui.id = lm.user_item_id
            LEFT JOIN user_interest_targets_v2 t ON t.id = lm.user_item_id
            JOIN market_listings_norm_v2 n ON n.id = lm.listing_id
            WHERE lm.status = 'active'
            ORDER BY lm.match_score DESC, lm.user_id, subject_label, n.title
            LIMIT 40
            """
        ).fetchall()

    timestamp = now_utc_iso().replace(":", "").replace("-", "").replace("+00:00", "Z")
    report_path = out_dir / f"v2_match_audit_{timestamp}.md"
    lines = [
        "# V2 Match Audit",
        "",
        f"- Active matches: `{active_match_count}`",
        f"- Relationship counts: `{json.dumps(relationship_counts, ensure_ascii=False, separators=(',', ':'))}`",
        "",
        "## Top User Items By Match Count",
        "",
    ]
    for row in top_items:
        lines.append(f"- `{row['user_id']}` | `{row['subject_label']}` | `{row['count']}`")
    lines.extend(["", "## Sample Matches", ""])
    for row in samples:
        reasons = json.loads(str(row["match_reasons_json"]))
        lines.append(
            f"- `{row['user_id']}` | `{row['subject_label']}` -> `{row['title']}` | "
            f"`{row['relationship_type']}` | score `{row['match_score']}` | reasons `{','.join(reasons)}`"
        )

    report_path.write_text("\n".join(lines), encoding="utf-8")
    return MatchAuditResult(
        report_path=str(report_path),
        active_match_count=active_match_count,
        relationship_counts=relationship_counts,
    )
