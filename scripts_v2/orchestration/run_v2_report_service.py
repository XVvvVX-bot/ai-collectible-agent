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
import uuid
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Event, Thread
from urllib.parse import parse_qs, quote, unquote, urlparse

ROOT_DIR = Path(__file__).resolve().parents[2]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ai_agent_v2.ingestion.live_incremental import DEFAULT_STATE_SOURCE_KEY
from ai_agent_v2.matching.v2_matcher import run_v2_matching
from ai_agent_v2.parsing.listing_parser import _classify_parse_family, _parse_coin_title, _parse_stamp_title
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
                    self._write_html(HTTPStatus.BAD_REQUEST, render_error_html("interest_id is required"))
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
                    self._write_html(HTTPStatus.NOT_FOUND, render_error_html(str(exc)))
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
                    self._write_html(HTTPStatus.NOT_FOUND, render_error_html(str(exc)))
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
                    self._write_html(HTTPStatus.NOT_FOUND, render_error_html("Latest report not found"))
                    return
                self.send_response(HTTPStatus.FOUND)
                self.send_header("Location", f"/reports/{quote(target.name)}")
                self.end_headers()
                return
            if path.startswith("/reports/"):
                name = unquote(path.removeprefix("/reports/"))
                target = safe_child(reports_dir, name)
                if target is None or not target.exists():
                    self._write_html(HTTPStatus.NOT_FOUND, render_error_html("Report not found"))
                    return
                self._write_html(HTTPStatus.OK, render_report_html(target))
                return
            if path.startswith("/raw/"):
                name = unquote(path.removeprefix("/raw/"))
                target = safe_child(reports_dir, name)
                if target is None or not target.exists():
                    self._write_html(HTTPStatus.NOT_FOUND, render_error_html("Report not found"))
                    return
                self._write_file(target, "text/markdown; charset=utf-8", as_attachment=False)
                return
            if path.startswith("/downloads/"):
                name = unquote(path.removeprefix("/downloads/"))
                target = safe_child(exports_dir, name)
                if target is None or not target.exists():
                    self._write_html(HTTPStatus.NOT_FOUND, render_error_html("Bundle not found"))
                    return
                self._write_file(target, "application/zip", as_attachment=True)
                return
            self._write_html(HTTPStatus.NOT_FOUND, render_error_html("Route not found"))

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
                            payload=payload,
                            user_id=user_id,
                        ),
                    )
                except ValueError as exc:
                    self._write_html(HTTPStatus.BAD_REQUEST, render_error_html(str(exc)))
                except Exception as exc:  # pragma: no cover - defensive form fallback
                    self._write_html(HTTPStatus.INTERNAL_SERVER_ERROR, render_error_html(str(exc)))
                return
            if parsed.path == "/interests/save":
                form = parse_qs(self.rfile.read(int(self.headers.get("Content-Length", "0") or "0")).decode("utf-8"))
                user_id = first_query_value(form, "user_id") or default_user_id
                interest_id = first_query_value(form, "interest_id")
                if not interest_id:
                    self._write_html(HTTPStatus.BAD_REQUEST, render_error_html("interest_id is required"))
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
                            payload=payload,
                            user_id=user_id,
                            interest_id=interest_id,
                        ),
                    )
                except ValueError as exc:
                    self._write_html(HTTPStatus.BAD_REQUEST, render_error_html(str(exc)))
                except Exception as exc:  # pragma: no cover - defensive form fallback
                    self._write_html(HTTPStatus.INTERNAL_SERVER_ERROR, render_error_html(str(exc)))
                return
            if parsed.path == "/interests/delete":
                form = parse_qs(self.rfile.read(int(self.headers.get("Content-Length", "0") or "0")).decode("utf-8"))
                user_id = first_query_value(form, "user_id") or default_user_id
                interest_id = first_query_value(form, "interest_id")
                if not interest_id:
                    self._write_html(HTTPStatus.BAD_REQUEST, render_error_html("interest_id is required"))
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
                            payload=payload,
                            user_id=user_id,
                        ),
                    )
                except ValueError as exc:
                    self._write_html(HTTPStatus.BAD_REQUEST, render_error_html(str(exc)))
                except Exception as exc:  # pragma: no cover - defensive form fallback
                    self._write_html(HTTPStatus.INTERNAL_SERVER_ERROR, render_error_html(str(exc)))
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
                    self._write_html(HTTPStatus.BAD_REQUEST, render_error_html(str(exc)))
                except Exception as exc:  # pragma: no cover - defensive form fallback
                    self._write_html(HTTPStatus.INTERNAL_SERVER_ERROR, render_error_html(str(exc)))
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
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
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


def load_user_interests_payload(db_path: Path, *, user_id: str) -> dict[str, object]:
    profile_payload = load_user_profile_payload(db_path, user_id=user_id)
    interests = profile_payload["interests"] if isinstance(profile_payload.get("interests"), list) else []

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
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
    valid_interest_kinds = {"collecting", "watch_buy", "watch_sell", "discovery", "portfolio_monitor"}
    valid_scope_kinds = {"exact_item", "issue_part", "issue_family", "series", "theme", "category", "keyword"}
    valid_precision_modes = {"exact", "balanced", "broad"}
    valid_priorities = {"high", "normal", "low"}
    valid_condition_modes = {"ignore", "prefer", "require"}
    valid_delivery_modes = {"immediate", "daily_digest", "silent_log"}

    interest_name = interest_name.strip()
    raw_input = raw_input.strip()
    interest_notes = interest_notes.strip()
    if not interest_name:
        raise ValueError("interest_name is required")
    if not raw_input:
        raise ValueError("raw_input is required")
    if interest_kind not in valid_interest_kinds:
        raise ValueError("invalid interest_kind")
    if scope_kind not in valid_scope_kinds:
        raise ValueError("invalid scope_kind")
    if precision_mode not in valid_precision_modes:
        raise ValueError("invalid precision_mode")
    if interest_priority not in valid_priorities:
        raise ValueError("invalid interest_priority")
    if condition_mode not in valid_condition_modes:
        raise ValueError("invalid condition_mode")
    if delivery_mode not in valid_delivery_modes:
        raise ValueError("invalid delivery_mode")

    now_iso = utc_now_iso()
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        user_row = conn.execute(
            """
            SELECT id
            FROM users
            WHERE id = ?
            """,
            (user_id,),
        ).fetchone()
        if user_row is None:
            raise ValueError(f"user not found: {user_id}")

        defaults_row = conn.execute(
            """
            SELECT default_min_match_score, default_allow_related_matches, default_allow_series_matches,
                   default_allow_variant_matches, default_condition_mode, default_delivery_mode,
                   default_cooldown_hours
            FROM user_profile_defaults_v2
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()
        defaults = normalize_sqlite_row(defaults_row) if defaults_row is not None else {}

        parsed_target = build_manual_interest_target(
            raw_input=raw_input,
            scope_kind=scope_kind,
            precision_mode=precision_mode,
            interest_priority=interest_priority,
            condition_mode=condition_mode,
            budget_max=budget_max,
        )
        allow_related_matches, allow_series_matches, allow_variant_matches = resolve_match_flags(
            scope_kind=scope_kind,
            precision_mode=precision_mode,
            defaults=defaults,
        )
        policy_values = resolve_signal_policy_defaults(
            interest_kind=interest_kind,
            delivery_mode=delivery_mode,
            cooldown_hours=cooldown_hours,
            min_match_score=min_match_score if min_match_score is not None else defaults.get("default_min_match_score"),
            max_signals_per_day=max_signals_per_day,
            allow_series_matches=allow_series_matches,
            allow_variant_matches=allow_variant_matches,
        )

        interest_id = str(uuid.uuid4())
        target_id = str(uuid.uuid4())
        policy_id = str(uuid.uuid4())
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
                user_id,
                interest_name,
                interest_kind,
                scope_kind,
                precision_mode,
                interest_priority,
                resolve_intent_confidence(interest_kind),
                int(allow_related_matches),
                int(allow_series_matches),
                int(allow_variant_matches),
                interest_notes,
                now_iso,
                now_iso,
            ),
        )
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
              condition_mode,
              year_value,
              budget_min,
              budget_max,
              strictness_override,
              priority_override,
              is_active,
              created_at,
              updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (
                target_id,
                interest_id,
                str(parsed_target["target_label"]),
                str(parsed_target["target_kind"]),
                str(parsed_target["parse_family"]),
                raw_input,
                parsed_target["normalized_name"],
                parsed_target["issue_code_norm"],
                parsed_target["issue_part_token"],
                parsed_target["series_key"],
                parsed_target["theme_name"],
                parsed_target["asset_type"],
                str(parsed_target["variant_tokens_json"]),
                str(parsed_target["quantity_tokens_json"]),
                str(parsed_target["condition_tokens_json"]),
                condition_mode,
                parsed_target["year_value"],
                None,
                budget_max,
                precision_mode,
                interest_priority,
                now_iso,
                now_iso,
            ),
        )
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
                policy_id,
                interest_id,
                policy_values["notify_on_preview"],
                policy_values["notify_on_live"],
                policy_values["notify_on_ended"],
                policy_values["notify_on_exact_match"],
                policy_values["notify_on_variant_match"],
                policy_values["notify_on_series_match"],
                policy_values["notify_on_price_opportunity"],
                policy_values["notify_on_sell_opportunity"],
                policy_values["min_match_score"],
                policy_values["cooldown_hours"],
                policy_values["delivery_mode"],
                policy_values["max_signals_per_day"],
                now_iso,
                now_iso,
            ),
        )
        conn.commit()

    created = load_interest_editor_payload(db_path, user_id=user_id, interest_id=interest_id)
    return {
        "ok": True,
        "created_at": now_iso,
        "user": created["user"],
        "interest": created["interest"],
        "target_id": target_id,
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
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
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

    updated = load_interest_editor_payload(db_path, user_id=user_id, interest_id=interest_id)
    return {
        "ok": True,
        "updated_at": now_iso,
        "user": updated["user"],
        "interest": updated["interest"],
    }


def delete_interest_form(
    *,
    db_path: Path,
    user_id: str,
    interest_id: str,
) -> dict[str, object]:
    now_iso = utc_now_iso()
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        interest_row = conn.execute(
            """
            SELECT id, interest_name, active_status
            FROM user_interests_v2
            WHERE id = ? AND user_id = ?
            """,
            (interest_id, user_id),
        ).fetchone()
        if interest_row is None:
            raise ValueError(f"interest not found: {interest_id}")

        target_rows = conn.execute(
            """
            SELECT id
            FROM user_interest_targets_v2
            WHERE interest_id = ?
            """,
            (interest_id,),
        ).fetchall()
        target_ids = [str(row["id"]) for row in target_rows]
        holding_rows = conn.execute(
            """
            SELECT id
            FROM user_holdings_v2
            WHERE user_id = ? AND linked_interest_id = ?
            """,
            (user_id, interest_id),
        ).fetchall()
        holding_ids = [str(row["id"]) for row in holding_rows]

        conn.execute(
            """
            UPDATE user_interests_v2
            SET active_status = 'inactive',
                updated_at = ?
            WHERE id = ? AND user_id = ?
            """,
            (now_iso, interest_id, user_id),
        )
        conn.execute(
            """
            UPDATE user_interest_targets_v2
            SET is_active = 0,
                updated_at = ?
            WHERE interest_id = ?
            """,
            (now_iso, interest_id),
        )
        conn.execute(
            """
            UPDATE signals_v2
            SET status = 'inactive',
                last_seen_at = ?
            WHERE user_id = ? AND interest_id = ? AND status = 'active'
            """,
            (now_iso, user_id, interest_id),
        )
        related_item_ids = target_ids + holding_ids
        if related_item_ids:
            placeholders = ",".join("?" for _ in related_item_ids)
            conn.execute(
                f"""
                UPDATE listing_matches_v2
                SET status = 'inactive',
                    updated_at = ?
                WHERE user_id = ? AND status = 'active' AND user_item_id IN ({placeholders})
                """,
                (now_iso, user_id, *related_item_ids),
            )
        conn.commit()

    refreshed = load_user_interests_payload(db_path, user_id=user_id)
    return {
        "ok": True,
        "deleted_at": now_iso,
        "user": refreshed["user"],
        "summary": refreshed["summary"],
        "interest": {
            "id": str(interest_row["id"]),
            "interest_name": str(interest_row["interest_name"] or interest_id),
        },
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
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
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
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
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

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Operator Actions</title>
  <style>
    :root {{
      --bg: #f4ede1;
      --panel: rgba(255, 250, 244, 0.88);
      --panel-strong: #fff9f0;
      --border: #decaae;
      --ink: #1d2128;
      --muted: #706658;
      --accent: #8f3911;
      --accent-soft: #f1e0cb;
      --accent-deep: #4e2513;
      --shadow: 0 24px 60px rgba(91, 58, 20, 0.09);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      font-family: "Avenir Next", "Segoe UI Variable", "Trebuchet MS", sans-serif;
      margin: 0;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(188, 121, 48, 0.18), transparent 22%),
        radial-gradient(circle at 80% 10%, rgba(124, 86, 43, 0.1), transparent 20%),
        linear-gradient(180deg, #f8f2ea 0%, var(--bg) 100%);
    }}
    main {{ max-width: 1120px; margin: 0 auto; padding: 36px 20px 60px; }}
    nav {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-bottom: 18px;
    }}
    nav a {{
      padding: 8px 12px;
      border: 1px solid var(--border);
      border-radius: 999px;
      background: rgba(255, 250, 244, 0.78);
      color: var(--muted);
      font-size: 0.92rem;
      text-decoration: none;
    }}
    .action-button, .danger-button {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      border-radius: 999px;
      padding: 9px 14px;
      border: 1px solid var(--border);
      text-decoration: none;
      font-size: 0.92rem;
      cursor: pointer;
    }}
    .action-button {{
      background: var(--accent);
      color: #fff9f0;
    }}
    .danger-button {{
      background: #fff3ef;
      color: #8b2d17;
    }}
    .hero, .section {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 28px;
      padding: 24px;
      margin-bottom: 22px;
      box-shadow: var(--shadow);
    }}
    .hero {{
      background: linear-gradient(135deg, rgba(255, 247, 236, 0.98), rgba(241, 223, 195, 0.9));
    }}
    .hero h1 {{
      font-family: Georgia, "Times New Roman", serif;
      font-size: clamp(2.1rem, 4vw, 3.3rem);
      letter-spacing: -0.04em;
      margin: 0 0 10px;
    }}
    .hero p, .section p {{
      color: var(--muted);
      line-height: 1.6;
    }}
    .eyebrow {{
      text-transform: uppercase;
      letter-spacing: 0.12em;
      font-size: 0.78rem;
      color: var(--muted);
    }}
    .chip-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 16px;
    }}
    .chip {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      border-radius: 999px;
      padding: 7px 11px;
      background: var(--accent-soft);
      color: var(--accent);
      font-size: 0.84rem;
      font-weight: 600;
      border: 1px solid var(--border);
    }}
    .summary-grid, .actions-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 14px;
    }}
    .summary-card, .action-card {{
      background: var(--panel-strong);
      border: 1px solid var(--border);
      border-radius: 22px;
      padding: 18px;
      box-shadow: var(--shadow);
    }}
    .summary-card strong {{
      display: block;
      font-size: 1.9rem;
      font-family: Georgia, "Times New Roman", serif;
      color: var(--accent-deep);
      margin-top: 8px;
    }}
    .action-card h3 {{
      margin: 0 0 8px;
      font-size: 1.12rem;
    }}
    .action-card form {{
      display: grid;
      gap: 12px;
      margin-top: 14px;
    }}
    .action-card label {{
      display: grid;
      gap: 6px;
      color: var(--muted);
      font-size: 0.94rem;
    }}
    .action-card input, .action-card select, .action-card button {{
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 10px 12px;
      font: inherit;
      background: #fffdf8;
      color: var(--ink);
    }}
    .action-card button {{
      background: var(--accent);
      color: #fff9f0;
      font-weight: 700;
      cursor: pointer;
    }}
    .action-card button:hover {{
      background: var(--accent-deep);
    }}
    .section-header {{
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      gap: 12px;
      margin-bottom: 18px;
    }}
    .report-list {{
      display: grid;
      gap: 12px;
    }}
    .report-row {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 14px;
      align-items: center;
      background: var(--panel-strong);
      border: 1px solid var(--border);
      border-radius: 18px;
      padding: 16px 18px;
    }}
    .report-row h3 {{ margin: 0 0 6px; font-size: 1.05rem; }}
    .report-row p {{ margin: 0; color: var(--muted); line-height: 1.5; }}
    .meta-stack {{
      display: flex;
      flex-direction: column;
      align-items: flex-end;
      gap: 8px;
      color: var(--muted);
      font-size: 0.92rem;
    }}
    code {{
      font-family: "JetBrains Mono", "Cascadia Code", monospace;
      background: #efe4d4;
      padding: 2px 6px;
      border-radius: 6px;
    }}
    a {{ color: var(--accent); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .empty-state {{ color: var(--muted); margin: 0; }}
    @media (max-width: 720px) {{
      .report-row {{
        grid-template-columns: 1fr;
      }}
      .meta-stack {{
        align-items: flex-start;
      }}
    }}
  </style>
</head>
<body>
  <main>
    <nav>
      <a href="/?user_id={quote(user_id)}">Dashboard</a>
      <a href="/actions?user_id={quote(user_id)}">Actions</a>
      <a href="/interests?user_id={quote(user_id)}">Interests</a>
      <a href="/matches?user_id={quote(user_id)}">Opportunities</a>
      <a href="/api/users/{quote(user_id)}/profile">Profile JSON</a>
    </nav>
    <section class="hero">
      <span class="eyebrow">Operator Actions</span>
      <h1>{html.escape(str(user["display_name"]))}</h1>
      <p>Trigger the core collector workflows directly from the browser: refresh matching, regenerate signals, and rebuild the latest digest without dropping into shell commands or raw API calls.</p>
      <div class="chip-row">
        <span class="chip">User <code>{html.escape(str(user["id"]))}</code></span>
        <span class="chip">Interests <strong>{summary.get("active_interest_count", 0)}</strong></span>
        <span class="chip">Matches <strong>{summary.get("active_match_count", 0)}</strong></span>
        <span class="chip">Signals <strong>{summary.get("active_signal_count", 0)}</strong></span>
      </div>
    </section>
    <section class="actions-grid">
      <article class="action-card">
        <span class="eyebrow">Action</span>
        <h3>Run Matching</h3>
        <p>Refresh active opportunity inventory for this collector.</p>
        <form method="post" action="/actions/run">
          <input type="hidden" name="user_id" value="{html.escape(user_id)}">
          <input type="hidden" name="action" value="matching">
          <label>Active listings only
            <select name="only_active">
              <option value="true" selected>Yes</option>
              <option value="false">No</option>
            </select>
          </label>
          <button type="submit">Run matching now</button>
        </form>
      </article>
      <article class="action-card">
        <span class="eyebrow">Action</span>
        <h3>Run Signals</h3>
        <p>Recompute the active signal inbox from the current match and event state.</p>
        <form method="post" action="/actions/run">
          <input type="hidden" name="user_id" value="{html.escape(user_id)}">
          <input type="hidden" name="action" value="signals">
          <label>Lookback hours
            <input type="number" name="lookback_hours" min="1" max="168" value="{lookback_hours}">
          </label>
          <button type="submit">Run signals now</button>
        </form>
      </article>
      <article class="action-card">
        <span class="eyebrow">Action</span>
        <h3>Refresh Digest</h3>
        <p>Rebuild the latest collector digest and open the new rendered report immediately after.</p>
        <form method="post" action="/actions/run">
          <input type="hidden" name="user_id" value="{html.escape(user_id)}">
          <input type="hidden" name="action" value="digest">
          <label>Lookback hours
            <input type="number" name="lookback_hours" min="1" max="168" value="{lookback_hours}">
          </label>
          <button type="submit">Refresh digest</button>
        </form>
      </article>
    </section>
    <section class="section">
      <div class="section-header">
        <div>
          <h2>Latest Outputs</h2>
          <p>Quick links back into the most recent collector artifacts.</p>
        </div>
      </div>
      <div class="report-list">
        {render_action_report_row(digest, empty_label="No digest generated yet.")}
        {render_action_report_row(signal_review, empty_label="No signal review generated yet.")}
      </div>
    </section>
  </main>
</body>
</html>"""


def render_action_result_html(
    *,
    db_path: Path,
    reports_dir: Path,
    user_id: str,
    action_name: str,
    lookback_hours: int,
    only_active_listings: bool,
) -> str:
    if action_name == "matching":
        payload = run_matching_payload(db_path, user_id=user_id, only_active_listings=only_active_listings)
        title = "Matching Complete"
        summary_bits = [
            f"user <code>{html.escape(user_id)}</code>",
            f"active only <code>{str(only_active_listings).lower()}</code>",
            f"matched <code>{html.escape(str(((payload.get('result') or {}).get('matches_upserted') or 0)))}</code>",
        ]
        links_html = "".join(
            [
                f'<a href="/matches?user_id={quote(user_id)}">Open opportunities</a>',
                f'<a href="/api/users/{quote(user_id)}/matches">Matches JSON</a>',
                f'<a href="/actions?user_id={quote(user_id)}">Back to actions</a>',
            ]
        )
    elif action_name == "signals":
        payload = run_signals_payload(db_path, user_id=user_id, lookback_hours=lookback_hours)
        result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
        title = "Signals Complete"
        summary_bits = [
            f"user <code>{html.escape(user_id)}</code>",
            f"lookback <code>{lookback_hours}h</code>",
            f"inserted <code>{html.escape(str(result.get('inserted') or 0))}</code>",
            f"updated <code>{html.escape(str(result.get('updated') or 0))}</code>",
        ]
        links_html = "".join(
            [
                f'<a href="/?user_id={quote(user_id)}#signals">Open dashboard signals</a>',
                f'<a href="/api/users/{quote(user_id)}/signals">Signals JSON</a>',
                f'<a href="/actions?user_id={quote(user_id)}">Back to actions</a>',
            ]
        )
    elif action_name == "digest":
        payload = run_digest_payload(db_path=db_path, reports_dir=reports_dir, user_id=user_id, lookback_hours=lookback_hours)
        report = payload.get("report") if isinstance(payload.get("report"), dict) else {}
        title = "Digest Refreshed"
        summary_bits = [
            f"user <code>{html.escape(user_id)}</code>",
            f"lookback <code>{lookback_hours}h</code>",
            f"report <code>{html.escape(str(report.get('name') or '-'))}</code>",
        ]
        links_html = "".join(
            [
                f'<a href="{html.escape(str(report.get("rendered") or "/"))}">Open rendered digest</a>',
                f'<a href="{html.escape(str(report.get("raw") or "/"))}">Open raw markdown</a>',
                f'<a href="/actions?user_id={quote(user_id)}">Back to actions</a>',
            ]
        )
    else:
        raise ValueError("unknown action")

    pretty_payload = html.escape(json.dumps(payload, ensure_ascii=False, indent=2))
    summary_html = " | ".join(summary_bits)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    :root {{
      --bg: #f4ede1;
      --panel: rgba(255, 250, 244, 0.88);
      --panel-strong: #fff9f0;
      --border: #decaae;
      --ink: #1d2128;
      --muted: #706658;
      --accent: #8f3911;
      --shadow: 0 24px 60px rgba(91, 58, 20, 0.09);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      font-family: "Avenir Next", "Segoe UI Variable", "Trebuchet MS", sans-serif;
      margin: 0;
      color: var(--ink);
      background: linear-gradient(180deg, #f8f2ea 0%, var(--bg) 100%);
    }}
    main {{ max-width: 960px; margin: 0 auto; padding: 36px 20px 60px; }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 28px;
      padding: 24px;
      box-shadow: var(--shadow);
      margin-bottom: 20px;
    }}
    h1 {{
      font-family: Georgia, "Times New Roman", serif;
      font-size: clamp(2rem, 4vw, 3rem);
      letter-spacing: -0.04em;
      margin: 0 0 10px;
    }}
    p {{ color: var(--muted); line-height: 1.6; }}
    .link-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      margin-top: 16px;
    }}
    pre {{
      white-space: pre-wrap;
      overflow-x: auto;
      background: var(--panel-strong);
      border: 1px solid var(--border);
      border-radius: 20px;
      padding: 18px;
      font-family: "JetBrains Mono", "Cascadia Code", monospace;
      font-size: 0.93rem;
    }}
    code {{
      font-family: "JetBrains Mono", "Cascadia Code", monospace;
      background: #efe4d4;
      padding: 2px 6px;
      border-radius: 6px;
    }}
    a {{ color: var(--accent); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
  </style>
</head>
<body>
  <main>
    <section class="panel">
      <h1>{html.escape(title)}</h1>
      <p>{summary_html}</p>
      <div class="link-row">{links_html}</div>
    </section>
    <section class="panel">
      <h2>Action Payload</h2>
      <pre>{pretty_payload}</pre>
    </section>
  </main>
</body>
</html>"""


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

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Edit Interest</title>
  <style>
    :root {{
      --bg: #f4ede1;
      --panel: rgba(255, 250, 244, 0.88);
      --panel-strong: #fff9f0;
      --border: #decaae;
      --ink: #1d2128;
      --muted: #706658;
      --accent: #8f3911;
      --accent-deep: #4e2513;
      --shadow: 0 24px 60px rgba(91, 58, 20, 0.09);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      font-family: "Avenir Next", "Segoe UI Variable", "Trebuchet MS", sans-serif;
      margin: 0;
      color: var(--ink);
      background: linear-gradient(180deg, #f8f2ea 0%, var(--bg) 100%);
    }}
    main {{ max-width: 900px; margin: 0 auto; padding: 36px 20px 60px; }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 28px;
      padding: 24px;
      box-shadow: var(--shadow);
      margin-bottom: 20px;
    }}
    h1 {{
      font-family: Georgia, "Times New Roman", serif;
      font-size: clamp(2rem, 4vw, 3rem);
      letter-spacing: -0.04em;
      margin: 0 0 10px;
    }}
    p {{ color: var(--muted); line-height: 1.6; }}
    .chip-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 16px;
    }}
    .chip {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      border-radius: 999px;
      padding: 7px 11px;
      background: #f1e0cb;
      color: var(--accent);
      font-size: 0.84rem;
      font-weight: 600;
      border: 1px solid var(--border);
    }}
    form {{
      display: grid;
      gap: 16px;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 14px;
    }}
    label {{
      display: grid;
      gap: 6px;
      color: var(--muted);
      font-size: 0.94rem;
    }}
    input, select, textarea, button {{
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 10px 12px;
      font: inherit;
      background: #fffdf8;
      color: var(--ink);
    }}
    textarea {{
      min-height: 120px;
      resize: vertical;
    }}
    button {{
      background: var(--accent);
      color: #fff9f0;
      font-weight: 700;
      cursor: pointer;
    }}
    button:hover {{
      background: var(--accent-deep);
    }}
    code {{
      font-family: "JetBrains Mono", "Cascadia Code", monospace;
      background: #efe4d4;
      padding: 2px 6px;
      border-radius: 6px;
    }}
    a {{ color: var(--accent); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
  </style>
</head>
<body>
  <main>
    <section class="panel">
      <h1>{html.escape(str(interest.get("interest_name") or "-"))}</h1>
      <p>Edit the main operational knobs for this interest without leaving the browser.</p>
      <div class="chip-row">
        <span class="chip">User <code>{html.escape(str(user.get("id") or user_id))}</code></span>
        <span class="chip">Target <code>{html.escape(str(primary_target.get("target_label") or "-"))}</code></span>
        <span class="chip">Holding <code>{html.escape(str(primary_holding.get("raw_input") or primary_holding.get("normalized_name") or "none"))}</code></span>
      </div>
    </section>
    <section class="panel">
      <form method="post" action="/interests/save">
        <input type="hidden" name="user_id" value="{html.escape(user_id)}">
        <input type="hidden" name="interest_id" value="{html.escape(interest_id)}">
        <div class="grid">
          <label>Priority
            <select name="interest_priority">
              {render_select_option('high', str(interest.get('interest_priority') or ''), 'High')}
              {render_select_option('normal', str(interest.get('interest_priority') or ''), 'Normal')}
              {render_select_option('low', str(interest.get('interest_priority') or ''), 'Low')}
            </select>
          </label>
          <label>Budget max
            <input type="number" step="0.01" name="budget_max" value="{html.escape(str(primary_target.get('budget_max') or ''))}">
          </label>
          <label>Condition mode
            <select name="condition_mode">
              {render_select_option('ignore', str(primary_target.get('condition_mode') or ''), 'Ignore')}
              {render_select_option('prefer', str(primary_target.get('condition_mode') or ''), 'Prefer')}
              {render_select_option('require', str(primary_target.get('condition_mode') or ''), 'Require')}
            </select>
          </label>
          <label>Delivery mode
            <select name="delivery_mode">
              {render_select_option('immediate', str(policy.get('delivery_mode') or ''), 'Immediate')}
              {render_select_option('daily_digest', str(policy.get('delivery_mode') or ''), 'Daily digest')}
            </select>
          </label>
          <label>Cooldown hours
            <input type="number" min="1" max="168" name="cooldown_hours" value="{html.escape(str(policy.get('cooldown_hours') or 24))}">
          </label>
          <label>Min match score
            <input type="number" step="0.1" name="min_match_score" value="{html.escape(str(policy.get('min_match_score') or ''))}">
          </label>
          <label>Max signals per day
            <input type="number" min="1" max="100" name="max_signals_per_day" value="{html.escape(str(policy.get('max_signals_per_day') or 5))}">
          </label>
        </div>
        <label>Operator notes
          <textarea name="interest_notes">{html.escape(str(interest.get("notes") or ""))}</textarea>
        </label>
        <button type="submit">Save interest settings</button>
      </form>
      <p><a href="/interests?user_id={quote(user_id)}">Back to interests</a></p>
    </section>
  </main>
</body>
</html>"""


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
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Add Interest</title>
  <style>
    :root {{
      --bg: #f4ede1;
      --panel: rgba(255, 250, 244, 0.88);
      --border: #decaae;
      --ink: #1d2128;
      --muted: #706658;
      --accent: #8f3911;
      --accent-deep: #4e2513;
    }}
    body {{
      font-family: "Avenir Next", "Segoe UI Variable", "Trebuchet MS", sans-serif;
      margin: 0;
      color: var(--ink);
      background: linear-gradient(180deg, #f8f2ea 0%, var(--bg) 100%);
    }}
    main {{ max-width: 980px; margin: 0 auto; padding: 36px 20px 60px; }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 28px;
      padding: 24px;
      box-shadow: 0 24px 60px rgba(91, 58, 20, 0.09);
      margin-bottom: 20px;
    }}
    h1 {{
      font-family: Georgia, "Times New Roman", serif;
      font-size: clamp(2rem, 4vw, 3rem);
      letter-spacing: -0.04em;
      margin: 0 0 10px;
    }}
    p {{ color: var(--muted); line-height: 1.6; }}
    .chip-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 16px;
    }}
    .chip {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      border-radius: 999px;
      padding: 7px 11px;
      background: #f1e0cb;
      color: var(--accent);
      font-size: 0.84rem;
      font-weight: 600;
      border: 1px solid var(--border);
    }}
    form {{
      display: grid;
      gap: 16px;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 14px;
    }}
    label {{
      display: grid;
      gap: 6px;
      color: var(--muted);
      font-size: 0.94rem;
    }}
    input, select, textarea, button {{
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 10px 12px;
      font: inherit;
      background: #fffdf8;
      color: var(--ink);
    }}
    textarea {{
      min-height: 120px;
      resize: vertical;
    }}
    button {{
      background: var(--accent);
      color: #fff9f0;
      font-weight: 700;
      cursor: pointer;
    }}
    button:hover {{
      background: var(--accent-deep);
    }}
    code {{
      font-family: "JetBrains Mono", "Cascadia Code", monospace;
      background: #efe4d4;
      padding: 2px 6px;
      border-radius: 6px;
    }}
    a {{ color: var(--accent); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
  </style>
</head>
<body>
  <main>
    <section class="panel">
      <h1>Add Interest</h1>
      <p>Create a new active interest, its first target, and its signal policy together. This is the missing browser-native entry point for manual curation.</p>
      <div class="chip-row">
        <span class="chip">User <code>{html.escape(str(user.get("id") or user_id))}</code></span>
        <span class="chip">Language <code>{html.escape(str(user.get("language") or "-"))}</code></span>
        <span class="chip">Timezone <code>{html.escape(str(user.get("timezone") or "-"))}</code></span>
      </div>
    </section>
    <section class="panel">
      <form method="post" action="/interests/create">
        <input type="hidden" name="user_id" value="{html.escape(user_id)}">
        <div class="grid">
          <label>Interest name
            <input type="text" name="interest_name" placeholder="e.g. 红楼梦型张补仓" required>
          </label>
          <label>Raw target input
            <input type="text" name="raw_input" placeholder="e.g. T69M红楼梦型张新" required>
          </label>
          <label>Interest kind
            <select name="interest_kind">
              <option value="watch_buy">Watch buy</option>
              <option value="watch_sell">Watch sell</option>
              <option value="collecting">Collecting</option>
              <option value="discovery">Discovery</option>
              <option value="portfolio_monitor">Portfolio monitor</option>
            </select>
          </label>
          <label>Scope
            <select name="scope_kind">
              <option value="exact_item">Exact item</option>
              <option value="issue_family">Issue family</option>
              <option value="series">Series</option>
              <option value="theme">Theme</option>
              <option value="keyword">Keyword</option>
            </select>
          </label>
          <label>Precision
            <select name="precision_mode">
              {render_select_option('exact', default_precision_mode, 'Exact')}
              {render_select_option('balanced', default_precision_mode, 'Balanced')}
              {render_select_option('broad', default_precision_mode, 'Broad')}
            </select>
          </label>
          <label>Priority
            <select name="interest_priority">
              {render_select_option('high', default_priority, 'High')}
              {render_select_option('normal', default_priority, 'Normal')}
              {render_select_option('low', default_priority, 'Low')}
            </select>
          </label>
          <label>Budget max
            <input type="number" step="0.01" name="budget_max" value="">
          </label>
          <label>Condition mode
            <select name="condition_mode">
              {render_select_option('ignore', default_condition_mode, 'Ignore')}
              {render_select_option('prefer', default_condition_mode, 'Prefer')}
              {render_select_option('require', default_condition_mode, 'Require')}
            </select>
          </label>
          <label>Delivery mode
            <select name="delivery_mode">
              {render_select_option('immediate', default_delivery_mode, 'Immediate')}
              {render_select_option('daily_digest', default_delivery_mode, 'Daily digest')}
              {render_select_option('silent_log', default_delivery_mode, 'Silent log')}
            </select>
          </label>
          <label>Cooldown hours
            <input type="number" min="1" max="168" name="cooldown_hours" value="{html.escape(str(default_cooldown))}">
          </label>
          <label>Min match score
            <input type="number" step="0.1" name="min_match_score" value="{html.escape(str(default_min_match_score))}">
          </label>
          <label>Max signals per day
            <input type="number" min="1" max="100" name="max_signals_per_day" value="8">
          </label>
        </div>
        <label>Operator notes
          <textarea name="interest_notes" placeholder="Why this interest exists, what matters, and any curation rules."></textarea>
        </label>
        <button type="submit">Create interest</button>
      </form>
      <p><a href="/interests?user_id={quote(user_id)}">Back to interests</a></p>
    </section>
  </main>
</body>
</html>"""


def render_interest_save_result_html(
    *,
    payload: dict[str, object],
    user_id: str,
    interest_id: str,
) -> str:
    interest = payload.get("interest") if isinstance(payload.get("interest"), dict) else {}
    summary = interest.get("summary") if isinstance(interest.get("summary"), dict) else {}
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Interest Saved</title>
  <style>
    body {{
      font-family: "Avenir Next", "Segoe UI Variable", "Trebuchet MS", sans-serif;
      margin: 0;
      color: #1d2128;
      background: linear-gradient(180deg, #f8f2ea 0%, #f4ede1 100%);
    }}
    main {{ max-width: 900px; margin: 0 auto; padding: 36px 20px 60px; }}
    .panel {{
      background: rgba(255, 250, 244, 0.88);
      border: 1px solid #decaae;
      border-radius: 28px;
      padding: 24px;
      box-shadow: 0 24px 60px rgba(91, 58, 20, 0.09);
      margin-bottom: 20px;
    }}
    h1 {{
      font-family: Georgia, "Times New Roman", serif;
      font-size: clamp(2rem, 4vw, 3rem);
      letter-spacing: -0.04em;
      margin: 0 0 10px;
    }}
    p {{ color: #706658; line-height: 1.6; }}
    .link-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      margin-top: 16px;
    }}
    a {{ color: #8f3911; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    code {{
      font-family: "JetBrains Mono", "Cascadia Code", monospace;
      background: #efe4d4;
      padding: 2px 6px;
      border-radius: 6px;
    }}
  </style>
</head>
<body>
  <main>
    <section class="panel">
      <h1>Interest Saved</h1>
      <p><code>{html.escape(str(interest.get("interest_name") or interest_id))}</code> was updated successfully.</p>
      <p>Signals <strong>{html.escape(str(summary.get("active_signal_count") or 0))}</strong> | matches <strong>{html.escape(str(summary.get("active_match_count") or 0))}</strong> | updated at <code>{html.escape(str(payload.get("updated_at") or "-"))}</code></p>
      <div class="link-row">
        <a href="/interests/edit?user_id={quote(user_id)}&interest_id={quote(interest_id)}">Keep editing</a>
        <a href="/interests?user_id={quote(user_id)}">Back to interests</a>
        <a href="/?user_id={quote(user_id)}">Back to dashboard</a>
      </div>
    </section>
  </main>
</body>
</html>"""


def render_interest_create_result_html(
    *,
    payload: dict[str, object],
    user_id: str,
) -> str:
    interest = payload.get("interest") if isinstance(payload.get("interest"), dict) else {}
    summary = interest.get("summary") if isinstance(interest.get("summary"), dict) else {}
    interest_id = str(interest.get("id") or "")
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Interest Created</title>
  <style>
    body {{
      font-family: "Avenir Next", "Segoe UI Variable", "Trebuchet MS", sans-serif;
      margin: 0;
      color: #1d2128;
      background: linear-gradient(180deg, #f8f2ea 0%, #f4ede1 100%);
    }}
    main {{ max-width: 900px; margin: 0 auto; padding: 36px 20px 60px; }}
    .panel {{
      background: rgba(255, 250, 244, 0.88);
      border: 1px solid #decaae;
      border-radius: 28px;
      padding: 24px;
      box-shadow: 0 24px 60px rgba(91, 58, 20, 0.09);
      margin-bottom: 20px;
    }}
    h1 {{
      font-family: Georgia, "Times New Roman", serif;
      font-size: clamp(2rem, 4vw, 3rem);
      letter-spacing: -0.04em;
      margin: 0 0 10px;
    }}
    p {{ color: #706658; line-height: 1.6; }}
    .link-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      margin-top: 16px;
    }}
    a {{ color: #8f3911; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    code {{
      font-family: "JetBrains Mono", "Cascadia Code", monospace;
      background: #efe4d4;
      padding: 2px 6px;
      border-radius: 6px;
    }}
  </style>
</head>
<body>
  <main>
    <section class="panel">
      <h1>Interest Created</h1>
      <p><code>{html.escape(str(interest.get("interest_name") or interest_id))}</code> was created successfully.</p>
      <p>Signals <strong>{html.escape(str(summary.get("active_signal_count") or 0))}</strong> | matches <strong>{html.escape(str(summary.get("active_match_count") or 0))}</strong> | created at <code>{html.escape(str(payload.get("created_at") or "-"))}</code></p>
      <p>The new interest is active immediately. If you want fresh matches or signals right away, use the action tools next.</p>
      <div class="link-row">
        <a href="/interests/edit?user_id={quote(user_id)}&interest_id={quote(interest_id)}">Edit this interest</a>
        <a href="/actions?user_id={quote(user_id)}">Open actions</a>
        <a href="/interests?user_id={quote(user_id)}">Back to interests</a>
        <a href="/?user_id={quote(user_id)}">Back to dashboard</a>
      </div>
    </section>
  </main>
</body>
</html>"""


def render_interest_delete_result_html(
    *,
    payload: dict[str, object],
    user_id: str,
) -> str:
    interest = payload.get("interest") if isinstance(payload.get("interest"), dict) else {}
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Interest Removed</title>
  <style>
    body {{
      font-family: "Avenir Next", "Segoe UI Variable", "Trebuchet MS", sans-serif;
      margin: 0;
      color: #1d2128;
      background: linear-gradient(180deg, #f8f2ea 0%, #f4ede1 100%);
    }}
    main {{ max-width: 900px; margin: 0 auto; padding: 36px 20px 60px; }}
    .panel {{
      background: rgba(255, 250, 244, 0.88);
      border: 1px solid #decaae;
      border-radius: 28px;
      padding: 24px;
      box-shadow: 0 24px 60px rgba(91, 58, 20, 0.09);
      margin-bottom: 20px;
    }}
    h1 {{
      font-family: Georgia, "Times New Roman", serif;
      font-size: clamp(2rem, 4vw, 3rem);
      letter-spacing: -0.04em;
      margin: 0 0 10px;
    }}
    p {{ color: #706658; line-height: 1.6; }}
    .link-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      margin-top: 16px;
    }}
    a {{ color: #8f3911; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    code {{
      font-family: "JetBrains Mono", "Cascadia Code", monospace;
      background: #efe4d4;
      padding: 2px 6px;
      border-radius: 6px;
    }}
  </style>
</head>
<body>
  <main>
    <section class="panel">
      <h1>Interest Removed</h1>
      <p><code>{html.escape(str(interest.get("interest_name") or "-"))}</code> was moved out of the active set.</p>
      <p>The linked target was deactivated, and any active matches/signals attached to it were marked inactive so the dashboard stays honest.</p>
      <p>Remaining active interests <strong>{html.escape(str(summary.get("active_interest_count") or 0))}</strong> | active targets <strong>{html.escape(str(summary.get("active_target_count") or 0))}</strong> | removed at <code>{html.escape(str(payload.get("deleted_at") or "-"))}</code></p>
      <div class="link-row">
        <a href="/interests/new?user_id={quote(user_id)}">Add another interest</a>
        <a href="/interests?user_id={quote(user_id)}">Back to interests</a>
        <a href="/?user_id={quote(user_id)}">Back to dashboard</a>
      </div>
    </section>
  </main>
</body>
</html>"""


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
    reports = report_entries(reports_dir)
    bundles = bundle_entries(exports_dir)
    user = profile_payload["user"]
    summary = profile_payload["summary"]
    signal_summary = signals_payload["summary"]
    interests = list(profile_payload["interests"])[:4]
    latest_cards_html = render_latest_dashboard_cards(reports_payload)
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
    ) or '<p class="empty-state">No opportunity groups available yet.</p>'
    interest_cards_html = "\n".join(render_interest_card(interest) for interest in interests) or '<p class="empty-state">No active interests found.</p>'
    report_rows = "\n".join(render_report_row(item) for item in reports_payload["reports"]) or '<p class="empty-state">No user-scoped reports found yet.</p>'
    shared_report_rows = "\n".join(render_report_row(item) for item in reports_payload["shared_reports"]) or '<p class="empty-state">No shared daily reports found yet.</p>'
    bundle_rows = "\n".join(render_bundle_row(item) for item in bundles) or '<p class="empty-state">No bundles found yet.</p>'
    digest_preview = render_digest_preview(str(digest_payload["markdown"]))
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Collector Dashboard</title>
  <style>
    :root {{
      --bg: #f4ede1;
      --panel: rgba(255, 250, 244, 0.88);
      --panel-strong: #fff9f0;
      --border: #decaae;
      --ink: #1d2128;
      --muted: #706658;
      --accent: #8f3911;
      --accent-soft: #f1e0cb;
      --accent-deep: #4e2513;
      --shadow: 0 24px 60px rgba(91, 58, 20, 0.09);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      font-family: "Avenir Next", "Segoe UI Variable", "Trebuchet MS", sans-serif;
      margin: 0;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(188, 121, 48, 0.18), transparent 22%),
        radial-gradient(circle at 80% 10%, rgba(124, 86, 43, 0.1), transparent 20%),
        linear-gradient(180deg, #f8f2ea 0%, var(--bg) 100%);
    }}
    main {{ max-width: 1120px; margin: 0 auto; padding: 36px 20px 60px; }}
    h1, h2, h3 {{ margin: 0 0 12px; }}
    nav {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-bottom: 18px;
    }}
    nav a {{
      padding: 8px 12px;
      border: 1px solid var(--border);
      border-radius: 999px;
      background: rgba(255, 250, 244, 0.78);
      color: var(--muted);
      font-size: 0.92rem;
    }}
    .hero {{
      background: linear-gradient(135deg, rgba(255, 247, 236, 0.98), rgba(241, 223, 195, 0.9));
      border: 1px solid var(--border);
      border-radius: 30px;
      padding: 30px;
      box-shadow: var(--shadow);
      margin-bottom: 24px;
    }}
    .hero h1 {{
      font-family: Georgia, "Times New Roman", serif;
      font-size: clamp(2.3rem, 4vw, 3.6rem);
      letter-spacing: -0.04em;
    }}
    .hero p {{
      color: var(--muted);
      max-width: 760px;
      font-size: 1.08rem;
      line-height: 1.6;
    }}
    .eyebrow {{
      text-transform: uppercase;
      letter-spacing: 0.12em;
      font-size: 0.78rem;
      color: var(--muted);
    }}
    .hero-grid {{
      display: grid;
      grid-template-columns: 1.4fr 0.9fr;
      gap: 18px;
      align-items: end;
    }}
    .hero-side {{
      background: rgba(255, 250, 244, 0.66);
      border: 1px solid var(--border);
      border-radius: 22px;
      padding: 18px;
    }}
    .hero-side h3 {{
      font-family: Georgia, "Times New Roman", serif;
      margin-bottom: 8px;
    }}
    .chip-row {{ display: flex; flex-wrap: wrap; gap: 10px; margin-top: 20px; }}
    .chip {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      border-radius: 999px;
      padding: 9px 14px;
      background: var(--panel-strong);
      border: 1px solid var(--border);
      color: var(--muted);
      font-size: 0.96rem;
    }}
    .summary-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 14px;
      margin: 0 0 24px;
    }}
    .summary-card {{
      background: var(--panel-strong);
      border: 1px solid var(--border);
      border-radius: 22px;
      padding: 18px;
      box-shadow: var(--shadow);
    }}
    .summary-card strong {{
      display: block;
      font-size: 2rem;
      font-family: Georgia, "Times New Roman", serif;
      color: var(--accent-deep);
      margin-top: 8px;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 14px;
      margin-bottom: 24px;
    }}
    .latest-card {{
      display: flex;
      flex-direction: column;
      gap: 8px;
      padding: 18px;
      background: var(--panel-strong);
      border: 1px solid var(--border);
      border-radius: 22px;
      box-shadow: var(--shadow);
      min-height: 148px;
    }}
    .eyebrow {{
      text-transform: uppercase;
      letter-spacing: 0.1em;
      font-size: 0.75rem;
      color: var(--muted);
    }}
    .latest-card strong {{ font-size: 1.1rem; line-height: 1.3; }}
    .latest-card .meta {{ margin-top: auto; color: var(--muted); font-size: 0.92rem; }}
    .section {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 28px;
      padding: 24px;
      margin-bottom: 22px;
      box-shadow: var(--shadow);
      backdrop-filter: blur(10px);
    }}
    .section-header {{
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      gap: 12px;
      margin-bottom: 18px;
    }}
    .section-header p {{ margin: 0; color: var(--muted); }}
    .report-list, .bundle-list {{
      display: grid;
      gap: 12px;
    }}
    .report-row, .bundle-row {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 14px;
      align-items: center;
      background: var(--panel-strong);
      border: 1px solid var(--border);
      border-radius: 18px;
      padding: 16px 18px;
    }}
    .report-row h3, .bundle-row h3 {{ margin: 0 0 6px; font-size: 1.05rem; }}
    .report-row p, .bundle-row p {{ margin: 0; color: var(--muted); line-height: 1.5; }}
    .meta-stack {{
      display: flex;
      flex-direction: column;
      align-items: flex-end;
      gap: 8px;
      color: var(--muted);
      font-size: 0.92rem;
    }}
    .meta-stack .link-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      justify-content: flex-end;
    }}
    .digest-card {{
      background: linear-gradient(180deg, rgba(255, 249, 239, 0.95), rgba(249, 239, 225, 0.92));
      border: 1px solid var(--border);
      border-radius: 24px;
      padding: 22px;
      box-shadow: var(--shadow);
      display: grid;
      gap: 14px;
    }}
    .digest-card p {{
      margin: 0;
      color: var(--muted);
      line-height: 1.7;
    }}
    .digest-meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
    }}
    .interest-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 14px;
    }}
    .interest-card {{
      background: var(--panel-strong);
      border: 1px solid var(--border);
      border-radius: 22px;
      padding: 18px;
      box-shadow: var(--shadow);
    }}
    .interest-card p {{
      margin: 8px 0 0;
      color: var(--muted);
      line-height: 1.55;
    }}
    .signal-summary-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      margin-bottom: 18px;
    }}
    .signal-summary-card {{
      background: var(--panel-strong);
      border: 1px solid var(--border);
      border-radius: 20px;
      padding: 16px 18px;
    }}
    .signal-summary-card strong {{
      display: block;
      font-size: 1.6rem;
      font-family: Georgia, "Times New Roman", serif;
      color: var(--accent-deep);
      margin-top: 8px;
    }}
    .signal-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 14px;
      margin-bottom: 18px;
    }}
    .signal-card {{
      background: var(--panel-strong);
      border: 1px solid var(--border);
      border-radius: 22px;
      padding: 18px;
      box-shadow: var(--shadow);
      display: grid;
      gap: 10px;
    }}
    .signal-card h3 {{
      margin: 0;
      font-size: 1.08rem;
      line-height: 1.35;
    }}
    .signal-card p {{
      margin: 0;
      color: var(--muted);
      line-height: 1.55;
    }}
    .signal-meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }}
    .signal-note {{
      font-size: 0.94rem;
      color: var(--muted);
    }}
    .signal-links {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 4px;
    }}
    .signal-links a {{
      font-size: 0.94rem;
    }}
    .signal-interest-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 14px;
    }}
    .signal-interest-card {{
      background: rgba(255, 250, 244, 0.72);
      border: 1px solid var(--border);
      border-radius: 20px;
      padding: 18px;
      display: grid;
      gap: 8px;
    }}
    .signal-interest-card h3 {{
      margin: 0;
      font-size: 1.04rem;
    }}
    .mini-list {{
      margin: 0;
      padding-left: 18px;
      color: var(--muted);
      display: grid;
      gap: 6px;
    }}
    .pill {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      border-radius: 999px;
      padding: 6px 10px;
      background: var(--accent-soft);
      color: var(--accent);
      font-size: 0.82rem;
      font-weight: 600;
    }}
    a {{ color: var(--accent); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    code {{
      font-family: "JetBrains Mono", "Cascadia Code", monospace;
      background: #efe4d4;
      padding: 2px 6px;
      border-radius: 6px;
    }}
    .empty-state {{ color: var(--muted); margin: 0; }}
    @media (max-width: 720px) {{
      .hero-grid {{
        grid-template-columns: 1fr;
      }}
      .report-row, .bundle-row {{
        grid-template-columns: 1fr;
      }}
      .meta-stack {{
        align-items: flex-start;
      }}
      .meta-stack .link-row {{
        justify-content: flex-start;
      }}
    }}
  </style>
</head>
<body>
  <main>
    <nav>
      <a href="#overview">Overview</a>
      <a href="/actions?user_id={quote(user_id)}">Actions</a>
      <a href="#signals">Signals</a>
      <a href="/interests?user_id={quote(user_id)}">Interests</a>
      <a href="/matches?user_id={quote(user_id)}">Opportunities</a>
      <a href="#digest">Digest</a>
      <a href="#reports">Reports</a>
      <a href="#api">API</a>
    </nav>
    <section class="hero" id="overview">
      <div class="hero-grid">
        <div>
          <span class="eyebrow">Collector Dashboard</span>
          <h1>{html.escape(str(user["display_name"]))}</h1>
          <p>Track live collectible opportunities, signals, and daily digest summaries from the same always-on Render service that runs sync, matching, and report generation.</p>
          <div class="chip-row">
            <span class="chip">User: <code>{html.escape(str(user["id"]))}</code></span>
            <span class="chip">Language: <code>{html.escape(str(user["language"]))}</code></span>
            <span class="chip">Timezone: <code>{html.escape(str(user["timezone"]))}</code></span>
            <span class="chip">Health: <a href="/healthz"><code>/healthz</code></a></span>
          </div>
        </div>
        <aside class="hero-side">
          <h3>Latest Digest</h3>
          <p>{html.escape(str(digest_payload["report"]["timestamp_label"]))}</p>
          <p><a href="{html.escape(str(digest_payload["report"]["links"]["rendered"]))}">{html.escape(str(digest_payload["report"]["name"]))}</a></p>
          <p><a href="/api/users/{quote(user_id)}/digest/latest">Open digest API response</a></p>
        </aside>
      </div>
    </section>

    <section class="summary-grid" aria-label="Summary cards">
      <article class="summary-card">
        <span class="eyebrow">Active Interests</span>
        <strong>{summary["active_interest_count"]}</strong>
      </article>
      <article class="summary-card">
        <span class="eyebrow">Active Matches</span>
        <strong>{summary["active_match_count"]}</strong>
      </article>
      <article class="summary-card">
        <span class="eyebrow">Active Signals</span>
        <strong>{summary["active_signal_count"]}</strong>
      </article>
      <article class="summary-card">
        <span class="eyebrow">Tracked Holdings</span>
        <strong>{summary["active_holding_count"]}</strong>
      </article>
    </section>

    <section class="section" id="signals">
      <div class="section-header">
        <div>
          <h2>Signals Inbox</h2>
          <p>The most actionable active alerts, grouped from the live V2 signal engine rather than from report markdown.</p>
        </div>
      </div>
      <div class="signal-summary-grid">
        <article class="signal-summary-card">
          <span class="eyebrow">High urgency</span>
          <strong>{signal_summary["high_count"]}</strong>
        </article>
        <article class="signal-summary-card">
          <span class="eyebrow">Fresh in {lookback_hours}h</span>
          <strong>{signal_summary["recent_signal_count"]}</strong>
        </article>
        <article class="signal-summary-card">
          <span class="eyebrow">Event-driven</span>
          <strong>{signal_summary["event_signal_count"]}</strong>
        </article>
        <article class="signal-summary-card">
          <span class="eyebrow">Standing</span>
          <strong>{signal_summary["standing_signal_count"]}</strong>
        </article>
      </div>
      {signals_inbox_html}
    </section>

    <section class="section" id="digest">
      <div class="section-header">
        <div>
          <h2>Latest Digest & Snapshots</h2>
          <p>Start here if you want the fastest view of what changed recently for this collector.</p>
        </div>
      </div>
      <div class="digest-card">
        <div class="digest-meta">
          <span class="pill">{html.escape(str(digest_payload["report"]["label"]))}</span>
          <span class="pill">{html.escape(str(digest_payload["report"]["timestamp_label"]))}</span>
        </div>
        <div>{digest_preview}</div>
        <div class="chip-row">
          <span class="chip"><a href="{html.escape(str(digest_payload["report"]["links"]["rendered"]))}">Rendered digest</a></span>
          <span class="chip"><a href="{html.escape(str(digest_payload["report"]["links"]["raw"]))}">Raw markdown</a></span>
          <span class="chip"><a href="/api/users/{quote(user_id)}/digest/latest">Digest JSON</a></span>
        </div>
      </div>
      <div class="grid" style="margin-top: 18px;">{latest_cards_html}</div>
    </section>

    <section class="section" id="interests">
      <div class="section-header">
        <div>
          <h2>Priority Interests</h2>
          <p>The most important tracked interests, with signal policy and budget context.</p>
        </div>
        <a href="/interests?user_id={quote(user_id)}">Open full interests page</a>
      </div>
      <div class="interest-grid">{interest_cards_html}</div>
    </section>

    <section class="section">
      <div class="section-header">
        <div>
          <h2>Top Opportunities</h2>
          <p>Highest-priority grouped matches across live and preview inventory.</p>
        </div>
        <a href="/matches?user_id={quote(user_id)}">Open full opportunities page</a>
      </div>
      <div class="interest-grid">{opportunity_cards_html}</div>
    </section>

    <section class="section" id="reports">
      <div class="section-header">
        <div>
          <h2>User Reports</h2>
          <p>User-scoped report outputs first, then shared daily review artifacts.</p>
        </div>
      </div>
      <div class="report-list">{report_rows}</div>
      <div class="section-header" style="margin-top: 24px;">
        <div>
          <h3>Shared Daily Reports</h3>
          <p>Global review/index reports that still help explain system state.</p>
        </div>
      </div>
      <div class="report-list">{shared_report_rows}</div>
    </section>

    <section class="section">
      <div class="section-header">
        <div>
          <h2>Bundles</h2>
          <p>Zip exports you can download directly when you package reports on the server.</p>
        </div>
      </div>
      <div class="bundle-list">{bundle_rows}</div>
    </section>

    <section class="section" id="api">
      <div class="section-header">
        <div>
          <h2>Frontend API Hooks</h2>
          <p>These are the live JSON endpoints this dashboard is designed to evolve around.</p>
        </div>
      </div>
      <div class="report-list">
        <article class="report-row">
          <div>
            <span class="pill">Profile</span>
            <h3><a href="/api/users/{quote(user_id)}/profile">/api/users/{html.escape(user_id)}/profile</a></h3>
            <p>Interests, targets, holdings, signal policies, and top-level summary counts.</p>
          </div>
        </article>
        <article class="report-row">
          <div>
            <span class="pill">Interests</span>
            <h3><a href="/api/users/{quote(user_id)}/interests">/api/users/{html.escape(user_id)}/interests</a></h3>
            <p>Frontend-ready interest inventory with per-interest counts, target labels, holdings, and policy summaries.</p>
          </div>
        </article>
        <article class="report-row">
          <div>
            <span class="pill">Reports</span>
            <h3><a href="/api/users/{quote(user_id)}/reports">/api/users/{html.escape(user_id)}/reports</a></h3>
            <p>User-scoped report list plus latest digest/review metadata.</p>
          </div>
        </article>
        <article class="report-row">
          <div>
            <span class="pill">Matches</span>
            <h3><a href="/api/users/{quote(user_id)}/matches">/api/users/{html.escape(user_id)}/matches</a></h3>
            <p>Active match inventory, grouped opportunity clusters, relationship mix, and top candidates.</p>
          </div>
        </article>
        <article class="report-row">
          <div>
            <span class="pill">Signals</span>
            <h3><a href="/api/users/{quote(user_id)}/signals">/api/users/{html.escape(user_id)}/signals</a></h3>
            <p>Active signal inbox payload with urgency counts, grouped interest coverage, and top alerts.</p>
          </div>
        </article>
        <article class="report-row">
          <div>
            <span class="pill">Digest</span>
            <h3><a href="/api/users/{quote(user_id)}/digest/latest">/api/users/{html.escape(user_id)}/digest/latest</a></h3>
            <p>Latest digest metadata and markdown content for the collector.</p>
          </div>
        </article>
      </div>
    </section>
  </main>
</body>
</html>"""


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


def render_signals_inbox(
    signals_payload: dict[str, object],
    *,
    user_id: str,
    signal_review_metadata: object,
) -> str:
    top_signals = signals_payload.get("top_signals")
    interest_groups = signals_payload.get("interest_groups")
    signal_cards = "\n".join(
        render_signal_card(signal, user_id=user_id, signal_review_metadata=signal_review_metadata)
        for signal in (top_signals if isinstance(top_signals, list) else [])
        if isinstance(signal, dict)
    ) or '<p class="empty-state">No active signals available yet.</p>'
    group_cards = "\n".join(
        render_signal_interest_group_card(group)
        for group in (interest_groups[:4] if isinstance(interest_groups, list) else [])
        if isinstance(group, dict)
    ) or '<p class="empty-state">No signal coverage groups available yet.</p>'
    return f"""
    <div class="signal-grid">{signal_cards}</div>
    <div class="section-header" style="margin-top: 4px;">
      <div>
        <h3>Signal Coverage By Interest</h3>
        <p>Which interests currently hold the most active signal pressure.</p>
      </div>
    </div>
    <div class="signal-interest-grid">{group_cards}</div>
    """


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
    ) or '<p class="empty-state">No active interest kinds found yet.</p>'
    interest_cards_html = "\n".join(
        render_interest_detail_card(interest, user_id=user_id)
        for interest in interests
        if isinstance(interest, dict)
    ) or '<p class="empty-state">No active interests found yet.</p>'

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Interest Management</title>
  <style>
    :root {{
      --bg: #f4ede1;
      --panel: rgba(255, 250, 244, 0.88);
      --panel-strong: #fff9f0;
      --border: #decaae;
      --ink: #1d2128;
      --muted: #706658;
      --accent: #8f3911;
      --accent-soft: #f1e0cb;
      --accent-deep: #4e2513;
      --shadow: 0 24px 60px rgba(91, 58, 20, 0.09);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      font-family: "Avenir Next", "Segoe UI Variable", "Trebuchet MS", sans-serif;
      margin: 0;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(188, 121, 48, 0.18), transparent 22%),
        radial-gradient(circle at 80% 10%, rgba(124, 86, 43, 0.1), transparent 20%),
        linear-gradient(180deg, #f8f2ea 0%, var(--bg) 100%);
    }}
    main {{ max-width: 1120px; margin: 0 auto; padding: 36px 20px 60px; }}
    nav {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-bottom: 18px;
    }}
    nav a {{
      padding: 8px 12px;
      border: 1px solid var(--border);
      border-radius: 999px;
      background: rgba(255, 250, 244, 0.78);
      color: var(--muted);
      font-size: 0.92rem;
      text-decoration: none;
    }}
    .hero, .section {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 28px;
      padding: 24px;
      margin-bottom: 22px;
      box-shadow: var(--shadow);
    }}
    .hero {{
      background: linear-gradient(135deg, rgba(255, 247, 236, 0.98), rgba(241, 223, 195, 0.9));
    }}
    .hero h1 {{
      font-family: Georgia, "Times New Roman", serif;
      font-size: clamp(2.1rem, 4vw, 3.3rem);
      letter-spacing: -0.04em;
      margin: 0 0 10px;
    }}
    .hero p, .section p {{
      color: var(--muted);
      line-height: 1.6;
    }}
    .eyebrow {{
      text-transform: uppercase;
      letter-spacing: 0.12em;
      font-size: 0.78rem;
      color: var(--muted);
    }}
    .chip-row, .detail-row, .meta-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 16px;
    }}
    .chip, .pill {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      border-radius: 999px;
      padding: 7px 11px;
      background: var(--accent-soft);
      color: var(--accent);
      font-size: 0.84rem;
      font-weight: 600;
      border: 1px solid var(--border);
    }}
    .summary-grid, .interest-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 14px;
    }}
    .interest-grid {{
      grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
    }}
    .summary-card, .interest-detail-card {{
      background: var(--panel-strong);
      border: 1px solid var(--border);
      border-radius: 22px;
      padding: 18px;
      box-shadow: var(--shadow);
    }}
    .summary-card strong {{
      display: block;
      font-size: 1.9rem;
      font-family: Georgia, "Times New Roman", serif;
      color: var(--accent-deep);
      margin-top: 8px;
    }}
    .section-header {{
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      gap: 12px;
      margin-bottom: 18px;
    }}
    .interest-detail-card h3 {{
      margin: 0;
      font-size: 1.18rem;
      line-height: 1.3;
    }}
    .interest-detail-card p {{
      margin: 8px 0 0;
      color: var(--muted);
      line-height: 1.55;
    }}
    .stack {{
      display: grid;
      gap: 10px;
      margin-top: 14px;
    }}
    .hero-actions, .detail-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      margin-top: 16px;
      align-items: center;
    }}
    .subpanel {{
      background: rgba(255, 250, 244, 0.76);
      border: 1px solid var(--border);
      border-radius: 18px;
      padding: 14px;
    }}
    .subpanel h4 {{
      margin: 0 0 8px;
      font-size: 0.98rem;
      color: var(--accent-deep);
    }}
    ul {{
      margin: 0;
      padding-left: 18px;
      color: var(--muted);
      display: grid;
      gap: 6px;
    }}
    code {{
      font-family: "JetBrains Mono", "Cascadia Code", monospace;
      background: #efe4d4;
      padding: 2px 6px;
      border-radius: 6px;
    }}
    a {{ color: var(--accent); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .empty-state {{ color: var(--muted); margin: 0; }}
    .inline-form {{
      margin: 0;
    }}
  </style>
</head>
<body>
  <main>
    <nav>
      <a href="/?user_id={quote(user_id)}">Dashboard</a>
      <a href="/actions?user_id={quote(user_id)}">Actions</a>
      <a href="/interests?user_id={quote(user_id)}">Interests</a>
      <a href="/matches?user_id={quote(user_id)}">Opportunities</a>
      <a href="/api/users/{quote(user_id)}/interests">Interests JSON</a>
      <a href="/api/users/{quote(user_id)}/profile">Profile JSON</a>
    </nav>
    <section class="hero">
      <span class="eyebrow">Interest Management</span>
      <h1>{html.escape(str(user["display_name"]))}</h1>
      <p>Inspect the collector's active interests, targets, holdings, signal policies, and the current operational pressure around each idea.</p>
      <div class="chip-row">
        <span class="chip">User <code>{html.escape(str(user["id"]))}</code></span>
        <span class="chip">Language <code>{html.escape(str(user["language"]))}</code></span>
        <span class="chip">Timezone <code>{html.escape(str(user["timezone"]))}</code></span>
      </div>
      <div class="hero-actions">
        <a class="action-button" href="/interests/new?user_id={quote(user_id)}">Add interest</a>
        <a href="/actions?user_id={quote(user_id)}">Open actions</a>
      </div>
    </section>
    <section class="summary-grid">
      <article class="summary-card"><span class="eyebrow">Active Interests</span><strong>{summary.get("active_interest_count", 0)}</strong></article>
      <article class="summary-card"><span class="eyebrow">Active Targets</span><strong>{summary.get("active_target_count", 0)}</strong></article>
      <article class="summary-card"><span class="eyebrow">Tracked Holdings</span><strong>{summary.get("active_holding_count", 0)}</strong></article>
      <article class="summary-card"><span class="eyebrow">High Priority</span><strong>{summary.get("high_priority_count", 0)}</strong></article>
      <article class="summary-card"><span class="eyebrow">Immediate Delivery</span><strong>{summary.get("immediate_policy_count", 0)}</strong></article>
      <article class="summary-card"><span class="eyebrow">Interests With Holdings</span><strong>{summary.get("interests_with_holdings", 0)}</strong></article>
    </section>
    <section class="section">
      <div class="section-header">
        <div>
          <h2>Interest Mix</h2>
          <p>How this collector's active interests are distributed by kind.</p>
        </div>
      </div>
      <div class="summary-grid">{kind_cards_html}</div>
    </section>
    <section class="section">
      <div class="section-header">
        <div>
          <h2>All Active Interests</h2>
          <p>Each card includes the current target, policy, holdings, and live match/signal counts.</p>
        </div>
        <a class="action-button" href="/interests/new?user_id={quote(user_id)}">Add interest</a>
      </div>
      <div class="interest-grid">{interest_cards_html}</div>
    </section>
  </main>
</body>
</html>"""


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
    ) or '<p class="empty-state">No active matches found yet.</p>'
    group_cards_html = "\n".join(
        render_opportunity_group_card(group, user_id=user_id)
        for group in groups
        if isinstance(group, dict)
    ) or '<p class="empty-state">No grouped opportunities found yet.</p>'
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Matches & Opportunities</title>
  <style>
    :root {{
      --bg: #f4ede1;
      --panel: rgba(255, 250, 244, 0.88);
      --panel-strong: #fff9f0;
      --border: #decaae;
      --ink: #1d2128;
      --muted: #706658;
      --accent: #8f3911;
      --accent-soft: #f1e0cb;
      --accent-deep: #4e2513;
      --shadow: 0 24px 60px rgba(91, 58, 20, 0.09);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      font-family: "Avenir Next", "Segoe UI Variable", "Trebuchet MS", sans-serif;
      margin: 0;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(188, 121, 48, 0.18), transparent 22%),
        radial-gradient(circle at 80% 10%, rgba(124, 86, 43, 0.1), transparent 20%),
        linear-gradient(180deg, #f8f2ea 0%, var(--bg) 100%);
    }}
    main {{ max-width: 1120px; margin: 0 auto; padding: 36px 20px 60px; }}
    nav {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-bottom: 18px;
    }}
    nav a {{
      padding: 8px 12px;
      border: 1px solid var(--border);
      border-radius: 999px;
      background: rgba(255, 250, 244, 0.78);
      color: var(--muted);
      font-size: 0.92rem;
      text-decoration: none;
    }}
    .hero, .section {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 28px;
      padding: 24px;
      margin-bottom: 22px;
      box-shadow: var(--shadow);
    }}
    .hero {{
      background: linear-gradient(135deg, rgba(255, 247, 236, 0.98), rgba(241, 223, 195, 0.9));
    }}
    .hero h1 {{
      font-family: Georgia, "Times New Roman", serif;
      font-size: clamp(2.1rem, 4vw, 3.3rem);
      letter-spacing: -0.04em;
      margin: 0 0 10px;
    }}
    .hero p, .section p {{
      color: var(--muted);
      line-height: 1.6;
    }}
    .eyebrow {{
      text-transform: uppercase;
      letter-spacing: 0.12em;
      font-size: 0.78rem;
      color: var(--muted);
    }}
    .chip-row, .meta-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 16px;
    }}
    .chip, .pill {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      border-radius: 999px;
      padding: 7px 11px;
      background: var(--accent-soft);
      color: var(--accent);
      font-size: 0.84rem;
      font-weight: 600;
      border: 1px solid var(--border);
    }}
    .summary-grid, .card-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 14px;
    }}
    .summary-card, .match-card, .opportunity-card {{
      background: var(--panel-strong);
      border: 1px solid var(--border);
      border-radius: 22px;
      padding: 18px;
      box-shadow: var(--shadow);
    }}
    .summary-card strong {{
      display: block;
      font-size: 1.9rem;
      font-family: Georgia, "Times New Roman", serif;
      color: var(--accent-deep);
      margin-top: 8px;
    }}
    .section-header {{
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      gap: 12px;
      margin-bottom: 18px;
    }}
    .match-card h3, .opportunity-card h3 {{
      margin: 0;
      font-size: 1.08rem;
      line-height: 1.35;
    }}
    .match-card p, .opportunity-card p {{
      margin: 8px 0 0;
      color: var(--muted);
      line-height: 1.55;
    }}
    a {{ color: var(--accent); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .empty-state {{ color: var(--muted); margin: 0; }}
  </style>
</head>
<body>
  <main>
    <nav>
      <a href="/?user_id={quote(user_id)}">Dashboard</a>
      <a href="/actions?user_id={quote(user_id)}">Actions</a>
      <a href="/matches?user_id={quote(user_id)}">Opportunities</a>
      <a href="/api/users/{quote(user_id)}/matches">Matches JSON</a>
      <a href="/api/users/{quote(user_id)}/matching/run">Matching action</a>
    </nav>
    <section class="hero">
      <span class="eyebrow">Matches & Opportunities</span>
      <h1>{html.escape(str(user["display_name"]))}</h1>
      <p>Review the active matched inventory for this collector, grouped into opportunity clusters by relationship strength and listing status.</p>
      <div class="chip-row">
        <span class="chip">User <strong>{html.escape(str(user["id"]))}</strong></span>
        <span class="chip">Language <strong>{html.escape(str(user["language"]))}</strong></span>
        <span class="chip">Timezone <strong>{html.escape(str(user["timezone"]))}</strong></span>
      </div>
    </section>
    <section class="summary-grid">
      <article class="summary-card"><span class="eyebrow">Active Matches</span><strong>{summary["active_match_count"]}</strong></article>
      <article class="summary-card"><span class="eyebrow">High Score</span><strong>{summary["high_score_count"]}</strong></article>
      <article class="summary-card"><span class="eyebrow">Live</span><strong>{summary["live_count"]}</strong></article>
      <article class="summary-card"><span class="eyebrow">Preview</span><strong>{summary["preview_count"]}</strong></article>
      <article class="summary-card"><span class="eyebrow">Exact</span><strong>{summary["exact_count"]}</strong></article>
      <article class="summary-card"><span class="eyebrow">Groups</span><strong>{summary["opportunity_group_count"]}</strong></article>
    </section>
    <section class="section">
      <div class="section-header">
        <div>
          <h2>Opportunity Groups</h2>
          <p>Grouped by interest, relationship type, listing status, and listing title so repeated inventory reads like one opportunity cluster.</p>
        </div>
      </div>
      <div class="card-grid">{group_cards_html}</div>
    </section>
    <section class="section">
      <div class="section-header">
        <div>
          <h2>Top Matches</h2>
          <p>Highest-scoring current candidates across all active interests.</p>
        </div>
      </div>
      <div class="card-grid">{match_cards_html}</div>
    </section>
  </main>
</body>
</html>"""


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
    links = [f'<a href="/api/users/{quote(user_id)}/signals">Signals JSON</a>']
    if latest_review_link:
        links.append(f'<a href="{html.escape(str(latest_review_link))}">Latest signal review</a>')
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
      <div class="signal-links">{''.join(links)}</div>
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
    items_html = "".join(items) or "<li>No active signals.</li>"
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
      <p><a href="/api/users/{quote(user_id)}/matches">Open matches JSON</a></p>
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
      <p><a href="/api/users/{quote(user_id)}/matches">Open matches JSON</a></p>
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
    holding_html = "".join(holding_items) or "<li>No linked holdings.</li>"

    policy_bits = [
        f"delivery <strong>{html.escape(str(policy.get('delivery_mode') or '-'))}</strong>",
        f"cooldown <strong>{html.escape(str(policy.get('cooldown_hours') or '-'))}h</strong>",
        f"min score <strong>{html.escape(str(policy.get('min_match_score') or '-'))}</strong>",
        f"signals/day <strong>{html.escape(str(policy.get('max_signals_per_day') or '-'))}</strong>",
    ]
    note_html = f"<p>{html.escape(notes)}</p>" if notes else "<p class=\"empty-state\">No operator notes attached.</p>"

    return f"""
    <article class="interest-detail-card">
      <div class="meta-row">
        <span class="pill">{html.escape(str(interest.get("interest_kind") or "-"))}</span>
        <span class="pill">{html.escape(str(interest.get("scope_kind") or "-"))}</span>
        <span class="pill">{html.escape(str(interest.get("precision_mode") or "-"))}</span>
        <span class="pill">{html.escape(str(interest.get("interest_priority") or "-"))}</span>
      </div>
      <h3>{html.escape(str(interest.get("interest_name") or "-"))}</h3>
      <p>Signals <strong>{html.escape(str(summary.get("active_signal_count") or 0))}</strong> | matches <strong>{html.escape(str(summary.get("active_match_count") or 0))}</strong> | targets <strong>{html.escape(str(summary.get("active_target_count") or 0))}</strong> | holdings <strong>{html.escape(str(summary.get("active_holding_count") or 0))}</strong></p>
      <div class="stack">
        <section class="subpanel">
          <h4>Target Setup</h4>
          <ul>{target_html}</ul>
        </section>
        <section class="subpanel">
          <h4>Holdings</h4>
          <ul>{holding_html}</ul>
        </section>
        <section class="subpanel">
          <h4>Signal Policy</h4>
          <p>{" | ".join(policy_bits)}</p>
          <p>notify preview <strong>{html.escape(str(policy.get("notify_on_preview") or 0))}</strong> | live <strong>{html.escape(str(policy.get("notify_on_live") or 0))}</strong> | ended <strong>{html.escape(str(policy.get("notify_on_ended") or 0))}</strong></p>
          <p>exact <strong>{html.escape(str(policy.get("notify_on_exact_match") or 0))}</strong> | variant <strong>{html.escape(str(policy.get("notify_on_variant_match") or 0))}</strong> | series <strong>{html.escape(str(policy.get("notify_on_series_match") or 0))}</strong></p>
        </section>
        <section class="subpanel">
          <h4>Operator Notes</h4>
          {note_html}
        </section>
      </div>
      <div class="detail-row">
        <a href="/interests/edit?user_id={quote(user_id)}&interest_id={quote(str(interest.get('id') or ''))}">Edit settings</a>
        <a href="/api/users/{quote(user_id)}/interests">Interests JSON</a>
        <a href="/api/users/{quote(user_id)}/signals">Signals JSON</a>
        <a href="/api/users/{quote(user_id)}/matches">Matches JSON</a>
        <a href="/matches?user_id={quote(user_id)}">Open opportunities</a>
        <form class="inline-form" method="post" action="/interests/delete" onsubmit="return confirm('Deactivate this interest and hide its active matches/signals?');">
          <input type="hidden" name="user_id" value="{html.escape(user_id)}">
          <input type="hidden" name="interest_id" value="{html.escape(str(interest.get('id') or ''))}">
          <button class="danger-button" type="submit">Delete interest</button>
        </form>
      </div>
    </article>
    """


def render_digest_preview(markdown: str) -> str:
    preview_lines: list[str] = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped or stripped == "# V2 Interest Daily Digest":
            continue
        preview_lines.append(stripped)
        if len(preview_lines) >= 6:
            break
    if not preview_lines:
        return '<p class="empty-state">No digest summary available yet.</p>'
    preview_html = "".join(f"<p>{render_inline_markdown(line)}</p>" for line in preview_lines)
    return preview_html


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
        link_html += f'<div><a href="{html.escape(str(rendered))}">Open rendered</a></div>'
    if raw:
        link_html += f'<div><a href="{html.escape(str(raw))}">Open raw</a></div>'
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


def render_markdown_html(text: str) -> str:
    lines = text.splitlines()
    blocks: list[str] = []
    paragraph_lines: list[str] = []
    list_items: list[str] = []

    def flush_paragraph() -> None:
        nonlocal paragraph_lines
        if paragraph_lines:
            joined = " ".join(line.strip() for line in paragraph_lines if line.strip())
            blocks.append(f"<p>{render_inline_markdown(joined)}</p>")
            paragraph_lines = []

    def flush_list() -> None:
        nonlocal list_items
        if list_items:
            items_html = "".join(f"<li>{render_inline_markdown(item)}</li>" for item in list_items)
            blocks.append(f"<ul>{items_html}</ul>")
            list_items = []

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
        if stripped.startswith("- "):
            flush_paragraph()
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
    rendered = render_markdown_html(path.read_text(encoding="utf-8"))
    metadata = classify_report(path.name)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(path.name)}</title>
  <style>
    :root {{
      --bg: #f4efe6;
      --panel: rgba(255, 250, 243, 0.92);
      --border: #dfcfb5;
      --ink: #21242a;
      --muted: #675d52;
      --accent: #8d3a12;
      --shadow: 0 24px 60px rgba(97, 67, 33, 0.08);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      font-family: "Avenir Next", "Segoe UI Variable", "Trebuchet MS", sans-serif;
      margin: 0;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(181, 118, 52, 0.13), transparent 30%),
        linear-gradient(180deg, #f7f2ea 0%, var(--bg) 100%);
    }}
    main {{ max-width: 980px; margin: 0 auto; padding: 30px 20px 60px; }}
    .topbar {{
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      align-items: center;
      margin-bottom: 18px;
      color: var(--muted);
    }}
    a {{ color: var(--accent); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .hero {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 28px;
      padding: 24px;
      box-shadow: var(--shadow);
      margin-bottom: 20px;
    }}
    .hero h1 {{
      font-family: Georgia, "Times New Roman", serif;
      font-size: clamp(2rem, 3.6vw, 3rem);
      margin: 8px 0 10px;
      letter-spacing: -0.04em;
    }}
    .eyebrow {{
      text-transform: uppercase;
      letter-spacing: 0.1em;
      color: var(--muted);
      font-size: 0.78rem;
    }}
    .meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 16px;
    }}
    .meta span {{
      padding: 8px 12px;
      border-radius: 999px;
      border: 1px solid var(--border);
      background: #fff9ef;
      color: var(--muted);
      font-size: 0.92rem;
    }}
    .content {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 28px;
      padding: 26px;
      box-shadow: var(--shadow);
    }}
    .content h1, .content h2, .content h3 {{
      font-family: Georgia, "Times New Roman", serif;
      line-height: 1.15;
      margin: 1.4em 0 0.55em;
    }}
    .content h1:first-child {{ margin-top: 0; }}
    .content p, .content li {{
      line-height: 1.72;
      font-size: 1.03rem;
    }}
    .content ul {{ padding-left: 1.3rem; }}
    .content hr {{
      border: 0;
      border-top: 1px solid var(--border);
      margin: 26px 0;
    }}
    code {{
      font-family: "JetBrains Mono", "Cascadia Code", monospace;
      background: #efe4d4;
      padding: 0.1em 0.35em;
      border-radius: 6px;
      font-size: 0.92em;
    }}
    pre {{
      white-space: pre-wrap;
      overflow-x: auto;
      background: #fff9ef;
      border: 1px solid var(--border);
      border-radius: 18px;
      padding: 16px;
    }}
  </style>
</head>
<body>
  <main>
    <div class="topbar">
      <a href="/">Back to report index</a>
      <span>|</span>
      <a href="/raw/{quote(path.name)}">Raw markdown</a>
    </div>
    <section class="hero">
      <span class="eyebrow">{html.escape(metadata["label"])}</span>
      <h1>{html.escape(path.name)}</h1>
      <div class="meta">
        <span>{html.escape(metadata["scope"])}</span>
        <span>{html.escape(metadata["timestamp_label"])}</span>
      </div>
    </section>
    <section class="content">
      {rendered}
    </section>
  </main>
</body>
</html>"""


def render_error_html(message: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Not Found</title>
</head>
<body>
  <main>
    <p>{html.escape(message)}</p>
    <p><a href="/">Back to report index</a></p>
  </main>
</body>
</html>"""


if __name__ == "__main__":
    raise SystemExit(main())
