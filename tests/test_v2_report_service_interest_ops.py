import sqlite3
import uuid
from pathlib import Path

from ai_agent_v2.profile.manual_interest_ops import create_interest_record, delete_interest_record
from ai_agent_v2.storage.sqlite_store import SqliteV2Store


def _seed_user(conn: sqlite3.Connection, *, user_id: str, now: str) -> None:
    conn.execute(
        """
        INSERT INTO users (id, display_name, language, timezone, created_at, updated_at)
        VALUES (?, 'Ops User', 'zh-CN', 'Asia/Shanghai', ?, ?)
        """,
        (user_id, now, now),
    )
    conn.execute(
        """
        INSERT INTO user_profile_defaults_v2 (
          user_id, default_currency, default_precision_mode, default_condition_mode,
          default_delivery_mode, default_min_match_score, default_cooldown_hours,
          default_allow_related_matches, default_allow_series_matches, default_allow_variant_matches,
          notes, created_at, updated_at
        ) VALUES (
          ?, 'CNY', 'balanced', 'prefer', 'daily_digest', 72, 24, 0, 1, 1,
          'seed defaults', ?, ?
        )
        """,
        (user_id, now, now),
    )
    conn.commit()


def test_create_interest_form_creates_interest_target_and_policy(tmp_path: Path) -> None:
    db_path = tmp_path / "agent_v2.db"
    SqliteV2Store(str(db_path)).ensure_schema()
    now = "2026-03-29T00:00:00+00:00"

    with sqlite3.connect(db_path) as conn:
        _seed_user(conn, user_id="u-ops", now=now)

    result = create_interest_record(
        db_path=db_path,
        user_id="u-ops",
        interest_name="中国龙抢拍",
        raw_input="2026年中国龙31.104克普制银币",
        interest_kind="watch_buy",
        scope_kind="exact_item",
        precision_mode="exact",
        interest_priority="high",
        interest_notes="operator-created",
        budget_max=1850.0,
        condition_mode="require",
        delivery_mode="immediate",
        cooldown_hours=6,
        min_match_score=90.0,
        max_signals_per_day=6,
    )
    assert result["ok"] is True

    with sqlite3.connect(db_path) as conn:
        interest_row = conn.execute(
            """
            SELECT interest_name, interest_kind, scope_kind, precision_mode, interest_priority, active_status,
                   allow_related_matches, allow_series_matches, allow_variant_matches, notes
            FROM user_interests_v2
            WHERE user_id = 'u-ops'
            """
        ).fetchone()
        target_row = conn.execute(
            """
            SELECT target_label, target_kind, parse_family, raw_input, series_key, theme_name,
                   asset_type, budget_max, condition_mode, strictness_override, priority_override
            FROM user_interest_targets_v2
            """
        ).fetchone()
        policy_row = conn.execute(
            """
            SELECT notify_on_preview, notify_on_live, notify_on_ended, notify_on_exact_match,
                   notify_on_variant_match, notify_on_series_match, notify_on_price_opportunity,
                   notify_on_sell_opportunity, min_match_score, cooldown_hours, delivery_mode,
                   max_signals_per_day
            FROM user_interest_signal_policies_v2
            """
        ).fetchone()

    assert interest_row == ("中国龙抢拍", "watch_buy", "exact_item", "exact", "high", "active", 0, 0, 0, "operator-created")
    assert target_row == (
        "2026年中国龙31.104克普制银币",
        "listing_identity",
        "coin_like",
        "2026年中国龙31.104克普制银币",
        "中国龙|银币",
        "中国龙",
        "银币",
        1850.0,
        "require",
        "exact",
        "high",
    )
    assert policy_row == (1, 1, 0, 1, 0, 0, 1, 0, 90.0, 6, "immediate", 6)


def test_delete_interest_form_soft_deactivates_interest_targets_matches_and_signals(tmp_path: Path) -> None:
    db_path = tmp_path / "agent_v2.db"
    SqliteV2Store(str(db_path)).ensure_schema()
    now = "2026-03-29T00:00:00+00:00"

    with sqlite3.connect(db_path) as conn:
        _seed_user(conn, user_id="u-ops", now=now)

    created = create_interest_record(
        db_path=db_path,
        user_id="u-ops",
        interest_name="红楼梦卖点",
        raw_input="T69M红楼梦型张新",
        interest_kind="watch_sell",
        scope_kind="exact_item",
        precision_mode="exact",
        interest_priority="high",
        interest_notes="sell watch",
        budget_max=None,
        condition_mode="require",
        delivery_mode="immediate",
        cooldown_hours=12,
        min_match_score=88.0,
        max_signals_per_day=4,
    )
    interest_id = str(created["interest_id"])
    target_id = str(created["target_id"])

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO listing_matches_v2 (
              id, user_id, listing_id, user_item_id, item_type, relationship_type,
              match_score, identity_score, series_score, variant_score, condition_score,
              matcher_version, match_reasons_json, status, matched_at, updated_at
            ) VALUES (?, 'u-ops', 'listing-1', ?, 'watch', 'exact_identity', 120, 90, 20, 5, 5, 'v2_test', '[]', 'active', ?, ?)
            """,
            (str(uuid.uuid4()), target_id, now, now),
        )
        conn.execute(
            """
            INSERT INTO signal_runs_v2 (
              id, user_id, lookback_hours, started_at, finished_at, status,
              interests_processed, candidates, inserted, skipped_cooldown, error_message
            ) VALUES ('run-1', 'u-ops', 24, ?, ?, 'success', 1, 1, 1, 0, NULL)
            """,
            (now, now),
        )
        conn.execute(
            """
            INSERT INTO signals_v2 (
              id, run_id, user_id, interest_id, target_id, listing_id, signal_type,
              urgency, reason_code, signal_title, signal_summary, group_key,
              payload_json, created_at, last_seen_at, status
            ) VALUES (?, 'run-1', 'u-ops', ?, ?, NULL, 'sell_comp_above_cost',
              'high', 'ended_comp_above_cost_basis', 'Above cost', 'sell standing', 'std-1',
              '{}', ?, ?, 'active')
            """,
            (str(uuid.uuid4()), interest_id, target_id, now, now),
        )
        conn.commit()

    deleted = delete_interest_record(db_path=db_path, user_id="u-ops", interest_id=interest_id)

    assert deleted["ok"] is True
    assert deleted["interest"]["interest_name"] == "红楼梦卖点"

    with sqlite3.connect(db_path) as conn:
        interest_status = conn.execute(
            "SELECT active_status FROM user_interests_v2 WHERE id = ?",
            (interest_id,),
        ).fetchone()[0]
        target_status = conn.execute(
            "SELECT is_active FROM user_interest_targets_v2 WHERE id = ?",
            (target_id,),
        ).fetchone()[0]
        signal_status = conn.execute(
            "SELECT status FROM signals_v2 WHERE interest_id = ?",
            (interest_id,),
        ).fetchone()[0]
        match_status = conn.execute(
            "SELECT status FROM listing_matches_v2 WHERE user_item_id = ?",
            (target_id,),
        ).fetchone()[0]

    assert interest_status == "inactive"
    assert target_status == 0
    assert signal_status == "inactive"
    assert match_status == "inactive"
