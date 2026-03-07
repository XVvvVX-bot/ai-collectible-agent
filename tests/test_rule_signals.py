from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

from ai_agent.matching.v1_matcher import run_v1_matching
from ai_agent.signals.rule_engine import run_rule_signal_generation
from ai_agent.storage.sqlite_raw_store import SqliteRawStore
from ai_agent.user_domain import UserDomainService


def _insert_listing(
    conn: sqlite3.Connection,
    source_listing_id: str,
    *,
    title: str,
    category_norm: str | None,
    series_norm: str | None,
    status_norm: str = "live",
    price_initial: float | None = None,
    price_current: float | None = None,
    is_active: int = 1,
) -> str:
    listing_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO market_listings_norm (
          id,
          source_platform,
          source_listing_id,
          title,
          category_norm,
          series_norm,
          status_norm,
          price_initial,
          price_current,
          currency,
          is_active,
          first_seen_at,
          last_seen_at,
          created_at,
          updated_at
        ) VALUES (?, 'zhaoonline', ?, ?, ?, ?, ?, ?, ?, 'CNY', ?, ?, ?, ?, ?)
        """,
        (
            listing_id,
            source_listing_id,
            title,
            category_norm,
            series_norm,
            status_norm,
            price_initial,
            price_current,
            is_active,
            "2026-03-07T00:00:00+00:00",
            "2026-03-07T00:00:00+00:00",
            "2026-03-07T00:00:00+00:00",
            "2026-03-07T00:00:00+00:00",
        ),
    )
    return listing_id


def test_rule_signal_generation_buy_sell_price_move_and_cooldown(tmp_path: Path):
    db_path = tmp_path / "agent.db"
    SqliteRawStore(str(db_path)).ensure_schema()
    service = UserDomainService(str(db_path))
    service.upsert_user("u-1")
    service.upsert_user_preferences(
        "u-1",
        high_interest_flag=True,
        keywords=["monkey"],
    )
    service.upsert_user_item(
        "u-1",
        "watch",
        category="stamp",
        series="t46",
        item_name="Monkey Ticket",
        year=1980,
        priority="high",
        max_buy_price=900.0,
    )
    service.upsert_user_item(
        "u-1",
        "holding",
        category="coin",
        series="panda",
        item_name="1983 Panda 1oz",
        year=1983,
        quantity=1,
        cost_basis_total=1000.0,
    )

    with sqlite3.connect(db_path) as conn:
        _insert_listing(
            conn,
            "L-watch",
            title="Monkey Ticket T46",
            category_norm="stamp",
            series_norm="t46",
            status_norm="live",
            price_initial=1000.0,
            price_current=800.0,
        )
        _insert_listing(
            conn,
            "L-hold",
            title="1983 Panda 1oz",
            category_norm="coin",
            series_norm="panda",
            status_norm="live",
            price_initial=1000.0,
            price_current=1300.0,
        )
        conn.commit()

    run_v1_matching(str(db_path), user_id="u-1", min_score=30.0, strict_name_match=False)
    first = run_rule_signal_generation(
        str(db_path),
        user_id="u-1",
        cooldown_hours=24,
        freshness_hours=24,
        price_move_threshold_pct=10.0,
    )
    assert first.inserted >= 4
    assert first.inserted_by_type.get("new_relevant_listing", 0) >= 2
    assert first.inserted_by_type.get("buy_opportunity", 0) == 1
    assert first.inserted_by_type.get("sell_opportunity", 0) == 1
    assert first.inserted_by_type.get("price_movement", 0) >= 2
    assert first.inserted_by_urgency.get("immediate", 0) >= 2

    second = run_rule_signal_generation(
        str(db_path),
        user_id="u-1",
        cooldown_hours=24,
        freshness_hours=24,
        price_move_threshold_pct=10.0,
    )
    assert second.inserted == 0
    assert second.skipped_cooldown >= first.inserted


def test_rule_signal_generation_without_preferences_defaults_to_daily(tmp_path: Path):
    db_path = tmp_path / "agent.db"
    SqliteRawStore(str(db_path)).ensure_schema()
    service = UserDomainService(str(db_path))
    service.upsert_user("u-2")
    service.upsert_user_item(
        "u-2",
        "watch",
        category="stamp",
        series="a",
        item_name="Alpha",
        year=2000,
        priority="normal",
        max_buy_price=100.0,
    )

    with sqlite3.connect(db_path) as conn:
        _insert_listing(
            conn,
            "L-alpha",
            title="Alpha",
            category_norm="stamp",
            series_norm="a",
            status_norm="live",
            price_initial=120.0,
            price_current=90.0,
        )
        conn.commit()

    run_v1_matching(str(db_path), user_id="u-2", min_score=30.0, strict_name_match=False)
    result = run_rule_signal_generation(str(db_path), user_id="u-2", cooldown_hours=0)
    assert result.inserted_by_urgency.get("daily", 0) >= 1
