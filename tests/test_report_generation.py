from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path

from ai_agent.reporting.report_service import run_report_generation
from ai_agent.storage.sqlite_raw_store import SqliteRawStore
from ai_agent.user_domain import UserDomainService


def _insert_listing(
    conn: sqlite3.Connection,
    source_listing_id: str,
    *,
    title: str,
    status_norm: str,
    is_active: int,
    price_current: float | None,
    created_at: str,
    end_at: str | None = None,
) -> str:
    listing_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO market_listings_norm (
          id,
          source_platform,
          source_listing_id,
          title,
          status_norm,
          end_at,
          price_current,
          currency,
          is_active,
          first_seen_at,
          last_seen_at,
          created_at,
          updated_at
        ) VALUES (?, 'zhaoonline', ?, ?, ?, ?, ?, 'CNY', ?, ?, ?, ?, ?)
        """,
        (
            listing_id,
            source_listing_id,
            title,
            status_norm,
            end_at,
            price_current,
            is_active,
            created_at,
            created_at,
            created_at,
            created_at,
        ),
    )
    return listing_id


def _insert_match(
    conn: sqlite3.Connection,
    *,
    user_id: str,
    listing_id: str,
    user_item_id: str,
    item_type: str,
    updated_at: str,
) -> None:
    conn.execute(
        """
        INSERT INTO listing_matches (
          id,
          user_id,
          listing_id,
          user_item_id,
          item_type,
          match_score,
          match_reasons_json,
          status,
          matched_at,
          updated_at
        ) VALUES (?, ?, ?, ?, ?, 80, '["item_name_exact"]', 'active', ?, ?)
        """,
        (str(uuid.uuid4()), user_id, listing_id, user_item_id, item_type, updated_at, updated_at),
    )


def _insert_signal(
    conn: sqlite3.Connection,
    *,
    user_id: str,
    listing_id: str,
    signal_type: str,
    created_at: str,
) -> str:
    signal_id = str(uuid.uuid4())
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
        ) VALUES (?, ?, ?, ?, 'daily', 'test_reason', 'medium', 'test_reco', 'active', ?, ?)
        """,
        (signal_id, user_id, listing_id, signal_type, created_at, created_at),
    )
    return signal_id


def test_report_generation_persists_sections_and_signal_links(tmp_path: Path):
    db_path = tmp_path / "agent.db"
    SqliteRawStore(str(db_path)).ensure_schema()
    service = UserDomainService(str(db_path))
    service.upsert_user("u-1")
    watch_match = service.upsert_user_item(
        "u-1",
        "watch",
        category="stamp",
        series="t46",
        item_name="Monkey Ticket",
        priority="high",
    )
    service.upsert_user_item(
        "u-1",
        "watch",
        category="stamp",
        series="jx",
        item_name="Uncovered Item",
        priority="normal",
    )

    with sqlite3.connect(db_path) as conn:
        listing_live = _insert_listing(
            conn,
            "L-live",
            title="Monkey Ticket",
            status_norm="live",
            is_active=1,
            price_current=120.0,
            created_at="2026-03-07T08:00:00+00:00",
            end_at="2026-03-08T08:00:00+00:00",
        )
        listing_ended = _insert_listing(
            conn,
            "L-ended",
            title="Ended Ticket",
            status_norm="ended",
            is_active=0,
            price_current=99.0,
            created_at="2026-03-06T08:00:00+00:00",
            end_at="2026-03-06T10:00:00+00:00",
        )
        listing_stale_unmatched = _insert_listing(
            conn,
            "L-stale",
            title="Stale Unmatched",
            status_norm="live",
            is_active=1,
            price_current=77.0,
            created_at="2026-03-07T07:00:00+00:00",
            end_at="2026-03-08T07:00:00+00:00",
        )
        _insert_match(
            conn,
            user_id="u-1",
            listing_id=listing_live,
            user_item_id=watch_match.id,
            item_type="watch",
            updated_at="2026-03-07T08:30:00+00:00",
        )
        _insert_match(
            conn,
            user_id="u-1",
            listing_id=listing_ended,
            user_item_id=watch_match.id,
            item_type="watch",
            updated_at="2026-03-06T11:00:00+00:00",
        )
        _insert_signal(
            conn,
            user_id="u-1",
            listing_id=listing_live,
            signal_type="new_relevant_listing",
            created_at="2026-03-07T09:00:00+00:00",
        )
        _insert_signal(
            conn,
            user_id="u-1",
            listing_id=listing_live,
            signal_type="buy_opportunity",
            created_at="2026-03-07T09:10:00+00:00",
        )
        _insert_signal(
            conn,
            user_id="u-1",
            listing_id=listing_live,
            signal_type="price_movement",
            created_at="2026-03-07T09:20:00+00:00",
        )
        _insert_signal(
            conn,
            user_id="u-1",
            listing_id=listing_stale_unmatched,
            signal_type="new_relevant_listing",
            created_at="2026-03-07T09:30:00+00:00",
        )
        conn.commit()

    result = run_report_generation(
        str(db_path),
        user_id="u-1",
        report_date="2026-03-07",
        report_type="daily",
    )
    assert result.generated_reports == 1
    assert result.linked_signals == 3

    with sqlite3.connect(db_path) as conn:
        report_row = conn.execute(
            """
            SELECT id, content_payload_json
            FROM reports
            WHERE user_id = 'u-1'
              AND report_date = '2026-03-07'
              AND report_type = 'daily'
            """
        ).fetchone()
        assert report_row is not None
        payload = json.loads(str(report_row[1]))
        sections = payload["sections"]
        assert "new_relevant_auctions_listings" in sections
        assert "buy_opportunities" in sections
        assert "sell_opportunities" in sections
        assert "price_movement_summary" in sections
        assert "missed_expired_opportunities" in sections
        assert "watchlist_coverage" in sections
        assert len(sections["missed_expired_opportunities"]) >= 1
        assert sections["watchlist_coverage"]["watch_items_total"] == 2
        assert sections["watchlist_coverage"]["watch_items_matched"] == 1
        assert len(sections["new_relevant_auctions_listings"]) == 1

        link_count = conn.execute(
            "SELECT COUNT(*) FROM report_signal_links WHERE report_id = ?",
            (str(report_row[0]),),
        ).fetchone()[0]
        assert int(link_count) == 3


def test_report_generation_is_idempotent_per_user_date_type(tmp_path: Path):
    db_path = tmp_path / "agent.db"
    SqliteRawStore(str(db_path)).ensure_schema()
    service = UserDomainService(str(db_path))
    service.upsert_user("u-2")
    item = service.upsert_user_item(
        "u-2",
        "watch",
        category="coin",
        series="panda",
        item_name="1983 Panda 1oz",
        priority="normal",
    )

    with sqlite3.connect(db_path) as conn:
        listing = _insert_listing(
            conn,
            "L-uniq",
            title="1983 Panda 1oz",
            status_norm="live",
            is_active=1,
            price_current=1000.0,
            created_at="2026-03-07T01:00:00+00:00",
        )
        _insert_match(
            conn,
            user_id="u-2",
            listing_id=listing,
            user_item_id=item.id,
            item_type="watch",
            updated_at="2026-03-07T01:10:00+00:00",
        )
        _insert_signal(
            conn,
            user_id="u-2",
            listing_id=listing,
            signal_type="new_relevant_listing",
            created_at="2026-03-07T02:00:00+00:00",
        )
        conn.commit()

    first = run_report_generation(str(db_path), user_id="u-2", report_date="2026-03-07", report_type="daily")
    second = run_report_generation(str(db_path), user_id="u-2", report_date="2026-03-07", report_type="daily")
    assert first.generated_reports == 1
    assert second.generated_reports == 1

    with sqlite3.connect(db_path) as conn:
        report_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM reports
            WHERE user_id = 'u-2'
              AND report_date = '2026-03-07'
              AND report_type = 'daily'
            """
        ).fetchone()[0]
    assert int(report_count) == 1


def test_report_generation_exports_markdown_file(tmp_path: Path):
    db_path = tmp_path / "agent.db"
    reports_dir = tmp_path / "reports_out"
    SqliteRawStore(str(db_path)).ensure_schema()
    service = UserDomainService(str(db_path))
    service.upsert_user("u-3")
    item = service.upsert_user_item(
        "u-3",
        "watch",
        category="coin",
        series="panda",
        item_name="1983 Panda 1oz",
        priority="normal",
    )

    with sqlite3.connect(db_path) as conn:
        listing = _insert_listing(
            conn,
            "L-md",
            title="1983 Panda 1oz",
            status_norm="live",
            is_active=1,
            price_current=1000.0,
            created_at="2026-03-07T01:00:00+00:00",
        )
        _insert_match(
            conn,
            user_id="u-3",
            listing_id=listing,
            user_item_id=item.id,
            item_type="watch",
            updated_at="2026-03-07T01:10:00+00:00",
        )
        _insert_signal(
            conn,
            user_id="u-3",
            listing_id=listing,
            signal_type="new_relevant_listing",
            created_at="2026-03-07T02:00:00+00:00",
        )
        conn.commit()

    result = run_report_generation(
        str(db_path),
        user_id="u-3",
        report_date="2026-03-07",
        report_type="daily",
        export_markdown=True,
        reports_dir=str(reports_dir),
        max_items_per_section=10,
    )
    assert result.generated_reports == 1
    assert result.exported_markdown_files == 1

    out_file = reports_dir / "report_u-3_2026-03-07_daily.md"
    assert out_file.exists()
    content = out_file.read_text(encoding="utf-8")
    assert "# Report - u-3 - 2026-03-07 (daily)" in content
    assert "## 1) New Relevant Auctions/Listings" in content
    assert "## 6) Watchlist Coverage" in content


def test_report_generation_exports_humanized_file_without_api_key(tmp_path: Path):
    db_path = tmp_path / "agent.db"
    reports_dir = tmp_path / "reports_out"
    SqliteRawStore(str(db_path)).ensure_schema()
    service = UserDomainService(str(db_path))
    service.upsert_user("u-4")
    item = service.upsert_user_item(
        "u-4",
        "watch",
        category="coin",
        series="panda",
        item_name="1983 Panda 1oz",
        priority="normal",
    )

    with sqlite3.connect(db_path) as conn:
        listing = _insert_listing(
            conn,
            "L-human",
            title="1983 Panda 1oz",
            status_norm="live",
            is_active=1,
            price_current=1000.0,
            created_at="2026-03-07T01:00:00+00:00",
        )
        _insert_match(
            conn,
            user_id="u-4",
            listing_id=listing,
            user_item_id=item.id,
            item_type="watch",
            updated_at="2026-03-07T01:10:00+00:00",
        )
        _insert_signal(
            conn,
            user_id="u-4",
            listing_id=listing,
            signal_type="new_relevant_listing",
            created_at="2026-03-07T02:00:00+00:00",
        )
        conn.commit()

    result = run_report_generation(
        str(db_path),
        user_id="u-4",
        report_date="2026-03-07",
        report_type="daily",
        export_markdown=True,
        reports_dir=str(reports_dir),
        max_items_per_section=10,
        llm_humanize=True,
    )
    assert result.generated_reports == 1
    assert result.exported_markdown_files == 1
    assert result.exported_humanized_files == 1

    human_file = reports_dir / "report_u-4_2026-03-07_daily_human.md"
    assert human_file.exists()
    content = human_file.read_text(encoding="utf-8")
    assert "LLM rendering skipped because `OPENAI_API_KEY` is not configured." in content
