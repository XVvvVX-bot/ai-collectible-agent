from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
import hashlib
from pathlib import Path


@dataclass(frozen=True)
class RawListingRecord:
    source_platform: str
    source_listing_id: str
    fetch_status: str
    fetched_at: str
    payload_json: str
    payload_hash: str
    request_meta_json: str
    created_at: str


class SqliteRawStore:
    def __init__(self, db_path: str):
        self.db_path = Path(db_path)

    def ensure_schema(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                  filename TEXT PRIMARY KEY,
                  applied_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            migrations_dir = Path(__file__).resolve().parents[3] / "migrations"
            files = sorted(migrations_dir.glob("*.sql"))
            for migration_path in files:
                filename = migration_path.name
                applied = conn.execute(
                    "SELECT 1 FROM schema_migrations WHERE filename = ?",
                    (filename,),
                ).fetchone()
                if applied:
                    continue
                sql = migration_path.read_text(encoding="utf-8")
                conn.executescript(sql)
                conn.execute(
                    "INSERT INTO schema_migrations (filename) VALUES (?)",
                    (filename,),
                )
            self._normalize_raw_rows(conn)

    def insert_raw_records(self, records: list[RawListingRecord]) -> int:
        if not records:
            return 0
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany(
                """
                INSERT OR IGNORE INTO market_listings_raw (
                  id,
                  source_platform,
                  source_listing_id,
                  fetch_status,
                  fetched_at,
                  payload_json,
                  payload_hash,
                  request_meta_json,
                  created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        str(uuid.uuid4()),
                        rec.source_platform,
                        rec.source_listing_id,
                        rec.fetch_status,
                        rec.fetched_at,
                        rec.payload_json,
                        rec.payload_hash,
                        rec.request_meta_json,
                        rec.created_at,
                    )
                    for rec in records
                ],
            )
            return conn.total_changes

    def ensure_crawl_state_rows(self, source_platform: str, statuses: tuple[int, ...]) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany(
                """
                INSERT OR IGNORE INTO ingestion_crawl_state (
                  source_platform, fetch_status, next_page, updated_at
                ) VALUES (?, ?, 1, datetime('now'))
                """,
                [(source_platform, str(status)) for status in statuses],
            )

    def get_next_page(self, source_platform: str, status: int) -> int:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT next_page FROM ingestion_crawl_state
                WHERE source_platform = ? AND fetch_status = ?
                """,
                (source_platform, str(status)),
            ).fetchone()
            if row is None:
                return 1
            page = int(row[0])
            return page if page >= 1 else 1

    def set_next_page(self, source_platform: str, status: int, next_page: int) -> None:
        value = max(1, int(next_page))
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE ingestion_crawl_state
                SET next_page = ?, updated_at = datetime('now')
                WHERE source_platform = ? AND fetch_status = ?
                """,
                (value, source_platform, str(status)),
            )

    def _normalize_raw_rows(self, conn: sqlite3.Connection) -> None:
        rows = conn.execute(
            """
            SELECT rowid, source_platform, source_listing_id, fetch_status, payload_json, payload_hash
            FROM market_listings_raw
            ORDER BY rowid
            """
        ).fetchall()
        if not rows:
            return

        seen: set[tuple[str, str | None, str, str]] = set()
        to_update: list[tuple[str, int]] = []
        to_delete: list[int] = []
        for rowid, platform, listing_id, fetch_status, payload_json, payload_hash in rows:
            resolved_hash = payload_hash
            if not resolved_hash:
                resolved_hash = hashlib.sha1(payload_json.encode("utf-8")).hexdigest()
            key = (platform, fetch_status, listing_id, resolved_hash)
            if key in seen:
                to_delete.append(rowid)
                continue
            seen.add(key)
            if payload_hash != resolved_hash:
                to_update.append((resolved_hash, rowid))

        if to_update:
            conn.executemany(
                "UPDATE market_listings_raw SET payload_hash = ? WHERE rowid = ?",
                to_update,
            )
        if to_delete:
            conn.executemany(
                "DELETE FROM market_listings_raw WHERE rowid = ?",
                [(rowid,) for rowid in to_delete],
            )
