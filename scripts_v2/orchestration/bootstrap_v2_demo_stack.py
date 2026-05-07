#!/usr/bin/env python3
"""Load local UTF-8 market fixtures + curated demo profile, matching, and signals."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ai_agent_v2.clients.zhaoonline import now_utc_iso
from ai_agent_v2.config import ZhaoV2Config
from ai_agent_v2.parsing.listing_parser import SOURCE_PLATFORM, run_listing_parse_v2
from ai_agent_v2.profile.demo_user_seed import DEFAULT_DEMO_INTEREST_SPECS, DEMO_USER_ID, seed_curated_demo_user_v2
from ai_agent_v2.storage.sqlite_store import SqliteV2Store

FIXTURE_PREFIX = "local_demo_fixture_"


def _slug(title: str) -> str:
    return hashlib.sha256(title.encode("utf-8")).hexdigest()[:12]


def _delete_fixtures(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        DELETE FROM listing_parse_v2
        WHERE source_platform = ? AND substr(source_listing_id, 1, ?) = ?
        """,
        (SOURCE_PLATFORM, len(FIXTURE_PREFIX), FIXTURE_PREFIX),
    )
    conn.execute(
        f"""
        DELETE FROM market_listings_norm_v2
        WHERE source_platform = ? AND substr(source_listing_id, 1, ?) = ?
        """,
        (SOURCE_PLATFORM, len(FIXTURE_PREFIX), FIXTURE_PREFIX),
    )


def _insert_pair(
    conn: sqlite3.Connection,
    *,
    title: str,
    category_name_raw: str,
    now: str,
) -> tuple[str, str]:
    slug = _slug(title)
    src_ended = f"{FIXTURE_PREFIX}{slug}_e"
    src_live = f"{FIXTURE_PREFIX}{slug}_l"
    lid_ended = f"fx_{slug}_ended"
    lid_live = f"fx_{slug}_live"

    conn.execute(
        """
        INSERT INTO market_listings_norm_v2 (
          id, source_platform, source_listing_id, title, status_raw, status_norm,
          category_name_raw,
          character_name_raw, description_character,
          price_initial, price_end, end_at,
          first_seen_at, last_seen_at, created_at, updated_at
        ) VALUES (
          ?, ?, ?, ?, '3', 'ended',
          ?,
          NULL, NULL,
          1400.0, 1740.0, ?,
          ?, ?, ?, ?
        )
        """,
        (lid_ended, SOURCE_PLATFORM, src_ended, title, category_name_raw, now, now, now, now, now),
    )
    conn.execute(
        """
        INSERT INTO market_listings_norm_v2 (
          id, source_platform, source_listing_id, title, status_raw, status_norm,
          category_name_raw,
          character_name_raw, description_character,
          price_initial, price_end, end_at,
          first_seen_at, last_seen_at, created_at, updated_at
        ) VALUES (
          ?, ?, ?, ?, '2', 'live',
          ?,
          NULL, NULL,
          1500.0, NULL, NULL,
          ?, ?, ?, ?
        )
        """,
        (lid_live, SOURCE_PLATFORM, src_live, title, category_name_raw, now, now, now, now),
    )
    return src_ended, src_live


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", default=ZhaoV2Config.from_env().database_path)
    parser.add_argument("--skip-matching", action="store_true")
    parser.add_argument("--skip-signals", action="store_true")
    parser.add_argument("--lookback-hours", type=int, default=24)
    args = parser.parse_args()

    db_path = args.db_path
    SqliteV2Store(db_path).ensure_schema()
    now = now_utc_iso()

    specs = tuple(DEFAULT_DEMO_INTEREST_SPECS)
    titles = sorted({spec.seed_title for spec in specs})
    slug_by_title = {title: _slug(title) for title in titles}

    with sqlite3.connect(db_path) as conn:
        _delete_fixtures(conn)
        src_ids: list[str] = []
        for title in titles:
            category = "纪念币-银" if title.startswith("2026年") else "JT邮票"
            se, sl = _insert_pair(conn, title=title, category_name_raw=category, now=now)
            src_ids.extend((se, sl))
        dragon_slug = slug_by_title["2026年中国龙31.104克普制银币"]
        for lid in (f"fx_{dragon_slug}_ended", f"fx_{dragon_slug}_live"):
            conn.execute(
                """
                UPDATE market_listings_norm_v2
                SET character_name_raw = '评级币', description_character = '首日发行'
                WHERE id = ?
                """,
                (lid,),
            )
        conn.commit()

    run_listing_parse_v2(db_path, source_listing_ids=src_ids)

    seed_curated_demo_user_v2(db_path, clear_existing_profile_layer=True, specs=specs)

    with sqlite3.connect(db_path) as conn:
        conn.execute("DELETE FROM listing_matches_v2 WHERE user_id = ?", (DEMO_USER_ID,))
        conn.execute("DELETE FROM signals_v2 WHERE user_id = ?", (DEMO_USER_ID,))
        conn.commit()

    if not args.skip_matching:
        from ai_agent_v2.matching.v2_matcher import run_v2_matching

        run_v2_matching(db_path, user_id=DEMO_USER_ID, only_active_listings=True)

    if not args.skip_signals:
        from ai_agent_v2.signals.interest_signals import run_interest_signal_generation

        run_interest_signal_generation(db_path, user_id=DEMO_USER_ID, lookback_hours=args.lookback_hours)

    with sqlite3.connect(db_path) as conn:
        n_int = conn.execute(
            "SELECT COUNT(*) FROM user_interests_v2 WHERE user_id = ?",
            (DEMO_USER_ID,),
        ).fetchone()[0]
        n_match = conn.execute(
            "SELECT COUNT(*) FROM listing_matches_v2 WHERE user_id = ? AND status = 'active'",
            (DEMO_USER_ID,),
        ).fetchone()[0]
        n_sig = conn.execute(
            "SELECT COUNT(*) FROM signals_v2 WHERE user_id = ? AND status = 'active'",
            (DEMO_USER_ID,),
        ).fetchone()[0]

    print(
        json.dumps(
            {
                "ok": True,
                "db_path": db_path,
                "user_id": DEMO_USER_ID,
                "interests": int(n_int),
                "active_matches": int(n_match),
                "active_signals": int(n_sig),
                "fixture_titles": titles,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
