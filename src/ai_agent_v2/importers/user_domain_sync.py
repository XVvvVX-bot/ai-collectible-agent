from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from ai_agent_v2.storage.sqlite_store import SqliteV2Store


@dataclass(frozen=True)
class UserDomainSyncResult:
    users_upserted: int
    items_upserted: int
    preferences_upserted: int


def sync_user_domain_to_v2(
    source_db_path: str,
    target_db_path: str,
    *,
    user_id: str | None = None,
) -> UserDomainSyncResult:
    SqliteV2Store(target_db_path).ensure_schema()

    source_path = Path(source_db_path)
    if not source_path.exists():
        raise ValueError(f"source db not found: {source_db_path}")

    with sqlite3.connect(source_path) as source_conn, sqlite3.connect(target_db_path) as target_conn:
        source_conn.row_factory = sqlite3.Row
        target_conn.row_factory = sqlite3.Row

        user_rows = _load_rows(source_conn, "users", user_id=user_id)
        item_rows = _load_rows(source_conn, "user_items", user_id=user_id)
        pref_rows = _load_rows(source_conn, "user_preferences", user_id=user_id)

        for row in user_rows:
            target_conn.execute(
                """
                INSERT INTO users (id, display_name, language, timezone, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  display_name = excluded.display_name,
                  language = excluded.language,
                  timezone = excluded.timezone,
                  updated_at = excluded.updated_at
                """,
                (
                    str(row["id"]),
                    row["display_name"],
                    str(row["language"]),
                    str(row["timezone"]),
                    str(row["created_at"]),
                    str(row["updated_at"]),
                ),
            )

        for row in item_rows:
            target_conn.execute(
                """
                INSERT INTO user_items (
                  id, user_id, item_type, category, series, item_name, year, grade_condition,
                  quantity, cost_basis_total, priority, max_buy_price, notes, is_active,
                  dedupe_key, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  user_id = excluded.user_id,
                  item_type = excluded.item_type,
                  category = excluded.category,
                  series = excluded.series,
                  item_name = excluded.item_name,
                  year = excluded.year,
                  grade_condition = excluded.grade_condition,
                  quantity = excluded.quantity,
                  cost_basis_total = excluded.cost_basis_total,
                  priority = excluded.priority,
                  max_buy_price = excluded.max_buy_price,
                  notes = excluded.notes,
                  is_active = excluded.is_active,
                  dedupe_key = excluded.dedupe_key,
                  updated_at = excluded.updated_at
                """,
                (
                    str(row["id"]),
                    str(row["user_id"]),
                    str(row["item_type"]),
                    row["category"],
                    row["series"],
                    str(row["item_name"]),
                    row["year"],
                    row["grade_condition"],
                    row["quantity"],
                    row["cost_basis_total"],
                    row["priority"],
                    row["max_buy_price"],
                    row["notes"],
                    int(row["is_active"]),
                    row["dedupe_key"],
                    str(row["created_at"]),
                    str(row["updated_at"]),
                ),
            )

        for row in pref_rows:
            target_conn.execute(
                """
                INSERT INTO user_preferences (
                  id, user_id, buy_rule_text, sell_rule_text, high_interest_flag,
                  keywords_json, rules_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  user_id = excluded.user_id,
                  buy_rule_text = excluded.buy_rule_text,
                  sell_rule_text = excluded.sell_rule_text,
                  high_interest_flag = excluded.high_interest_flag,
                  keywords_json = excluded.keywords_json,
                  rules_json = excluded.rules_json,
                  updated_at = excluded.updated_at
                """,
                (
                    str(row["id"]),
                    str(row["user_id"]),
                    row["buy_rule_text"],
                    row["sell_rule_text"],
                    int(row["high_interest_flag"]),
                    row["keywords_json"],
                    row["rules_json"],
                    str(row["created_at"]),
                    str(row["updated_at"]),
                ),
            )

        target_conn.commit()

    return UserDomainSyncResult(
        users_upserted=len(user_rows),
        items_upserted=len(item_rows),
        preferences_upserted=len(pref_rows),
    )


def _load_rows(conn: sqlite3.Connection, table_name: str, *, user_id: str | None) -> list[sqlite3.Row]:
    try:
        if user_id:
            if table_name == "users":
                return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchall()
            return conn.execute(f"SELECT * FROM {table_name} WHERE user_id = ?", (user_id,)).fetchall()
        return conn.execute(f"SELECT * FROM {table_name}").fetchall()
    except sqlite3.OperationalError as exc:
        raise ValueError(f"source db missing required table: {table_name}") from exc
