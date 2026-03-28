from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path

from ai_agent_v2.clients.zhaoonline import now_utc_iso
from ai_agent_v2.storage.sqlite_store import SqliteV2Store

DEMO_USER_ID = "demo_u_v2_curated"
DEMO_DISPLAY_NAME = "V2 Curated Demo Collector"
DEMO_LANGUAGE = "zh-CN"
DEMO_TIMEZONE = "Asia/Shanghai"


@dataclass(frozen=True)
class DemoInterestSpec:
    seed_title: str
    interest_name: str
    interest_kind: str
    scope_kind: str
    precision_mode: str
    interest_priority: str
    allow_related_matches: int
    allow_series_matches: int
    allow_variant_matches: int
    target_label: str
    target_kind: str
    normalized_name: str | None
    use_issue_code_norm: bool
    use_issue_part_token: bool
    use_series_key: bool
    use_theme_name: bool
    use_asset_type: bool
    use_year_value: bool
    variant_tokens: tuple[str, ...]
    quantity_tokens: tuple[str, ...]
    condition_tokens: tuple[str, ...]
    budget_min: float | None
    budget_max: float | None
    strictness_override: str | None
    priority_override: str | None
    intent_confidence: float
    policy_notify_on_preview: int
    policy_notify_on_live: int
    policy_notify_on_ended: int
    policy_notify_on_exact_match: int
    policy_notify_on_variant_match: int
    policy_notify_on_series_match: int
    policy_notify_on_price_opportunity: int
    policy_notify_on_sell_opportunity: int
    policy_min_match_score: float
    policy_cooldown_hours: int
    policy_delivery_mode: str
    policy_max_signals_per_day: int
    holding_quantity: float | None = None
    cost_basis_unit: float | None = None
    interest_note: str | None = None
    holding_note: str | None = None


@dataclass(frozen=True)
class DemoSeedSelection:
    title: str
    source_listing_id: str
    listing_id: str
    overall_count: int
    ended_count: int
    price_end: float | None
    parse_family: str
    issue_code_norm: str | None
    series_key: str | None
    theme_name: str | None
    asset_type: str | None


@dataclass(frozen=True)
class DemoUserSeedResult:
    user_id: str
    profile_tables_cleared: bool
    users_upserted: int
    defaults_upserted: int
    interests_upserted: int
    targets_upserted: int
    holdings_upserted: int
    policies_upserted: int
    selections: tuple[DemoSeedSelection, ...]


DEFAULT_DEMO_INTEREST_SPECS: tuple[DemoInterestSpec, ...] = (
    DemoInterestSpec(
        seed_title="2026年中国龙31.104克普制银币",
        interest_name="中国龙普制银币抢拍",
        interest_kind="watch_buy",
        scope_kind="exact_item",
        precision_mode="exact",
        interest_priority="high",
        allow_related_matches=0,
        allow_series_matches=0,
        allow_variant_matches=0,
        target_label="2026年中国龙31.104克普制银币",
        target_kind="listing_identity",
        normalized_name="中国龙普制银币",
        use_issue_code_norm=False,
        use_issue_part_token=False,
        use_series_key=True,
        use_theme_name=True,
        use_asset_type=True,
        use_year_value=True,
        variant_tokens=("普制", "31.104克"),
        quantity_tokens=(),
        condition_tokens=("评级币",),
        budget_min=None,
        budget_max=1850.0,
        strictness_override="exact",
        priority_override="high",
        intent_confidence=0.96,
        policy_notify_on_preview=1,
        policy_notify_on_live=1,
        policy_notify_on_ended=0,
        policy_notify_on_exact_match=1,
        policy_notify_on_variant_match=0,
        policy_notify_on_series_match=0,
        policy_notify_on_price_opportunity=1,
        policy_notify_on_sell_opportunity=0,
        policy_min_match_score=90.0,
        policy_cooldown_hours=6,
        policy_delivery_mode="immediate",
        policy_max_signals_per_day=6,
        interest_note="High-conviction exact buy watch derived from a high-volume ended dragon silver-coin listing.",
    ),
    DemoInterestSpec(
        seed_title="2026年中国龙31.104克普制银币",
        interest_name="中国龙银币系列捡漏",
        interest_kind="discovery",
        scope_kind="series",
        precision_mode="broad",
        interest_priority="normal",
        allow_related_matches=1,
        allow_series_matches=1,
        allow_variant_matches=1,
        target_label="中国龙银币系列",
        target_kind="series_key",
        normalized_name="中国龙银币系列",
        use_issue_code_norm=False,
        use_issue_part_token=False,
        use_series_key=True,
        use_theme_name=True,
        use_asset_type=True,
        use_year_value=False,
        variant_tokens=(),
        quantity_tokens=(),
        condition_tokens=(),
        budget_min=None,
        budget_max=2200.0,
        strictness_override="broad",
        priority_override="normal",
        intent_confidence=0.7,
        policy_notify_on_preview=1,
        policy_notify_on_live=1,
        policy_notify_on_ended=1,
        policy_notify_on_exact_match=1,
        policy_notify_on_variant_match=1,
        policy_notify_on_series_match=1,
        policy_notify_on_price_opportunity=1,
        policy_notify_on_sell_opportunity=0,
        policy_min_match_score=58.0,
        policy_cooldown_hours=24,
        policy_delivery_mode="daily_digest",
        policy_max_signals_per_day=20,
        interest_note="Broad discovery track for the dragon silver-coin family, tolerant of neighboring years and packaging variants.",
    ),
    DemoInterestSpec(
        seed_title="T43西游记新全",
        interest_name="西游记套票补全",
        interest_kind="collecting",
        scope_kind="issue_family",
        precision_mode="balanced",
        interest_priority="high",
        allow_related_matches=0,
        allow_series_matches=0,
        allow_variant_matches=1,
        target_label="T43西游记",
        target_kind="issue_family",
        normalized_name="西游记",
        use_issue_code_norm=True,
        use_issue_part_token=False,
        use_series_key=True,
        use_theme_name=True,
        use_asset_type=False,
        use_year_value=False,
        variant_tokens=(),
        quantity_tokens=(),
        condition_tokens=("新全",),
        budget_min=None,
        budget_max=260.0,
        strictness_override="balanced",
        priority_override="high",
        intent_confidence=0.83,
        policy_notify_on_preview=1,
        policy_notify_on_live=1,
        policy_notify_on_ended=0,
        policy_notify_on_exact_match=1,
        policy_notify_on_variant_match=1,
        policy_notify_on_series_match=0,
        policy_notify_on_price_opportunity=1,
        policy_notify_on_sell_opportunity=0,
        policy_min_match_score=74.0,
        policy_cooldown_hours=12,
        policy_delivery_mode="daily_digest",
        policy_max_signals_per_day=8,
        interest_note="Family-level collecting interest focused on standard mint-complete Journey to the West material.",
    ),
    DemoInterestSpec(
        seed_title="T89M仕女图型张新",
        interest_name="仕女图型张只收全品",
        interest_kind="watch_buy",
        scope_kind="exact_item",
        precision_mode="exact",
        interest_priority="high",
        allow_related_matches=0,
        allow_series_matches=0,
        allow_variant_matches=0,
        target_label="T89M仕女图型张新",
        target_kind="listing_identity",
        normalized_name="仕女图型张",
        use_issue_code_norm=True,
        use_issue_part_token=False,
        use_series_key=True,
        use_theme_name=True,
        use_asset_type=False,
        use_year_value=False,
        variant_tokens=("型张", "M"),
        quantity_tokens=(),
        condition_tokens=("新", "全品"),
        budget_min=None,
        budget_max=420.0,
        strictness_override="exact",
        priority_override="high",
        intent_confidence=0.94,
        policy_notify_on_preview=1,
        policy_notify_on_live=1,
        policy_notify_on_ended=0,
        policy_notify_on_exact_match=1,
        policy_notify_on_variant_match=0,
        policy_notify_on_series_match=0,
        policy_notify_on_price_opportunity=1,
        policy_notify_on_sell_opportunity=0,
        policy_min_match_score=92.0,
        policy_cooldown_hours=8,
        policy_delivery_mode="immediate",
        policy_max_signals_per_day=5,
        interest_note="Strict condition-sensitive stamp watch where full-quality miniature-sheet examples matter more than related variants.",
    ),
    DemoInterestSpec(
        seed_title="T69M红楼梦型张新",
        interest_name="红楼梦型张持仓卖点",
        interest_kind="watch_sell",
        scope_kind="exact_item",
        precision_mode="exact",
        interest_priority="high",
        allow_related_matches=0,
        allow_series_matches=0,
        allow_variant_matches=0,
        target_label="T69M红楼梦型张新",
        target_kind="listing_identity",
        normalized_name="红楼梦型张",
        use_issue_code_norm=True,
        use_issue_part_token=False,
        use_series_key=True,
        use_theme_name=True,
        use_asset_type=False,
        use_year_value=False,
        variant_tokens=("型张", "M"),
        quantity_tokens=(),
        condition_tokens=("新", "全品"),
        budget_min=None,
        budget_max=None,
        strictness_override="exact",
        priority_override="high",
        intent_confidence=0.93,
        policy_notify_on_preview=0,
        policy_notify_on_live=0,
        policy_notify_on_ended=1,
        policy_notify_on_exact_match=0,
        policy_notify_on_variant_match=0,
        policy_notify_on_series_match=0,
        policy_notify_on_price_opportunity=0,
        policy_notify_on_sell_opportunity=1,
        policy_min_match_score=88.0,
        policy_cooldown_hours=12,
        policy_delivery_mode="immediate",
        policy_max_signals_per_day=4,
        holding_quantity=1.0,
        cost_basis_unit=480.0,
        interest_note="Sell-monitor track for a held miniature-sheet position rather than a new acquisition target.",
        holding_note="Seeded as an owned position with cost basis below recent ended-market levels.",
    ),
)


def seed_curated_demo_user_v2(
    db_path: str,
    *,
    clear_existing_profile_layer: bool = True,
    specs: tuple[DemoInterestSpec, ...] = DEFAULT_DEMO_INTEREST_SPECS,
) -> DemoUserSeedResult:
    SqliteV2Store(db_path).ensure_schema()
    now = now_utc_iso()

    with sqlite3.connect(Path(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        if clear_existing_profile_layer:
            _clear_profile_layer(conn)

        _upsert_demo_user(conn, now=now)
        _upsert_demo_defaults(conn, now=now)

        selections: list[DemoSeedSelection] = []
        interests_upserted = 0
        targets_upserted = 0
        holdings_upserted = 0
        policies_upserted = 0

        for spec in specs:
            listing = _load_seed_listing(conn, spec.seed_title)
            selection = DemoSeedSelection(
                title=str(listing["title"]),
                source_listing_id=str(listing["source_listing_id"]),
                listing_id=str(listing["id"]),
                overall_count=int(listing["overall_count"]),
                ended_count=int(listing["ended_count"]),
                price_end=float(listing["price_end"]) if listing["price_end"] is not None else None,
                parse_family=str(listing["parse_family"]),
                issue_code_norm=_text(listing["issue_code_norm"]),
                series_key=_text(listing["series_key"]),
                theme_name=_text(listing["theme_name"]),
                asset_type=_text(listing["asset_type"]),
            )
            selections.append(selection)

            interest_id = str(uuid.uuid4())
            _insert_interest(conn, spec=spec, listing=listing, interest_id=interest_id, now=now)
            interests_upserted += 1
            _insert_target(conn, spec=spec, listing=listing, interest_id=interest_id, now=now)
            targets_upserted += 1
            _insert_policy(conn, spec=spec, interest_id=interest_id, now=now)
            policies_upserted += 1
            if spec.holding_quantity is not None and spec.cost_basis_unit is not None:
                _insert_holding(conn, spec=spec, listing=listing, interest_id=interest_id, now=now)
                holdings_upserted += 1

        conn.commit()

    return DemoUserSeedResult(
        user_id=DEMO_USER_ID,
        profile_tables_cleared=clear_existing_profile_layer,
        users_upserted=1,
        defaults_upserted=1,
        interests_upserted=interests_upserted,
        targets_upserted=targets_upserted,
        holdings_upserted=holdings_upserted,
        policies_upserted=policies_upserted,
        selections=tuple(selections),
    )


def _clear_profile_layer(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM user_interest_signal_policies_v2")
    conn.execute("DELETE FROM user_interest_targets_v2")
    conn.execute("DELETE FROM user_holdings_v2")
    conn.execute("DELETE FROM user_interests_v2")
    conn.execute("DELETE FROM user_profile_defaults_v2")


def _upsert_demo_user(conn: sqlite3.Connection, *, now: str) -> None:
    conn.execute(
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
            DEMO_USER_ID,
            DEMO_DISPLAY_NAME,
            DEMO_LANGUAGE,
            DEMO_TIMEZONE,
            now,
            now,
        ),
    )


def _upsert_demo_defaults(conn: sqlite3.Connection, *, now: str) -> None:
    conn.execute(
        """
        INSERT INTO user_profile_defaults_v2 (
          user_id,
          default_currency,
          default_precision_mode,
          default_delivery_mode,
          default_min_match_score,
          default_cooldown_hours,
          default_allow_related_matches,
          default_allow_series_matches,
          default_allow_variant_matches,
          notes,
          created_at,
          updated_at
        ) VALUES (?, 'CNY', 'balanced', 'daily_digest', 70, 24, 0, 1, 1, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
          default_allow_series_matches = excluded.default_allow_series_matches,
          default_allow_variant_matches = excluded.default_allow_variant_matches,
          notes = excluded.notes,
          updated_at = excluded.updated_at
        """,
        (
            DEMO_USER_ID,
            "Curated V2 demo profile seeded from common titles with ended listing examples.",
            now,
            now,
        ),
    )


def _load_seed_listing(conn: sqlite3.Connection, title: str) -> sqlite3.Row:
    row = conn.execute(
        """
        WITH overall AS (
          SELECT COUNT(*) AS overall_count
          FROM market_listings_norm_v2
          WHERE title = ?
        ),
        ended AS (
          SELECT COUNT(*) AS ended_count
          FROM market_listings_norm_v2
          WHERE title = ? AND status_raw = '3'
        )
        SELECT
          l.id,
          l.source_listing_id,
          l.title,
          l.price_end,
          l.price_initial,
          l.character_name_raw,
          l.description_character,
          l.end_at,
          p.parse_family,
          p.issue_code_norm,
          p.series_key,
          p.theme_name,
          p.asset_type,
          p.variant_tokens_json,
          p.quantity_tokens_json,
          p.condition_tokens_json,
          p.year_value,
          overall.overall_count,
          ended.ended_count
        FROM market_listings_norm_v2 l
        JOIN listing_parse_v2 p
          ON p.listing_id = l.id
        CROSS JOIN overall
        CROSS JOIN ended
        WHERE l.title = ?
          AND l.status_raw = '3'
        ORDER BY COALESCE(l.end_at, l.updated_at) DESC, l.id DESC
        LIMIT 1
        """,
        (title, title, title),
    ).fetchone()
    if row is None:
        raise ValueError(f"No ended listing found for demo seed title: {title}")
    if int(row["overall_count"]) <= 0:
        raise ValueError(f"No listings found for demo seed title: {title}")
    return row


def _insert_interest(
    conn: sqlite3.Connection,
    *,
    spec: DemoInterestSpec,
    listing: sqlite3.Row,
    interest_id: str,
    now: str,
) -> None:
    note = (
        f"{spec.interest_note or ''} "
        f"Seed row source_listing_id={listing['source_listing_id']} overall={listing['overall_count']} ended={listing['ended_count']}."
    ).strip()
    conn.execute(
        """
        INSERT INTO user_interests_v2 (
          id,
          user_id,
          legacy_user_item_id,
          interest_name,
          interest_kind,
          scope_kind,
          precision_mode,
          interest_priority,
          intent_confidence,
          allow_related_matches,
          allow_series_matches,
          allow_variant_matches,
          active_status,
          notes,
          created_at,
          updated_at
        ) VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)
        """,
        (
            interest_id,
            DEMO_USER_ID,
            spec.interest_name,
            spec.interest_kind,
            spec.scope_kind,
            spec.precision_mode,
            spec.interest_priority,
            spec.intent_confidence,
            spec.allow_related_matches,
            spec.allow_series_matches,
            spec.allow_variant_matches,
            note,
            now,
            now,
        ),
    )


def _insert_target(
    conn: sqlite3.Connection,
    *,
    spec: DemoInterestSpec,
    listing: sqlite3.Row,
    interest_id: str,
    now: str,
) -> None:
    conn.execute(
        """
        INSERT INTO user_interest_targets_v2 (
          id,
          interest_id,
          target_label,
          target_kind,
          parse_family,
          raw_input,
          normalized_name,
          issue_code_norm,
          issue_part_token,
          series_key,
          theme_name,
          asset_type,
          variant_tokens_json,
          quantity_tokens_json,
          condition_tokens_json,
          year_value,
          budget_min,
          budget_max,
          strictness_override,
          priority_override,
          is_active,
          created_at,
          updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
        """,
        (
            str(uuid.uuid4()),
            interest_id,
            spec.target_label,
            spec.target_kind,
            str(listing["parse_family"]),
            str(listing["title"]),
            spec.normalized_name,
            _value_or_none(spec.use_issue_code_norm, listing["issue_code_norm"]),
            _value_or_none(spec.use_issue_part_token, None),
            _value_or_none(spec.use_series_key, listing["series_key"]),
            _value_or_none(spec.use_theme_name, listing["theme_name"]),
            _value_or_none(spec.use_asset_type, listing["asset_type"]),
            _json_text(spec.variant_tokens),
            _json_text(spec.quantity_tokens),
            _json_text(spec.condition_tokens),
            int(listing["year_value"]) if spec.use_year_value and listing["year_value"] is not None else None,
            spec.budget_min,
            spec.budget_max,
            spec.strictness_override,
            spec.priority_override,
            now,
            now,
        ),
    )


def _insert_policy(
    conn: sqlite3.Connection,
    *,
    spec: DemoInterestSpec,
    interest_id: str,
    now: str,
) -> None:
    conn.execute(
        """
        INSERT INTO user_interest_signal_policies_v2 (
          id,
          interest_id,
          notify_on_preview,
          notify_on_live,
          notify_on_ended,
          notify_on_exact_match,
          notify_on_variant_match,
          notify_on_series_match,
          notify_on_price_opportunity,
          notify_on_sell_opportunity,
          min_match_score,
          cooldown_hours,
          delivery_mode,
          max_signals_per_day,
          created_at,
          updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(uuid.uuid4()),
            interest_id,
            spec.policy_notify_on_preview,
            spec.policy_notify_on_live,
            spec.policy_notify_on_ended,
            spec.policy_notify_on_exact_match,
            spec.policy_notify_on_variant_match,
            spec.policy_notify_on_series_match,
            spec.policy_notify_on_price_opportunity,
            spec.policy_notify_on_sell_opportunity,
            spec.policy_min_match_score,
            spec.policy_cooldown_hours,
            spec.policy_delivery_mode,
            spec.policy_max_signals_per_day,
            now,
            now,
        ),
    )


def _insert_holding(
    conn: sqlite3.Connection,
    *,
    spec: DemoInterestSpec,
    listing: sqlite3.Row,
    interest_id: str,
    now: str,
) -> None:
    quantity = float(spec.holding_quantity or 0)
    unit = float(spec.cost_basis_unit or 0)
    total = quantity * unit
    note = (
        f"{spec.holding_note or ''} "
        f"Seed row source_listing_id={listing['source_listing_id']} ended_price={listing['price_end']}."
    ).strip()
    conn.execute(
        """
        INSERT INTO user_holdings_v2 (
          id,
          user_id,
          legacy_user_item_id,
          linked_interest_id,
          raw_input,
          parse_family,
          normalized_name,
          issue_code_norm,
          issue_part_token,
          series_key,
          theme_name,
          asset_type,
          variant_tokens_json,
          quantity_tokens_json,
          condition_tokens_json,
          year_value,
          holding_quantity,
          cost_basis_total,
          cost_basis_unit,
          acquired_at,
          notes,
          is_active,
          created_at,
          updated_at
        ) VALUES (?, ?, NULL, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, 1, ?, ?)
        """,
        (
            str(uuid.uuid4()),
            DEMO_USER_ID,
            interest_id,
            str(listing["title"]),
            str(listing["parse_family"]),
            spec.normalized_name,
            _text(listing["issue_code_norm"]),
            _text(listing["series_key"]),
            _text(listing["theme_name"]),
            _text(listing["asset_type"]),
            _json_text(spec.variant_tokens),
            _json_text(spec.quantity_tokens),
            _json_text(spec.condition_tokens),
            int(listing["year_value"]) if listing["year_value"] is not None else None,
            quantity,
            total,
            unit,
            note,
            now,
            now,
        ),
    )


def _json_text(values: tuple[str, ...]) -> str:
    return json.dumps([value for value in values if value], ensure_ascii=False, separators=(",", ":"))


def _value_or_none(enabled: bool, value: object) -> object:
    return value if enabled else None


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None

