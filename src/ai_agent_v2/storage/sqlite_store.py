from __future__ import annotations

import sqlite3
from pathlib import Path


class SqliteV2Store:
    def __init__(self, db_path: str):
        self.db_path = Path(db_path)

    def ensure_schema(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations_v2 (
                  filename TEXT PRIMARY KEY,
                  applied_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            migrations_dir = Path(__file__).resolve().parents[3] / "migrations_v2"
            for migration_path in sorted(migrations_dir.glob("*.sql")):
                filename = migration_path.name
                applied = conn.execute(
                    "SELECT 1 FROM schema_migrations_v2 WHERE filename = ?",
                    (filename,),
                ).fetchone()
                if applied:
                    continue
                conn.executescript(migration_path.read_text(encoding="utf-8"))
                conn.execute(
                    "INSERT INTO schema_migrations_v2 (filename) VALUES (?)",
                    (filename,),
                )
