from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Callable

from ai_agent.clients.zhaoonline import ZhaoClient, now_utc_iso
from ai_agent.config import ZhaoConfig
from ai_agent.ingestion.raw_ingest import FileRateLimiter, RawIngestionJob
from ai_agent.matching.v1_matcher import run_v1_matching
from ai_agent.metrics.market_metrics import run_market_metrics
from ai_agent.normalization.zhaoonline_norm import normalize_zhaoonline_raw
from ai_agent.quality.norm_quality import run_norm_quality_checks
from ai_agent.reporting.report_service import run_report_generation
from ai_agent.signals.rule_engine import run_rule_signal_generation
from ai_agent.storage.sqlite_raw_store import SqliteRawStore
from ai_agent.taxonomy.zhaoonline_taxonomy import get_unmapped_report


StageFn = Callable[[], dict[str, Any]]


@dataclass(frozen=True)
class PipelineRunnerConfig:
    db_path: str
    user_id: str | None = None
    report_date: str | None = None
    run_ingestion: bool = True
    run_normalization: bool = True
    run_taxonomy_observability: bool = True
    run_quality_checks: bool = True
    run_matching: bool = True
    run_signals: bool = True
    run_alert_dispatch: bool = True
    run_market_metrics: bool = True
    run_reports: bool = True
    max_stage_retries: int = 2
    normalization_batch_size: int = 1000000
    quality_batch_size: int = 2000
    matching_min_score: float = 30.0
    strict_name_match: bool = True
    cooldown_hours: int = 24
    freshness_hours: int = 24
    price_move_threshold_pct: float = 10.0
    metrics_window_days: int = 30
    metrics_full_window_days: int = 30
    report_type: str = "daily"
    max_report_items_per_section: int = 50
    call_budget_per_run: int = 30
    fresh_pages_per_status: int = 2


@dataclass(frozen=True)
class StageRunResult:
    stage: str
    status: str
    attempts: int
    metrics: dict[str, Any]
    error: str | None = None


@dataclass(frozen=True)
class PipelineRunResult:
    run_id: str
    status: str
    started_at: str
    finished_at: str
    stage_results: list[StageRunResult]


class PipelineRunner:
    def __init__(self, config: PipelineRunnerConfig):
        if config.max_stage_retries < 1:
            raise ValueError("max_stage_retries must be >= 1.")
        self.config = config
        self.db_path = Path(config.db_path)
        self.store = SqliteRawStore(str(self.db_path))

    def run(self) -> PipelineRunResult:
        self.store.ensure_schema()
        run_id = str(uuid.uuid4())
        started_at = now_utc_iso()
        stage_results: list[StageRunResult] = []
        status = "success"
        error_text: str | None = None

        with sqlite3.connect(self.db_path) as conn:
            self._insert_run_row(conn, run_id=run_id, started_at=started_at, status="running")
            conn.commit()

            stage_plan = self._build_stage_plan()
            for stage_name, stage_fn in stage_plan:
                stage_result = self._run_stage_with_retries(
                    conn=conn,
                    run_id=run_id,
                    stage_name=stage_name,
                    stage_fn=stage_fn,
                )
                stage_results.append(stage_result)
                if stage_result.status != "success":
                    status = "failed"
                    error_text = stage_result.error or f"Stage failed: {stage_name}"
                    break

            finished_at = now_utc_iso()
            self._finish_run_row(
                conn,
                run_id=run_id,
                finished_at=finished_at,
                status=status,
                error_message=error_text,
            )
            conn.commit()

        return PipelineRunResult(
            run_id=run_id,
            status=status,
            started_at=started_at,
            finished_at=finished_at,
            stage_results=stage_results,
        )

    def _build_stage_plan(self) -> list[tuple[str, StageFn]]:
        plan: list[tuple[str, StageFn]] = []
        if self.config.run_ingestion:
            plan.append(("raw_ingestion", self._stage_raw_ingestion))
        if self.config.run_normalization:
            plan.append(("normalization", self._stage_normalization))
        if self.config.run_taxonomy_observability:
            plan.append(("taxonomy_unmapped_report", self._stage_taxonomy_observability))
        if self.config.run_quality_checks:
            plan.append(("norm_quality_checks", self._stage_quality_checks))
        if self.config.run_matching:
            plan.append(("matching", self._stage_matching))
        if self.config.run_signals:
            plan.append(("signals", self._stage_signals))
        if self.config.run_alert_dispatch:
            plan.append(("immediate_alert_dispatch", self._stage_alert_dispatch))
        if self.config.run_market_metrics:
            plan.append(("market_metrics", self._stage_market_metrics))
        if self.config.run_reports:
            plan.append(("report_generation", self._stage_reports))
        return plan

    def _run_stage_with_retries(
        self,
        *,
        conn: sqlite3.Connection,
        run_id: str,
        stage_name: str,
        stage_fn: StageFn,
    ) -> StageRunResult:
        attempts = 0
        last_error: str | None = None

        for attempt_no in range(1, self.config.max_stage_retries + 1):
            attempts = attempt_no
            stage_run_id = str(uuid.uuid4())
            started_at = now_utc_iso()
            try:
                metrics = stage_fn()
                finished_at = now_utc_iso()
                self._insert_stage_row(
                    conn,
                    stage_run_id=stage_run_id,
                    run_id=run_id,
                    stage_name=stage_name,
                    attempt_no=attempt_no,
                    started_at=started_at,
                    finished_at=finished_at,
                    status="success",
                    metrics=metrics,
                    error_message=None,
                )
                conn.commit()
                return StageRunResult(
                    stage=stage_name,
                    status="success",
                    attempts=attempts,
                    metrics=metrics,
                    error=None,
                )
            except Exception as exc:  # pragma: no cover - defensive for runtime ops
                last_error = str(exc)
                finished_at = now_utc_iso()
                self._insert_stage_row(
                    conn,
                    stage_run_id=stage_run_id,
                    run_id=run_id,
                    stage_name=stage_name,
                    attempt_no=attempt_no,
                    started_at=started_at,
                    finished_at=finished_at,
                    status="failed",
                    metrics={},
                    error_message=last_error,
                )
                conn.commit()

        return StageRunResult(
            stage=stage_name,
            status="failed",
            attempts=attempts,
            metrics={},
            error=last_error,
        )

    def _stage_raw_ingestion(self) -> dict[str, Any]:
        cfg = ZhaoConfig.from_env()
        client = ZhaoClient(
            base_url=cfg.base_url,
            search_path=cfg.search_path,
            secret=cfg.secret,
            timeout_sec=cfg.timeout_sec,
        )
        limiter = FileRateLimiter(
            state_path=cfg.rate_limit_state_path,
            max_calls=cfg.max_calls_per_hour,
        )
        job = RawIngestionJob(
            client=client,
            store=self.store,
            rate_limiter=limiter,
            page_size=cfg.default_page_size,
            statuses=(2, 1),
            call_budget_per_run=self.config.call_budget_per_run,
            fresh_pages_per_status=self.config.fresh_pages_per_status,
        )
        result = job.run_once()
        return {
            "total_inserted": result.total_inserted,
            "calls_used": result.calls_used,
            "inserted_by_status": result.inserted_by_status,
            "pages_fetched_by_status": result.pages_fetched_by_status,
            "completed_by_status": result.completed_by_status,
            "next_page_by_status": result.next_page_by_status,
        }

    def _stage_normalization(self) -> dict[str, Any]:
        result = normalize_zhaoonline_raw(
            db_path=str(self.db_path),
            batch_size=self.config.normalization_batch_size,
        )
        return {
            "processed": result.processed,
            "upserted": result.upserted,
            "skipped": result.skipped,
            "last_raw_rowid": result.last_raw_rowid,
        }

    def _stage_taxonomy_observability(self) -> dict[str, Any]:
        report = get_unmapped_report(
            db_path=str(self.db_path),
            top_n_per_field=20,
            sample_size=3,
        )
        counts = {field: len(values) for field, values in report.items()}
        return {"unmapped_counts": counts}

    def _stage_quality_checks(self) -> dict[str, Any]:
        result = run_norm_quality_checks(
            db_path=str(self.db_path),
            batch_size=self.config.quality_batch_size,
            since_last_run=True,
        )
        return {
            "run_id": result.run_id,
            "rows_evaluated": result.rows_evaluated,
            "pass_count": result.pass_count,
            "warning_count": result.warning_count,
            "fail_count": result.fail_count,
            "issue_counts": result.issue_counts,
        }

    def _stage_matching(self) -> dict[str, Any]:
        result = run_v1_matching(
            db_path=str(self.db_path),
            user_id=self.config.user_id,
            min_score=self.config.matching_min_score,
            only_active_listings=True,
            strict_name_match=self.config.strict_name_match,
        )
        return {
            "users_processed": result.users_processed,
            "listings_scanned": result.listings_scanned,
            "items_scanned": result.items_scanned,
            "evaluated_pairs": result.evaluated_pairs,
            "matched_pairs": result.matched_pairs,
            "inserted": result.inserted,
            "updated": result.updated,
            "deactivated": result.deactivated,
        }

    def _stage_signals(self) -> dict[str, Any]:
        result = run_rule_signal_generation(
            db_path=str(self.db_path),
            user_id=self.config.user_id,
            cooldown_hours=self.config.cooldown_hours,
            freshness_hours=self.config.freshness_hours,
            price_move_threshold_pct=self.config.price_move_threshold_pct,
        )
        return {
            "users_processed": result.users_processed,
            "matches_scanned": result.matches_scanned,
            "candidates": result.candidates,
            "inserted": result.inserted,
            "skipped_cooldown": result.skipped_cooldown,
            "skipped_duplicate_run": result.skipped_duplicate_run,
            "inserted_by_type": result.inserted_by_type,
            "inserted_by_urgency": result.inserted_by_urgency,
        }

    def _stage_alert_dispatch(self) -> dict[str, Any]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            signal_rows = conn.execute(
                """
                SELECT
                  s.id AS signal_id,
                  s.user_id,
                  s.urgency,
                  s.signal_type,
                  s.reason_code,
                  s.confidence_level,
                  s.recommendation_text,
                  s.created_at,
                  n.source_listing_id,
                  n.title,
                  n.price_current,
                  n.price_end
                FROM signals s
                JOIN market_listings_norm n ON n.id = s.listing_id
                WHERE s.status = 'active'
                  AND s.urgency = 'immediate'
                  AND (? IS NULL OR s.user_id = ?)
                ORDER BY s.created_at ASC, s.id ASC
                """,
                (self.config.user_id, self.config.user_id),
            ).fetchall()

            inserted = 0
            skipped_existing = 0
            now_iso = now_utc_iso()
            for row in signal_rows:
                payload = {
                    "signal_type": str(row["signal_type"]),
                    "reason_code": str(row["reason_code"]),
                    "confidence_level": str(row["confidence_level"] or ""),
                    "recommendation_text": str(row["recommendation_text"] or ""),
                    "listing": {
                        "source_listing_id": str(row["source_listing_id"] or ""),
                        "title": str(row["title"] or ""),
                        "price_current": row["price_current"],
                        "price_end": row["price_end"],
                    },
                    "signal_created_at": str(row["created_at"]),
                }
                before = conn.total_changes
                conn.execute(
                    """
                    INSERT OR IGNORE INTO alert_dispatch_log (
                      id,
                      user_id,
                      signal_id,
                      urgency,
                      channel,
                      status,
                      dispatched_at,
                      response_meta_json
                    ) VALUES (?, ?, ?, ?, 'app_console', 'sent', ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        str(row["user_id"]),
                        str(row["signal_id"]),
                        str(row["urgency"]),
                        now_iso,
                        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                    ),
                )
                if conn.total_changes > before:
                    inserted += 1
                else:
                    skipped_existing += 1
            conn.commit()

        return {
            "scanned_immediate_signals": len(signal_rows),
            "dispatched_new": inserted,
            "skipped_already_dispatched": skipped_existing,
        }

    def _stage_market_metrics(self) -> dict[str, Any]:
        result = run_market_metrics(
            db_path=str(self.db_path),
            window_days=self.config.metrics_window_days,
            full_window_days=self.config.metrics_full_window_days,
        )
        return {
            "rows_scanned": result.rows_scanned,
            "groups_built": result.groups_built,
            "upserted": result.upserted,
            "window_days": result.window_days,
            "provisional_groups": result.provisional_groups,
            "full_window_groups": result.full_window_groups,
        }

    def _stage_reports(self) -> dict[str, Any]:
        report_date: str | None = self.config.report_date
        if report_date is None:
            report_date = date.fromisoformat(now_utc_iso()[:10]).isoformat()
        result = run_report_generation(
            db_path=str(self.db_path),
            user_id=self.config.user_id,
            report_date=report_date,
            report_type=self.config.report_type,
            export_markdown=False,
            max_items_per_section=self.config.max_report_items_per_section,
        )
        return {
            "users_processed": result.users_processed,
            "generated_reports": result.generated_reports,
            "linked_signals": result.linked_signals,
            "report_type": result.report_type,
            "report_date": result.report_date,
        }

    def _insert_run_row(
        self,
        conn: sqlite3.Connection,
        *,
        run_id: str,
        started_at: str,
        status: str,
    ) -> None:
        conn.execute(
            """
            INSERT INTO orchestration_runs (
              id,
              trigger_source,
              user_id,
              report_date,
              report_type,
              started_at,
              status
            ) VALUES (?, 'manual_cli', ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                self.config.user_id,
                self.config.report_date,
                self.config.report_type,
                started_at,
                status,
            ),
        )

    def _finish_run_row(
        self,
        conn: sqlite3.Connection,
        *,
        run_id: str,
        finished_at: str,
        status: str,
        error_message: str | None,
    ) -> None:
        conn.execute(
            """
            UPDATE orchestration_runs
            SET finished_at = ?,
                status = ?,
                error_message = ?
            WHERE id = ?
            """,
            (finished_at, status, error_message, run_id),
        )

    def _insert_stage_row(
        self,
        conn: sqlite3.Connection,
        *,
        stage_run_id: str,
        run_id: str,
        stage_name: str,
        attempt_no: int,
        started_at: str,
        finished_at: str,
        status: str,
        metrics: dict[str, Any],
        error_message: str | None,
    ) -> None:
        conn.execute(
            """
            INSERT INTO orchestration_stage_runs (
              id,
              orchestration_run_id,
              stage_name,
              attempt_no,
              started_at,
              finished_at,
              status,
              metrics_json,
              error_message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                stage_run_id,
                run_id,
                stage_name,
                attempt_no,
                started_at,
                finished_at,
                status,
                json.dumps(metrics, ensure_ascii=False, separators=(",", ":")),
                error_message,
            ),
        )
