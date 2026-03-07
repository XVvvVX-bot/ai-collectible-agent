from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

from ai_agent.importers.user_data_import import import_user_items_file
from ai_agent.storage.sqlite_raw_store import SqliteRawStore
from ai_agent.user_domain import UserDomainService


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    if not rows:
        raise ValueError("rows must not be empty")
    fieldnames: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row.keys():
            if key in seen:
                continue
            seen.add(key)
            fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_preview_mode_reports_counts_without_writing(tmp_path: Path):
    db_path = tmp_path / "agent.db"
    csv_path = tmp_path / "items.csv"
    _write_csv(
        csv_path,
        [
            {
                "Type": "holding",
                "Category": "stamp",
                "Series": "t46",
                "Name": "Monkey",
                "Year": "1980",
                "Quantity": "2",
                "Cost": "1200",
                "is_active": "1",
            },
            {
                "Type": "watch",
                "Category": "coin",
                "Series": "panda",
                "Name": "1983 Panda 1oz",
                "Year": "1983",
                "Priority": "high",
                "Budget": "10000",
                "is_active": "true",
            },
        ],
    )

    result = import_user_items_file(
        db_path=str(db_path),
        user_id="u-1",
        file_path=str(csv_path),
        commit=False,
    )

    assert result.mode == "preview"
    assert result.inserted == 2
    assert result.updated == 0
    assert result.skipped == 0
    assert result.errors == []

    SqliteRawStore(str(db_path)).ensure_schema()
    with sqlite3.connect(db_path) as conn:
        users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        items = conn.execute("SELECT COUNT(*) FROM user_items").fetchone()[0]
    assert users == 0
    assert items == 0


def test_commit_mode_inserts_updates_and_reports_row_errors(tmp_path: Path):
    db_path = tmp_path / "agent.db"
    csv_path = tmp_path / "items.csv"
    service = UserDomainService(str(db_path))
    service.upsert_user("u-1")
    service.upsert_user_item(
        "u-1",
        "holding",
        category="stamp",
        series="t46",
        item_name="Monkey",
        year=1980,
        quantity=1,
        cost_basis_total=1000,
        is_active=True,
    )

    _write_csv(
        csv_path,
        [
            {
                "item_type": "holding",
                "category": "stamp",
                "series": "t46",
                "item_name": "Monkey",
                "year": "1980",
                "quantity": "3",
                "cost_basis_total": "1500",
            },
            {
                "item_type": "watch",
                "category": "coin",
                "series": "panda",
                "item_name": "1983 Panda 1oz",
                "year": "1983",
                "priority": "high",
                "max_buy_price": "12000",
            },
            {
                "item_type": "watch",
                "item_name": "Bad Row",
                "quantity": "2",
            },
            {
                "item_type": "watch",
                "category": "coin",
                "series": "panda",
                "item_name": "1983 Panda 1oz",
                "year": "1983",
                "priority": "high",
            },
        ],
    )

    result = import_user_items_file(
        db_path=str(db_path),
        user_id="u-1",
        file_path=str(csv_path),
        commit=True,
    )
    assert result.mode == "commit"
    assert result.inserted == 1
    assert result.updated == 1
    assert result.skipped == 0
    assert len(result.errors) == 2
    assert result.errors[0].code == "invalid_row"
    assert result.errors[1].code == "duplicate_in_file"

    holdings = service.list_user_items("u-1", item_type="holding", include_inactive=True)
    watches = service.list_user_items("u-1", item_type="watch", include_inactive=True)
    assert len(holdings) == 1
    assert holdings[0].quantity == 3.0
    assert holdings[0].cost_basis_total == 1500.0
    assert len(watches) == 1
    assert watches[0].priority == "high"
    assert watches[0].max_buy_price == 12000.0
