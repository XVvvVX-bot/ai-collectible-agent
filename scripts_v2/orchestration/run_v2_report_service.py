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
from datetime import datetime
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
            "/healthz",
            "/api/reports",
            "/api/users/<user_id>/profile",
            "/api/users/<user_id>/reports",
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
            user_route = match_user_api_route(path)
            if user_route is not None:
                user_id, action = user_route
                self._handle_user_api_get(user_id=user_id, action=action, query=parse_qs(parsed.query))
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
                if action == "reports":
                    payload = load_user_reports_payload(reports_dir, user_id=user_id)
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
      <a href="#signals">Signals</a>
      <a href="#digest">Digest</a>
      <a href="#interests">Interests</a>
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
      </div>
      <div class="interest-grid">{interest_cards_html}</div>
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
            <span class="pill">Reports</span>
            <h3><a href="/api/users/{quote(user_id)}/reports">/api/users/{html.escape(user_id)}/reports</a></h3>
            <p>User-scoped report list plus latest digest/review metadata.</p>
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
