from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ai_agent.clients.zhaoonline import now_utc_iso
from ai_agent.storage.sqlite_raw_store import SqliteRawStore


VALID_ITEM_TYPES = {"holding", "watch"}
VALID_PRIORITIES = {"high", "normal", "low"}


@dataclass(frozen=True)
class UserRecord:
    id: str
    display_name: str | None
    language: str
    timezone: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class UserItemRecord:
    id: str
    user_id: str
    item_type: str
    category: str | None
    series: str | None
    item_name: str
    year: int | None
    grade_condition: str | None
    quantity: float | None
    cost_basis_total: float | None
    priority: str | None
    max_buy_price: float | None
    notes: str | None
    is_active: int
    dedupe_key: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class UserPreferenceRecord:
    id: str
    user_id: str
    buy_rule_text: str | None
    sell_rule_text: str | None
    high_interest_flag: int
    keywords_json: str | None
    rules_json: str | None
    created_at: str
    updated_at: str


class UserDomainService:
    def __init__(self, db_path: str):
        self.db_path = Path(db_path)

    def upsert_user(
        self,
        user_id: str,
        *,
        display_name: str | None = None,
        language: str = "zh-CN",
        timezone: str = "Asia/Shanghai",
    ) -> UserRecord:
        now = now_utc_iso()
        clean_user_id = _required_text("user_id", user_id)
        clean_display_name = _optional_text(display_name)
        clean_language = _required_text("language", language)
        clean_timezone = _required_text("timezone", timezone)

        self._ensure_schema()
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT id, display_name, language, timezone, created_at, updated_at
                FROM users
                WHERE id = ?
                """,
                (clean_user_id,),
            ).fetchone()

            if row is None:
                conn.execute(
                    """
                    INSERT INTO users (id, display_name, language, timezone, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        clean_user_id,
                        clean_display_name,
                        clean_language,
                        clean_timezone,
                        now,
                        now,
                    ),
                )
            else:
                conn.execute(
                    """
                    UPDATE users
                    SET display_name = ?, language = ?, timezone = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        clean_display_name,
                        clean_language,
                        clean_timezone,
                        now,
                        clean_user_id,
                    ),
                )

            conn.commit()
            return self.get_user(clean_user_id, conn=conn)

    def get_user(self, user_id: str, *, conn: sqlite3.Connection | None = None) -> UserRecord:
        clean_user_id = _required_text("user_id", user_id)
        owns_conn = conn is None
        if owns_conn:
            self._ensure_schema()
            conn = sqlite3.connect(self.db_path)
        assert conn is not None
        try:
            row = conn.execute(
                """
                SELECT id, display_name, language, timezone, created_at, updated_at
                FROM users
                WHERE id = ?
                """,
                (clean_user_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"user not found: {clean_user_id}")
            return UserRecord(
                id=str(row[0]),
                display_name=_optional_text(row[1]),
                language=str(row[2]),
                timezone=str(row[3]),
                created_at=str(row[4]),
                updated_at=str(row[5]),
            )
        finally:
            if owns_conn:
                conn.close()

    def upsert_user_item(
        self,
        user_id: str,
        item_type: str,
        *,
        category: str | None,
        series: str | None,
        item_name: str,
        year: int | None = None,
        grade_condition: str | None = None,
        quantity: float | None = None,
        cost_basis_total: float | None = None,
        priority: str | None = None,
        max_buy_price: float | None = None,
        notes: str | None = None,
        is_active: bool = True,
    ) -> UserItemRecord:
        clean_user_id = _required_text("user_id", user_id)
        clean_item_type = _required_text("item_type", item_type).lower()
        if clean_item_type not in VALID_ITEM_TYPES:
            raise ValueError(f"invalid item_type: {item_type}")

        clean_category = _optional_text(category)
        clean_series = _optional_text(series)
        clean_item_name = _required_text("item_name", item_name)
        clean_grade_condition = _optional_text(grade_condition)
        clean_priority = _optional_text(priority)
        if clean_priority and clean_priority not in VALID_PRIORITIES:
            raise ValueError(f"invalid priority: {priority}")

        clean_year = _optional_int(year, field_name="year")
        clean_quantity = _optional_float(quantity, field_name="quantity")
        clean_cost_basis_total = _optional_float(cost_basis_total, field_name="cost_basis_total")
        clean_max_buy_price = _optional_float(max_buy_price, field_name="max_buy_price")
        clean_notes = _optional_text(notes)
        active_value = 1 if is_active else 0

        dedupe_key = _build_item_dedupe_key(
            category=clean_category,
            series=clean_series,
            item_name=clean_item_name,
            year=clean_year,
            grade_condition=clean_grade_condition,
        )
        now = now_utc_iso()

        self._ensure_schema()
        with sqlite3.connect(self.db_path) as conn:
            self._require_user_exists(conn, clean_user_id)
            row = conn.execute(
                """
                SELECT id, created_at
                FROM user_items
                WHERE user_id = ? AND item_type = ? AND dedupe_key = ?
                """,
                (clean_user_id, clean_item_type, dedupe_key),
            ).fetchone()
            if row is None:
                item_id = str(uuid.uuid4())
                created_at = now
                conn.execute(
                    """
                    INSERT INTO user_items (
                      id,
                      user_id,
                      item_type,
                      category,
                      series,
                      item_name,
                      year,
                      grade_condition,
                      quantity,
                      cost_basis_total,
                      priority,
                      max_buy_price,
                      notes,
                      is_active,
                      dedupe_key,
                      created_at,
                      updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item_id,
                        clean_user_id,
                        clean_item_type,
                        clean_category,
                        clean_series,
                        clean_item_name,
                        clean_year,
                        clean_grade_condition,
                        clean_quantity,
                        clean_cost_basis_total,
                        clean_priority,
                        clean_max_buy_price,
                        clean_notes,
                        active_value,
                        dedupe_key,
                        created_at,
                        now,
                    ),
                )
            else:
                item_id = str(row[0])
                created_at = str(row[1])
                conn.execute(
                    """
                    UPDATE user_items
                    SET category = ?,
                        series = ?,
                        item_name = ?,
                        year = ?,
                        grade_condition = ?,
                        quantity = ?,
                        cost_basis_total = ?,
                        priority = ?,
                        max_buy_price = ?,
                        notes = ?,
                        is_active = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        clean_category,
                        clean_series,
                        clean_item_name,
                        clean_year,
                        clean_grade_condition,
                        clean_quantity,
                        clean_cost_basis_total,
                        clean_priority,
                        clean_max_buy_price,
                        clean_notes,
                        active_value,
                        now,
                        item_id,
                    ),
                )

            conn.commit()
            return self.get_user_item(item_id, conn=conn)

    def get_user_item(self, item_id: str, *, conn: sqlite3.Connection | None = None) -> UserItemRecord:
        clean_item_id = _required_text("item_id", item_id)
        owns_conn = conn is None
        if owns_conn:
            self._ensure_schema()
            conn = sqlite3.connect(self.db_path)
        assert conn is not None
        try:
            row = conn.execute(
                """
                SELECT
                  id,
                  user_id,
                  item_type,
                  category,
                  series,
                  item_name,
                  year,
                  grade_condition,
                  quantity,
                  cost_basis_total,
                  priority,
                  max_buy_price,
                  notes,
                  is_active,
                  dedupe_key,
                  created_at,
                  updated_at
                FROM user_items
                WHERE id = ?
                """,
                (clean_item_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"user_item not found: {clean_item_id}")
            return UserItemRecord(
                id=str(row[0]),
                user_id=str(row[1]),
                item_type=str(row[2]),
                category=_optional_text(row[3]),
                series=_optional_text(row[4]),
                item_name=str(row[5]),
                year=_optional_int(row[6], field_name="year"),
                grade_condition=_optional_text(row[7]),
                quantity=_optional_float(row[8], field_name="quantity"),
                cost_basis_total=_optional_float(row[9], field_name="cost_basis_total"),
                priority=_optional_text(row[10]),
                max_buy_price=_optional_float(row[11], field_name="max_buy_price"),
                notes=_optional_text(row[12]),
                is_active=int(row[13]),
                dedupe_key=str(row[14]),
                created_at=str(row[15]),
                updated_at=str(row[16]),
            )
        finally:
            if owns_conn:
                conn.close()

    def list_user_items(
        self,
        user_id: str,
        *,
        item_type: str | None = None,
        include_inactive: bool = False,
    ) -> list[UserItemRecord]:
        clean_user_id = _required_text("user_id", user_id)
        clean_item_type: str | None = None
        if item_type is not None:
            clean_item_type = _required_text("item_type", item_type).lower()
            if clean_item_type not in VALID_ITEM_TYPES:
                raise ValueError(f"invalid item_type: {item_type}")

        self._ensure_schema()
        with sqlite3.connect(self.db_path) as conn:
            filters = ["user_id = ?"]
            params: list[Any] = [clean_user_id]
            if clean_item_type is not None:
                filters.append("item_type = ?")
                params.append(clean_item_type)
            if not include_inactive:
                filters.append("is_active = 1")

            rows = conn.execute(
                f"""
                SELECT id
                FROM user_items
                WHERE {" AND ".join(filters)}
                ORDER BY updated_at DESC, id DESC
                """
                ,
                tuple(params),
            ).fetchall()
            return [self.get_user_item(str(row[0]), conn=conn) for row in rows]

    def deactivate_missing_user_items(
        self,
        user_id: str,
        item_type: str,
        *,
        keep_dedupe_keys: list[str],
    ) -> int:
        clean_user_id = _required_text("user_id", user_id)
        clean_item_type = _required_text("item_type", item_type).lower()
        if clean_item_type not in VALID_ITEM_TYPES:
            raise ValueError(f"invalid item_type: {item_type}")

        canonical_keep = {
            _required_text("dedupe_key", dedupe_key).lower() for dedupe_key in keep_dedupe_keys
        }
        now = now_utc_iso()

        self._ensure_schema()
        with sqlite3.connect(self.db_path) as conn:
            self._require_user_exists(conn, clean_user_id)
            if canonical_keep:
                placeholders = ", ".join("?" for _ in canonical_keep)
                params = (clean_user_id, clean_item_type, *sorted(canonical_keep), now)
                conn.execute(
                    f"""
                    UPDATE user_items
                    SET is_active = 0, updated_at = ?
                    WHERE user_id = ?
                      AND item_type = ?
                      AND is_active = 1
                      AND dedupe_key NOT IN ({placeholders})
                    """,
                    (now, clean_user_id, clean_item_type, *sorted(canonical_keep)),
                )
            else:
                conn.execute(
                    """
                    UPDATE user_items
                    SET is_active = 0, updated_at = ?
                    WHERE user_id = ? AND item_type = ? AND is_active = 1
                    """,
                    (now, clean_user_id, clean_item_type),
                )
            changed = conn.total_changes
            conn.commit()
            return changed

    def upsert_user_preferences(
        self,
        user_id: str,
        *,
        buy_rule_text: str | None = None,
        sell_rule_text: str | None = None,
        high_interest_flag: bool = False,
        keywords: list[str] | None = None,
        rules: dict[str, Any] | None = None,
    ) -> UserPreferenceRecord:
        clean_user_id = _required_text("user_id", user_id)
        now = now_utc_iso()
        self._ensure_schema()
        with sqlite3.connect(self.db_path) as conn:
            self._require_user_exists(conn, clean_user_id)
            existing = conn.execute(
                """
                SELECT id, created_at
                FROM user_preferences
                WHERE user_id = ?
                """,
                (clean_user_id,),
            ).fetchone()
            keywords_json = _serialize_keywords(keywords)
            rules_json = _serialize_rules(rules)
            if existing is None:
                pref_id = str(uuid.uuid4())
                created_at = now
                conn.execute(
                    """
                    INSERT INTO user_preferences (
                      id,
                      user_id,
                      buy_rule_text,
                      sell_rule_text,
                      high_interest_flag,
                      keywords_json,
                      rules_json,
                      created_at,
                      updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        pref_id,
                        clean_user_id,
                        _optional_text(buy_rule_text),
                        _optional_text(sell_rule_text),
                        1 if high_interest_flag else 0,
                        keywords_json,
                        rules_json,
                        created_at,
                        now,
                    ),
                )
            else:
                pref_id = str(existing[0])
                conn.execute(
                    """
                    UPDATE user_preferences
                    SET buy_rule_text = ?,
                        sell_rule_text = ?,
                        high_interest_flag = ?,
                        keywords_json = ?,
                        rules_json = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        _optional_text(buy_rule_text),
                        _optional_text(sell_rule_text),
                        1 if high_interest_flag else 0,
                        keywords_json,
                        rules_json,
                        now,
                        pref_id,
                    ),
                )
            conn.commit()
            return self.get_user_preferences(clean_user_id, conn=conn)

    def get_user_preferences(
        self,
        user_id: str,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> UserPreferenceRecord:
        clean_user_id = _required_text("user_id", user_id)
        owns_conn = conn is None
        if owns_conn:
            self._ensure_schema()
            conn = sqlite3.connect(self.db_path)
        assert conn is not None
        try:
            row = conn.execute(
                """
                SELECT
                  id,
                  user_id,
                  buy_rule_text,
                  sell_rule_text,
                  high_interest_flag,
                  keywords_json,
                  rules_json,
                  created_at,
                  updated_at
                FROM user_preferences
                WHERE user_id = ?
                """,
                (clean_user_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"user_preferences not found for user: {clean_user_id}")
            return UserPreferenceRecord(
                id=str(row[0]),
                user_id=str(row[1]),
                buy_rule_text=_optional_text(row[2]),
                sell_rule_text=_optional_text(row[3]),
                high_interest_flag=int(row[4]),
                keywords_json=_optional_text(row[5]),
                rules_json=_optional_text(row[6]),
                created_at=str(row[7]),
                updated_at=str(row[8]),
            )
        finally:
            if owns_conn:
                conn.close()

    def _ensure_schema(self) -> None:
        SqliteRawStore(str(self.db_path)).ensure_schema()

    def _require_user_exists(self, conn: sqlite3.Connection, user_id: str) -> None:
        row = conn.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            raise ValueError(f"user not found: {user_id}")


def _serialize_keywords(keywords: list[str] | None) -> str | None:
    if keywords is None:
        return None
    normalized = []
    seen = set()
    for value in keywords:
        text = _optional_text(value)
        if not text:
            continue
        lowered = text.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        normalized.append(text)
    if not normalized:
        return None
    return json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))


def _serialize_rules(rules: dict[str, Any] | None) -> str | None:
    if rules is None:
        return None
    if not isinstance(rules, dict):
        raise ValueError("rules must be a dict when provided.")
    return json.dumps(rules, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _build_item_dedupe_key(
    *,
    category: str | None,
    series: str | None,
    item_name: str,
    year: int | None,
    grade_condition: str | None,
) -> str:
    parts = [
        _canon_text(category),
        _canon_text(series),
        _canon_text(item_name),
        str(year) if year is not None else "",
        _canon_text(grade_condition),
    ]
    return "|".join(parts)


def canonical_item_dedupe_key(
    *,
    category: str | None,
    series: str | None,
    item_name: str,
    year: int | None = None,
    grade_condition: str | None = None,
) -> str:
    return _build_item_dedupe_key(
        category=_optional_text(category),
        series=_optional_text(series),
        item_name=_required_text("item_name", item_name),
        year=_optional_int(year, field_name="year"),
        grade_condition=_optional_text(grade_condition),
    )


def _canon_text(value: str | None) -> str:
    if value is None:
        return ""
    return value.strip().lower()


def _required_text(field_name: str, value: Any) -> str:
    text = _optional_text(value)
    if not text:
        raise ValueError(f"{field_name} is required.")
    return text


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _optional_int(value: Any, *, field_name: str) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer when provided.") from exc


def _optional_float(value: Any, *, field_name: str) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a number when provided.") from exc
