from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ai_agent.user_domain import UserDomainService, canonical_item_dedupe_key


def test_upsert_user_is_deterministic(tmp_path: Path):
    db_path = tmp_path / "agent.db"
    service = UserDomainService(str(db_path))

    first = service.upsert_user(
        "u-1",
        display_name="Alice",
        language="zh-CN",
        timezone="Asia/Shanghai",
    )
    second = service.upsert_user(
        "u-1",
        display_name="Alice Updated",
        language="en-US",
        timezone="America/Los_Angeles",
    )

    assert first.id == second.id == "u-1"
    assert second.display_name == "Alice Updated"
    assert second.language == "en-US"
    assert second.timezone == "America/Los_Angeles"
    assert second.created_at == first.created_at
    assert second.updated_at >= first.updated_at


def test_user_item_upsert_dedupes_natural_key_and_updates_fields(tmp_path: Path):
    db_path = tmp_path / "agent.db"
    service = UserDomainService(str(db_path))
    service.upsert_user("u-1")

    first = service.upsert_user_item(
        "u-1",
        "holding",
        category="Stamp",
        series="T46",
        item_name="Monkey Ticket",
        year=1980,
        grade_condition=" VF ",
        quantity=1,
        cost_basis_total=1200,
        notes="first",
        is_active=True,
    )
    second = service.upsert_user_item(
        "u-1",
        "holding",
        category=" stamp ",
        series="t46",
        item_name=" monkey ticket ",
        year=1980,
        grade_condition="vf",
        quantity=3,
        cost_basis_total=3200,
        notes="updated",
        is_active=True,
    )

    assert first.id == second.id
    assert second.quantity == 3.0
    assert second.cost_basis_total == 3200.0
    assert second.notes == "updated"
    assert second.dedupe_key == canonical_item_dedupe_key(
        category="stamp",
        series="T46",
        item_name="Monkey Ticket",
        year=1980,
        grade_condition="vf",
    )

    with sqlite3.connect(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM user_items").fetchone()[0]
    assert count == 1


def test_deactivate_missing_user_items_and_preferences_upsert(tmp_path: Path):
    db_path = tmp_path / "agent.db"
    service = UserDomainService(str(db_path))
    service.upsert_user("u-1")

    keep = service.upsert_user_item(
        "u-1",
        "watch",
        category="coin",
        series="panda",
        item_name="1983 Panda 1oz",
        year=1983,
        grade_condition="MS65",
        priority="high",
        is_active=True,
    )
    drop = service.upsert_user_item(
        "u-1",
        "watch",
        category="coin",
        series="panda",
        item_name="1985 Panda 1oz",
        year=1985,
        grade_condition="MS64",
        priority="normal",
        is_active=True,
    )

    changed = service.deactivate_missing_user_items(
        "u-1",
        "watch",
        keep_dedupe_keys=[keep.dedupe_key],
    )
    assert changed == 1
    refreshed_keep = service.get_user_item(keep.id)
    refreshed_drop = service.get_user_item(drop.id)
    assert refreshed_keep.is_active == 1
    assert refreshed_drop.is_active == 0

    first_pref = service.upsert_user_preferences(
        "u-1",
        buy_rule_text="below avg",
        high_interest_flag=True,
        keywords=["Panda", " panda ", "Gold"],
        rules={"max_buy_price": 12000, "window_days": 30},
    )
    second_pref = service.upsert_user_preferences(
        "u-1",
        buy_rule_text="below p30",
        sell_rule_text="above p80",
        high_interest_flag=False,
        keywords=["gold"],
        rules={"window_days": 30, "max_buy_price": 11000},
    )

    assert first_pref.id == second_pref.id
    assert second_pref.high_interest_flag == 0
    assert second_pref.buy_rule_text == "below p30"
    assert second_pref.sell_rule_text == "above p80"
    assert json.loads(second_pref.keywords_json or "[]") == ["gold"]
    assert second_pref.rules_json == '{"max_buy_price":11000,"window_days":30}'

    with sqlite3.connect(db_path) as conn:
        pref_count = conn.execute("SELECT COUNT(*) FROM user_preferences WHERE user_id = 'u-1'").fetchone()[0]
    assert pref_count == 1


def test_demo_profile_from_report_section_zero_end_to_end(tmp_path: Path):
    db_path = tmp_path / "agent.db"
    service = UserDomainService(str(db_path))

    # Section 0 profile in reports/report_preview_demo_u_20260307.md
    user = service.upsert_user(
        "demo_u_20260307",
        display_name="Demo Collector",
        language="zh-CN",
        timezone="Asia/Shanghai",
    )
    pref = service.upsert_user_preferences(
        "demo_u_20260307",
        buy_rule_text="价格低于预算或明显低于起拍价时提醒",
        sell_rule_text="价格明显高于成本时提醒",
        high_interest_flag=True,
        keywords=["纪94", "日本邮票", "T67"],
        rules={"cooldown_hours": 24, "price_move_threshold_pct": 10},
    )

    h1 = service.upsert_user_item(
        "demo_u_20260307",
        "holding",
        category="178",
        series="2",
        item_name="T67（7-6）带色标数字直角边12连新",
        quantity=1,
        cost_basis_total=400,
        notes="测试持仓-1",
    )
    h2 = service.upsert_user_item(
        "demo_u_20260307",
        "holding",
        category="178",
        series="10",
        item_name="纪94（8-8）新",
        quantity=1,
        cost_basis_total=300,
        notes="测试持仓-2",
    )
    w1 = service.upsert_user_item(
        "demo_u_20260307",
        "watch",
        category="471",
        series="10",
        item_name="日本邮票",
        priority="normal",
        max_buy_price=120,
        notes="日本票低价机会",
    )
    w2 = service.upsert_user_item(
        "demo_u_20260307",
        "watch",
        category="178",
        series="10",
        item_name="纪94（8-1）新",
        priority="high",
        max_buy_price=220,
        notes="纪字票重点关注",
    )

    # Deterministic upsert on natural key for an existing holding.
    h2_updated = service.upsert_user_item(
        "demo_u_20260307",
        "holding",
        category="178",
        series="10",
        item_name="纪94（8-8）新",
        quantity=2,
        cost_basis_total=600,
        notes="测试持仓-2-updated",
    )
    assert h2.id == h2_updated.id
    assert h2_updated.quantity == 2.0
    assert h2_updated.cost_basis_total == 600.0

    holdings = service.list_user_items("demo_u_20260307", item_type="holding")
    watches = service.list_user_items("demo_u_20260307", item_type="watch")
    assert len(holdings) == 2
    assert len(watches) == 2

    # Lifecycle control: deactivate watches not in keep set.
    changed = service.deactivate_missing_user_items(
        "demo_u_20260307",
        "watch",
        keep_dedupe_keys=[w1.dedupe_key],
    )
    assert changed == 1
    assert service.get_user_item(w1.id).is_active == 1
    assert service.get_user_item(w2.id).is_active == 0

    assert user.id == "demo_u_20260307"
    assert pref.high_interest_flag == 1
    assert json.loads(pref.keywords_json or "[]") == ["纪94", "日本邮票", "T67"]
    assert pref.rules_json == '{"cooldown_hours":24,"price_move_threshold_pct":10}'
    assert h1.user_id == "demo_u_20260307"
