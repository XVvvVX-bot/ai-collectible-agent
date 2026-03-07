from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from ai_agent.clients.zhaoonline import now_utc_iso
from ai_agent.ingestion.raw_ingest import SOURCE_PLATFORM
from ai_agent.storage.sqlite_raw_store import SqliteRawStore

SEVERITY_PASS = "pass"
SEVERITY_WARNING = "warning"
SEVERITY_FAIL = "fail"
VALID_STATUS_NORM = {"preview", "live", "ended", "unknown"}


@dataclass(frozen=True)
class NormQualityResult:
    run_id: str
    source_platform: str
    since_last_run: bool
    rowid_start: int
    rowid_end: int
    rows_evaluated: int
    pass_count: int
    warning_count: int
    fail_count: int
    issue_counts: dict[str, int]
    sample_listing_ids: dict[str, list[str]]


def run_norm_quality_checks(
    db_path: str,
    batch_size: int = 2000,
    since_last_run: bool = True,
) -> NormQualityResult:
    if batch_size < 1:
        raise ValueError("batch_size must be >= 1.")

    store = SqliteRawStore(db_path)
    store.ensure_schema()
    db_file = Path(db_path)
    started_at = now_utc_iso()
    run_id = str(uuid.uuid4())

    with sqlite3.connect(db_file) as conn:
        conn.row_factory = sqlite3.Row
        rowid_start = _get_state_rowid(conn, SOURCE_PLATFORM) if since_last_run else 0
        rows = conn.execute(
            """
            SELECT
              rowid,
              source_listing_id,
              title,
              category_raw,
              category_norm,
              series_raw,
              series_norm,
              status_norm,
              start_at,
              end_at,
              preview_at,
              price_initial,
              price_current,
              price_end,
              is_active
            FROM market_listings_norm
            WHERE source_platform = ?
              AND rowid > ?
            ORDER BY rowid
            LIMIT ?
            """,
            (SOURCE_PLATFORM, rowid_start, batch_size),
        ).fetchall()

        issue_counts: dict[str, int] = {}
        sample_listing_ids: dict[str, list[str]] = {}
        pass_count = 0
        warning_count = 0
        fail_count = 0
        rowid_end = rowid_start

        for row in rows:
            listing_id = str(row["source_listing_id"])
            rowid_end = max(rowid_end, int(row["rowid"]))
            issues = _evaluate_row(row)
            if not issues:
                pass_count += 1
                continue

            has_fail = False
            has_warning = False
            for issue_code, severity in issues:
                issue_counts[issue_code] = issue_counts.get(issue_code, 0) + 1
                bucket = sample_listing_ids.setdefault(issue_code, [])
                if len(bucket) < 5 and listing_id not in bucket:
                    bucket.append(listing_id)
                if severity == SEVERITY_FAIL:
                    has_fail = True
                elif severity == SEVERITY_WARNING:
                    has_warning = True

            if has_fail:
                fail_count += 1
            elif has_warning:
                warning_count += 1
            else:
                pass_count += 1

        rows_evaluated = len(rows)
        if since_last_run and rows_evaluated > 0:
            _set_state_rowid(conn, SOURCE_PLATFORM, rowid_end)

        finished_at = now_utc_iso()
        conn.execute(
            """
            INSERT INTO quality_check_runs (
              id,
              source_platform,
              started_at,
              finished_at,
              since_last_run,
              rowid_start,
              rowid_end,
              rows_evaluated,
              pass_count,
              warning_count,
              fail_count,
              issue_counts_json,
              sample_listing_ids_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                SOURCE_PLATFORM,
                started_at,
                finished_at,
                1 if since_last_run else 0,
                rowid_start,
                rowid_end,
                rows_evaluated,
                pass_count,
                warning_count,
                fail_count,
                json.dumps(issue_counts, ensure_ascii=False, separators=(",", ":")),
                json.dumps(sample_listing_ids, ensure_ascii=False, separators=(",", ":")),
            ),
        )
        conn.commit()

    return NormQualityResult(
        run_id=run_id,
        source_platform=SOURCE_PLATFORM,
        since_last_run=since_last_run,
        rowid_start=rowid_start,
        rowid_end=rowid_end,
        rows_evaluated=rows_evaluated,
        pass_count=pass_count,
        warning_count=warning_count,
        fail_count=fail_count,
        issue_counts=issue_counts,
        sample_listing_ids=sample_listing_ids,
    )


def _evaluate_row(row: sqlite3.Row) -> list[tuple[str, str]]:
    issues: list[tuple[str, str]] = []
    title = _to_text(row["title"])
    source_listing_id = _to_text(row["source_listing_id"])
    status_norm = _to_text(row["status_norm"])
    start_at = _to_text(row["start_at"])
    end_at = _to_text(row["end_at"])
    preview_at = _to_text(row["preview_at"])
    category_raw = _to_text(row["category_raw"])
    category_norm = _to_text(row["category_norm"])
    series_raw = _to_text(row["series_raw"])
    series_norm = _to_text(row["series_norm"])
    is_active = int(row["is_active"]) if row["is_active"] is not None else 0

    if not source_listing_id:
        issues.append(("missing_source_listing_id", SEVERITY_FAIL))
    if not title:
        issues.append(("missing_title", SEVERITY_FAIL))
    if not status_norm:
        issues.append(("missing_status_norm", SEVERITY_FAIL))
    elif status_norm not in VALID_STATUS_NORM:
        issues.append(("invalid_status_norm", SEVERITY_WARNING))

    start_dt = _parse_iso(start_at, "invalid_start_at", issues)
    end_dt = _parse_iso(end_at, "invalid_end_at", issues)
    _parse_iso(preview_at, "invalid_preview_at", issues)
    if start_dt is not None and end_dt is not None and start_dt > end_dt:
        issues.append(("start_after_end", SEVERITY_FAIL))

    price_initial = _to_float(row["price_initial"])
    price_current = _to_float(row["price_current"])
    price_end = _to_float(row["price_end"])
    _check_non_negative("price_initial_negative", price_initial, issues)
    _check_non_negative("price_current_negative", price_current, issues)
    _check_non_negative("price_end_negative", price_end, issues)

    if price_end is not None and price_current is not None and price_current != price_end:
        issues.append(("price_current_not_equal_end", SEVERITY_WARNING))
    if price_end is None and price_initial is not None and price_current is not None:
        if price_current != price_initial:
            issues.append(("price_current_not_equal_initial", SEVERITY_WARNING))

    expected_active = 1 if status_norm in {"preview", "live"} else 0
    if status_norm:
        if is_active != expected_active:
            issues.append(("is_active_mismatch_status", SEVERITY_FAIL))

    if category_raw and not category_norm:
        issues.append(("unmapped_category", SEVERITY_WARNING))
    if series_raw and not series_norm:
        issues.append(("unmapped_series", SEVERITY_WARNING))

    return issues


def _parse_iso(value: str | None, issue_code: str, issues: list[tuple[str, str]]) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        issues.append((issue_code, SEVERITY_FAIL))
        return None


def _check_non_negative(issue_code: str, value: float | None, issues: list[tuple[str, str]]) -> None:
    if value is not None and value < 0:
        issues.append((issue_code, SEVERITY_FAIL))


def _to_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _get_state_rowid(conn: sqlite3.Connection, source_platform: str) -> int:
    row = conn.execute(
        """
        SELECT last_norm_rowid
        FROM quality_check_state
        WHERE source_platform = ?
        """,
        (source_platform,),
    ).fetchone()
    if row is None:
        conn.execute(
            """
            INSERT INTO quality_check_state (source_platform, last_norm_rowid, updated_at)
            VALUES (?, 0, datetime('now'))
            """,
            (source_platform,),
        )
        return 0
    return int(row[0])


def _set_state_rowid(conn: sqlite3.Connection, source_platform: str, rowid_value: int) -> None:
    conn.execute(
        """
        UPDATE quality_check_state
        SET last_norm_rowid = ?, updated_at = datetime('now')
        WHERE source_platform = ?
        """,
        (int(rowid_value), source_platform),
    )

