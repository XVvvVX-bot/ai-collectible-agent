from __future__ import annotations

import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median

from ai_agent.clients.zhaoonline import now_utc_iso
from ai_agent.storage.sqlite_raw_store import SqliteRawStore


@dataclass(frozen=True)
class MarketMetricsRunResult:
    rows_scanned: int
    groups_built: int
    upserted: int
    window_days: int
    provisional_groups: int
    full_window_groups: int


@dataclass(frozen=True)
class _MetricPoint:
    price: float
    observed_at: datetime


def run_market_metrics(
    db_path: str,
    *,
    window_days: int = 30,
    full_window_days: int = 30,
) -> MarketMetricsRunResult:
    if window_days <= 0:
        raise ValueError("window_days must be > 0.")
    if full_window_days <= 0:
        raise ValueError("full_window_days must be > 0.")

    store = SqliteRawStore(db_path)
    store.ensure_schema()

    now = _parse_iso(now_utc_iso())
    cutoff = now - timedelta(days=window_days)

    db_file = Path(db_path)
    with sqlite3.connect(db_file) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT
              source_platform,
              source_listing_id,
              category_norm,
              series_norm,
              title,
              COALESCE(last_seen_at, created_at, first_seen_at) AS observed_at,
              price_end,
              price_current,
              price_initial
            FROM market_listings_norm
            WHERE COALESCE(price_end, price_current, price_initial) IS NOT NULL
              AND COALESCE(last_seen_at, created_at, first_seen_at) >= ?
            ORDER BY source_platform, observed_at, id
            """,
            (cutoff.replace(tzinfo=timezone.utc).isoformat(),),
        ).fetchall()

        grouped: dict[tuple[str, str], list[_MetricPoint]] = {}
        for row in rows:
            price = _pick_price(row)
            if price is None:
                continue
            observed_at_raw = str(row["observed_at"] or "")
            if not observed_at_raw:
                continue
            source_platform = str(row["source_platform"] or "unknown").strip() or "unknown"
            item_key = _build_item_key(
                category_norm=row["category_norm"],
                series_norm=row["series_norm"],
                title=row["title"],
                source_listing_id=row["source_listing_id"],
            )
            grouped.setdefault((source_platform, item_key), []).append(
                _MetricPoint(
                    price=price,
                    observed_at=_parse_iso(observed_at_raw),
                )
            )

        provisional_groups = 0
        full_window_groups = 0
        upserted = 0
        computed_at = now.replace(tzinfo=timezone.utc).isoformat()
        for (source_platform, item_key), points in grouped.items():
            points.sort(key=lambda x: x.observed_at)
            stats = _compute_stats(points)
            coverage_days = _coverage_days(points)
            is_temporary = 1 if coverage_days < full_window_days else 0
            if is_temporary:
                provisional_groups += 1
            else:
                full_window_groups += 1
            confidence_level = _confidence_level(
                sample_count=stats["sample_count"],
                coverage_days=coverage_days,
                full_window_days=full_window_days,
            )

            conn.execute(
                """
                INSERT INTO market_metrics (
                  id,
                  item_key,
                  source_platform,
                  window_days,
                  sample_count,
                  price_avg,
                  price_median,
                  price_min,
                  price_max,
                  trend_direction,
                  data_coverage_days,
                  confidence_level,
                  is_temporary,
                  computed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(item_key, source_platform, window_days) DO UPDATE SET
                  sample_count = excluded.sample_count,
                  price_avg = excluded.price_avg,
                  price_median = excluded.price_median,
                  price_min = excluded.price_min,
                  price_max = excluded.price_max,
                  trend_direction = excluded.trend_direction,
                  data_coverage_days = excluded.data_coverage_days,
                  confidence_level = excluded.confidence_level,
                  is_temporary = excluded.is_temporary,
                  computed_at = excluded.computed_at
                """,
                (
                    str(uuid.uuid4()),
                    item_key,
                    source_platform,
                    window_days,
                    stats["sample_count"],
                    stats["price_avg"],
                    stats["price_median"],
                    stats["price_min"],
                    stats["price_max"],
                    stats["trend_direction"],
                    coverage_days,
                    confidence_level,
                    is_temporary,
                    computed_at,
                ),
            )
            upserted += 1

        conn.commit()

    return MarketMetricsRunResult(
        rows_scanned=len(rows),
        groups_built=len(grouped),
        upserted=upserted,
        window_days=window_days,
        provisional_groups=provisional_groups,
        full_window_groups=full_window_groups,
    )


def _build_item_key(
    *,
    category_norm: str | None,
    series_norm: str | None,
    title: str | None,
    source_listing_id: str | None,
) -> str:
    category = _normalize_token(category_norm)
    series = _normalize_token(series_norm)
    title_norm = _normalize_token(title)
    listing = _normalize_token(source_listing_id)

    if category and series:
        return f"category:{category}|series:{series}"
    if category and title_norm:
        return f"category:{category}|title:{title_norm}"
    if series and title_norm:
        return f"series:{series}|title:{title_norm}"
    if title_norm:
        return f"title:{title_norm}"
    if listing:
        return f"listing:{listing}"
    return "unknown"


def _normalize_token(value: str | None) -> str:
    if value is None:
        return ""
    text = str(value).strip().lower()
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text)
    return text


def _pick_price(row: sqlite3.Row) -> float | None:
    for key in ("price_end", "price_current", "price_initial"):
        price = _to_float(row[key])
        if price is not None:
            return price
    return None


def _coverage_days(points: list[_MetricPoint]) -> int:
    return len({p.observed_at.date().isoformat() for p in points})


def _compute_stats(points: list[_MetricPoint]) -> dict[str, float | int | str]:
    prices = [p.price for p in points]
    sample_count = len(prices)
    first_price = prices[0]
    last_price = prices[-1]
    trend_direction = _trend_direction(first_price=first_price, last_price=last_price)
    return {
        "sample_count": sample_count,
        "price_avg": sum(prices) / sample_count,
        "price_median": float(median(prices)),
        "price_min": min(prices),
        "price_max": max(prices),
        "trend_direction": trend_direction,
    }


def _trend_direction(*, first_price: float, last_price: float) -> str:
    if first_price <= 0:
        return "flat"
    pct = ((last_price - first_price) / first_price) * 100.0
    if pct > 2.0:
        return "up"
    if pct < -2.0:
        return "down"
    return "flat"


def _confidence_level(*, sample_count: int, coverage_days: int, full_window_days: int) -> str:
    medium_floor = min(full_window_days, 21)
    low_floor = min(full_window_days, 7)
    if coverage_days < low_floor or sample_count < 5:
        return "low"
    if coverage_days < medium_floor or sample_count < 15:
        return "medium"
    return "high"


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _to_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
