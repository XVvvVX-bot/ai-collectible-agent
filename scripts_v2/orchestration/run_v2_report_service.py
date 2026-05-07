#!/usr/bin/env python3
"""Serve V2 reports over HTTP while the background loop keeps running."""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sqlite3
import sys
import time
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Event, Thread
from urllib.parse import parse_qs, quote, unquote, urlparse

ROOT_DIR = Path(__file__).resolve().parents[2]
SRC_DIR = ROOT_DIR / "src"
ORCH_DIR = Path(__file__).resolve().parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if str(ORCH_DIR) not in sys.path:
    sys.path.insert(0, str(ORCH_DIR))

from report_ui.layout import (
    html_lang_attr,
    render_dashboard_anchor_nav,
    render_document,
    show_app_dev_ui,
)

from ai_agent_v2.ingestion.live_incremental import DEFAULT_STATE_SOURCE_KEY
from ai_agent_v2.matching.v2_matcher import run_v2_matching
from ai_agent_v2.profile.manual_interest_ops import create_interest_record, delete_interest_record
from ai_agent_v2.reporting.interest_digest import build_interest_digest_report
from ai_agent_v2.reporting.signal_review import EVENT_SIGNAL_TYPES
from ai_agent_v2.runtime_host import BackgroundServiceRunner, DEFAULT_BASE_URL, build_service_config, emit_json
from ai_agent_v2.signals.interest_signals import run_interest_signal_generation

REPORT_PATTERNS = (
    ("interest_digest_user", "Interest Digest", "Collector digest", r"^v2_interest_digest_(.+)_(\d{8}T\d{6}\+\d{4})\.md$"),
    ("interest_digest_index", "Interest Digest Index", "Daily index", r"^v2_daily_interest_digest_index_(\d{8}T\d{6}\+\d{4})\.md$"),
    ("signal_review_user", "Signal Review", "Collector signals", r"^v2_signal_review_(.+)_(\d{8}T\d{6}\+\d{4})\.md$"),
    ("signal_review_index", "Signal Review Index", "Daily index", r"^v2_daily_signal_review_index_(\d{8}T\d{6}\+\d{4})\.md$"),
    ("user_base_review", "User Base Review", "Daily summary", r"^v2_daily_user_base_review_(\d{8}T\d{6}\+\d{4})\.md$"),
)
DEFAULT_DASHBOARD_USER_ID = os.getenv("APP_DEFAULT_USER_ID") or "demo_u_v2_curated"
DEFAULT_INTEREST_REFRESH_LOOKBACK_HOURS = int(os.getenv("APP_DAILY_LOOKBACK_HOURS", "24"))
SQLITE_BUSY_TIMEOUT_MS = int(os.getenv("APP_SQLITE_BUSY_TIMEOUT_MS", "30000"))


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Serve V2 reports over HTTP with the background loop.")
    parser.add_argument("--runtime-root", default=os.getenv("APP_RUNTIME_ROOT") or "runtime")
    parser.add_argument("--db-path")
    parser.add_argument("--output-dir")
    parser.add_argument("--state-dir")
    parser.add_argument("--secret-file")
    parser.add_argument("--lock-path")
    parser.add_argument("--rate-limit-state-path")
    parser.add_argument("--timezone", default=os.getenv("APP_TIMEZONE") or "UTC")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--secret", default=os.getenv("ZHAO_V2_SECRET") or os.getenv("ZHAO_SECRET"))
    parser.add_argument("--state-source-key", default=os.getenv("ZHAO_V2_STATE_SOURCE_KEY") or DEFAULT_STATE_SOURCE_KEY)
    parser.add_argument("--window-hours", type=int, default=int(os.getenv("ZHAO_V2_WINDOW_HOURS", "1")))
    parser.add_argument("--max-windows-per-run", type=int, default=int(os.getenv("ZHAO_V2_MAX_WINDOWS_PER_RUN", "4")))
    parser.add_argument("--page-size", type=int, default=int(os.getenv("ZHAO_V2_PAGE_SIZE", "500")))
    parser.add_argument("--min-interval-sec", type=int, default=int(os.getenv("ZHAO_V2_MIN_INTERVAL_SEC", "60")))
    parser.add_argument("--timeout-sec", type=int, default=int(os.getenv("ZHAO_V2_REQUEST_TIMEOUT_SEC", "60")))
    parser.add_argument("--incremental-check-minutes", type=int, default=int(os.getenv("APP_INCREMENTAL_CHECK_MINUTES", "10")))
    parser.add_argument("--daily-check-minutes", type=int, default=int(os.getenv("APP_DAILY_CHECK_MINUTES", "60")))
    parser.add_argument("--daily-lookback-hours", type=int, default=int(os.getenv("APP_DAILY_LOOKBACK_HOURS", "24")))
    parser.add_argument("--loop-sleep-seconds", type=int, default=int(os.getenv("APP_LOOP_SLEEP_SECONDS", "60")))
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "10000")))
    parser.add_argument("--default-user-id", default=DEFAULT_DASHBOARD_USER_ID)
    args = parser.parse_args()

    config = build_service_config(
        runtime_root=args.runtime_root,
        timezone_name=args.timezone,
        db_path=args.db_path,
        output_dir=args.output_dir,
        state_dir=args.state_dir,
        secret_file=args.secret_file,
        lock_path=args.lock_path,
        rate_limit_state_path=args.rate_limit_state_path,
        base_url=args.base_url,
        secret=args.secret,
        state_source_key=args.state_source_key,
        window_hours=args.window_hours,
        max_windows_per_run=args.max_windows_per_run,
        page_size=args.page_size,
        min_interval_sec=args.min_interval_sec,
        timeout_sec=args.timeout_sec,
        incremental_check_minutes=args.incremental_check_minutes,
        daily_check_minutes=args.daily_check_minutes,
        daily_lookback_hours=args.daily_lookback_hours,
        loop_sleep_seconds=args.loop_sleep_seconds,
    )
    runner = BackgroundServiceRunner(config)
    runner.ensure_runtime()

    stop_event = Event()
    worker_thread = Thread(target=runner.run_forever, kwargs={"stop_event": stop_event}, daemon=True)
    worker_thread.start()

    handler_class = build_handler(
        runtime_root=Path(config.runtime_paths.runtime_root),
        reports_dir=Path(config.runtime_paths.output_dir),
        db_path=Path(config.runtime_paths.db_path),
        default_lookback_hours=config.daily_lookback_hours,
        default_user_id=args.default_user_id,
    )
    server = ThreadingHTTPServer((args.host, args.port), handler_class)
    emit_json(
        "report_service_started",
        host=args.host,
        port=args.port,
        runtime=runner.start_event()["runtime"],
        routes=[
            "/",
            "/actions",
            "/actions/run",
            "/interests",
            "/interests/new",
            "/interests/edit",
            "/interests/create",
            "/interests/save",
            "/interests/delete",
            "/matches",
            "/healthz",
            "/api/reports",
            "/api/users/<user_id>/profile",
            "/api/users/<user_id>/interests",
            "/api/users/<user_id>/reports",
            "/api/users/<user_id>/matches",
            "/api/users/<user_id>/signals",
            "/api/users/<user_id>/digest/latest",
            "/api/users/<user_id>/matching/run",
            "/api/users/<user_id>/signals/run",
            "/latest/<kind>",
            "/reports/<name>",
            "/raw/<name>",
            "/downloads/<name>",
        ],
    )
    try:
        server.serve_forever()
    finally:
        stop_event.set()
        server.server_close()
    return 0


def build_handler(
    *,
    runtime_root: Path,
    reports_dir: Path,
    db_path: Path,
    default_lookback_hours: int,
    default_user_id: str,
):
    exports_dir = runtime_root / "exports"

    class ReportHandler(BaseHTTPRequestHandler):
        server_version = "AIAgentReportServer/1.0"

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path
            if path == "/healthz":
                self._write_json(HTTPStatus.OK, {"ok": True, "reports_dir": str(reports_dir), "exports_dir": str(exports_dir)})
                return
            if path == "/api/reports":
                self._write_json(HTTPStatus.OK, {"reports": report_entries(reports_dir), "bundles": bundle_entries(exports_dir)})
                return
            if path == "/actions":
                actions_user_id = first_query_value(parse_qs(parsed.query), "user_id") or default_user_id
                self._write_html(
                    HTTPStatus.OK,
                    render_actions_html(
                        db_path=db_path,
                        reports_dir=reports_dir,
                        user_id=actions_user_id,
                        lookback_hours=default_lookback_hours,
                    ),
                )
                return
            if path == "/interests/edit":
                query = parse_qs(parsed.query)
                interests_user_id = first_query_value(query, "user_id") or default_user_id
                interest_id = first_query_value(query, "interest_id")
                if not interest_id:
                    self._write_html(
                        HTTPStatus.BAD_REQUEST,
                        render_error_html(
                            "interest_id is required",
                            db_path=db_path,
                            user_id=interests_user_id,
                        ),
                    )
                    return
                try:
                    self._write_html(
                        HTTPStatus.OK,
                        render_interest_edit_html(
                            db_path=db_path,
                            user_id=interests_user_id,
                            interest_id=interest_id,
                        ),
                    )
                except ValueError as exc:
                    self._write_html(
                        HTTPStatus.NOT_FOUND,
                        render_error_html(str(exc), db_path=db_path, user_id=interests_user_id),
                    )
                return
            if path == "/interests/new":
                query = parse_qs(parsed.query)
                interests_user_id = first_query_value(query, "user_id") or default_user_id
                try:
                    self._write_html(
                        HTTPStatus.OK,
                        render_interest_create_html(
                            db_path=db_path,
                            user_id=interests_user_id,
                        ),
                    )
                except ValueError as exc:
                    self._write_html(
                        HTTPStatus.NOT_FOUND,
                        render_error_html(str(exc), db_path=db_path, user_id=interests_user_id),
                    )
                return
            user_route = match_user_api_route(path)
            if user_route is not None:
                user_id, action = user_route
                self._handle_user_api_get(user_id=user_id, action=action, query=parse_qs(parsed.query))
                return
            if path == "/interests":
                interests_user_id = first_query_value(parse_qs(parsed.query), "user_id") or default_user_id
                self._write_html(
                    HTTPStatus.OK,
                    render_interests_html(
                        db_path=db_path,
                        user_id=interests_user_id,
                    ),
                )
                return
            if path == "/matches":
                matches_user_id = first_query_value(parse_qs(parsed.query), "user_id") or default_user_id
                self._write_html(
                    HTTPStatus.OK,
                    render_matches_html(
                        db_path=db_path,
                        user_id=matches_user_id,
                    ),
                )
                return
            if path == "/":
                dashboard_user_id = first_query_value(parse_qs(parsed.query), "user_id") or default_user_id
                self._write_html(
                    HTTPStatus.OK,
                    render_dashboard_html(
                        db_path=db_path,
                        reports_dir=reports_dir,
                        exports_dir=exports_dir,
                        user_id=dashboard_user_id,
                        lookback_hours=default_lookback_hours,
                    ),
                )
                return
            if path.startswith("/latest/"):
                report_kind = unquote(path.removeprefix("/latest/"))
                target = latest_report_for_kind(reports_dir, report_kind)
                if target is None:
                    self._write_html(
                        HTTPStatus.NOT_FOUND,
                        render_error_html(
                            "Latest report not found",
                            db_path=db_path,
                            user_id=default_user_id,
                        ),
                    )
                    return
                self.send_response(HTTPStatus.FOUND)
                self.send_header("Location", f"/reports/{quote(target.name)}")
                self.end_headers()
                return
            if path.startswith("/reports/"):
                name = unquote(path.removeprefix("/reports/"))
                target = safe_child(reports_dir, name)
                if target is None or not target.exists():
                    self._write_html(
                        HTTPStatus.NOT_FOUND,
                        render_error_html(
                            "Report not found",
                            db_path=db_path,
                            user_id=default_user_id,
                        ),
                    )
                    return
                self._write_html(HTTPStatus.OK, render_report_html(target))
                return
            if path.startswith("/raw/"):
                name = unquote(path.removeprefix("/raw/"))
                target = safe_child(reports_dir, name)
                if target is None or not target.exists():
                    self._write_html(
                        HTTPStatus.NOT_FOUND,
                        render_error_html(
                            "Report not found",
                            db_path=db_path,
                            user_id=default_user_id,
                        ),
                    )
                    return
                self._write_file(target, "text/markdown; charset=utf-8", as_attachment=False)
                return
            if path.startswith("/downloads/"):
                name = unquote(path.removeprefix("/downloads/"))
                target = safe_child(exports_dir, name)
                if target is None or not target.exists():
                    self._write_html(
                        HTTPStatus.NOT_FOUND,
                        render_error_html(
                            "Bundle not found",
                            db_path=db_path,
                            user_id=default_user_id,
                        ),
                    )
                    return
                self._write_file(target, "application/zip", as_attachment=True)
                return
            self._write_html(
                HTTPStatus.NOT_FOUND,
                render_error_html(
                    "Route not found",
                    db_path=db_path,
                    user_id=default_user_id,
                ),
            )

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/interests/create":
                form = parse_qs(self.rfile.read(int(self.headers.get("Content-Length", "0") or "0")).decode("utf-8"))
                user_id = first_query_value(form, "user_id") or default_user_id
                try:
                    payload = create_interest_form(
                        db_path=db_path,
                        user_id=user_id,
                        interest_name=first_query_value(form, "interest_name") or "",
                        raw_input=first_query_value(form, "raw_input") or "",
                        interest_kind=first_query_value(form, "interest_kind") or "watch_buy",
                        scope_kind=first_query_value(form, "scope_kind") or "exact_item",
                        precision_mode=first_query_value(form, "precision_mode") or "balanced",
                        interest_priority=first_query_value(form, "interest_priority") or "normal",
                        interest_notes=first_query_value(form, "interest_notes") or "",
                        budget_max=parse_optional_float_param(form, "budget_max"),
                        condition_mode=first_query_value(form, "condition_mode") or "ignore",
                        delivery_mode=first_query_value(form, "delivery_mode") or "daily_digest",
                        cooldown_hours=parse_int_param(form, "cooldown_hours", default=24),
                        min_match_score=parse_optional_float_param(form, "min_match_score"),
                        max_signals_per_day=parse_int_param(form, "max_signals_per_day", default=8),
                    )
                    self._write_html(
                        HTTPStatus.OK,
                        render_interest_create_result_html(
                            db_path=db_path,
                            payload=payload,
                            user_id=user_id,
                        ),
                    )
                except ValueError as exc:
                    self._write_html(
                        HTTPStatus.BAD_REQUEST,
                        render_error_html(str(exc), db_path=db_path, user_id=user_id),
                    )
                except Exception as exc:  # pragma: no cover - defensive form fallback
                    self._write_html(
                        HTTPStatus.INTERNAL_SERVER_ERROR,
                        render_error_html(str(exc), db_path=db_path, user_id=user_id),
                    )
                return
            if parsed.path == "/interests/save":
                form = parse_qs(self.rfile.read(int(self.headers.get("Content-Length", "0") or "0")).decode("utf-8"))
                user_id = first_query_value(form, "user_id") or default_user_id
                interest_id = first_query_value(form, "interest_id")
                if not interest_id:
                    self._write_html(
                        HTTPStatus.BAD_REQUEST,
                        render_error_html(
                            "interest_id is required",
                            db_path=db_path,
                            user_id=user_id,
                        ),
                    )
                    return
                try:
                    payload = save_interest_form(
                        db_path=db_path,
                        user_id=user_id,
                        interest_id=interest_id,
                        interest_priority=first_query_value(form, "interest_priority") or "normal",
                        interest_notes=first_query_value(form, "interest_notes") or "",
                        budget_max=parse_optional_float_param(form, "budget_max"),
                        condition_mode=first_query_value(form, "condition_mode") or "ignore",
                        delivery_mode=first_query_value(form, "delivery_mode") or "daily_digest",
                        cooldown_hours=parse_int_param(form, "cooldown_hours", default=24),
                        min_match_score=parse_optional_float_param(form, "min_match_score"),
                        max_signals_per_day=parse_int_param(form, "max_signals_per_day", default=5),
                    )
                    self._write_html(
                        HTTPStatus.OK,
                        render_interest_save_result_html(
                            db_path=db_path,
                            payload=payload,
                            user_id=user_id,
                            interest_id=interest_id,
                        ),
                    )
                except ValueError as exc:
                    self._write_html(
                        HTTPStatus.BAD_REQUEST,
                        render_error_html(str(exc), db_path=db_path, user_id=user_id),
                    )
                except Exception as exc:  # pragma: no cover - defensive form fallback
                    self._write_html(
                        HTTPStatus.INTERNAL_SERVER_ERROR,
                        render_error_html(str(exc), db_path=db_path, user_id=user_id),
                    )
                return
            if parsed.path == "/interests/delete":
                form = parse_qs(self.rfile.read(int(self.headers.get("Content-Length", "0") or "0")).decode("utf-8"))
                user_id = first_query_value(form, "user_id") or default_user_id
                interest_id = first_query_value(form, "interest_id")
                if not interest_id:
                    self._write_html(
                        HTTPStatus.BAD_REQUEST,
                        render_error_html(
                            "interest_id is required",
                            db_path=db_path,
                            user_id=user_id,
                        ),
                    )
                    return
                try:
                    payload = delete_interest_form(
                        db_path=db_path,
                        user_id=user_id,
                        interest_id=interest_id,
                    )
                    self._write_html(
                        HTTPStatus.OK,
                        render_interest_delete_result_html(
                            db_path=db_path,
                            payload=payload,
                            user_id=user_id,
                        ),
                    )
                except ValueError as exc:
                    self._write_html(
                        HTTPStatus.BAD_REQUEST,
                        render_error_html(str(exc), db_path=db_path, user_id=user_id),
                    )
                except Exception as exc:  # pragma: no cover - defensive form fallback
                    self._write_html(
                        HTTPStatus.INTERNAL_SERVER_ERROR,
                        render_error_html(str(exc), db_path=db_path, user_id=user_id),
                    )
                return
            if parsed.path == "/actions/run":
                form = parse_qs(self.rfile.read(int(self.headers.get("Content-Length", "0") or "0")).decode("utf-8"))
                user_id = first_query_value(form, "user_id") or default_user_id
                action_name = first_query_value(form, "action") or ""
                try:
                    self._write_html(
                        HTTPStatus.OK,
                        render_action_result_html(
                            db_path=db_path,
                            reports_dir=reports_dir,
                            user_id=user_id,
                            action_name=action_name,
                            lookback_hours=parse_int_param(form, "lookback_hours", default=default_lookback_hours),
                            only_active_listings=parse_bool_param(form, "only_active", default=True),
                        ),
                    )
                except ValueError as exc:
                    self._write_html(
                        HTTPStatus.BAD_REQUEST,
                        render_error_html(str(exc), db_path=db_path, user_id=user_id),
                    )
                except Exception as exc:  # pragma: no cover - defensive form fallback
                    self._write_html(
                        HTTPStatus.INTERNAL_SERVER_ERROR,
                        render_error_html(str(exc), db_path=db_path, user_id=user_id),
                    )
                return
            user_route = match_user_api_route(parsed.path)
            if user_route is None:
                self._write_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "Route not found"})
                return
            user_id, action = user_route
            self._handle_user_api_post(user_id=user_id, action=action, query=parse_qs(parsed.query))

        def log_message(self, format: str, *args) -> None:  # noqa: A003
            return

        def _handle_user_api_get(self, *, user_id: str, action: str, query: dict[str, list[str]]) -> None:
            try:
                if action == "profile":
                    payload = load_user_profile_payload(db_path, user_id=user_id)
                    self._write_json(HTTPStatus.OK, payload)
                    return
                if action == "interests":
                    payload = load_user_interests_payload(db_path, user_id=user_id)
                    self._write_json(HTTPStatus.OK, payload)
                    return
                if action == "reports":
                    payload = load_user_reports_payload(reports_dir, user_id=user_id)
                    self._write_json(HTTPStatus.OK, payload)
                    return
                if action == "matches":
                    payload = load_user_matches_payload(db_path, user_id=user_id)
                    self._write_json(HTTPStatus.OK, payload)
                    return
                if action == "signals":
                    lookback_hours = parse_int_param(query, "lookback_hours", default=default_lookback_hours)
                    payload = load_user_signals_payload(db_path, user_id=user_id, lookback_hours=lookback_hours)
                    self._write_json(HTTPStatus.OK, payload)
                    return
                if action == "digest/latest":
                    lookback_hours = parse_int_param(query, "lookback_hours", default=default_lookback_hours)
                    payload = load_latest_digest_payload(
                        db_path=db_path,
                        reports_dir=reports_dir,
                        user_id=user_id,
                        lookback_hours=lookback_hours,
                    )
                    self._write_json(HTTPStatus.OK, payload)
                    return
                self._write_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "Route not found"})
            except ValueError as exc:
                self._write_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": str(exc)})
            except Exception as exc:  # pragma: no cover - defensive API fallback
                self._write_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": str(exc)})

        def _handle_user_api_post(self, *, user_id: str, action: str, query: dict[str, list[str]]) -> None:
            try:
                if action == "matching/run":
                    payload = run_matching_payload(
                        db_path=db_path,
                        user_id=user_id,
                        only_active_listings=parse_bool_param(query, "only_active", default=True),
                    )
                    self._write_json(HTTPStatus.OK, payload)
                    return
                if action == "signals/run":
                    payload = run_signals_payload(
                        db_path=db_path,
                        user_id=user_id,
                        lookback_hours=parse_int_param(query, "lookback_hours", default=default_lookback_hours),
                    )
                    self._write_json(HTTPStatus.OK, payload)
                    return
                self._write_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "Route not found"})
            except ValueError as exc:
                self._write_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": str(exc)})
            except Exception as exc:  # pragma: no cover - defensive API fallback
                self._write_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": str(exc)})

        def _write_json(self, status: HTTPStatus, payload: dict[str, object]) -> None:
            body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _write_html(self, status: HTTPStatus, html_body: str) -> None:
            body = html_body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            # Avoid stale SSR during local edits (browser heuristic cache).
            self.send_header("Cache-Control", "no-store, max-age=0, must-revalidate")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _write_file(self, path: Path, content_type: str, *, as_attachment: bool) -> None:
            body = path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            if as_attachment:
                self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return ReportHandler


def report_entries(reports_dir: Path) -> list[dict[str, object]]:
    if not reports_dir.exists():
        return []
    entries = []
    for path in sorted(reports_dir.glob("*.md"), key=lambda item: item.stat().st_mtime, reverse=True):
        stat = path.stat()
        metadata = classify_report(path.name)
        entries.append(
            {
                "name": path.name,
                "size_bytes": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "kind": metadata["kind"],
                "label": metadata["label"],
                "scope": metadata["scope"],
                "timestamp_label": metadata["timestamp_label"],
            }
        )
    return entries


def bundle_entries(exports_dir: Path) -> list[dict[str, object]]:
    if not exports_dir.exists():
        return []
    entries = []
    for path in sorted(exports_dir.glob("*.zip"), key=lambda item: item.stat().st_mtime, reverse=True):
        stat = path.stat()
        entries.append(
            {
                "name": path.name,
                "size_bytes": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            }
        )
    return entries


def match_user_api_route(path: str) -> tuple[str, str] | None:
    match = re.fullmatch(r"/api/users/([^/]+)/(.+)", path)
    if not match:
        return None
    return unquote(match.group(1)), match.group(2)


def parse_int_param(query: dict[str, list[str]], key: str, *, default: int) -> int:
    values = query.get(key)
    if not values or not values[0].strip():
        return default
    try:
        return int(values[0])
    except ValueError as exc:
        raise ValueError(f"invalid integer for {key}") from exc


def parse_optional_float_param(query: dict[str, list[str]], key: str) -> float | None:
    values = query.get(key)
    if not values or not values[0].strip():
        return None
    try:
        return float(values[0])
    except ValueError as exc:
        raise ValueError(f"invalid float for {key}") from exc


def parse_bool_param(query: dict[str, list[str]], key: str, *, default: bool) -> bool:
    values = query.get(key)
    if not values or not values[0].strip():
        return default
    value = values[0].strip().lower()
    if value in {"1", "true", "yes", "y"}:
        return True
    if value in {"0", "false", "no", "n"}:
        return False
    raise ValueError(f"invalid boolean for {key}")


def first_query_value(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    if not values:
        return None
    value = values[0].strip()
    return value or None


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "+00:00")


def db_connect(db_path: Path, *, write: bool = False) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=SQLITE_BUSY_TIMEOUT_MS / 1000)
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
    if write:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def run_with_sqlite_retry(callable_fn, *, attempts: int = 4, base_delay_s: float = 0.25):
    last_exc: Exception | None = None
    for idx in range(attempts):
        try:
            return callable_fn()
        except sqlite3.OperationalError as exc:
            msg = str(exc).lower()
            if "database is locked" not in msg and "database is busy" not in msg:
                raise
            last_exc = exc
            if idx >= attempts - 1:
                break
            time.sleep(base_delay_s * (idx + 1))
    raise ValueError("Database is busy right now. Please retry in a moment.") from last_exc


def resolve_intent_confidence(interest_kind: str) -> float:
    return {
        "watch_buy": 0.9,
        "watch_sell": 0.9,
        "collecting": 0.82,
        "discovery": 0.7,
        "portfolio_monitor": 0.78,
    }.get(interest_kind, 0.75)


def resolve_match_flags(
    *,
    scope_kind: str,
    precision_mode: str,
    defaults: dict[str, object],
) -> tuple[bool, bool, bool]:
    default_related = bool(int(defaults.get("default_allow_related_matches") or 0))
    default_series = bool(int(defaults.get("default_allow_series_matches") or 0))
    default_variant = bool(int(defaults.get("default_allow_variant_matches") or 0))
    if precision_mode == "exact":
        return False, False, False
    if precision_mode == "broad":
        return True, True, True

    allow_variant = default_variant or scope_kind in {"issue_family", "series", "theme", "category", "keyword"}
    allow_series = default_series or scope_kind in {"series", "theme", "category", "keyword"}
    allow_related = default_related or scope_kind in {"theme", "category", "keyword"}
    return allow_related, allow_series, allow_variant


def resolve_signal_policy_defaults(
    *,
    interest_kind: str,
    delivery_mode: str,
    cooldown_hours: int,
    min_match_score: object,
    max_signals_per_day: int,
    allow_series_matches: bool,
    allow_variant_matches: bool,
) -> dict[str, object]:
    safe_min_match_score = float(min_match_score) if min_match_score is not None else 70.0
    if interest_kind == "watch_sell":
        return {
            "notify_on_preview": 0,
            "notify_on_live": 0,
            "notify_on_ended": 1,
            "notify_on_exact_match": 0,
            "notify_on_variant_match": 0,
            "notify_on_series_match": 0,
            "notify_on_price_opportunity": 0,
            "notify_on_sell_opportunity": 1,
            "min_match_score": safe_min_match_score,
            "cooldown_hours": cooldown_hours,
            "delivery_mode": delivery_mode,
            "max_signals_per_day": max_signals_per_day,
        }
    return {
        "notify_on_preview": 1,
        "notify_on_live": 1,
        "notify_on_ended": 1 if interest_kind == "discovery" else 0,
        "notify_on_exact_match": 1,
        "notify_on_variant_match": int(allow_variant_matches),
        "notify_on_series_match": int(allow_series_matches),
        "notify_on_price_opportunity": 1,
        "notify_on_sell_opportunity": 1 if interest_kind == "portfolio_monitor" else 0,
        "min_match_score": safe_min_match_score,
        "cooldown_hours": cooldown_hours,
        "delivery_mode": delivery_mode,
        "max_signals_per_day": max_signals_per_day,
    }


def map_scope_kind_to_target_kind(scope_kind: str) -> str:
    return {
        "exact_item": "listing_identity",
        "issue_part": "issue_part",
        "issue_family": "issue_family",
        "series": "series_key",
        "theme": "theme",
        "category": "category",
        "keyword": "keyword",
    }.get(scope_kind, "listing_identity")


def build_manual_interest_target(
    *,
    raw_input: str,
    scope_kind: str,
    precision_mode: str,
    interest_priority: str,
    condition_mode: str,
    budget_max: float | None,
) -> dict[str, object]:
    parse_family = _classify_parse_family(raw_input, None)
    parsed: dict[str, object]
    if parse_family == "stamp_like":
        parsed = _parse_stamp_title(raw_title=raw_input, character_condition=None, description_character=None)
    elif parse_family == "coin_like":
        parsed = _parse_coin_title(raw_title=raw_input, character_condition=None, description_character=None)
    else:
        parsed = {
            "title_normalized": raw_input,
            "issue_code_norm": None,
            "series_key": raw_input,
            "theme_name": raw_input,
            "asset_type": None,
            "variant_tokens_json": "[]",
            "quantity_tokens_json": "[]",
            "condition_tokens_json": "[]",
            "year_value": None,
            "issue_name": raw_input,
        }

    normalized_name = (
        parsed.get("issue_name")
        or parsed.get("title_normalized")
        or parsed.get("theme_name")
        or raw_input
    )
    target_kind = map_scope_kind_to_target_kind(scope_kind)
    return {
        "target_label": raw_input,
        "target_kind": target_kind,
        "parse_family": parse_family,
        "normalized_name": normalized_name,
        "issue_code_norm": parsed.get("issue_code_norm"),
        "issue_part_token": None,
        "series_key": parsed.get("series_key"),
        "theme_name": parsed.get("theme_name"),
        "asset_type": parsed.get("asset_type"),
        "variant_tokens_json": parsed.get("variant_tokens_json") or "[]",
        "quantity_tokens_json": parsed.get("quantity_tokens_json") or "[]",
        "condition_tokens_json": parsed.get("condition_tokens_json") or "[]",
        "year_value": parsed.get("year_value"),
        "strictness_override": precision_mode,
        "priority_override": interest_priority,
        "condition_mode": condition_mode,
        "budget_max": budget_max,
    }


def load_user_profile_payload(db_path: Path, *, user_id: str) -> dict[str, object]:
    with db_connect(db_path) as conn:
        user_row = conn.execute(
            """
            SELECT id, display_name, language, timezone, created_at, updated_at
            FROM users
            WHERE id = ?
            """,
            (user_id,),
        ).fetchone()
        if user_row is None:
            raise ValueError(f"user not found: {user_id}")

        defaults_row = conn.execute(
            """
            SELECT default_currency, default_precision_mode, default_condition_mode,
                   default_delivery_mode, default_min_match_score, default_cooldown_hours,
                   default_allow_related_matches, default_allow_series_matches, default_allow_variant_matches,
                   notes, created_at, updated_at
            FROM user_profile_defaults_v2
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()

        interest_rows = conn.execute(
            """
            SELECT
              id, interest_name, interest_kind, scope_kind, precision_mode, interest_priority,
              intent_confidence, allow_related_matches, allow_series_matches, allow_variant_matches,
              active_status, notes, created_at, updated_at
            FROM user_interests_v2
            WHERE user_id = ?
            ORDER BY
              CASE interest_priority WHEN 'high' THEN 1 WHEN 'normal' THEN 2 ELSE 3 END,
              updated_at DESC,
              id
            """,
            (user_id,),
        ).fetchall()

        interests: list[dict[str, object]] = []
        active_interest_count = 0
        active_target_count = 0
        active_holding_count = 0
        active_signal_count = int(
            conn.execute(
                "SELECT COUNT(*) FROM signals_v2 WHERE user_id = ? AND status = 'active'",
                (user_id,),
            ).fetchone()[0]
        )
        active_match_count = int(
            conn.execute(
                "SELECT COUNT(*) FROM listing_matches_v2 WHERE user_id = ? AND status = 'active'",
                (user_id,),
            ).fetchone()[0]
        )

        for row in interest_rows:
            interest = dict(row)
            interest_id = str(row["id"])
            targets = [
                normalize_sqlite_row(target)
                for target in conn.execute(
                    """
                    SELECT
                      id, target_label, target_kind, parse_family, raw_input, normalized_name,
                      issue_code_norm, issue_part_token, series_key, theme_name, asset_type,
                      variant_tokens_json, quantity_tokens_json, condition_tokens_json,
                      year_value, budget_min, budget_max, strictness_override, priority_override,
                      is_active, created_at, updated_at, condition_mode
                    FROM user_interest_targets_v2
                    WHERE interest_id = ?
                    ORDER BY is_active DESC, updated_at DESC, id
                    """,
                    (interest_id,),
                ).fetchall()
            ]
            holdings = [
                normalize_sqlite_row(holding)
                for holding in conn.execute(
                    """
                    SELECT
                      id, raw_input, parse_family, normalized_name, issue_code_norm, issue_part_token,
                      series_key, theme_name, asset_type, variant_tokens_json, quantity_tokens_json,
                      condition_tokens_json, year_value, holding_quantity, cost_basis_total,
                      cost_basis_unit, acquired_at, notes, is_active, created_at, updated_at
                    FROM user_holdings_v2
                    WHERE linked_interest_id = ?
                    ORDER BY is_active DESC, updated_at DESC, id
                    """,
                    (interest_id,),
                ).fetchall()
            ]
            policy_row = conn.execute(
                """
                SELECT
                  id, notify_on_preview, notify_on_live, notify_on_ended,
                  notify_on_exact_match, notify_on_variant_match, notify_on_series_match,
                  notify_on_price_opportunity, notify_on_sell_opportunity,
                  min_match_score, cooldown_hours, delivery_mode, max_signals_per_day,
                  created_at, updated_at
                FROM user_interest_signal_policies_v2
                WHERE interest_id = ?
                ORDER BY updated_at DESC, id DESC
                LIMIT 1
                """,
                (interest_id,),
            ).fetchone()
            active_interest_count += 1 if interest.get("active_status") == "active" else 0
            active_target_count += sum(1 for target in targets if int(target.get("is_active") or 0) == 1)
            active_holding_count += sum(1 for holding in holdings if int(holding.get("is_active") or 0) == 1)
            interest["targets"] = [decode_json_fields(target) for target in targets]
            interest["holdings"] = [decode_json_fields(holding) for holding in holdings]
            interest["signal_policy"] = normalize_sqlite_row(policy_row) if policy_row is not None else None
            interests.append(interest)

    return {
        "ok": True,
        "user": normalize_sqlite_row(user_row),
        "defaults": normalize_sqlite_row(defaults_row) if defaults_row is not None else None,
        "summary": {
            "active_interest_count": active_interest_count,
            "active_target_count": active_target_count,
            "active_holding_count": active_holding_count,
            "active_match_count": active_match_count,
            "active_signal_count": active_signal_count,
        },
        "interests": interests,
    }


def profile_html_lang(db_path: Path, *, user_id: str) -> str:
    try:
        payload = load_user_profile_payload(db_path, user_id=user_id)
    except ValueError:
        return "en"
    user_obj = payload.get("user") if isinstance(payload.get("user"), dict) else {}
    return html_lang_attr(str(user_obj.get("language") or ""))


def load_user_interests_payload(db_path: Path, *, user_id: str) -> dict[str, object]:
    profile_payload = load_user_profile_payload(db_path, user_id=user_id)
    interests = profile_payload["interests"] if isinstance(profile_payload.get("interests"), list) else []

    with db_connect(db_path) as conn:
        signal_count_rows = conn.execute(
            """
            SELECT interest_id, COUNT(*) AS signal_count
            FROM signals_v2
            WHERE user_id = ? AND status = 'active'
            GROUP BY interest_id
            """,
            (user_id,),
        ).fetchall()
        match_count_rows = conn.execute(
            """
            SELECT t.interest_id, COUNT(*) AS match_count
            FROM listing_matches_v2 m
            JOIN user_interest_targets_v2 t ON t.id = m.user_item_id
            WHERE m.user_id = ? AND m.status = 'active'
            GROUP BY t.interest_id
            """,
            (user_id,),
        ).fetchall()

    signal_count_by_interest = {str(row["interest_id"]): int(row["signal_count"]) for row in signal_count_rows}
    match_count_by_interest = {str(row["interest_id"]): int(row["match_count"]) for row in match_count_rows}

    enriched_interests: list[dict[str, object]] = []
    interest_kind_counts: dict[str, int] = {}
    high_priority_count = 0
    immediate_policy_count = 0
    total_target_count = 0
    total_holding_count = 0
    interests_with_holdings = 0

    for raw_interest in interests:
        if not isinstance(raw_interest, dict):
            continue
        interest = dict(raw_interest)
        if str(interest.get("active_status") or "") != "active":
            continue
        interest_id = str(interest.get("id") or "")
        targets = interest.get("targets") if isinstance(interest.get("targets"), list) else []
        holdings = interest.get("holdings") if isinstance(interest.get("holdings"), list) else []
        policy = interest.get("signal_policy") if isinstance(interest.get("signal_policy"), dict) else {}
        active_target_count = sum(1 for target in targets if isinstance(target, dict) and int(target.get("is_active") or 0) == 1)
        active_holding_count = sum(1 for holding in holdings if isinstance(holding, dict) and int(holding.get("is_active") or 0) == 1)
        target_labels = [str(target.get("target_label")) for target in targets if isinstance(target, dict) and target.get("target_label")]
        holding_labels = [str(holding.get("raw_input") or holding.get("normalized_name")) for holding in holdings if isinstance(holding, dict)]
        signal_count = signal_count_by_interest.get(interest_id, 0)
        match_count = match_count_by_interest.get(interest_id, 0)

        interest_kind = str(interest.get("interest_kind") or "unknown")
        interest_kind_counts[interest_kind] = interest_kind_counts.get(interest_kind, 0) + 1
        if str(interest.get("interest_priority") or "") == "high":
            high_priority_count += 1
        if str(policy.get("delivery_mode") or "") == "immediate":
            immediate_policy_count += 1
        total_target_count += active_target_count
        total_holding_count += active_holding_count
        if active_holding_count:
            interests_with_holdings += 1

        interest["summary"] = {
            "active_target_count": active_target_count,
            "active_holding_count": active_holding_count,
            "active_signal_count": signal_count,
            "active_match_count": match_count,
            "has_holdings": active_holding_count > 0,
            "primary_target_label": target_labels[0] if target_labels else None,
            "target_labels": target_labels,
            "holding_labels": holding_labels,
            "delivery_mode": policy.get("delivery_mode"),
            "budget_max": next(
                (
                    target.get("budget_max")
                    for target in targets
                    if isinstance(target, dict) and target.get("budget_max") is not None
                ),
                None,
            ),
        }
        enriched_interests.append(interest)

    enriched_interests.sort(
        key=lambda item: (
            0 if str(item.get("interest_priority") or "") == "high" else 1,
            -int(((item.get("summary") or {}).get("active_signal_count") or 0)),
            -int(((item.get("summary") or {}).get("active_match_count") or 0)),
            str(item.get("interest_name") or ""),
        )
    )

    return {
        "ok": True,
        "user": profile_payload["user"],
        "defaults": profile_payload.get("defaults"),
        "summary": {
            "active_interest_count": len(enriched_interests),
            "active_target_count": total_target_count,
            "active_holding_count": total_holding_count,
            "interests_with_holdings": interests_with_holdings,
            "high_priority_count": high_priority_count,
            "immediate_policy_count": immediate_policy_count,
        },
        "interest_kind_counts": interest_kind_counts,
        "interests": enriched_interests,
    }


def load_interest_editor_payload(db_path: Path, *, user_id: str, interest_id: str) -> dict[str, object]:
    payload = load_user_interests_payload(db_path, user_id=user_id)
    interests = payload["interests"] if isinstance(payload.get("interests"), list) else []
    interest = next(
        (
            item
            for item in interests
            if isinstance(item, dict) and str(item.get("id") or "") == interest_id
        ),
        None,
    )
    if interest is None:
        raise ValueError(f"interest not found: {interest_id}")
    return {
        "ok": True,
        "user": payload["user"],
        "interest": interest,
    }


def load_interest_creation_payload(db_path: Path, *, user_id: str) -> dict[str, object]:
    payload = load_user_profile_payload(db_path, user_id=user_id)
    return {
        "ok": True,
        "user": payload["user"],
        "defaults": payload.get("defaults") if isinstance(payload.get("defaults"), dict) else {},
    }


def create_interest_form(
    *,
    db_path: Path,
    user_id: str,
    interest_name: str,
    raw_input: str,
    interest_kind: str,
    scope_kind: str,
    precision_mode: str,
    interest_priority: str,
    interest_notes: str,
    budget_max: float | None,
    condition_mode: str,
    delivery_mode: str,
    cooldown_hours: int,
    min_match_score: float | None,
    max_signals_per_day: int,
) -> dict[str, object]:
    created_record = run_with_sqlite_retry(
        lambda: create_interest_record(
            db_path=db_path,
            user_id=user_id,
            interest_name=interest_name,
            raw_input=raw_input,
            interest_kind=interest_kind,
            scope_kind=scope_kind,
            precision_mode=precision_mode,
            interest_priority=interest_priority,
            interest_notes=interest_notes,
            budget_max=budget_max,
            condition_mode=condition_mode,
            delivery_mode=delivery_mode,
            cooldown_hours=cooldown_hours,
            min_match_score=min_match_score,
            max_signals_per_day=max_signals_per_day,
        ),
    )
    interest_id = str(created_record["interest_id"])
    refresh_payload = run_with_sqlite_retry(
        lambda: run_interest_refresh_payload(
            db_path,
            user_id=user_id,
            lookback_hours=DEFAULT_INTEREST_REFRESH_LOOKBACK_HOURS,
        ),
    )
    created = load_interest_editor_payload(db_path, user_id=user_id, interest_id=interest_id)
    return {
        "ok": True,
        "created_at": created_record["created_at"],
        "user": created["user"],
        "interest": created["interest"],
        "target_id": created_record["target_id"],
        "refresh": refresh_payload,
    }


def save_interest_form(
    *,
    db_path: Path,
    user_id: str,
    interest_id: str,
    interest_priority: str,
    interest_notes: str,
    budget_max: float | None,
    condition_mode: str,
    delivery_mode: str,
    cooldown_hours: int,
    min_match_score: float | None,
    max_signals_per_day: int,
) -> dict[str, object]:
    valid_priorities = {"high", "normal", "low"}
    valid_condition_modes = {"ignore", "prefer", "require"}
    valid_delivery_modes = {"immediate", "daily_digest"}
    if interest_priority not in valid_priorities:
        raise ValueError("invalid interest_priority")
    if condition_mode not in valid_condition_modes:
        raise ValueError("invalid condition_mode")
    if delivery_mode not in valid_delivery_modes:
        raise ValueError("invalid delivery_mode")

    now_iso = datetime.utcnow().replace(microsecond=0).isoformat() + "+00:00"
    with db_connect(db_path, write=True) as conn:
        interest_row = conn.execute(
            """
            SELECT id
            FROM user_interests_v2
            WHERE id = ? AND user_id = ?
            """,
            (interest_id, user_id),
        ).fetchone()
        if interest_row is None:
            raise ValueError(f"interest not found: {interest_id}")

        target_row = conn.execute(
            """
            SELECT id
            FROM user_interest_targets_v2
            WHERE interest_id = ? AND is_active = 1
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """,
            (interest_id,),
        ).fetchone()
        if target_row is None:
            raise ValueError("no editable active target found for interest")

        policy_row = conn.execute(
            """
            SELECT id
            FROM user_interest_signal_policies_v2
            WHERE interest_id = ?
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """,
            (interest_id,),
        ).fetchone()
        if policy_row is None:
            raise ValueError("no editable signal policy found for interest")

        conn.execute(
            """
            UPDATE user_interests_v2
            SET interest_priority = ?,
                notes = ?,
                updated_at = ?
            WHERE id = ? AND user_id = ?
            """,
            (interest_priority, interest_notes.strip(), now_iso, interest_id, user_id),
        )
        conn.execute(
            """
            UPDATE user_interest_targets_v2
            SET budget_max = ?,
                condition_mode = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (budget_max, condition_mode, now_iso, str(target_row["id"])),
        )
        conn.execute(
            """
            UPDATE user_interest_signal_policies_v2
            SET delivery_mode = ?,
                cooldown_hours = ?,
                min_match_score = ?,
                max_signals_per_day = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                delivery_mode,
                cooldown_hours,
                min_match_score,
                max_signals_per_day,
                now_iso,
                str(policy_row["id"]),
            ),
        )
        conn.commit()

    refresh_payload = run_interest_refresh_payload(
        db_path,
        user_id=user_id,
        lookback_hours=DEFAULT_INTEREST_REFRESH_LOOKBACK_HOURS,
    )
    updated = load_interest_editor_payload(db_path, user_id=user_id, interest_id=interest_id)
    return {
        "ok": True,
        "updated_at": now_iso,
        "user": updated["user"],
        "interest": updated["interest"],
        "refresh": refresh_payload,
    }


def delete_interest_form(
    *,
    db_path: Path,
    user_id: str,
    interest_id: str,
) -> dict[str, object]:
    deleted_record = run_with_sqlite_retry(
        lambda: delete_interest_record(
            db_path=db_path,
            user_id=user_id,
            interest_id=interest_id,
        ),
    )
    refresh_payload = run_with_sqlite_retry(
        lambda: run_interest_refresh_payload(
            db_path,
            user_id=user_id,
            lookback_hours=DEFAULT_INTEREST_REFRESH_LOOKBACK_HOURS,
        ),
    )
    refreshed = load_user_interests_payload(db_path, user_id=user_id)
    return {
        "ok": True,
        "deleted_at": deleted_record["deleted_at"],
        "user": refreshed["user"],
        "summary": refreshed["summary"],
        "interest": deleted_record["interest"],
        "refresh": refresh_payload,
    }


def load_user_reports_payload(reports_dir: Path, *, user_id: str) -> dict[str, object]:
    reports = report_entries(reports_dir)
    user_reports = []
    shared_reports = []
    for item in reports:
        kind = str(item["kind"])
        scope = str(item["scope"])
        if scope == f"Collector: {user_id}":
            user_reports.append(enrich_report_links(item))
        elif kind in {"interest_digest_index", "signal_review_index", "user_base_review"}:
            shared_reports.append(enrich_report_links(item))

    return {
        "ok": True,
        "user_id": user_id,
        "reports": user_reports,
        "shared_reports": shared_reports,
        "latest": {
            "digest": latest_report_metadata(reports_dir, "interest_digest_user", user_id=user_id),
            "signal_review": latest_report_metadata(reports_dir, "signal_review_user", user_id=user_id),
            "daily_review": latest_report_metadata(reports_dir, "user_base_review"),
        },
    }


def load_user_signals_payload(
    db_path: Path,
    *,
    user_id: str,
    lookback_hours: int,
) -> dict[str, object]:
    with db_connect(db_path) as conn:
        user_row = conn.execute(
            """
            SELECT id, display_name, language, timezone
            FROM users
            WHERE id = ?
            """,
            (user_id,),
        ).fetchone()
        if user_row is None:
            raise ValueError(f"user not found: {user_id}")

        signal_rows = conn.execute(
            """
            SELECT
              s.id,
              s.interest_id,
              s.target_id,
              s.listing_id,
              s.signal_type,
              s.urgency,
              s.reason_code,
              s.signal_title,
              s.signal_summary,
              s.group_key,
              s.payload_json,
              s.created_at,
              s.last_seen_at,
              s.status,
              i.interest_name,
              i.interest_kind,
              i.interest_priority,
              t.target_label,
              t.budget_max,
              n.source_listing_id,
              n.title AS listing_title,
              n.status_norm AS listing_status,
              COALESCE(n.price_end, n.price_initial) AS listing_price,
              n.price_end,
              n.updated_at AS listing_updated_at
            FROM signals_v2 s
            JOIN user_interests_v2 i ON i.id = s.interest_id
            LEFT JOIN user_interest_targets_v2 t ON t.id = s.target_id
            LEFT JOIN market_listings_norm_v2 n ON n.id = s.listing_id
            WHERE s.user_id = ? AND s.status = 'active'
            ORDER BY
              CASE s.urgency WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
              s.last_seen_at DESC,
              i.interest_name,
              s.signal_type
            """,
            (user_id,),
        ).fetchall()

    recent_cutoff = datetime.utcnow().timestamp() - (lookback_hours * 3600)
    signals: list[dict[str, object]] = []
    urgency_counts = {"high": 0, "medium": 0, "low": 0}
    event_signal_count = 0
    recent_signal_count = 0
    groups_by_interest: dict[str, dict[str, object]] = {}

    for row in signal_rows:
        signal = normalize_sqlite_row(row)
        payload = parse_json_blob(signal.pop("payload_json", None))
        urgency = str(signal.get("urgency") or "low")
        urgency_counts[urgency] = urgency_counts.get(urgency, 0) + 1
        signal_type = str(signal.get("signal_type") or "")
        signal_family = "event" if signal_type in EVENT_SIGNAL_TYPES else "standing"
        if signal_family == "event":
            event_signal_count += 1
        last_seen_at = str(signal.get("last_seen_at") or "")
        if iso_to_unix(last_seen_at) >= recent_cutoff:
            recent_signal_count += 1

        listing_price = signal.get("listing_price")
        signal["payload"] = payload
        signal["signal_family"] = signal_family
        signal["pricing_note"] = build_signal_pricing_note(signal=signal, payload=payload)
        signal["context_note"] = build_signal_context_note(signal=signal, payload=payload)
        signal["listing"] = {
            "source_listing_id": signal.get("source_listing_id"),
            "title": signal.get("listing_title"),
            "status": signal.get("listing_status"),
            "price": listing_price,
            "updated_at": signal.get("listing_updated_at"),
        }
        signals.append(signal)

        interest_key = str(signal.get("interest_id"))
        group = groups_by_interest.setdefault(
            interest_key,
            {
                "interest_id": signal.get("interest_id"),
                "interest_name": signal.get("interest_name"),
                "interest_kind": signal.get("interest_kind"),
                "interest_priority": signal.get("interest_priority"),
                "signal_count": 0,
                "high_count": 0,
                "signals": [],
            },
        )
        group["signal_count"] = int(group["signal_count"]) + 1
        if urgency == "high":
            group["high_count"] = int(group["high_count"]) + 1
        cast_signals = group["signals"]
        if isinstance(cast_signals, list) and len(cast_signals) < 3:
            cast_signals.append(signal)

    interest_groups = sorted(
        groups_by_interest.values(),
        key=lambda item: (
            -int(item["high_count"]),
            -int(item["signal_count"]),
            str(item["interest_name"]),
        ),
    )
    top_signals = signals[:8]

    return {
        "ok": True,
        "user_id": user_id,
        "user": normalize_sqlite_row(user_row),
        "lookback_hours": lookback_hours,
        "summary": {
            "active_signal_count": len(signals),
            "event_signal_count": event_signal_count,
            "standing_signal_count": len(signals) - event_signal_count,
            "recent_signal_count": recent_signal_count,
            "high_count": urgency_counts.get("high", 0),
            "medium_count": urgency_counts.get("medium", 0),
            "low_count": urgency_counts.get("low", 0),
            "interest_count": len(interest_groups),
        },
        "signals": signals,
        "top_signals": top_signals,
        "interest_groups": interest_groups,
    }


def load_user_matches_payload(
    db_path: Path,
    *,
    user_id: str,
) -> dict[str, object]:
    with db_connect(db_path) as conn:
        user_row = conn.execute(
            """
            SELECT id, display_name, language, timezone
            FROM users
            WHERE id = ?
            """,
            (user_id,),
        ).fetchone()
        if user_row is None:
            raise ValueError(f"user not found: {user_id}")

        match_rows = conn.execute(
            """
            SELECT
              lm.id,
              lm.listing_id,
              lm.user_item_id,
              lm.item_type,
              lm.relationship_type,
              lm.match_score,
              lm.identity_score,
              lm.series_score,
              lm.variant_score,
              lm.condition_score,
              lm.match_reasons_json,
              lm.matched_at,
              lm.updated_at,
              i.id AS interest_id,
              i.interest_name,
              i.interest_kind,
              i.interest_priority,
              t.target_label,
              t.budget_max,
              h.raw_input AS holding_label,
              h.cost_basis_unit,
              n.source_listing_id,
              n.title AS listing_title,
              n.status_norm AS listing_status,
              COALESCE(n.price_end, n.price_initial) AS listing_price,
              n.price_end,
              n.updated_at AS listing_updated_at,
              n.end_at,
              n.category_name_raw,
              n.character_name_raw
            FROM listing_matches_v2 lm
            JOIN market_listings_norm_v2 n ON n.id = lm.listing_id
            LEFT JOIN user_interest_targets_v2 t ON t.id = lm.user_item_id
            LEFT JOIN user_holdings_v2 h ON h.id = lm.user_item_id
            LEFT JOIN user_interests_v2 i ON i.id = COALESCE(t.interest_id, h.linked_interest_id)
            WHERE lm.user_id = ? AND lm.status = 'active'
            ORDER BY
              lm.match_score DESC,
              CASE n.status_norm WHEN 'live' THEN 1 WHEN 'preview' THEN 2 WHEN 'ended' THEN 3 ELSE 4 END,
              lm.updated_at DESC,
              n.title
            """,
            (user_id,),
        ).fetchall()

    matches: list[dict[str, object]] = []
    relationship_counts = {"exact_identity": 0, "variant_related": 0, "series_related": 0}
    status_counts = {"live": 0, "preview": 0, "ended": 0, "other": 0}
    high_score_count = 0
    groups: dict[str, dict[str, object]] = {}

    for row in match_rows:
        match = normalize_sqlite_row(row)
        reasons = parse_json_list(match.pop("match_reasons_json", None))
        relationship = str(match.get("relationship_type") or "other")
        listing_status = str(match.get("listing_status") or "other")
        relationship_counts[relationship] = relationship_counts.get(relationship, 0) + 1
        status_counts[listing_status if listing_status in status_counts else "other"] += 1
        score = float(match.get("match_score") or 0.0)
        if score >= 120.0:
            high_score_count += 1

        target_label = match.get("target_label") or match.get("holding_label") or match.get("interest_name")
        price = match.get("listing_price")
        budget_max = match.get("budget_max")
        cost_basis_unit = match.get("cost_basis_unit")
        opportunity_note = build_match_opportunity_note(
            relationship_type=relationship,
            listing_status=listing_status,
            listing_price=price,
            budget_max=budget_max,
            cost_basis_unit=cost_basis_unit,
        )
        match["match_reasons"] = reasons
        match["target_label"] = target_label
        match["opportunity_note"] = opportunity_note
        matches.append(match)

        group_key = "|".join(
            [
                str(match.get("interest_id") or ""),
                relationship,
                listing_status,
                str(match.get("listing_title") or ""),
            ]
        )
        group = groups.setdefault(
            group_key,
            {
                "interest_id": match.get("interest_id"),
                "interest_name": match.get("interest_name"),
                "interest_kind": match.get("interest_kind"),
                "interest_priority": match.get("interest_priority"),
                "relationship_type": relationship,
                "listing_status": listing_status,
                "listing_title": match.get("listing_title"),
                "target_label": target_label,
                "listing_count": 0,
                "top_match_score": 0.0,
                "price_min": None,
                "price_max": None,
                "sample_source_listing_ids": [],
            },
        )
        group["listing_count"] = int(group["listing_count"]) + 1
        group["top_match_score"] = max(float(group["top_match_score"]), score)
        if price is not None:
            current_min = group.get("price_min")
            current_max = group.get("price_max")
            group["price_min"] = price if current_min is None else min(float(current_min), float(price))
            group["price_max"] = price if current_max is None else max(float(current_max), float(price))
        sample_ids = group.get("sample_source_listing_ids")
        if isinstance(sample_ids, list) and len(sample_ids) < 4 and match.get("source_listing_id"):
            sample_ids.append(match.get("source_listing_id"))

    opportunity_groups = sorted(
        groups.values(),
        key=lambda item: (
            relationship_rank(str(item.get("relationship_type") or "")),
            status_rank(str(item.get("listing_status") or "")),
            -float(item.get("top_match_score") or 0.0),
            -int(item.get("listing_count") or 0),
            str(item.get("interest_name") or ""),
        ),
    )

    return {
        "ok": True,
        "user_id": user_id,
        "user": normalize_sqlite_row(user_row),
        "summary": {
            "active_match_count": len(matches),
            "high_score_count": high_score_count,
            "live_count": status_counts.get("live", 0),
            "preview_count": status_counts.get("preview", 0),
            "ended_count": status_counts.get("ended", 0),
            "exact_count": relationship_counts.get("exact_identity", 0),
            "variant_count": relationship_counts.get("variant_related", 0),
            "series_count": relationship_counts.get("series_related", 0),
            "opportunity_group_count": len(opportunity_groups),
        },
        "matches": matches,
        "top_matches": matches[:12],
        "opportunity_groups": opportunity_groups[:12],
    }


def load_latest_digest_payload(
    *,
    db_path: Path,
    reports_dir: Path,
    user_id: str,
    lookback_hours: int,
) -> dict[str, object]:
    report_path = latest_user_report_path(reports_dir, user_id=user_id, kind="interest_digest_user")
    if report_path is None:
        created = build_interest_digest_report(str(db_path), str(reports_dir), user_id=user_id, lookback_hours=lookback_hours)
        report_path = Path(created.report_path)
    if report_path is None or not report_path.exists():
        raise ValueError(f"latest digest not found for user: {user_id}")
    metadata = classify_report(report_path.name)
    stat = report_path.stat()
    markdown = report_path.read_text(encoding="utf-8")
    return {
        "ok": True,
        "user_id": user_id,
        "report": {
            "name": report_path.name,
            "kind": metadata["kind"],
            "label": metadata["label"],
            "scope": metadata["scope"],
            "timestamp_label": metadata["timestamp_label"],
            "size_bytes": stat.st_size,
            "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "links": {
                "rendered": f"/reports/{quote(report_path.name)}",
                "raw": f"/raw/{quote(report_path.name)}",
            },
        },
        "markdown": markdown,
        "lookback_hours": lookback_hours,
    }


def run_matching_payload(db_path: Path, *, user_id: str, only_active_listings: bool) -> dict[str, object]:
    result = run_v2_matching(str(db_path), user_id=user_id, only_active_listings=only_active_listings)
    return {
        "ok": True,
        "user_id": user_id,
        "only_active_listings": only_active_listings,
        "result": normalize_dataclass(result),
    }


def run_signals_payload(db_path: Path, *, user_id: str, lookback_hours: int) -> dict[str, object]:
    result = run_interest_signal_generation(str(db_path), user_id=user_id, lookback_hours=lookback_hours)
    return {
        "ok": True,
        "user_id": user_id,
        "lookback_hours": lookback_hours,
        "result": normalize_dataclass(result),
    }


def run_digest_payload(
    *,
    db_path: Path,
    reports_dir: Path,
    user_id: str,
    lookback_hours: int,
) -> dict[str, object]:
    result = build_interest_digest_report(str(db_path), str(reports_dir), user_id=user_id, lookback_hours=lookback_hours)
    report_path = Path(result.report_path)
    return {
        "ok": True,
        "user_id": user_id,
        "lookback_hours": lookback_hours,
        "result": normalize_dataclass(result),
        "report": {
            "name": report_path.name,
            "rendered": f"/reports/{quote(report_path.name)}",
            "raw": f"/raw/{quote(report_path.name)}",
        },
    }


def run_interest_refresh_payload(db_path: Path, *, user_id: str, lookback_hours: int) -> dict[str, object]:
    matching_payload = run_matching_payload(db_path, user_id=user_id, only_active_listings=True)
    signals_payload = run_signals_payload(db_path, user_id=user_id, lookback_hours=lookback_hours)
    return {
        "ok": True,
        "user_id": user_id,
        "lookback_hours": lookback_hours,
        "matching": matching_payload,
        "signals": signals_payload,
    }


def latest_user_report_path(reports_dir: Path, *, user_id: str, kind: str) -> Path | None:
    for item in report_entries(reports_dir):
        if item["kind"] == kind and item["scope"] == f"Collector: {user_id}":
            return reports_dir / str(item["name"])
    return None


def latest_report_metadata(reports_dir: Path, kind: str, *, user_id: str | None = None) -> dict[str, object] | None:
    for item in report_entries(reports_dir):
        if item["kind"] != kind:
            continue
        if user_id is not None and item["scope"] != f"Collector: {user_id}":
            continue
        return enrich_report_links(item)
    return None


def enrich_report_links(item: dict[str, object]) -> dict[str, object]:
    enriched = dict(item)
    name = str(item["name"])
    enriched["links"] = {
        "rendered": f"/reports/{quote(name)}",
        "raw": f"/raw/{quote(name)}",
        "latest_of_type": f"/latest/{quote(str(item['kind']))}",
    }
    return enriched


def normalize_sqlite_row(row: sqlite3.Row | None) -> dict[str, object]:
    if row is None:
        return {}
    return {key: row[key] for key in row.keys()}


def normalize_dataclass(value: object) -> dict[str, object]:
    return {key: getattr(value, key) for key in value.__dataclass_fields__.keys()}  # type: ignore[attr-defined]


def decode_json_fields(payload: dict[str, object]) -> dict[str, object]:
    decoded = dict(payload)
    for key in ("variant_tokens_json", "quantity_tokens_json", "condition_tokens_json"):
        raw = decoded.get(key)
        if not isinstance(raw, str):
            continue
        try:
            decoded[key.removesuffix("_json")] = json.loads(raw)
        except json.JSONDecodeError:
            decoded[key.removesuffix("_json")] = []
    return decoded


def parse_json_blob(value: object) -> dict[str, object]:
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def iso_to_unix(value: str) -> float:
    if not value:
        return 0.0
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def build_signal_pricing_note(*, signal: dict[str, object], payload: dict[str, object]) -> str | None:
    budget_max = payload.get("budget_max")
    expected_end_mid = payload.get("expected_end_mid")
    cost_basis_unit = payload.get("cost_basis_unit")
    listing_price = signal.get("listing_price")
    fragments: list[str] = []
    if listing_price is not None:
        fragments.append(f"listing price {listing_price}")
    if budget_max is not None:
        fragments.append(f"budget max {budget_max}")
    if expected_end_mid is not None:
        fragments.append(f"ended trend {expected_end_mid}")
    if cost_basis_unit is not None:
        fragments.append(f"cost basis {cost_basis_unit}")
    if not fragments:
        return None
    return " | ".join(fragments)


def build_signal_context_note(*, signal: dict[str, object], payload: dict[str, object]) -> str | None:
    listing_title = signal.get("listing_title")
    listing_status = signal.get("listing_status")
    if listing_title:
        if listing_status:
            return f"{listing_status} listing: {listing_title}"
        return f"listing: {listing_title}"

    event = payload.get("event")
    if isinstance(event, dict):
        title = event.get("title")
        new_status = event.get("new_status_raw")
        if title and new_status:
            return f"event listing: {title} -> status {new_status}"
        if title:
            return f"event listing: {title}"

    group = payload.get("group")
    if isinstance(group, dict):
        title = group.get("title")
        listing_count = group.get("listing_count")
        status_norm = group.get("status_norm")
        relationship_type = group.get("relationship_type")
        fragments = []
        if title:
            fragments.append(str(title))
        if listing_count is not None:
            fragments.append(f"{listing_count} listings")
        if status_norm:
            fragments.append(str(status_norm))
        if relationship_type:
            fragments.append(str(relationship_type))
        if fragments:
            return " | ".join(fragments)

    top_group = payload.get("top_group")
    if isinstance(top_group, dict):
        title = top_group.get("title")
        listing_count = top_group.get("listing_count")
        if title and listing_count is not None:
            return f"top discovery group: {title} ({listing_count} listings)"

    return None


def classify_report(name: str) -> dict[str, str]:
    for kind, label, scope, pattern in REPORT_PATTERNS:
        match = re.match(pattern, name)
        if not match:
            continue
        groups = match.groups()
        user_id = groups[0] if len(groups) == 2 else None
        timestamp_token = groups[-1]
        metadata = {
            "kind": kind,
            "label": label,
            "scope": scope,
            "timestamp_label": format_report_timestamp(timestamp_token),
            "user_id": user_id or "",
        }
        if user_id:
            metadata["scope"] = f"Collector: {user_id}"
        return metadata
    return {
        "kind": "other",
        "label": "Report",
        "scope": "Unclassified",
        "timestamp_label": "Unknown time",
        "user_id": "",
    }


def format_report_timestamp(token: str) -> str:
    try:
        parsed = datetime.strptime(token, "%Y%m%dT%H%M%S%z")
    except ValueError:
        return token
    return parsed.strftime("%b %d, %Y %H:%M %Z")


def latest_report_for_kind(reports_dir: Path, report_kind: str) -> Path | None:
    for item in report_entries(reports_dir):
        if item["kind"] == report_kind:
            return reports_dir / str(item["name"])
    return None


def format_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{int(num_bytes)} B"


def safe_child(parent: Path, name: str) -> Path | None:
    candidate = (parent / name).resolve()
    try:
        candidate.relative_to(parent.resolve())
    except ValueError:
        return None
    return candidate


def relationship_rank(value: str) -> int:
    if value == "exact_identity":
        return 1
    if value == "variant_related":
        return 2
    if value == "series_related":
        return 3
    return 4


def status_rank(value: str) -> int:
    if value == "live":
        return 1
    if value == "preview":
        return 2
    if value == "ended":
        return 3
    return 4


def parse_json_list(value: object) -> list[str]:
    if not isinstance(value, str) or not value.strip():
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed]


def build_match_opportunity_note(
    *,
    relationship_type: str,
    listing_status: str,
    listing_price: object,
    budget_max: object,
    cost_basis_unit: object,
) -> str | None:
    fragments = [format_relationship_type_label(relationship_type), format_listing_status_label(listing_status)]
    if listing_price is not None:
        fragments.append(f"price {listing_price}")
    if budget_max is not None:
        fragments.append(f"budget max {budget_max}")
    if cost_basis_unit is not None:
        fragments.append(f"cost basis {cost_basis_unit}")
    return " | ".join(fragment for fragment in fragments if fragment)


def render_actions_html(
    *,
    db_path: Path,
    reports_dir: Path,
    user_id: str,
    lookback_hours: int,
) -> str:
    profile_payload = load_user_profile_payload(db_path, user_id=user_id)
    reports_payload = load_user_reports_payload(reports_dir, user_id=user_id)
    user = profile_payload["user"]
    summary = profile_payload["summary"] if isinstance(profile_payload.get("summary"), dict) else {}
    latest = reports_payload.get("latest") if isinstance(reports_payload.get("latest"), dict) else {}
    digest = latest.get("digest") if isinstance(latest, dict) and isinstance(latest.get("digest"), dict) else None
    signal_review = latest.get("signal_review") if isinstance(latest, dict) and isinstance(latest.get("signal_review"), dict) else None
    lang = html_lang_attr(str(user.get("language") or ""))
    inner = f"""
    <div class="detail-body">
    <section class="hero page-hero">
      <span class="eyebrow">Actions</span>
      <h1>{html.escape(str(user["display_name"]))}</h1>
      <p>Refresh matches when the market changes, regenerate alerts after big updates, or rebuild your digest for a fresh read. These steps run on the server and may take up to a minute.</p>
      <div class="chip-row">
        <span class="chip">Interests <strong>{summary.get("active_interest_count", 0)}</strong></span>
        <span class="chip">Matches <strong>{summary.get("active_match_count", 0)}</strong></span>
        <span class="chip">Alerts <strong>{summary.get("active_signal_count", 0)}</strong></span>
      </div>
    </section>
    <section class="actions-grid">
      <article class="action-card">
        <span class="eyebrow">Step</span>
        <h3>Refresh live matches</h3>
        <p>Re-scan listings against your saved interests. By default only live and preview auctions are included.</p>
        <form method="post" action="/actions/run" onsubmit="return confirm(&quot;Refresh your match list now? You can keep browsing while this finishes.&quot;);">
          <input type="hidden" name="user_id" value="{html.escape(user_id)}">
          <input type="hidden" name="action" value="matching">
          <div class="radio-stack">
            <div class="radio-line">
              <input type="radio" name="only_active" id="only_act_yes" value="true" checked>
              <label for="only_act_yes"><strong>Live &amp; preview only</strong><span class="field-help">Focus on auctions you can still bid on.</span></label>
            </div>
            <div class="radio-line">
              <input type="radio" name="only_active" id="only_act_no" value="false">
              <label for="only_act_no"><strong>Include ended listings</strong><span class="field-help">Slower—useful for comps and research.</span></label>
            </div>
          </div>
          <button type="submit">Run refresh</button>
        </form>
      </article>
      <article class="action-card">
        <span class="eyebrow">Step</span>
        <h3>Regenerate alerts</h3>
        <p>Rebuild alert notices from current matches (uses the lookback window below).</p>
        <form method="post" action="/actions/run" onsubmit="return confirm(&quot;Regenerate alerts now?&quot;);">
          <input type="hidden" name="user_id" value="{html.escape(user_id)}">
          <input type="hidden" name="action" value="signals">
          <label>Lookback (hours)
            <input type="number" name="lookback_hours" min="1" max="168" value="{lookback_hours}">
          </label>
          <button type="submit">Regenerate alerts</button>
        </form>
      </article>
      <article class="action-card">
        <span class="eyebrow">Step</span>
        <h3>Rebuild digest</h3>
        <p>Create a fresh written digest PDF-style report from recent activity.</p>
        <form method="post" action="/actions/run" onsubmit="return confirm(&quot;Rebuild digest now?&quot;);">
          <input type="hidden" name="user_id" value="{html.escape(user_id)}">
          <input type="hidden" name="action" value="digest">
          <label>Lookback (hours)
            <input type="number" name="lookback_hours" min="1" max="168" value="{lookback_hours}">
          </label>
          <button type="submit">Rebuild digest</button>
        </form>
      </article>
    </section>
    <section class="section">
      <div class="section-header">
        <div>
          <h2>Latest generated reports</h2>
          <p>Open the newest digest or signal roundup rendered for this collector.</p>
        </div>
      </div>
      <div class="report-list">
        {render_action_report_row(digest, empty_label="No digest generated yet.")}
        {render_action_report_row(signal_review, empty_label="No signal roundup generated yet.")}
      </div>
    </section>
    </div>
    """

    add_css = ".field-help { display: block; font-size: 0.86rem; color: var(--muted); margin-top: 2px; }"
    return render_document(
        title="Settings & refresh",
        html_lang=lang,
        user_id=user_id,
        nav_active="settings",
        main_inner_html=inner.strip(),
        main_classes="page-wide detail-body-wrap",
        extra_css=add_css,
    )


def render_action_result_html(
    *,
    db_path: Path,
    reports_dir: Path,
    user_id: str,
    action_name: str,
    lookback_hours: int,
    only_active_listings: bool,
) -> str:
    lang = profile_html_lang(db_path, user_id=user_id)
    if action_name == "matching":
        payload = run_matching_payload(db_path, user_id=user_id, only_active_listings=only_active_listings)
        title = "Matches refreshed"
        touched = html.escape(str(((payload.get("result") or {}).get("matches_upserted") or 0)))
        scope_copy = (
            "Only auctions that were still eligible to bid on were scanned."
            if only_active_listings
            else "Ended listings stayed in the dataset so you can compare past sales."
        )
        summary_html = (
            f'<p>Wrote <strong>{touched}</strong> refreshed match rows. {html.escape(scope_copy)}</p>'
            f"<p class=\"signal-note\">This can take up to a minute on large catalogs—results are visible on the Matches page.</p>"
        )
        anchors = [
            f'<a class="action-button" href="/matches?user_id={quote(user_id)}">Open matches</a>',
            f'<a href="/?user_id={quote(user_id)}">Dashboard</a>',
            f'<a href="/actions?user_id={quote(user_id)}">Actions</a>',
        ]
        if show_app_dev_ui():
            anchors.append(f'<a href="/api/users/{quote(user_id)}/matches">Matches JSON</a>')
        links_html = f'<div class="detail-row hero-actions">{"".join(anchors)}</div>'
    elif action_name == "signals":
        payload = run_signals_payload(db_path, user_id=user_id, lookback_hours=lookback_hours)
        result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
        title = "Alerts refreshed"
        ins = html.escape(str(result.get("inserted") or 0))
        upd = html.escape(str(result.get("updated") or 0))
        summary_html = f"""<p>Generated <strong>{ins}</strong> new alerts and updated <strong>{upd}</strong> existing ones.</p><p class="signal-note">Window: last <strong>{html.escape(str(lookback_hours))}h</strong> of activity.</p>"""
        anchors = [
            f'<a class="action-button" href="/?user_id={quote(user_id)}#signals">Open alerts inbox</a>',
            f'<a href="/actions?user_id={quote(user_id)}">Actions</a>',
            f'<a href="/?user_id={quote(user_id)}">Dashboard</a>',
        ]
        if show_app_dev_ui():
            anchors.append(f'<a href="/api/users/{quote(user_id)}/signals">Alerts JSON</a>')
        links_html = f'<div class="detail-row hero-actions">{"".join(anchors)}</div>'
    elif action_name == "digest":
        payload = run_digest_payload(db_path=db_path, reports_dir=reports_dir, user_id=user_id, lookback_hours=lookback_hours)
        report = payload.get("report") if isinstance(payload.get("report"), dict) else {}
        title = "Digest regenerated"
        rname = html.escape(str(report.get("name") or "-"))
        rendered_href = str(report.get("rendered") or "/")
        raw_href = str(report.get("raw") or "/")
        summary_html = (
            f"<p>New digest file <strong>{rname}</strong> is ready to read.</p>"
            f'<p class="signal-note">Covered roughly the last <strong>{html.escape(str(lookback_hours))}h</strong> worth of churn.</p>'
        )
        anchors = [
            f'<a class="action-button" href="{html.escape(rendered_href)}">Open readable digest</a>',
            f'<a href="/actions?user_id={quote(user_id)}">Actions</a>',
            f'<a href="/?user_id={quote(user_id)}">Dashboard</a>',
        ]
        if show_app_dev_ui():
            anchors.append(f'<a href="{html.escape(raw_href)}">Markdown source</a>')
        links_html = f'<div class="detail-row hero-actions">{"".join(anchors)}</div>'
    else:
        raise ValueError("unknown action")

    dev_panel = ""
    if show_app_dev_ui():
        pretty_payload = html.escape(json.dumps(payload, ensure_ascii=False, indent=2))
        dev_panel = (
            '<section class="panel"><details class="dev-advanced"><summary>Advanced: raw response payload</summary>'
            f"<pre>{pretty_payload}</pre></details></section>"
        )

    inner = f"""
    <div class="detail-body">
    <section class="panel hero page-hero">
      <span class="eyebrow">{html.escape(title)}</span>
      <h1>All set</h1>
      {summary_html}
      {links_html}
    </section>
    {dev_panel}
    </div>
    """
    return render_document(
        title=title,
        html_lang=lang,
        user_id=user_id,
        nav_active="settings",
        main_inner_html=inner.strip(),
        main_classes="page-wide detail-body-wrap",
        omit_glossary_footer=True,
    )


def render_interest_edit_html(
    *,
    db_path: Path,
    user_id: str,
    interest_id: str,
) -> str:
    payload = load_interest_editor_payload(db_path, user_id=user_id, interest_id=interest_id)
    user = payload["user"]
    interest = payload["interest"]
    targets = interest.get("targets") if isinstance(interest.get("targets"), list) else []
    holdings = interest.get("holdings") if isinstance(interest.get("holdings"), list) else []
    policy = interest.get("signal_policy") if isinstance(interest.get("signal_policy"), dict) else {}
    primary_target = next((target for target in targets if isinstance(target, dict)), {})
    primary_holding = next((holding for holding in holdings if isinstance(holding, dict)), {})
    lang = html_lang_attr(str(user.get("language") or ""))
    tgt = html.escape(str(primary_target.get("target_label") or "-"))
    hld = html.escape(str(primary_holding.get("raw_input") or primary_holding.get("normalized_name") or "none"))
    inner = f"""
    <div class="detail-body">
    <section class="panel hero page-hero">
      <span class="eyebrow">Edit saved interest</span>
      <h1>{html.escape(str(interest.get("interest_name") or "-"))}</h1>
      <p>Update how aggressively we match, when we alert you, and any personal notes—without touching the API.</p>
      <p class="signal-note">Primary target: <strong>{tgt}</strong> · Linked holding: <strong>{hld}</strong></p>
      <details class="identity-advanced">
        <summary>Account id</summary>
        <p><code>{html.escape(str(user.get("id") or user_id))}</code></p>
      </details>
    </section>
    <section class="panel interest-detail-card form-panel">
      <form method="post" action="/interests/save">
        <input type="hidden" name="user_id" value="{html.escape(user_id)}">
        <input type="hidden" name="interest_id" value="{html.escape(interest_id)}">
        <p class="form-fieldset-title">Basics</p>
        <div class="grid">
          <label>Priority
            <select name="interest_priority">
              {render_select_option('high', str(interest.get('interest_priority') or ''), 'High')}
              {render_select_option('normal', str(interest.get('interest_priority') or ''), 'Normal')}
              {render_select_option('low', str(interest.get('interest_priority') or ''), 'Low')}
            </select>
            <span class="field-help">Higher priority surfaces first in digests and dashboards.</span>
          </label>
        </div>
        <p class="form-fieldset-title">Targeting</p>
        <div class="grid">
          <label>Budget max
            <input type="number" step="0.01" name="budget_max" value="{html.escape(str(primary_target.get('budget_max') or ''))}">
            <span class="field-help">Optional ceiling for this target line.</span>
          </label>
          <label>Condition mode
            <select name="condition_mode">
              {render_select_option('ignore', str(primary_target.get('condition_mode') or ''), 'Ignore')}
              {render_select_option('prefer', str(primary_target.get('condition_mode') or ''), 'Prefer')}
              {render_select_option('require', str(primary_target.get('condition_mode') or ''), 'Require')}
            </select>
            <span class="field-help">How strictly listing condition must line up with what you want.</span>
          </label>
        </div>
        <p class="form-fieldset-title">Alerts &amp; delivery</p>
        <div class="grid">
          <label>Delivery mode
            <select name="delivery_mode">
              {render_select_option('immediate', str(policy.get('delivery_mode') or ''), 'Immediate')}
              {render_select_option('daily_digest', str(policy.get('delivery_mode') or ''), 'Daily digest')}
            </select>
            <span class="field-help">Immediate feels like alerts; digest batches for calmer review.</span>
          </label>
          <label>Cooldown hours
            <input type="number" min="1" max="168" name="cooldown_hours" value="{html.escape(str(policy.get('cooldown_hours') or 24))}">
            <span class="field-help">Minimum quiet time before the same alert can fire again.</span>
          </label>
        </div>
        <details class="subpanel subpanel-collapsible">
          <summary><strong>Advanced alert tuning</strong></summary>
          <div class="grid">
            <label>Min match score
              <input type="number" step="0.1" name="min_match_score" value="{html.escape(str(policy.get('min_match_score') or ''))}">
              <span class="field-help">Higher = stricter matches, usually fewer alerts.</span>
            </label>
            <label>Max alerts per day
              <input type="number" min="1" max="100" name="max_signals_per_day" value="{html.escape(str(policy.get('max_signals_per_day') or 5))}">
              <span class="field-help">Safety valve so one interest cannot flood your inbox.</span>
            </label>
          </div>
        </details>
        <p class="form-fieldset-title">Notes</p>
        <label>Personal notes
          <textarea name="interest_notes">{html.escape(str(interest.get("notes") or ""))}</textarea>
          <span class="field-help">Why this interest exists, grading rules, or reminders for your future self.</span>
        </label>
        <button type="submit">Save changes</button>
      </form>
      <p><a href="/interests?user_id={quote(user_id)}">Back to saved interests</a></p>
    </section>
    </div>
    """
    return render_document(
        title="Edit interest",
        html_lang=lang,
        user_id=user_id,
        nav_active="interests",
        main_inner_html=inner.strip(),
        main_classes="page-wide detail-body-wrap",
    )


def render_interest_create_html(
    *,
    db_path: Path,
    user_id: str,
) -> str:
    payload = load_interest_creation_payload(db_path, user_id=user_id)
    user = payload.get("user") if isinstance(payload.get("user"), dict) else {}
    defaults = payload.get("defaults") if isinstance(payload.get("defaults"), dict) else {}
    default_priority = "normal"
    default_precision_mode = str(defaults.get("default_precision_mode") or "balanced")
    default_condition_mode = str(defaults.get("default_condition_mode") or "ignore")
    default_delivery_mode = str(defaults.get("default_delivery_mode") or "daily_digest")
    default_cooldown = int(defaults.get("default_cooldown_hours") or 24)
    default_min_match_score = defaults.get("default_min_match_score") or 70
    lang = html_lang_attr(str(user.get("language") or ""))
    create_extra_css = """
      .preset-grid, .guide-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
        gap: 14px;
        margin-top: 16px;
      }
      .preset-card, .guide-card {
        background: var(--panel-soft);
        border: 1px solid var(--border);
        border-radius: 18px;
        padding: 16px;
        box-shadow: 0 14px 36px rgba(81, 60, 31, 0.06);
      }
      .preset-card h3, .guide-card h3 {
        margin: 0 0 8px;
        color: var(--accent-deep);
        font-size: 1rem;
      }
      .preset-card p, .guide-card p { margin: 0 0 10px; font-size: 0.93rem; }
      .preset-card button { width: 100%; margin-top: 4px; }
    """
    preset_script = """
  <script>
    const presetDefinitions = {
      watch_buy_exact: {
        interest_kind: "watch_buy",
        scope_kind: "exact_item",
        precision_mode: "exact",
        interest_priority: "high",
        condition_mode: "require",
        delivery_mode: "immediate",
        cooldown_hours: "6",
        min_match_score: "90",
        max_signals_per_day: "6",
      },
      watch_sell_exit: {
        interest_kind: "watch_sell",
        scope_kind: "exact_item",
        precision_mode: "exact",
        interest_priority: "high",
        condition_mode: "require",
        delivery_mode: "immediate",
        cooldown_hours: "12",
        min_match_score: "88",
        max_signals_per_day: "4",
      },
      collecting_family: {
        interest_kind: "collecting",
        scope_kind: "issue_family",
        precision_mode: "balanced",
        interest_priority: "high",
        condition_mode: "prefer",
        delivery_mode: "daily_digest",
        cooldown_hours: "12",
        min_match_score: "74",
        max_signals_per_day: "8",
      },
      discovery_series: {
        interest_kind: "discovery",
        scope_kind: "series",
        precision_mode: "broad",
        interest_priority: "normal",
        condition_mode: "ignore",
        delivery_mode: "daily_digest",
        cooldown_hours: "24",
        min_match_score: "58",
        max_signals_per_day: "20",
      },
    };

    function applyInterestPreset(name) {
      const preset = presetDefinitions[name];
      if (!preset) {
        return;
      }
      for (const [fieldName, value] of Object.entries(preset)) {
        const field = document.querySelector('[name="' + fieldName + '"]');
        if (field) {
          field.value = value;
        }
      }
    }
  </script>

"""
    inner = f"""
    <div class="detail-body">
    <section class="panel hero page-hero">
      <span class="eyebrow">New saved interest</span>
      <h1>Add an interest</h1>
      <p>Name what you want to watch, paste a listing-style anchor, tune how wide the net should be, and choose alert pacing presets below if you prefer not to micromanage every field.</p>
      <details class="identity-advanced">
        <summary>Language &amp; account id</summary>
        <p>{html.escape(str(user.get("language") or "-"))} · {html.escape(str(user.get("timezone") or "-"))}</p>
        <p>Account id <code>{html.escape(str(user.get("id") or user_id))}</code></p>
      </details>
      <div class="preset-grid">
        <section class="preset-card">
          <h3>Watch Buy</h3>
          <p>For one exact item you want to buy quickly when it appears at a good level.</p>
          <button type="button" onclick="applyInterestPreset('watch_buy_exact')">Use Watch Buy preset</button>
        </section>
        <section class="preset-card">
          <h3>Watch Sell</h3>
          <p>For something you already hold and want exit signals when the market improves.</p>
          <button type="button" onclick="applyInterestPreset('watch_sell_exit')">Use Watch Sell preset</button>
        </section>
        <section class="preset-card">
          <h3>Collecting</h3>
          <p>For completing a set or family where related variants are still useful to see.</p>
          <button type="button" onclick="applyInterestPreset('collecting_family')">Use Collecting preset</button>
        </section>
        <section class="preset-card">
          <h3>Discovery</h3>
          <p>For broad market watching where you want a digest rather than immediate alerts.</p>
          <button type="button" onclick="applyInterestPreset('discovery_series')">Use Discovery preset</button>
        </section>
      </div>
    </section>
    <section class="panel interest-detail-card form-panel">
      <form method="post" action="/interests/create">
        <input type="hidden" name="user_id" value="{html.escape(user_id)}">
        <p class="form-fieldset-title">Basics</p>
        <div class="grid">
          <label>Interest name
            <input type="text" name="interest_name" placeholder="e.g. 红楼梦型张补仓" required>
            <span class="field-help">Shows up across the dashboard and digests.</span>
          </label>
          <label>Listing-style target text
            <input type="text" name="raw_input" placeholder="e.g. T69M红楼梦型张新" required>
            <span class="field-help">Paste wording like a marketplace title; we derive structured targets automatically.</span>
          </label>
        </div>
        <p class="form-fieldset-title">Targeting &amp; matching</p>
        <div class="grid">
          <label>Interest intent
            <select name="interest_kind">
              <option value="watch_buy">Watch buy</option>
              <option value="watch_sell">Watch sell</option>
              <option value="collecting">Collecting</option>
              <option value="discovery">Discovery</option>
              <option value="portfolio_monitor">Portfolio monitor</option>
            </select>
            <span class="field-help">What job this saved interest performs for you.</span>
          </label>
          <label>Scope width
            <select name="scope_kind">
              <option value="exact_item">Exact item</option>
              <option value="issue_family">Issue family</option>
              <option value="series">Series</option>
              <option value="theme">Theme</option>
              <option value="keyword">Keyword</option>
            </select>
            <span class="field-help">Narrow scopes are precise; broader ones include related variants.</span>
          </label>
          <label>Precision
            <select name="precision_mode">
              {render_select_option('exact', default_precision_mode, 'Exact')}
              {render_select_option('balanced', default_precision_mode, 'Balanced')}
              {render_select_option('broad', default_precision_mode, 'Broad')}
            </select>
            <span class="field-help">How strict fuzzy matching should be overall.</span>
          </label>
          <label>Priority
            <select name="interest_priority">
              {render_select_option('high', default_priority, 'High')}
              {render_select_option('normal', default_priority, 'Normal')}
              {render_select_option('low', default_priority, 'Low')}
            </select>
            <span class="field-help">Higher priority floats to the top of summaries.</span>
          </label>
          <label>Budget max
            <input type="number" step="0.01" name="budget_max" value="">
            <span class="field-help">Optional ceiling for affordability checks.</span>
          </label>
          <label>Condition stance
            <select name="condition_mode">
              {render_select_option('ignore', default_condition_mode, 'Ignore')}
              {render_select_option('prefer', default_condition_mode, 'Prefer')}
              {render_select_option('require', default_condition_mode, 'Require')}
            </select>
            <span class="field-help">How listing condition grading should influence matches.</span>
          </label>
        </div>
        <p class="form-fieldset-title">Alerts &amp; pacing</p>
        <div class="grid">
          <label>Delivery rhythm
            <select name="delivery_mode">
              {render_select_option('immediate', default_delivery_mode, 'Immediate')}
              {render_select_option('daily_digest', default_delivery_mode, 'Daily digest')}
              {render_select_option('silent_log', default_delivery_mode, 'Silent log')}
            </select>
            <span class="field-help">Immediate feels like pings; digest batches quieter review.</span>
          </label>
          <label>Cooldown hours
            <input type="number" min="1" max="168" name="cooldown_hours" value="{html.escape(str(default_cooldown))}">
            <span class="field-help">Minimum quiet window before repeating the same notice.</span>
          </label>
        </div>
        <details class="subpanel subpanel-collapsible">
          <summary><strong>Advanced alert thresholds</strong></summary>
          <div class="grid">
            <label>Min match score
              <input type="number" step="0.1" name="min_match_score" value="{html.escape(str(default_min_match_score))}">
              <span class="field-help">Raise for fewer, sharper hits; lower to widen coverage.</span>
            </label>
            <label>Max alerts per day
              <input type="number" min="1" max="100" name="max_signals_per_day" value="8">
              <span class="field-help">Keeps one interest from overwhelming your inbox.</span>
            </label>
          </div>
        </details>
        <p class="form-fieldset-title">Notes</p>
        <label>Personal notes
          <textarea name="interest_notes" placeholder="Personal reminders, grading rules, or why this matters."></textarea>
          <span class="field-help">Visible on saved-interest cards alongside operational stats.</span>
        </label>
        <button type="submit">Create interest</button>
      </form>
      <p><a href="/interests?user_id={quote(user_id)}">Back to saved interests</a></p>
    </section>
    <section class="panel">
      <span class="eyebrow">Quick tips</span>
      <div class="guide-grid">
        <section class="guide-card">
          <h3>Good anchor text</h3>
          <p><code>T69M红楼梦型张新</code>, <code>T43西游记新全</code>, <code>2026年中国龙31.104克普制银币</code></p>
        </section>
        <section class="guide-card">
          <h3>Broad scopes</h3>
          <p>Use <strong>series</strong>, <strong>theme</strong>, or <strong>keyword</strong> when exploration beats pinpoint accuracy.</p>
        </section>
        <section class="guide-card">
          <h3>Starter combo</h3>
          <p>Unsure? Try <strong>Watch buy</strong> + <strong>Exact item</strong> + <strong>Balanced</strong>, refresh matches, then refine.</p>
        </section>
      </div>
    </section>
    </div>
    """
    return render_document(
        title="Add saved interest",
        html_lang=lang,
        user_id=user_id,
        nav_active="interests",
        main_inner_html=inner.strip(),
        main_classes="page-wide detail-body-wrap",
        extra_css=create_extra_css.strip(),
        body_suffix_html=preset_script.strip(),
    )

def render_interest_save_result_html(
    *,
    db_path: Path,
    payload: dict[str, object],
    user_id: str,
    interest_id: str,
) -> str:
    lang = profile_html_lang(db_path, user_id=user_id)
    interest = payload.get("interest") if isinstance(payload.get("interest"), dict) else {}
    summary = interest.get("summary") if isinstance(interest.get("summary"), dict) else {}
    refresh = payload.get("refresh") if isinstance(payload.get("refresh"), dict) else {}
    iname = html.escape(str(interest.get("interest_name") or interest_id))
    inner = f"""
    <div class="detail-body">
    <section class="panel hero page-hero">
      <span class="eyebrow">Saved</span>
      <h1>Interest updated</h1>
      <p><strong>{iname}</strong> was saved successfully.</p>
      <p>Active alerts <strong>{html.escape(str(summary.get("active_signal_count") or 0))}</strong> ·
      live matches <strong>{html.escape(str(summary.get("active_match_count") or 0))}</strong></p>
      <p class="signal-note">Last saved timestamp <code>{html.escape(str(payload.get("updated_at") or "-"))}</code></p>
      {render_interest_refresh_summary(refresh, user_id=user_id)}
      <div class="detail-row hero-actions">
        <a class="action-button" href="/interests/edit?user_id={quote(user_id)}&interest_id={quote(interest_id)}">Keep editing</a>
        <a href="/interests?user_id={quote(user_id)}">Interests</a>
        <a href="/?user_id={quote(user_id)}">Dashboard</a>
      </div>
    </section>
    </div>
    """
    return render_document(
        title="Interest saved",
        html_lang=lang,
        user_id=user_id,
        nav_active="interests",
        main_inner_html=inner.strip(),
        main_classes="page-wide detail-body-wrap",
        omit_glossary_footer=True,
    )


def render_interest_create_result_html(
    *,
    db_path: Path,
    payload: dict[str, object],
    user_id: str,
) -> str:
    lang = profile_html_lang(db_path, user_id=user_id)
    interest = payload.get("interest") if isinstance(payload.get("interest"), dict) else {}
    summary = interest.get("summary") if isinstance(interest.get("summary"), dict) else {}
    interest_id = str(interest.get("id") or "")
    refresh = payload.get("refresh") if isinstance(payload.get("refresh"), dict) else {}
    iname = html.escape(str(interest.get("interest_name") or interest_id))
    inner = f"""
    <div class="detail-body">
    <section class="panel hero page-hero">
      <span class="eyebrow">Created</span>
      <h1>New interest ready</h1>
      <p><strong>{iname}</strong> is live—matching and alerts were regenerated automatically.</p>
      <p>Active alerts <strong>{html.escape(str(summary.get("active_signal_count") or 0))}</strong> ·
      live matches <strong>{html.escape(str(summary.get("active_match_count") or 0))}</strong></p>
      <p class="signal-note">Created at <code>{html.escape(str(payload.get("created_at") or "-"))}</code></p>
      {render_interest_refresh_summary(refresh, user_id=user_id)}
      <div class="detail-row hero-actions">
        <a class="action-button" href="/interests/edit?user_id={quote(user_id)}&interest_id={quote(interest_id)}">Fine-tune</a>
        <a href="/actions?user_id={quote(user_id)}">Actions</a>
        <a href="/interests?user_id={quote(user_id)}">Interests</a>
        <a href="/?user_id={quote(user_id)}">Dashboard</a>
      </div>
    </section>
    </div>
    """
    return render_document(
        title="Interest created",
        html_lang=lang,
        user_id=user_id,
        nav_active="interests",
        main_inner_html=inner.strip(),
        main_classes="page-wide detail-body-wrap",
        omit_glossary_footer=True,
    )


def render_interest_delete_result_html(
    *,
    db_path: Path,
    payload: dict[str, object],
    user_id: str,
) -> str:
    lang = profile_html_lang(db_path, user_id=user_id)
    interest = payload.get("interest") if isinstance(payload.get("interest"), dict) else {}
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    refresh = payload.get("refresh") if isinstance(payload.get("refresh"), dict) else {}
    iname = html.escape(str(interest.get("interest_name") or "-"))
    inner = f"""
    <div class="detail-body">
    <section class="panel hero page-hero">
      <span class="eyebrow">Removed</span>
      <h1>Interest retired</h1>
      <p><strong>{iname}</strong> is no longer monitored.</p>
      <p>Linked targets paused and related matches/alerts now read as inactive so counts stay truthful.</p>
      <p>Remaining saved interests <strong>{html.escape(str(summary.get("active_interest_count") or 0))}</strong> ·
      targets <strong>{html.escape(str(summary.get("active_target_count") or 0))}</strong></p>
      <p class="signal-note">Removed at <code>{html.escape(str(payload.get("deleted_at") or "-"))}</code></p>
      {render_interest_refresh_summary(refresh, user_id=user_id)}
      <div class="detail-row hero-actions">
        <a class="action-button" href="/interests/new?user_id={quote(user_id)}">Add another</a>
        <a href="/interests?user_id={quote(user_id)}">Interests</a>
        <a href="/?user_id={quote(user_id)}">Dashboard</a>
      </div>
    </section>
    </div>
    """
    return render_document(
        title="Interest removed",
        html_lang=lang,
        user_id=user_id,
        nav_active="interests",
        main_inner_html=inner.strip(),
        main_classes="page-wide detail-body-wrap",
        omit_glossary_footer=True,
    )


def render_interest_refresh_summary(refresh: dict[str, object], *, user_id: str) -> str:
    matching = refresh.get("matching") if isinstance(refresh.get("matching"), dict) else {}
    signals = refresh.get("signals") if isinstance(refresh.get("signals"), dict) else {}
    matching_result = matching.get("result") if isinstance(matching.get("result"), dict) else {}
    signals_result = signals.get("result") if isinstance(signals.get("result"), dict) else {}
    api_bit = ""
    if show_app_dev_ui():
        api_bit = (
            f'<p class="signal-note">Developer: '
            f'<a href="/api/users/{quote(user_id)}/signals">Alerts JSON</a> · '
            f'<a href="/api/users/{quote(user_id)}/matches">Matches JSON</a></p>'
        )
    return f"""
      <p>Background refresh finished: listings matched or updated <strong>{html.escape(str(matching_result.get("matches_upserted") or 0))}</strong> ·
      new alerts <strong>{html.escape(str(signals_result.get("inserted") or 0))}</strong> ·
      refreshed alerts <strong>{html.escape(str(signals_result.get("updated") or 0))}</strong> ·
      cleared stale alerts <strong>{html.escape(str(signals_result.get("deactivated") or 0))}</strong>.</p>
      <div class="detail-row hero-actions">
        <a href="/matches?user_id={quote(user_id)}">See matches</a>
        <a href="/?user_id={quote(user_id)}#signals">Open alerts inbox</a>
      </div>
      {api_bit}
    """


def render_dashboard_html(
    *,
    db_path: Path,
    reports_dir: Path,
    exports_dir: Path,
    user_id: str,
    lookback_hours: int,
) -> str:
    profile_payload = load_user_profile_payload(db_path, user_id=user_id)
    reports_payload = load_user_reports_payload(reports_dir, user_id=user_id)
    signals_payload = load_user_signals_payload(
        db_path,
        user_id=user_id,
        lookback_hours=lookback_hours,
    )
    matches_payload = load_user_matches_payload(db_path, user_id=user_id)
    digest_payload = load_latest_digest_payload(
        db_path=db_path,
        reports_dir=reports_dir,
        user_id=user_id,
        lookback_hours=lookback_hours,
    )
    user = profile_payload["user"]
    summary = profile_payload["summary"]
    latest_cards_html = render_latest_dashboard_cards(reports_payload)
    reports_browser_html = render_reports_browser(reports_payload, user_id=user_id)
    signals_inbox_html = render_signals_inbox(
        signals_payload,
        user_id=user_id,
        signal_review_metadata=(reports_payload.get("latest") or {}).get("signal_review") if isinstance(reports_payload.get("latest"), dict) else None,
    )
    top_opportunity_groups = matches_payload["opportunity_groups"][:3] if isinstance(matches_payload.get("opportunity_groups"), list) else []
    opportunity_cards_html = "\n".join(
        render_opportunity_group_card(group, user_id=user_id)
        for group in top_opportunity_groups
        if isinstance(group, dict)
    )
    if not opportunity_cards_html.strip():
        opportunity_cards_html = (
            '<p class="empty-state">No grouped matches yet.</p>'
            f'<p class="empty-cta"><a href="/actions?user_id={quote(user_id)}">Refresh matches</a> · '
            f'<a href="/interests?user_id={quote(user_id)}">Review saved interests</a></p>'
        )
    digest_preview = render_digest_preview(str(digest_payload["markdown"]))
    latest_digest = digest_payload.get("report") if isinstance(digest_payload.get("report"), dict) else {}
    latest_map = reports_payload.get("latest") if isinstance(reports_payload.get("latest"), dict) else {}
    latest_signal_review = latest_map.get("signal_review") if isinstance(latest_map.get("signal_review"), dict) else None
    latest_daily_review = latest_map.get("daily_review") if isinstance(latest_map.get("daily_review"), dict) else None
    lang = html_lang_attr(str(user.get("language") or ""))
    dlinks = latest_digest.get("links") if isinstance(latest_digest.get("links"), dict) else {}
    digest_primary = str(dlinks.get("rendered") or "#")
    digest_raw = str(dlinks.get("raw") or "#")
    digest_title = str(latest_digest.get("name") or "Read latest digest")
    signal_review_link_html = ""
    if isinstance(latest_signal_review, dict):
        srl = latest_signal_review.get("links")
        if isinstance(srl, dict) and srl.get("rendered"):
            signal_review_link_html = (
                f'<a href="{html.escape(str(srl["rendered"]))}">Latest alert roundup</a>'
            )
    daily_review_link_html = ""
    if isinstance(latest_daily_review, dict):
        drl = latest_daily_review.get("links")
        if isinstance(drl, dict) and drl.get("rendered"):
            daily_review_link_html = (
                f'<a href="{html.escape(str(drl["rendered"]))}">Daily summary</a>'
            )
    digest_advanced_block = ""
    if show_app_dev_ui():
        digest_advanced_block = f"""
        <details class="digest-advanced">
          <summary>Developer: alternate formats</summary>
          <p><a href="{html.escape(digest_raw)}">Raw markdown file</a></p>
        </details>
        """
    main_inner = f"""
    {render_dashboard_anchor_nav(user_id)}
    <section class="hero" id="overview">
      <div class="hero-grid">
        <div>
          <span class="eyebrow">Collector dashboard</span>
          <h1>{html.escape(str(user["display_name"]))}</h1>
          <p>Alerts and live matches appear first. Use <strong>Interests</strong> to tune what we watch, and <strong>Actions</strong> when you want to refresh data on demand.</p>
          <details class="identity-advanced">
            <summary>Account details</summary>
            <p>Language {html.escape(str(user["language"]))} · Time zone {html.escape(str(user["timezone"]))}</p>
            <p>Account id <code>{html.escape(str(user["id"]))}</code></p>
          </details>
        </div>
        <aside class="hero-side">
          <span class="eyebrow">Latest digest</span>
          <h3>{html.escape(str(latest_digest.get("timestamp_label") or "—"))}</h3>
          <p><a class="action-button" style="display:inline-flex;margin-top:8px;" href="{html.escape(digest_primary)}">Read digest</a></p>
          <p class="signal-note" style="margin-top:12px;">Your latest editorial summary of recent market activity.</p>
          <div class="subtle-links">
            <a href="/matches?user_id={quote(user_id)}">Browse matches</a>
            <a href="/actions?user_id={quote(user_id)}">Refresh data</a>
          </div>
        </aside>
      </div>
    </section>

    <section class="section" id="signals">
      <div class="section-header">
        <div>
          <h2>Alerts to review</h2>
          <p>Notices derived from your saved interests and the current market. We show a short list here; open <strong>Actions</strong> to regenerate.</p>
        </div>
        <div class="subtle-links">
          <a href="/actions?user_id={quote(user_id)}">Update alerts</a>
          {signal_review_link_html}
        </div>
      </div>
      {signals_inbox_html}
    </section>

    <section class="section" id="matches-preview">
      <div class="section-header">
        <div>
          <h2>Top match groups</h2>
          <p>Listings grouped by how closely they fit an interest. See the <strong>Matches</strong> page for the full list.</p>
        </div>
        <div class="subtle-links">
          <a href="/matches?user_id={quote(user_id)}">View all matches</a>
        </div>
      </div>
      <div class="opportunity-grid">{opportunity_cards_html}</div>
    </section>

    <section class="summary-grid" aria-label="At a glance">
      <article class="summary-card">
        <span class="eyebrow">Interests</span>
        <strong>{summary["active_interest_count"]}</strong>
      </article>
      <article class="summary-card">
        <span class="eyebrow">Active matches</span>
        <strong>{summary["active_match_count"]}</strong>
      </article>
      <article class="summary-card">
        <span class="eyebrow">Active alerts</span>
        <strong>{summary["active_signal_count"]}</strong>
      </article>
      <article class="summary-card">
        <span class="eyebrow">Tracked holdings</span>
        <strong>{summary["active_holding_count"]}</strong>
      </article>
    </section>

    <section class="section" id="digest-region">
      <div class="section-header">
        <div>
          <h2>Digest preview</h2>
          <p>A short excerpt from your latest collector digest.</p>
        </div>
        <div class="subtle-links">
          <a href="{html.escape(digest_primary)}">Open full digest</a>
          {daily_review_link_html}
        </div>
      </div>
      <div class="digest-card">
        <div class="digest-meta">
          <span class="pill">{html.escape(str(latest_digest.get("label") or "Digest"))}</span>
          <span class="pill">{html.escape(str(latest_digest.get("timestamp_label") or "-"))}</span>
        </div>
        <div>{digest_preview}</div>
        {digest_advanced_block}
      </div>
    </section>

    <section class="section" id="reports-region">
      <div class="section-header">
        <div>
          <h2>Recent reports</h2>
          <p>Jump into rendered digests and reviews generated for this workspace.</p>
        </div>
      </div>
      <div class="grid">{latest_cards_html}</div>
      <div class="reports-browser-wrap">
        <h3>All recent reports</h3>
        <p class="signal-note">Sort or filter to quickly find the report you need.</p>
        {reports_browser_html}
      </div>
    </section>
    """

    dashboard_extra_css = """
    .reports-browser-wrap { margin-top: 18px; display: grid; gap: 10px; }
    .reports-browser-toolbar { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
    .reports-browser-toolbar label { display: flex; gap: 8px; align-items: center; color: var(--muted); font-size: 0.92rem; }
    .reports-browser-toolbar select,
    .reports-browser-toolbar input {
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 8px 10px;
      background: #fffdf8;
      font: inherit;
      min-width: 160px;
    }
    .report-browser-item { transition: opacity .12s ease, transform .12s ease; }
    .report-browser-links { font-size: 0.92rem; color: var(--muted); }
    """
    dashboard_suffix_script = """
<script>
(() => {
  const list = document.getElementById("reports-browser-list");
  const sortSel = document.getElementById("reports-sort");
  const filter = document.getElementById("reports-filter");
  if (!list || !sortSel || !filter) return;
  const items = Array.from(list.querySelectorAll(".report-browser-item"));
  const parseTs = (el) => Date.parse(el.getAttribute("data-ts") || "") || 0;
  const keyText = (el) => [
    el.getAttribute("data-label") || "",
    el.getAttribute("data-scope") || "",
    el.getAttribute("data-kind") || "",
    el.textContent || "",
  ].join(" ").toLowerCase();
  const render = () => {
    const q = filter.value.trim().toLowerCase();
    const mode = sortSel.value;
    const shown = items.filter((el) => keyText(el).includes(q));
    for (const el of items) {
      el.style.display = shown.includes(el) ? "" : "none";
    }
    const sorted = [...shown].sort((a, b) => {
      if (mode === "oldest") return parseTs(a) - parseTs(b);
      if (mode === "label") return (a.getAttribute("data-label") || "").localeCompare(b.getAttribute("data-label") || "");
      return parseTs(b) - parseTs(a);
    });
    for (const el of sorted) list.appendChild(el);
  };
  sortSel.addEventListener("change", render);
  filter.addEventListener("input", render);
  render();
})();
</script>
"""

    return render_document(
        title="Collector home",
        html_lang=lang,
        user_id=user_id,
        nav_active="dashboard",
        main_inner_html=main_inner.strip(),
        extra_css=dashboard_extra_css.strip(),
        body_suffix_html=dashboard_suffix_script.strip(),
    )


def render_latest_dashboard_cards(reports_payload: dict[str, object]) -> str:
    latest = reports_payload["latest"]
    cards: list[str] = []
    labels = [
        ("digest", "Latest collector digest"),
        ("signal_review", "Latest signal review"),
        ("daily_review", "Latest daily review"),
    ]
    for key, heading in labels:
        item = latest.get(key) if isinstance(latest, dict) else None
        if not isinstance(item, dict):
            continue
        cards.append(
            f"""
            <a class="latest-card" href="{html.escape(str(item["links"]["rendered"]))}">
              <span class="eyebrow">{html.escape(heading)}</span>
              <strong>{html.escape(str(item["label"]))}</strong>
              <span>{html.escape(str(item["scope"]))}</span>
              <span class="meta">{html.escape(str(item["timestamp_label"]))}</span>
            </a>
            """
        )
    return "\n".join(cards) or '<p class="empty-state">No report shortcuts available yet.</p>'


def render_reports_browser(reports_payload: dict[str, object], *, user_id: str) -> str:
    reports = reports_payload.get("reports") if isinstance(reports_payload.get("reports"), list) else []
    shared_reports = reports_payload.get("shared_reports") if isinstance(reports_payload.get("shared_reports"), list) else []
    rows: list[str] = []
    for item in [*reports, *shared_reports]:
        if not isinstance(item, dict):
            continue
        links = item.get("links") if isinstance(item.get("links"), dict) else {}
        rendered = str(links.get("rendered") or "")
        raw = str(links.get("raw") or "")
        if not rendered:
            continue
        kind = str(item.get("kind") or "")
        label = str(item.get("label") or "Report")
        scope = str(item.get("scope") or "-")
        stamp = str(item.get("timestamp_label") or "-")
        stamp_iso = str(item.get("modified_at") or "")
        dev_link = ""
        if raw and show_app_dev_ui():
            dev_link = f' · <a href="{html.escape(raw)}">Markdown source</a>'
        rows.append(
            f"""
            <article class="report-row report-browser-item"
                data-kind="{html.escape(kind)}"
                data-label="{html.escape(label.lower())}"
                data-scope="{html.escape(scope.lower())}"
                data-ts="{html.escape(stamp_iso)}">
              <div>
                <span class="pill">{html.escape(label)}</span>
                <h3><a href="{html.escape(rendered)}">{html.escape(str(item.get("name") or "-"))}</a></h3>
                <p>{html.escape(scope)}</p>
              </div>
              <div class="meta-stack">
                <span>{html.escape(stamp)}</span>
                <div class="report-browser-links">
                  <a href="{html.escape(rendered)}">Open</a>{dev_link}
                </div>
              </div>
            </article>
            """
        )
    if not rows:
        return (
            f'<p class="empty-state">No reports yet.</p>'
            f'<p class="empty-cta"><a href="/actions?user_id={quote(user_id)}">Generate digest or alerts</a></p>'
        )
    return (
        '<div class="reports-browser-toolbar">'
        '<label>Sort <select id="reports-sort">'
        '<option value="newest">Newest first</option>'
        '<option value="oldest">Oldest first</option>'
        '<option value="label">By type</option>'
        '</select></label>'
        '<label>Filter <input id="reports-filter" type="search" placeholder="digest, signal, daily..."></label>'
        '</div>'
        f'<div id="reports-browser-list" class="report-list">{"".join(rows)}</div>'
    )


def render_signals_inbox(
    signals_payload: dict[str, object],
    *,
    user_id: str,
    signal_review_metadata: object,
) -> str:
    top_signals = signals_payload.get("top_signals")
    signal_cards = "\n".join(
        render_signal_card(signal, user_id=user_id, signal_review_metadata=signal_review_metadata)
        for signal in ((top_signals[:3]) if isinstance(top_signals, list) else [])
        if isinstance(signal, dict)
    )
    if not signal_cards.strip():
        signal_cards = (
            '<p class="empty-state">No active alerts yet.</p>'
            f'<p class="empty-cta"><a href="/actions?user_id={quote(user_id)}">Regenerate alerts</a> · '
            f'<a href="/interests?user_id={quote(user_id)}">Check saved interests</a></p>'
        )
    return f'<div class="signal-grid">{signal_cards}</div>'


def render_interests_html(
    *,
    db_path: Path,
    user_id: str,
) -> str:
    payload = load_user_interests_payload(db_path, user_id=user_id)
    user = payload["user"]
    summary = payload["summary"] if isinstance(payload.get("summary"), dict) else {}
    interest_kind_counts = payload["interest_kind_counts"] if isinstance(payload.get("interest_kind_counts"), dict) else {}
    interests = payload["interests"] if isinstance(payload.get("interests"), list) else []

    kind_cards_html = "\n".join(
        f"""
        <article class="summary-card">
          <span class="eyebrow">{html.escape(kind.replace('_', ' ').title())}</span>
          <strong>{count}</strong>
        </article>
        """
        for kind, count in sorted(interest_kind_counts.items())
    )
    if not kind_cards_html.strip():
        kind_cards_html = (
            '<p class="empty-state">No saved interests yet, so there is nothing to chart.</p>'
            f'<p class="empty-cta"><a class="action-button" href="/interests/new?user_id={quote(user_id)}">Add your first interest</a></p>'
        )
    interest_cards_html = "\n".join(
        render_interest_detail_card(interest, user_id=user_id)
        for interest in interests
        if isinstance(interest, dict)
    )
    if not interest_cards_html.strip():
        interest_cards_html = (
            '<p class="empty-state">No saved interests yet.</p>'
            f'<p class="empty-cta"><a class="action-button" href="/interests/new?user_id={quote(user_id)}">Add an interest</a>'
            f' · <a href="/actions?user_id={quote(user_id)}">Open settings</a></p>'
        )
    lang = html_lang_attr(str(user.get("language") or ""))
    inner = f"""
    <div class="detail-body">
    <section class="hero page-hero">
      <span class="eyebrow">Interests</span>
      <h1>{html.escape(str(user["display_name"]))}</h1>
      <p>Everything we watch on your behalf lives here—targets you care about, optional holdings you track, and how often we should ping you.</p>
      <details class="identity-advanced">
        <summary>Language & account id</summary>
        <p>{html.escape(str(user["language"]))} · {html.escape(str(user["timezone"]))}</p>
        <p>Account id <code>{html.escape(str(user["id"]))}</code></p>
      </details>
      <div class="hero-actions">
        <a class="action-button" href="/interests/new?user_id={quote(user_id)}">Add interest</a>
        <a href="/actions?user_id={quote(user_id)}">Actions</a>
      </div>
    </section>
    <section class="summary-grid" aria-label="Overview counts">
      <article class="summary-card"><span class="eyebrow">Interests</span><strong>{summary.get("active_interest_count", 0)}</strong></article>
      <article class="summary-card"><span class="eyebrow">Targets</span><strong>{summary.get("active_target_count", 0)}</strong></article>
      <article class="summary-card"><span class="eyebrow">Tracked holdings</span><strong>{summary.get("active_holding_count", 0)}</strong></article>
      <article class="summary-card"><span class="eyebrow">Marked high priority</span><strong>{summary.get("high_priority_count", 0)}</strong></article>
      <article class="summary-card"><span class="eyebrow">Immediate alerts on</span><strong>{summary.get("immediate_policy_count", 0)}</strong></article>
      <article class="summary-card"><span class="eyebrow">With holdings linked</span><strong>{summary.get("interests_with_holdings", 0)}</strong></article>
    </section>
    <section class="section">
      <div class="section-header">
        <div>
          <h2>Mix by intent</h2>
          <p>How many saved interests fall into each type (buy watch, collecting, discovery, and so on).</p>
        </div>
      </div>
      <div class="summary-grid">{kind_cards_html}</div>
    </section>
    <section class="section">
      <div class="section-header">
        <div>
          <h2>All saved interests</h2>
          <p>Expand sections on each card for technical detail. Alerts and matches summarize what is active today.</p>
        </div>
        <a class="action-button" href="/interests/new?user_id={quote(user_id)}">Add interest</a>
      </div>
      <div class="interest-grid">{interest_cards_html}</div>
    </section>
    </div>
    """
    return render_document(
        title="Interests",
        html_lang=lang,
        user_id=user_id,
        nav_active="interests",
        main_inner_html=inner.strip(),
        main_classes="page-wide detail-body-wrap detail-matches-wide",
    )


def render_matches_html(
    *,
    db_path: Path,
    user_id: str,
) -> str:
    payload = load_user_matches_payload(db_path, user_id=user_id)
    user = payload["user"]
    summary = payload["summary"]
    top_matches = payload["top_matches"] if isinstance(payload.get("top_matches"), list) else []
    groups = payload["opportunity_groups"] if isinstance(payload.get("opportunity_groups"), list) else []
    match_cards_html = "\n".join(
        render_match_card(match, user_id=user_id)
        for match in top_matches
        if isinstance(match, dict)
    )
    if not match_cards_html.strip():
        match_cards_html = (
            '<p class="empty-state">No live matches yet—they appear after syncing and refreshing.</p>'
            f'<p class="empty-cta"><a class="action-button" href="/actions?user_id={quote(user_id)}">Open settings &amp; refresh</a>'
            f' · <a href="/interests?user_id={quote(user_id)}">Review saved interests</a></p>'
        )
    group_cards_html = "\n".join(
        render_opportunity_group_card(group, user_id=user_id)
        for group in groups
        if isinstance(group, dict)
    )
    if not group_cards_html.strip():
        group_cards_html = (
            '<p class="empty-state">No clustered opportunities yet.</p>'
            f'<p class="empty-cta"><a href="/actions?user_id={quote(user_id)}">Run matching</a>'
            f' · <a href="/interests/new?user_id={quote(user_id)}">Add an interest</a></p>'
        )
    lang = html_lang_attr(str(user.get("language") or ""))
    inner = f"""
    <div class="detail-body">
    <section class="hero page-hero">
      <span class="eyebrow">Matches &amp; opportunities</span>
      <h1>{html.escape(str(user["display_name"]))}</h1>
      <p>Listings that line up with your saved interests—grouped where several auctions look like one opportunity.</p>
      <details class="identity-advanced">
        <summary>Language &amp; account id</summary>
        <p>{html.escape(str(user["language"]))} · {html.escape(str(user["timezone"]))}</p>
        <p>Account id <code>{html.escape(str(user["id"]))}</code></p>
      </details>
      <div class="hero-actions">
        <a class="action-button" href="/actions?user_id={quote(user_id)}">Refresh matches</a>
        <a href="/?user_id={quote(user_id)}#signals">View alerts</a>
      </div>
    </section>
    <section class="summary-grid" aria-label="Match overview">
      <article class="summary-card"><span class="eyebrow">Live matches</span><strong>{summary["active_match_count"]}</strong></article>
      <article class="summary-card"><span class="eyebrow">Strong fits (high score)</span><strong>{summary["high_score_count"]}</strong></article>
      <article class="summary-card"><span class="eyebrow">Auctions live now</span><strong>{summary["live_count"]}</strong></article>
      <article class="summary-card"><span class="eyebrow">Upcoming / preview</span><strong>{summary["preview_count"]}</strong></article>
      <article class="summary-card"><span class="eyebrow">Exact title fits</span><strong>{summary["exact_count"]}</strong></article>
      <article class="summary-card"><span class="eyebrow">Opportunity groups</span><strong>{summary["opportunity_group_count"]}</strong></article>
    </section>
    <section class="section">
      <div class="section-header">
        <div>
          <h2>Opportunity groups</h2>
          <p>Repeated listings clustered by interest, how close the fit is, and auction state.</p>
        </div>
      </div>
      <div class="card-grid">{group_cards_html}</div>
    </section>
    <section class="section">
      <div class="section-header">
        <div>
          <h2>Top individual matches</h2>
          <p>Highest-scoring listings across your active interests.</p>
        </div>
      </div>
      <div class="card-grid">{match_cards_html}</div>
    </section>
    </div>
    """
    return render_document(
        title="Matches & opportunities",
        html_lang=lang,
        user_id=user_id,
        nav_active="matches",
        main_inner_html=inner.strip(),
        main_classes="page-wide detail-body-wrap detail-matches-wide",
    )


def render_signal_card(
    signal: dict[str, object],
    *,
    user_id: str,
    signal_review_metadata: object,
) -> str:
    urgency = str(signal.get("urgency") or "low")
    family = str(signal.get("signal_family") or "standing")
    interest_name = str(signal.get("interest_name") or "-")
    context_note = signal.get("context_note")
    pricing_note = signal.get("pricing_note")
    listing = signal.get("listing")
    latest_review_link = None
    if isinstance(signal_review_metadata, dict):
        links = signal_review_metadata.get("links")
        if isinstance(links, dict):
            latest_review_link = links.get("rendered")
    listing_html = ""
    if isinstance(listing, dict) and listing.get("source_listing_id"):
        listing_html = f'<span class="pill">Listing {html.escape(str(listing.get("source_listing_id")))}</span>'
    note_bits = []
    if context_note:
        note_bits.append(f'<p class="signal-note">{html.escape(str(context_note))}</p>')
    if pricing_note:
        note_bits.append(f'<p class="signal-note">{html.escape(str(pricing_note))}</p>')
    links: list[str] = []
    if latest_review_link:
        links.append(f'<a href="{html.escape(str(latest_review_link))}">Latest alert roundup</a>')
    if show_app_dev_ui():
        links.append(f'<a href="/api/users/{quote(user_id)}/signals">Alerts (JSON)</a>')
    links_html = " · ".join(links) if links else ""
    links_block = f'<div class="signal-links">{links_html}</div>' if links_html else ""
    return f"""
    <article class="signal-card">
      <div class="signal-meta">
        <span class="pill">{html.escape(urgency.title())}</span>
        <span class="pill">{html.escape(family.title())}</span>
        <span class="pill">{html.escape(format_signal_type_label(str(signal.get("signal_type") or "")))}</span>
        {listing_html}
      </div>
      <h3>{html.escape(str(signal.get("signal_title") or "-"))}</h3>
      <p>{html.escape(str(signal.get("signal_summary") or ""))}</p>
      {''.join(note_bits)}
      <p class="signal-note">Interest: <strong>{html.escape(interest_name)}</strong> | last seen {html.escape(str(signal.get("last_seen_at") or "-"))}</p>
      {links_block}
    </article>
    """


def render_signal_interest_group_card(group: dict[str, object]) -> str:
    signals = group.get("signals")
    items = []
    if isinstance(signals, list):
        for signal in signals[:3]:
            if not isinstance(signal, dict):
                continue
            items.append(
                f"<li><strong>{html.escape(str(signal.get('signal_title') or '-'))}</strong> "
                f"<span class=\"signal-note\">{html.escape(str(signal.get('urgency') or '-'))} | "
                f"{html.escape(format_signal_type_label(str(signal.get('signal_type') or '')))}</span></li>"
            )
    items_html = "".join(items) or "<li>No active alerts.</li>"
    return f"""
    <article class="signal-interest-card">
      <div class="signal-meta">
        <span class="pill">{html.escape(str(group.get("interest_kind") or "-"))}</span>
        <span class="pill">{html.escape(str(group.get("signal_count") or 0))} active</span>
        <span class="pill">{html.escape(str(group.get("high_count") or 0))} high</span>
      </div>
      <h3>{html.escape(str(group.get("interest_name") or "-"))}</h3>
      <ul class="mini-list">{items_html}</ul>
    </article>
    """


def render_match_card(match: dict[str, object], *, user_id: str) -> str:
    reasons = match.get("match_reasons")
    reasons_text = ", ".join(str(item) for item in reasons[:4]) if isinstance(reasons, list) and reasons else "no reason tags"
    note = match.get("opportunity_note")
    return f"""
    <article class="match-card">
      <div class="meta-row">
        <span class="pill">{html.escape(format_relationship_type_label(str(match.get("relationship_type") or "")))}</span>
        <span class="pill">{html.escape(format_listing_status_label(str(match.get("listing_status") or "")))}</span>
        <span class="pill">score {html.escape(str(match.get("match_score") or 0))}</span>
      </div>
      <h3>{html.escape(str(match.get("listing_title") or "-"))}</h3>
      <p>Interest: <strong>{html.escape(str(match.get("interest_name") or "-"))}</strong></p>
      <p>Target: <strong>{html.escape(str(match.get("target_label") or "-"))}</strong></p>
      <p>Listing id <strong>{html.escape(str(match.get("source_listing_id") or "-"))}</strong> | last updated {html.escape(str(match.get("listing_updated_at") or "-"))}</p>
      <p>{html.escape(str(note or reasons_text))}</p>
      {f'<p class="signal-note"><a href="/api/users/{quote(user_id)}/matches">Matches (JSON)</a></p>' if show_app_dev_ui() else ""}
    </article>
    """


def render_opportunity_group_card(group: dict[str, object], *, user_id: str) -> str:
    price_min = group.get("price_min")
    price_max = group.get("price_max")
    price_label = "no visible price range"
    if price_min is not None and price_max is not None:
        price_label = f"{price_min}–{price_max}"
    elif price_min is not None:
        price_label = str(price_min)
    sample_ids = group.get("sample_source_listing_ids")
    sample_label = ", ".join(str(item) for item in sample_ids[:3]) if isinstance(sample_ids, list) and sample_ids else "no sample ids"
    return f"""
    <article class="opportunity-card">
      <div class="meta-row">
        <span class="pill">{html.escape(format_relationship_type_label(str(group.get("relationship_type") or "")))}</span>
        <span class="pill">{html.escape(format_listing_status_label(str(group.get("listing_status") or "")))}</span>
        <span class="pill">{html.escape(str(group.get("listing_count") or 0))} listings</span>
      </div>
      <h3>{html.escape(str(group.get("interest_name") or "-"))}</h3>
      <p><strong>{html.escape(str(group.get("listing_title") or "-"))}</strong></p>
      <p>Target: {html.escape(str(group.get("target_label") or "-"))}</p>
      <p>Top score {html.escape(str(group.get("top_match_score") or 0))} | price range {html.escape(price_label)}</p>
      <p>Examples: {html.escape(sample_label)}</p>
      {f'<p class="signal-note"><a href="/api/users/{quote(user_id)}/matches">Matches (JSON)</a></p>' if show_app_dev_ui() else ""}
    </article>
    """


def render_interest_card(interest: dict[str, object]) -> str:
    targets = interest.get("targets")
    holdings = interest.get("holdings")
    policy = interest.get("signal_policy")
    target = targets[0] if isinstance(targets, list) and targets else {}
    holding = holdings[0] if isinstance(holdings, list) and holdings else {}
    policy = policy if isinstance(policy, dict) else {}
    budget = target.get("budget_max")
    target_label = target.get("target_label") or interest.get("interest_name") or "-"
    holding_text = ""
    if holding:
        holding_text = (
            f"<p>Holding: qty <strong>{html.escape(str(holding.get('holding_quantity')))}</strong> "
            f"at cost <strong>{html.escape(str(holding.get('cost_basis_unit')))}</strong>.</p>"
        )
    budget_text = f"Budget max <strong>{html.escape(str(budget))}</strong>" if budget is not None else "No explicit budget cap"
    return f"""
    <article class="interest-card">
      <span class="pill">{html.escape(str(interest["interest_kind"]))}</span>
      <h3>{html.escape(str(interest["interest_name"]))}</h3>
      <p>Target: <strong>{html.escape(str(target_label))}</strong></p>
      <p>Scope / precision: <strong>{html.escape(str(interest["scope_kind"]))}</strong> / <strong>{html.escape(str(interest["precision_mode"]))}</strong></p>
      <p>{budget_text}</p>
      <p>Delivery <strong>{html.escape(str(policy.get("delivery_mode") or "-"))}</strong> | cooldown <strong>{html.escape(str(policy.get("cooldown_hours") or "-"))}h</strong></p>
      {holding_text}
    </article>
    """


def render_interest_detail_card(interest: dict[str, object], *, user_id: str) -> str:
    summary = interest.get("summary") if isinstance(interest.get("summary"), dict) else {}
    targets = interest.get("targets") if isinstance(interest.get("targets"), list) else []
    holdings = interest.get("holdings") if isinstance(interest.get("holdings"), list) else []
    policy = interest.get("signal_policy") if isinstance(interest.get("signal_policy"), dict) else {}
    notes = str(interest.get("notes") or "").strip()

    target_items = []
    for target in targets[:3]:
        if not isinstance(target, dict):
            continue
        budget = target.get("budget_max")
        budget_label = f"budget {budget}" if budget is not None else "no budget cap"
        target_items.append(
            f"<li><strong>{html.escape(str(target.get('target_label') or '-'))}</strong> "
            f"<span class=\"eyebrow\">{html.escape(str(target.get('target_kind') or '-'))}</span> | "
            f"{html.escape(str(target.get('condition_mode') or '-'))} | {html.escape(budget_label)}</li>"
        )
    target_html = "".join(target_items) or "<li>No targets attached.</li>"

    holding_items = []
    for holding in holdings[:3]:
        if not isinstance(holding, dict):
            continue
        holding_items.append(
            f"<li><strong>{html.escape(str(holding.get('raw_input') or holding.get('normalized_name') or '-'))}</strong> | "
            f"qty {html.escape(str(holding.get('holding_quantity') or '-'))} | "
            f"cost {html.escape(str(holding.get('cost_basis_unit') or '-'))}</li>"
        )
    holding_html = "".join(holding_items) or "<li>No holdings linked.</li>"

    policy_bits = [
        f"delivery <strong>{html.escape(str(policy.get('delivery_mode') or '-'))}</strong>",
        f"quiet period <strong>{html.escape(str(policy.get('cooldown_hours') or '-'))}h</strong>",
        f"min fit score <strong>{html.escape(str(policy.get('min_match_score') or '-'))}</strong>",
        f"max alerts/day <strong>{html.escape(str(policy.get('max_signals_per_day') or '-'))}</strong>",
    ]
    note_html = f"<p>{html.escape(notes)}</p>" if notes else '<p class="empty-state">No notes yet.</p>'
    prio = html.escape(str(interest.get("interest_priority") or "-"))
    kind = html.escape(str(interest.get("interest_kind") or "-"))
    dev_row = ""
    if show_app_dev_ui():
        dev_row = (
            f'<p class="signal-note">API: '
            f'<a href="/api/users/{quote(user_id)}/interests">interests</a> · '
            f'<a href="/api/users/{quote(user_id)}/signals">alerts</a> · '
            f'<a href="/api/users/{quote(user_id)}/matches">matches</a>'
            f"</p>"
        )

    return f"""
    <article class="interest-detail-card">
      <div class="meta-row">
        <span class="pill">{kind}</span>
        <span class="pill">Priority {prio}</span>
      </div>
      <h3>{html.escape(str(interest.get("interest_name") or "-"))}</h3>
      <p>Active alerts <strong>{html.escape(str(summary.get("active_signal_count") or 0))}</strong> ·
      live matches <strong>{html.escape(str(summary.get("active_match_count") or 0))}</strong> ·
      targets <strong>{html.escape(str(summary.get("active_target_count") or 0))}</strong> ·
      holdings <strong>{html.escape(str(summary.get("active_holding_count") or 0))}</strong></p>
      <div class="stack">
        <details class="subpanel subpanel-collapsible" open>
          <summary><h4>Targeting &amp; budget</h4></summary>
          <ul>{target_html}</ul>
        </details>
        <details class="subpanel subpanel-collapsible">
          <summary><h4>Holdings</h4></summary>
          <ul>{holding_html}</ul>
        </details>
        <details class="subpanel subpanel-collapsible">
          <summary><h4>Alert rules</h4></summary>
          <p>{" | ".join(policy_bits)}</p>
          <p class="signal-note">When to notify:
          preview listings <strong>{html.escape(str(policy.get("notify_on_preview") or 0))}</strong> ·
          live <strong>{html.escape(str(policy.get("notify_on_live") or 0))}</strong> ·
          ended <strong>{html.escape(str(policy.get("notify_on_ended") or 0))}</strong></p>
          <p class="signal-note">Match shape:
          exact <strong>{html.escape(str(policy.get("notify_on_exact_match") or 0))}</strong> ·
          variant <strong>{html.escape(str(policy.get("notify_on_variant_match") or 0))}</strong> ·
          series <strong>{html.escape(str(policy.get("notify_on_series_match") or 0))}</strong></p>
        </details>
        <details class="subpanel subpanel-collapsible">
          <summary><h4>Notes</h4></summary>
          {note_html}
        </details>
        <details class="subpanel subpanel-collapsible">
          <summary><h4>Advanced matching scope</h4></summary>
          <p class="signal-note">
            Scope <strong>{html.escape(str(interest.get("scope_kind") or "-"))}</strong>
            · precision <strong>{html.escape(str(interest.get("precision_mode") or "-"))}</strong>
          </p>
        </details>
      </div>
      {dev_row}
      <div class="detail-row">
        <a class="action-button" href="/interests/edit?user_id={quote(user_id)}&interest_id={quote(str(interest.get('id') or ''))}">Edit</a>
        <a href="/matches?user_id={quote(user_id)}">See matches</a>
        <form class="inline-form" method="post" action="/interests/delete" onsubmit="return confirm('Stop tracking this interest? Active matches and alerts tied to it will be hidden.');">
          <input type="hidden" name="user_id" value="{html.escape(user_id)}">
          <input type="hidden" name="interest_id" value="{html.escape(str(interest.get('id') or ''))}">
          <button class="danger-button" type="submit">Remove interest</button>
        </form>
      </div>
    </article>
    """


DIGEST_PREVIEW_MAX_HIGHLIGHTS = 5


def render_digest_preview(markdown: str) -> str:
    """Short excerpt shown on dashboard – structured for quick scanning."""
    lines = markdown.splitlines()
    highlight_lines: list[str] = []
    inside_highlights = False
    for line in lines:
        stripped = line.strip()
        if stripped in {"## Highlights", "## At a glance"}:
            inside_highlights = True
            continue
        if inside_highlights and stripped.startswith("## "):
            break
        if inside_highlights and stripped.startswith("- "):
            highlight_lines.append(stripped[2:])
        elif inside_highlights and stripped.startswith("* "):
            highlight_lines.append(stripped[2:])
            if len(highlight_lines) >= DIGEST_PREVIEW_MAX_HIGHLIGHTS:
                break

    def item_html(text: str) -> str:
        return f"<li>{render_inline_markdown(text)}</li>"

    if highlight_lines:
        items = "".join(item_html(bit) for bit in highlight_lines)
        return (
            '<article class="digest-preview-read">'
            '<h4 class="digest-preview-heading">At a glance</h4>'
            f'<ul class="digest-preview-list">{items}</ul>'
            "</article>"
        )

    preview_items: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped == "# V2 Interest Daily Digest":
            continue
        if stripped.startswith("## ") or stripped == "---":
            break
        if stripped.startswith("- "):
            preview_items.append(stripped[2:])
        elif stripped.startswith("* "):
            preview_items.append(stripped[2:])
            if len(preview_items) >= 6:
                break
        else:
            break

    if preview_items:
        items = "".join(item_html(bit) for bit in preview_items)
        return (
            '<article class="digest-preview-read">'
            '<h4 class="digest-preview-heading">Snapshot</h4>'
            f'<ul class="digest-preview-list">{items}</ul>'
            "</article>"
        )

    preview_lines_fallback: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped == "# V2 Interest Daily Digest":
            continue
        preview_lines_fallback.append(stripped)
        if len(preview_lines_fallback) >= 5:
            break
    if not preview_lines_fallback:
        return '<p class="empty-state">No digest summary available yet.</p>'
    paras = "".join(f"<p class=\"digest-preview-para\">{render_inline_markdown(line)}</p>" for line in preview_lines_fallback)
    return f'<article class="digest-preview-read">{paras}</article>'


def format_signal_type_label(signal_type: str) -> str:
    if not signal_type:
        return "Signal"
    return signal_type.replace("_", " ").title()


def format_relationship_type_label(value: str) -> str:
    if value == "exact_identity":
        return "Exact"
    if value == "variant_related":
        return "Variant"
    if value == "series_related":
        return "Series"
    return value.replace("_", " ").title() if value else "Match"


def format_listing_status_label(value: str) -> str:
    if not value:
        return "Unknown"
    return value.title()


def render_select_option(value: str, current: str, label: str) -> str:
    selected = ' selected' if value == current else ''
    return f'<option value="{html.escape(value)}"{selected}>{html.escape(label)}</option>'


def render_action_report_row(item: object, *, empty_label: str) -> str:
    if not isinstance(item, dict):
        return f'<p class="empty-state">{html.escape(empty_label)}</p>'
    links = item.get("links") if isinstance(item.get("links"), dict) else {}
    rendered = links.get("rendered") if isinstance(links, dict) else None
    raw = links.get("raw") if isinstance(links, dict) else None
    link_html = ""
    if rendered:
        link_html += f'<div><a href="{html.escape(str(rendered))}">Readable view</a></div>'
    if raw and show_app_dev_ui():
        link_html += f'<div><a href="{html.escape(str(raw))}">Markdown source</a></div>'
    return f"""
    <article class="report-row">
      <div>
        <span class="pill">{html.escape(str(item.get("label") or "Report"))}</span>
        <h3>{html.escape(str(item.get("name") or "-"))}</h3>
        <p>{html.escape(str(item.get("scope") or "-"))}</p>
      </div>
      <div class="meta-stack">
        <span>{html.escape(str(item.get("timestamp_label") or "-"))}</span>
        {link_html}
      </div>
    </article>
    """


def render_report_row(item: dict[str, object]) -> str:
    return f"""
    <article class="report-row">
      <div>
        <span class="pill">{html.escape(str(item["label"]))}</span>
        <h3><a href="/reports/{quote(str(item["name"]))}">{html.escape(str(item["name"]))}</a></h3>
        <p>{html.escape(str(item["scope"]))}</p>
      </div>
      <div class="meta-stack">
        <span>{html.escape(str(item["timestamp_label"]))}</span>
        <span>{format_size(int(item["size_bytes"]))}</span>
        <div class="link-row">
          <a href="/reports/{quote(str(item["name"]))}">Open</a>
          <a href="/raw/{quote(str(item["name"]))}">Raw</a>
          <a href="/latest/{quote(str(item["kind"]))}">Latest of type</a>
        </div>
      </div>
    </article>
    """


def render_bundle_row(item: dict[str, object]) -> str:
    return f"""
    <article class="bundle-row">
      <div>
        <span class="pill">Bundle</span>
        <h3><a href="/downloads/{quote(str(item["name"]))}">{html.escape(str(item["name"]))}</a></h3>
        <p>Packaged report export for offline download.</p>
      </div>
      <div class="meta-stack">
        <span>{html.escape(str(item["modified_at"]))}</span>
        <span>{format_size(int(item["size_bytes"]))}</span>
        <div class="link-row">
          <a href="/downloads/{quote(str(item["name"]))}">Download</a>
        </div>
      </div>
    </article>
    """


_DIGEST_HEADING_SWAP = {
    "## Highlights": "## At a glance",
    "## Interest Breakdown": "## By saved interest",
    "## highlights": "## At a glance",
    "## interest breakdown": "## By saved interest",
}


_COMP_NOISE_RE = re.compile(
    r"\s*using\s+`?\d+`?\s+of\s+`?\d+`?\s+ended\s+comps\s+on\s+`?[^`(]+`?\s+basis\s*"
    r"\(\s*`?\d+`?\s+exact.*?\)"
)
_SEED_ROW_RE = re.compile(r"\s*Seed row\s+source_listing_id=\S+\s+overall=\d+\s+ended=\d+\.?")
_COMP_TREND_LINE_RE = re.compile(r"^-\s*Comp trend:.*$", re.MULTILINE)
_RELATIONSHIP_MIX_RE = re.compile(r"^Relationship mix:.*$", re.MULTILINE)
_KIND_SCOPE_LINE_RE = re.compile(r"^-\s*Kind\s*/\s*scope\s*/\s*precision:.*$", re.MULTILINE)
_POLICY_LINE_RE = re.compile(r"^-\s*Policy:\s*delivery.*$", re.MULTILINE)
_CONDITION_MODE_RE = re.compile(r"^-\s*Condition mode:.*$", re.MULTILINE)


def _simplify_digest_line(line: str) -> str:
    """Remove verbose comp-basis noise and seed-row metadata from a single line."""
    line = _COMP_NOISE_RE.sub("", line)
    line = _SEED_ROW_RE.sub("", line)
    line = line.replace("comp-trend estimate", "trend")
    line = line.replace("weighted ended trend", "trend")
    line = line.replace("has recent ended comps around", "recent comps around")
    return line.rstrip()


def humanize_digest_markdown(markdown: str, *, omit_leading_digest_title: bool = False) -> str:
    """Simplify technical jargon and strip noise so the digest reads like an editorial note."""
    text = markdown
    text = _COMP_TREND_LINE_RE.sub("", text)
    text = _RELATIONSHIP_MIX_RE.sub("", text)
    text = _KIND_SCOPE_LINE_RE.sub("", text)
    text = _POLICY_LINE_RE.sub("", text)
    text = _CONDITION_MODE_RE.sub("", text)

    lines = text.splitlines()
    if omit_leading_digest_title and lines:
        strip0 = lines[0].strip()
        if strip0 == "# V2 Interest Daily Digest" or strip0 == "# Your daily digest":
            lines = lines[1:]
            while lines and not lines[0].strip():
                lines = lines[1:]
    out: list[str] = []
    for raw in lines:
        s = raw
        stripped = s.strip()
        if stripped == "# V2 Interest Daily Digest":
            s = "# Your daily digest"
        elif stripped in _DIGEST_HEADING_SWAP:
            s = _DIGEST_HEADING_SWAP[stripped]
        s = _simplify_digest_line(s)
        if not s.strip():
            if out and not out[-1].strip():
                continue
        out.append(s)
    return "\n".join(out)


_META_SKIP_PREFIXES = (
    "User:", "Language", "Default precision", "Default min score",
    "Lookback window",
)


def extract_digest_leading_bullets(markdown: str) -> tuple[list[str], str]:
    """Pull useful metadata bullets; skip noisy technical lines."""
    lines = markdown.splitlines()
    idx = 0
    while idx < len(lines) and not lines[idx].strip():
        idx += 1
    bullets: list[str] = []
    while idx < len(lines):
        stripped = lines[idx].strip()
        if stripped.startswith("- ") or stripped.startswith("* "):
            payload = stripped[2:].strip()
            skip = any(payload.startswith(p) for p in _META_SKIP_PREFIXES)
            if not skip and payload:
                bullets.append(payload)
            idx += 1
            continue
        break
    remainder = "\n".join(lines[idx:])
    return bullets, remainder


def render_digest_markdown_html(text: str) -> str:
    """Full digest markdown → readable HTML with a skim-friendly overview strip."""
    prepared = humanize_digest_markdown(text, omit_leading_digest_title=True).lstrip("\n")
    bullets, remainder = extract_digest_leading_bullets(prepared)
    sections: list[str] = []
    if bullets:
        lis = "".join(f"<li>{render_inline_markdown(item)}</li>" for item in bullets)
        sections.append(
            '<aside class="digest-doc-meta" aria-label="Digest overview">'
            "<p>This edition covers</p>"
            f"<ul>{lis}</ul></aside>"
        )
    trimmed = remainder.strip()
    if trimmed:
        sections.append(render_markdown_html(trimmed))
    return "\n".join(sections) if sections else "<p>No digest body.</p>"


def render_digest_structured_html(text: str) -> str:
    """Digest-specific rendering with cards and grouped details."""
    prepared = humanize_digest_markdown(text, omit_leading_digest_title=True)
    bullets, remainder = extract_digest_leading_bullets(prepared.lstrip("\n"))
    lines = remainder.splitlines()

    at_a_glance: list[str] = []
    interest_cards: list[dict[str, object]] = []

    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if stripped in {"## At a glance", "## Highlights"}:
            i += 1
            while i < len(lines):
                item = lines[i].strip()
                if item.startswith("## "):
                    break
                if item.startswith("- ") or item.startswith("* "):
                    at_a_glance.append(item[2:])
                i += 1
            continue
        if stripped in {"## By saved interest", "## Interest Breakdown"}:
            i += 1
            break
        i += 1

    current: dict[str, object] | None = None
    current_group: str | None = None
    while i < len(lines):
        stripped = lines[i].strip()
        if stripped.startswith("### "):
            if current:
                interest_cards.append(current)
            current = {"title": stripped[4:], "facts": [], "groups": {}, "digest_summary": ""}
            current_group = None
            i += 1
            continue
        if current is None:
            i += 1
            continue
        if stripped == "---":
            if current:
                interest_cards.append(current)
            current = None
            current_group = None
            i += 1
            continue
        if not stripped:
            i += 1
            continue
        if stripped.endswith(":") and not stripped.startswith("- "):
            current_group = stripped[:-1]
            groups = current.get("groups")
            if isinstance(groups, dict):
                groups.setdefault(current_group, [])
            i += 1
            continue
        if stripped.startswith("- ") or stripped.startswith("* "):
            payload = stripped[2:]
            if payload.lower().startswith("digest summary:"):
                current["digest_summary"] = payload.split(":", 1)[1].strip() if ":" in payload else payload
            elif current_group:
                groups = current.get("groups")
                if isinstance(groups, dict):
                    bucket = groups.get(current_group)
                    if isinstance(bucket, list):
                        bucket.append(payload)
            else:
                facts = current.get("facts")
                if isinstance(facts, list):
                    facts.append(payload)
            i += 1
            continue
        if current_group:
            groups = current.get("groups")
            if isinstance(groups, dict):
                bucket = groups.get(current_group)
                if isinstance(bucket, list):
                    bucket.append(stripped)
        i += 1
    if current:
        interest_cards.append(current)

    head_bits: list[str] = []
    if bullets:
        lis = "".join(f"<li>{render_inline_markdown(item)}</li>" for item in bullets)
        head_bits.append(
            '<aside class="digest-doc-meta" aria-label="Digest overview">'
            "<p>This edition covers</p>"
            f"<ul>{lis}</ul></aside>"
        )
    if at_a_glance:
        lis = "".join(f"<li>{render_inline_markdown(item)}</li>" for item in at_a_glance)
        head_bits.append(
            '<section class="digest-at-a-glance"><h2>At a glance</h2>'
            f"<ul>{lis}</ul></section>"
        )

    cards_html: list[str] = []
    for card in interest_cards:
        title = html.escape(str(card.get("title") or "-"))
        facts = card.get("facts") if isinstance(card.get("facts"), list) else []
        groups = card.get("groups") if isinstance(card.get("groups"), dict) else {}
        digest_summary = str(card.get("digest_summary") or "").strip()
        key_facts = "".join(f"<li>{render_inline_markdown(str(item))}</li>" for item in facts[:8])
        grouped_html_parts: list[str] = []
        for name, items in groups.items():
            if not isinstance(items, list) or not items:
                continue
            lis = "".join(f"<li>{render_inline_markdown(str(it))}</li>" for it in items[:8])
            grouped_html_parts.append(
                f'<details class="digest-detail-group"><summary>{html.escape(str(name))}</summary><ul>{lis}</ul></details>'
            )
        grouped_html = "".join(grouped_html_parts) or '<p class="digest-muted">No extra detail blocks.</p>'
        summary_html = (
            f'<p class="digest-summary">{render_inline_markdown(digest_summary)}</p>'
            if digest_summary
            else ""
        )
        cards_html.append(
            f'<article class="digest-interest-card"><h3>{title}</h3>{summary_html}'
            f'<ul class="digest-key-facts">{key_facts}</ul><div class="digest-groups">{grouped_html}</div></article>'
        )

    if cards_html:
        return "".join(head_bits) + '<section class="digest-interest-cards">' + "".join(cards_html) + "</section>"
    return render_digest_markdown_html(text)


def render_markdown_html(text: str) -> str:
    lines = text.splitlines()
    blocks: list[str] = []
    paragraph_lines: list[str] = []
    list_kind: str | None = None
    list_items: list[str] = []

    def flush_paragraph() -> None:
        nonlocal paragraph_lines
        if paragraph_lines:
            joined = " ".join(line.strip() for line in paragraph_lines if line.strip())
            blocks.append(f"<p>{render_inline_markdown(joined)}</p>")
            paragraph_lines = []

    def flush_list() -> None:
        nonlocal list_kind, list_items
        if list_items and list_kind:
            items_html = "".join(f"<li>{render_inline_markdown(item)}</li>" for item in list_items)
            blocks.append(f"<{list_kind}>{items_html}</{list_kind}>")
            list_items = []
            list_kind = None

    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            flush_paragraph()
            flush_list()
            continue

        if stripped == "---":
            flush_paragraph()
            flush_list()
            blocks.append("<hr>")
            continue
        if stripped.startswith("### "):
            flush_paragraph()
            flush_list()
            blocks.append(f"<h3>{render_inline_markdown(stripped[4:])}</h3>")
            continue
        if stripped.startswith("## "):
            flush_paragraph()
            flush_list()
            blocks.append(f"<h2>{render_inline_markdown(stripped[3:])}</h2>")
            continue
        if stripped.startswith("# "):
            flush_paragraph()
            flush_list()
            blocks.append(f"<h1>{render_inline_markdown(stripped[2:])}</h1>")
            continue
        numbered = re.match(r"^(\d+)\.\s+(.+)$", stripped)
        if numbered:
            flush_paragraph()
            if list_kind != "ol":
                flush_list()
            list_kind = "ol"
            list_items.append(numbered.group(2))
            continue
        if stripped.startswith("- ") or stripped.startswith("* "):
            flush_paragraph()
            if list_kind != "ul":
                flush_list()
            list_kind = "ul"
            list_items.append(stripped[2:])
            continue
        if line.startswith("    ") or line.startswith("\t"):
            flush_paragraph()
            flush_list()
            blocks.append(f"<pre><code>{html.escape(line.lstrip())}</code></pre>")
            continue
        paragraph_lines.append(stripped)

    flush_paragraph()
    flush_list()
    return "\n".join(blocks)


def render_inline_markdown(text: str) -> str:
    escaped = html.escape(text)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\[(.+?)\]\((.+?)\)", r'<a href="\2">\1</a>', escaped)
    return escaped


def render_report_html(path: Path) -> str:
    markdown_source = path.read_text(encoding="utf-8")
    metadata = classify_report(path.name)
    digest_article = metadata.get("kind") == "interest_digest_user"
    rendered = render_digest_structured_html(markdown_source) if digest_article else render_markdown_html(markdown_source)
    eyebrow_txt = html.escape(metadata["label"])
    hero_title = (
        f"Your daily digest · {metadata['timestamp_label']}" if digest_article else metadata.get("label", path.name)
    )
    meta_scope = html.escape(metadata["scope"])
    raw_link = f' · <a href="/raw/{quote(path.name)}">Raw markdown</a>' if show_app_dev_ui() else ""
    meta_spans_html = (
        f'<span class="chip">{meta_scope}</span>'
        if digest_article
        else f'<span class="chip">{meta_scope}</span><span class="chip">{html.escape(metadata["timestamp_label"])}</span>'
    )
    content_class = "digest-reading" if digest_article else ""
    inner = f"""
    <div class="detail-body">
      <section class="panel hero page-hero">
        <span class="eyebrow">{eyebrow_txt}</span>
        <h1>{html.escape(hero_title)}</h1>
        <div class="chip-row">{meta_spans_html}</div>
        <div class="subtle-links" style="margin-top:12px;">
          <a href="/?user_id={quote(DEFAULT_DASHBOARD_USER_ID)}">Back to dashboard</a>{raw_link}
        </div>
      </section>
      <section class="panel {content_class}">
        {rendered}
      </section>
    </div>
    """
    report_extra_css = """
    .digest-reading { font-size: 1.05rem; line-height: 1.74; letter-spacing: 0.01em; }
    .digest-reading aside.digest-doc-meta {
      background: rgba(253, 250, 244, 0.95);
      border: 1px solid rgba(223, 207, 181, 0.85);
      border-left: 4px solid var(--accent);
      border-radius: 16px;
      padding: 18px 20px;
      margin: 0 0 26px;
    }
    .digest-reading aside.digest-doc-meta > p:first-child {
      margin: 0 0 12px; font-size: 0.94rem; color: var(--muted);
      text-transform: uppercase; letter-spacing: 0.08em;
    }
    .digest-reading aside.digest-doc-meta ul { margin: 0; padding-left: 1.2rem; }
    .digest-reading aside.digest-doc-meta li { margin: 0.5em 0; padding-left: 0.35em; }
    .digest-at-a-glance {
      background: rgba(255, 252, 246, 0.94);
      border: 1px solid rgba(223, 207, 181, 0.8);
      border-radius: 16px; padding: 16px 18px; margin: 0 0 22px;
    }
    .digest-at-a-glance h2 { margin: 0 0 10px; border: 0; padding: 0; font-size: 1.15rem; }
    .digest-at-a-glance ul { margin: 0; padding-left: 1.2rem; }
    .digest-interest-cards { display: grid; gap: 16px; }
    .digest-interest-card {
      background: rgba(255, 252, 246, 0.96);
      border: 1px solid rgba(223, 207, 181, 0.9);
      border-radius: 16px; padding: 16px 18px;
    }
    .digest-interest-card h3 { margin: 0 0 10px; font-size: 1.18rem; }
    .digest-summary {
      margin: 0 0 12px; padding: 10px 12px; border-radius: 10px;
      background: rgba(244, 230, 213, 0.55);
      border: 1px solid rgba(223, 207, 181, 0.85); font-size: 0.98rem;
    }
    .digest-key-facts { margin: 0; padding-left: 1.2rem; }
    .digest-groups { margin-top: 12px; display: grid; gap: 10px; }
    .digest-detail-group {
      border: 1px solid rgba(223, 207, 181, 0.75);
      border-radius: 10px; background: rgba(255, 255, 255, 0.6);
      padding: 8px 10px;
    }
    .digest-detail-group summary { cursor: pointer; font-weight: 600; }
    .digest-detail-group ul { margin-top: 8px; }
    .digest-muted { color: var(--muted); margin: 0; }
    .digest-reading h2 { margin: 2.1rem 0 0.9rem; padding-bottom: 0.35em; border-bottom: 1px solid var(--border); font-weight: 700; }
    .digest-reading h3 { margin: 1.65rem 0 0.6rem; font-size: 1.18rem; color: rgba(53, 45, 35, 0.95); }
    .digest-reading p { margin: 0.95em 0; }
    .digest-reading ul, .digest-reading ol { padding-left: 1.35rem; margin: 0.7em 0 1rem; }
    .digest-reading li { margin: 0.52em 0; }
    .digest-reading hr { margin: 1.85rem 0; opacity: 0.52; border: 0; border-top: 1px solid var(--border); }
    """
    return render_document(
        title=hero_title,
        html_lang="en",
        user_id=DEFAULT_DASHBOARD_USER_ID,
        nav_active="report",
        main_inner_html=inner.strip(),
        extra_css=report_extra_css.strip(),
        main_classes="page-wide",
    )


def render_error_html(
    message: str,
    *,
    db_path: Path | None = None,
    user_id: str | None = None,
) -> str:
    uid = user_id or DEFAULT_DASHBOARD_USER_ID
    lang = profile_html_lang(db_path, user_id=uid) if db_path is not None else "en"
    inner = f"""
    <div class="detail-body">
    <section class="panel hero page-hero">
      <h1>Something went wrong</h1>
      <p>{html.escape(message)}</p>
      <div class="detail-row hero-actions">
        <a class="action-button" href="/?user_id={quote(uid)}">Dashboard</a>
        <a href="/actions?user_id={quote(uid)}">Actions</a>
      </div>
    </section>
    </div>
    """
    return render_document(
        title="Error",
        html_lang=lang,
        user_id=uid,
        nav_active="dashboard",
        main_inner_html=inner.strip(),
        main_classes="page-wide detail-body-wrap",
        omit_glossary_footer=True,
    )


if __name__ == "__main__":
    raise SystemExit(main())
