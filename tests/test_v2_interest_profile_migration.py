from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ai_agent_v2.profile.user_profile_migration import migrate_interest_profile_v2
from ai_agent_v2.storage.sqlite_store import SqliteV2Store


def test_interest_profile_migration_builds_interests_targets_holdings_and_policies(tmp_path: Path):
    db_path = tmp_path / "agent_v2.db"
    SqliteV2Store(str(db_path)).ensure_schema()

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO users (id, display_name, language, timezone, created_at, updated_at)
            VALUES ('u-1', 'Tester', 'zh-CN', 'Asia/Shanghai', '2026-03-27T00:00:00+00:00', '2026-03-27T00:00:00+00:00')
            """
        )
        conn.execute(
            """
            INSERT INTO user_items (
              id, user_id, item_type, category, series, item_name, priority, max_buy_price,
              is_active, dedupe_key, created_at, updated_at
            ) VALUES (
              'watch-1', 'u-1', 'watch', '邮票', 'J94', '纪94（8-1）新', 'high', 220,
              1, '邮票|j94|纪94（8-1）新||', '2026-03-27T00:00:00+00:00', '2026-03-27T00:00:00+00:00'
            )
            """
        )
        conn.execute(
            """
            INSERT INTO user_items (
              id, user_id, item_type, category, series, item_name, quantity, cost_basis_total,
              is_active, dedupe_key, created_at, updated_at
            ) VALUES (
              'holding-1', 'u-1', 'holding', '邮票', 'T130', 'T130泰山新28套（一版）', 2, 800,
              1, '邮票|t130|T130泰山新28套（一版）||', '2026-03-27T00:00:00+00:00', '2026-03-27T00:00:00+00:00'
            )
            """
        )
        conn.execute(
            """
            INSERT INTO user_preferences (
              id, user_id, buy_rule_text, sell_rule_text, high_interest_flag, keywords_json, rules_json, created_at, updated_at
            ) VALUES (
              'pref-1', 'u-1', 'budget first', 'profit first', 1, '["纪94"]', '{"cooldown_hours":12}',
              '2026-03-27T00:00:00+00:00', '2026-03-27T00:00:00+00:00'
            )
            """
        )
        conn.commit()

    result = migrate_interest_profile_v2(str(db_path))
    assert result.users_processed == 1
    assert result.defaults_upserted == 1
    assert result.interests_upserted == 1
    assert result.targets_upserted == 1
    assert result.holdings_upserted == 1
    assert result.policies_upserted == 1

    with sqlite3.connect(db_path) as conn:
        defaults = conn.execute(
            "SELECT default_allow_series_matches FROM user_profile_defaults_v2 WHERE user_id = 'u-1'"
        ).fetchone()
        interest = conn.execute(
            "SELECT interest_kind, scope_kind, precision_mode FROM user_interests_v2 WHERE legacy_user_item_id = 'watch-1'"
        ).fetchone()
        target = conn.execute(
            "SELECT issue_code_norm, issue_part_token, budget_max, strictness_override FROM user_interest_targets_v2"
        ).fetchone()
        holding = conn.execute(
            "SELECT holding_quantity, cost_basis_total, cost_basis_unit FROM user_holdings_v2 WHERE legacy_user_item_id = 'holding-1'"
        ).fetchone()
        policy = conn.execute(
            "SELECT notify_on_variant_match, notify_on_series_match, cooldown_hours, delivery_mode FROM user_interest_signal_policies_v2"
        ).fetchone()

    assert defaults == (1,)
    assert interest == ("watch_buy", "issue_part", "exact")
    assert target == ("J94", "8-1", 220.0, "exact")
    assert holding == (2.0, 800.0, 400.0)
    assert policy == (1, 0, 12, "immediate")
