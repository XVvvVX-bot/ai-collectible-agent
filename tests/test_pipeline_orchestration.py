from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

from ai_agent.clients.zhaoonline import now_utc_iso
from ai_agent.orchestration.pipeline import PipelineRunner, PipelineRunnerConfig
from ai_agent.storage.sqlite_raw_store import SqliteRawStore
from ai_agent.user_domain import UserDomainService


def _insert_listing(
    conn: sqlite3.Connection,
    source_listing_id: str,
    *,
    title: str,
    category_norm: str,
    series_norm: str,
    status_norm: str,
    price_initial: float,
    price_current: float,
) -> str:
    listing_id = str(uuid.uuid4())
    observed_at = now_utc_iso()
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
        ) VALUES (?, 'zhaoonline', ?, ?, ?, ?, ?, ?, ?, 'CNY', 1, ?, ?, ?, ?)
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
            observed_at,
            observed_at,
            observed_at,
            observed_at,
        ),
    )
    return listing_id


def test_pipeline_runner_persists_run_state_and_alert_dispatch(tmp_path: Path):
    db_path = tmp_path / "agent.db"
    SqliteRawStore(str(db_path)).ensure_schema()
    service = UserDomainService(str(db_path))
    service.upsert_user("u-1")
    service.upsert_user_preferences("u-1", high_interest_flag=True, keywords=["monkey"])
    service.upsert_user_item(
        "u-1",
        "watch",
        category="stamp",
        series="t46",
        item_name="Monkey Ticket",
        priority="high",
        max_buy_price=100.0,
    )
    with sqlite3.connect(db_path) as conn:
        _insert_listing(
            conn,
            "L-1",
            title="Monkey Ticket",
            category_norm="stamp",
            series_norm="t46",
            status_norm="live",
            price_initial=150.0,
            price_current=90.0,
        )
        conn.commit()

    report_date = now_utc_iso()[:10]
    config = PipelineRunnerConfig(
        db_path=str(db_path),
        user_id="u-1",
        report_date=report_date,
        run_ingestion=False,
        run_normalization=False,
        run_taxonomy_observability=False,
    )
    first = PipelineRunner(config).run()
    assert first.status == "success"
    stage_names = [x.stage for x in first.stage_results]
    assert stage_names == [
        "norm_quality_checks",
        "matching",
        "signals",
        "immediate_alert_dispatch",
        "market_metrics",
        "report_generation",
    ]

    second = PipelineRunner(config).run()
    assert second.status == "success"
    alert_stage = [x for x in second.stage_results if x.stage == "immediate_alert_dispatch"][0]
    assert int(alert_stage.metrics["dispatched_new"]) == 0
    assert int(alert_stage.metrics["skipped_already_dispatched"]) >= 1

    with sqlite3.connect(db_path) as conn:
        run_count = conn.execute("SELECT COUNT(*) FROM orchestration_runs").fetchone()[0]
        stage_count = conn.execute("SELECT COUNT(*) FROM orchestration_stage_runs").fetchone()[0]
        dispatched_count = conn.execute("SELECT COUNT(*) FROM alert_dispatch_log").fetchone()[0]
    assert int(run_count) == 2
    assert int(stage_count) == 12
    assert int(dispatched_count) >= 1
