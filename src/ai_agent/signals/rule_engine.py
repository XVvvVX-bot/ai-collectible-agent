from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ai_agent.clients.zhaoonline import now_utc_iso
from ai_agent.storage.sqlite_raw_store import SqliteRawStore


@dataclass(frozen=True)
class SignalRunResult:
    users_processed: int
    matches_scanned: int
    candidates: int
    inserted: int
    skipped_cooldown: int
    skipped_duplicate_run: int
    inserted_by_type: dict[str, int]
    inserted_by_urgency: dict[str, int]


@dataclass(frozen=True)
class _SignalCandidate:
    user_id: str
    listing_id: str
    signal_type: str
    reason_code: str
    confidence_level: str
    recommendation_text: str
    urgency: str


def run_rule_signal_generation(
    db_path: str,
    *,
    user_id: str | None = None,
    cooldown_hours: int = 24,
    freshness_hours: int = 24,
    price_move_threshold_pct: float = 10.0,
) -> SignalRunResult:
    if cooldown_hours < 0:
        raise ValueError("cooldown_hours must be >= 0.")
    if freshness_hours < 0:
        raise ValueError("freshness_hours must be >= 0.")
    if price_move_threshold_pct < 0:
        raise ValueError("price_move_threshold_pct must be >= 0.")

    store = SqliteRawStore(db_path)
    store.ensure_schema()
    db_file = Path(db_path)

    with sqlite3.connect(db_file) as conn:
        conn.row_factory = sqlite3.Row
        users = _load_users(conn, user_id=user_id)
        now = _parse_iso(now_utc_iso())
        cooldown_cutoff = now - timedelta(hours=cooldown_hours)
        freshness_cutoff = now - timedelta(hours=freshness_hours)

        users_processed = len(users)
        matches_scanned = 0
        candidates = 0
        inserted = 0
        skipped_cooldown = 0
        skipped_duplicate_run = 0
        inserted_by_type: dict[str, int] = {}
        inserted_by_urgency: dict[str, int] = {}
        seen_in_run: set[tuple[str, str, str, str]] = set()

        for user in users:
            uid = str(user["id"])
            pref = _load_user_preferences(conn, uid)
            match_rows = _load_active_matches(conn, uid)
            matches_scanned += len(match_rows)
            for row in match_rows:
                row_candidates = _build_candidates(
                    row=row,
                    pref=pref,
                    freshness_cutoff=freshness_cutoff,
                    price_move_threshold_pct=price_move_threshold_pct,
                )
                for candidate in row_candidates:
                    candidates += 1
                    dedupe_key = (
                        candidate.user_id,
                        candidate.listing_id,
                        candidate.signal_type,
                        candidate.reason_code,
                    )
                    if dedupe_key in seen_in_run:
                        skipped_duplicate_run += 1
                        continue
                    seen_in_run.add(dedupe_key)

                    if _is_in_cooldown(conn, candidate, cooldown_cutoff):
                        skipped_cooldown += 1
                        continue

                    _insert_signal(conn, candidate, now)
                    inserted += 1
                    inserted_by_type[candidate.signal_type] = (
                        inserted_by_type.get(candidate.signal_type, 0) + 1
                    )
                    inserted_by_urgency[candidate.urgency] = (
                        inserted_by_urgency.get(candidate.urgency, 0) + 1
                    )

        conn.commit()

    return SignalRunResult(
        users_processed=users_processed,
        matches_scanned=matches_scanned,
        candidates=candidates,
        inserted=inserted,
        skipped_cooldown=skipped_cooldown,
        skipped_duplicate_run=skipped_duplicate_run,
        inserted_by_type=inserted_by_type,
        inserted_by_urgency=inserted_by_urgency,
    )


def _build_candidates(
    *,
    row: sqlite3.Row,
    pref: dict[str, Any],
    freshness_cutoff: datetime,
    price_move_threshold_pct: float,
) -> list[_SignalCandidate]:
    user_id = str(row["user_id"])
    listing_id = str(row["listing_id"])
    item_type = str(row["item_type"])
    match_score = float(row["match_score"] or 0.0)
    reasons = _parse_json_list(row["match_reasons_json"])
    title = str(row["title"] or "")
    created_at = _parse_iso(str(row["created_at"]))
    status_norm = str(row["status_norm"] or "")

    is_high_interest = bool(pref["high_interest_flag"])
    keyword_hit = _has_keyword_hit(title, pref["keywords"])

    confidence_level = _confidence_from_score(match_score)
    urgency_default = "immediate" if (is_high_interest and keyword_hit) else "daily"

    out: list[_SignalCandidate] = []

    if status_norm in {"preview", "live"} and created_at >= freshness_cutoff:
        out.append(
            _SignalCandidate(
                user_id=user_id,
                listing_id=listing_id,
                signal_type="new_relevant_listing",
                reason_code="matched_active_listing_recent",
                confidence_level=confidence_level,
                recommendation_text="Relevant active listing detected.",
                urgency=urgency_default,
            )
        )

    current = _to_float(row["price_current"])
    initial = _to_float(row["price_initial"])
    end_price = _to_float(row["price_end"])
    quantity = _to_float(row["quantity"])
    cost_basis_total = _to_float(row["cost_basis_total"])
    max_buy_price = _to_float(row["max_buy_price"])

    if item_type == "watch":
        if current is not None and max_buy_price is not None and current <= max_buy_price:
            out.append(
                _SignalCandidate(
                    user_id=user_id,
                    listing_id=listing_id,
                    signal_type="buy_opportunity",
                    reason_code="price_below_watch_budget",
                    confidence_level=confidence_level,
                    recommendation_text="Current price is at or below your watch budget.",
                    urgency=_immediate_if_high_interest(is_high_interest),
                )
            )
        elif current is not None and initial is not None and current <= initial * 0.95:
            out.append(
                _SignalCandidate(
                    user_id=user_id,
                    listing_id=listing_id,
                    signal_type="buy_opportunity",
                    reason_code="price_below_initial_threshold",
                    confidence_level=confidence_level,
                    recommendation_text="Current price is materially below initial price.",
                    urgency=_immediate_if_high_interest(is_high_interest),
                )
            )

    if item_type == "holding":
        if (
            current is not None
            and cost_basis_total is not None
            and quantity is not None
            and quantity > 0
            and current >= (cost_basis_total / quantity) * 1.2
        ):
            out.append(
                _SignalCandidate(
                    user_id=user_id,
                    listing_id=listing_id,
                    signal_type="sell_opportunity",
                    reason_code="price_above_cost_basis_threshold",
                    confidence_level=confidence_level,
                    recommendation_text="Current price is well above your cost basis reference.",
                    urgency=_immediate_if_high_interest(is_high_interest),
                )
            )

    move_pct = _price_move_pct(initial, current if current is not None else end_price)
    if move_pct is not None and abs(move_pct) >= price_move_threshold_pct:
        code = "price_move_up_large" if move_pct > 0 else "price_move_down_large"
        out.append(
            _SignalCandidate(
                user_id=user_id,
                listing_id=listing_id,
                signal_type="price_movement",
                reason_code=code,
                confidence_level=confidence_level,
                recommendation_text="Significant price movement detected.",
                urgency="daily",
            )
        )

    # deterministic reason enrichment
    if "category_exact" in reasons and "series_exact" in reasons:
        out = [
            _SignalCandidate(
                user_id=c.user_id,
                listing_id=c.listing_id,
                signal_type=c.signal_type,
                reason_code=c.reason_code,
                confidence_level=_bump_confidence(c.confidence_level),
                recommendation_text=c.recommendation_text,
                urgency=c.urgency,
            )
            for c in out
        ]
    return out


def _insert_signal(conn: sqlite3.Connection, candidate: _SignalCandidate, now: datetime) -> None:
    now_iso = now.replace(tzinfo=timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO signals (
          id,
          user_id,
          listing_id,
          signal_type,
          urgency,
          reason_code,
          confidence_level,
          recommendation_text,
          status,
          created_at,
          updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
        """,
        (
            str(uuid.uuid4()),
            candidate.user_id,
            candidate.listing_id,
            candidate.signal_type,
            candidate.urgency,
            candidate.reason_code,
            candidate.confidence_level,
            candidate.recommendation_text,
            now_iso,
            now_iso,
        ),
    )


def _is_in_cooldown(conn: sqlite3.Connection, candidate: _SignalCandidate, cutoff: datetime) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM signals
        WHERE user_id = ?
          AND listing_id = ?
          AND signal_type = ?
          AND reason_code = ?
          AND created_at >= ?
        LIMIT 1
        """,
        (
            candidate.user_id,
            candidate.listing_id,
            candidate.signal_type,
            candidate.reason_code,
            cutoff.replace(tzinfo=timezone.utc).isoformat(),
        ),
    ).fetchone()
    return row is not None


def _load_active_matches(conn: sqlite3.Connection, user_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT
          lm.user_id,
          lm.listing_id,
          lm.item_type,
          lm.match_score,
          lm.match_reasons_json,
          n.title,
          n.created_at,
          n.status_norm,
          n.price_initial,
          n.price_current,
          n.price_end,
          ui.quantity,
          ui.cost_basis_total,
          ui.max_buy_price
        FROM listing_matches lm
        JOIN market_listings_norm n ON n.id = lm.listing_id
        JOIN user_items ui ON ui.id = lm.user_item_id
        WHERE lm.user_id = ?
          AND lm.status = 'active'
          AND n.is_active = 1
          AND ui.is_active = 1
        ORDER BY lm.listing_id, lm.user_item_id
        """,
        (user_id,),
    ).fetchall()


def _load_users(conn: sqlite3.Connection, *, user_id: str | None) -> list[sqlite3.Row]:
    if user_id:
        row = conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            raise ValueError(f"user not found: {user_id}")
        return [row]
    return conn.execute("SELECT id FROM users ORDER BY id").fetchall()


def _load_user_preferences(conn: sqlite3.Connection, user_id: str) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT high_interest_flag, keywords_json
        FROM user_preferences
        WHERE user_id = ?
        """,
        (user_id,),
    ).fetchone()
    if row is None:
        return {"high_interest_flag": 0, "keywords": []}
    keywords = _parse_json_list(row["keywords_json"])
    return {
        "high_interest_flag": int(row["high_interest_flag"] or 0),
        "keywords": [str(x).strip().lower() for x in keywords if str(x).strip()],
    }


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _parse_json_list(value: Any) -> list[Any]:
    if value in (None, ""):
        return []
    try:
        payload = json.loads(str(value))
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    return payload


def _has_keyword_hit(title: str, keywords: list[str]) -> bool:
    text = title.lower().strip()
    if not text or not keywords:
        return False
    return any(keyword in text for keyword in keywords)


def _confidence_from_score(score: float) -> str:
    if score >= 80:
        return "high"
    if score >= 45:
        return "medium"
    return "low"


def _bump_confidence(value: str) -> str:
    if value == "low":
        return "medium"
    if value == "medium":
        return "high"
    return "high"


def _immediate_if_high_interest(is_high_interest: bool) -> str:
    return "immediate" if is_high_interest else "daily"


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _price_move_pct(initial: float | None, current: float | None) -> float | None:
    if initial is None or current is None or initial == 0:
        return None
    return ((current - initial) / initial) * 100.0
