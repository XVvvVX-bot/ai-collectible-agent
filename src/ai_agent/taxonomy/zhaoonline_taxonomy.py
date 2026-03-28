from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path

from ai_agent.ingestion.raw_ingest import SOURCE_PLATFORM
from ai_agent.storage.sqlite_raw_store import SqliteRawStore


FIELD_TO_RAW_COLUMN = {
    "category": "category_raw",
    "series": "series_raw",
    "status": "status_raw",
    "auction_type": "auction_type_raw",
    "grade": "grade_raw",
}

STATUS_DEFAULTS = {
    "1": "preview",
    "2": "live",
    "3": "ended",
}

AUCTION_TYPE_DEFAULTS = {
    "1": "auction",
}


@dataclass(frozen=True)
class TaxonomyCandidate:
    field_name: str
    raw_value: str
    norm_value: str
    observed_count: int
    source: str = "provisional"


def build_provisional_candidates(
    db_path: str,
    top_n_per_field: int = 100,
    fields: tuple[str, ...] = ("category", "series", "status", "auction_type", "grade"),
) -> list[TaxonomyCandidate]:
    _ensure_schema(db_path)
    with sqlite3.connect(Path(db_path)) as conn:
        candidates: list[TaxonomyCandidate] = []
        for field_name in fields:
            if field_name not in FIELD_TO_RAW_COLUMN:
                raise ValueError(f"Unsupported taxonomy field: {field_name}")
            rows = _query_unmapped_values(
                conn=conn,
                source_platform=SOURCE_PLATFORM,
                field_name=field_name,
                limit=top_n_per_field,
            )
            for raw_value, observed_count in rows:
                candidates.append(
                    TaxonomyCandidate(
                        field_name=field_name,
                        raw_value=raw_value,
                        norm_value=_provisional_norm_value(field_name, raw_value),
                        observed_count=int(observed_count),
                    )
                )
    return candidates


def apply_taxonomy_candidates(db_path: str, candidates: list[TaxonomyCandidate]) -> int:
    if not candidates:
        return 0
    _ensure_schema(db_path)
    with sqlite3.connect(Path(db_path)) as conn:
        before = conn.total_changes
        for item in candidates:
            conn.execute(
                """
                INSERT INTO market_taxonomy_map (
                  id, source_platform, field_name, raw_value, norm_value, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                ON CONFLICT(source_platform, field_name, raw_value)
                DO UPDATE SET
                  norm_value = excluded.norm_value,
                  updated_at = excluded.updated_at
                """,
                (
                    str(uuid.uuid4()),
                    SOURCE_PLATFORM,
                    item.field_name,
                    item.raw_value,
                    item.norm_value,
                ),
            )
        conn.commit()
        return conn.total_changes - before


def get_unmapped_report(
    db_path: str,
    top_n_per_field: int = 20,
    sample_size: int = 3,
    fields: tuple[str, ...] = ("category", "series", "status", "auction_type", "grade"),
) -> dict[str, list[dict[str, object]]]:
    _ensure_schema(db_path)
    with sqlite3.connect(Path(db_path)) as conn:
        report: dict[str, list[dict[str, object]]] = {}
        for field_name in fields:
            rows = _query_unmapped_values(
                conn=conn,
                source_platform=SOURCE_PLATFORM,
                field_name=field_name,
                limit=top_n_per_field,
            )
            items: list[dict[str, object]] = []
            for raw_value, observed_count in rows:
                items.append(
                    {
                        "raw_value": raw_value,
                        "observed_count": int(observed_count),
                        "sample_listing_ids": _sample_listing_ids(
                            conn=conn,
                            field_name=field_name,
                            raw_value=raw_value,
                            limit=sample_size,
                        ),
                    }
                )
            report[field_name] = items
    return report


def _query_unmapped_values(
    conn: sqlite3.Connection,
    source_platform: str,
    field_name: str,
    limit: int,
) -> list[tuple[str, int]]:
    raw_column = FIELD_TO_RAW_COLUMN[field_name]
    sql = f"""
    WITH observed AS (
      SELECT {raw_column} AS raw_value, COUNT(*) AS observed_count
      FROM market_listings_norm
      WHERE source_platform = ?
        AND {raw_column} IS NOT NULL
        AND {raw_column} <> ''
      GROUP BY {raw_column}
    )
    SELECT observed.raw_value, observed.observed_count
    FROM observed
    LEFT JOIN market_taxonomy_map map
      ON map.source_platform = ?
     AND map.field_name = ?
     AND map.raw_value = observed.raw_value
    WHERE map.id IS NULL
    ORDER BY observed.observed_count DESC, observed.raw_value ASC
    LIMIT ?
    """
    return conn.execute(sql, (source_platform, source_platform, field_name, int(limit))).fetchall()


def _sample_listing_ids(
    conn: sqlite3.Connection,
    field_name: str,
    raw_value: str,
    limit: int,
) -> list[str]:
    raw_column = FIELD_TO_RAW_COLUMN[field_name]
    sql = f"""
    SELECT source_listing_id
    FROM market_listings_norm
    WHERE source_platform = ?
      AND {raw_column} = ?
    ORDER BY last_seen_at DESC, source_listing_id ASC
    LIMIT ?
    """
    rows = conn.execute(sql, (SOURCE_PLATFORM, raw_value, int(limit))).fetchall()
    return [str(row[0]) for row in rows]


def _provisional_norm_value(field_name: str, raw_value: str) -> str:
    if field_name == "status":
        return STATUS_DEFAULTS.get(raw_value, f"status_{raw_value}")
    if field_name == "auction_type":
        return AUCTION_TYPE_DEFAULTS.get(raw_value, f"auction_type_{raw_value}")
    if field_name == "category":
        return f"category_{raw_value}"
    if field_name == "series":
        return f"series_{raw_value}"
    if field_name == "grade":
        return raw_value
    raise ValueError(f"Unsupported taxonomy field: {field_name}")


def _ensure_schema(db_path: str) -> None:
    SqliteRawStore(db_path).ensure_schema()

