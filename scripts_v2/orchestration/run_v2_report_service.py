#!/usr/bin/env python3
"""Serve V2 reports over HTTP while the background loop keeps running."""

from __future__ import annotations

import argparse
import html
import json
import os
import sys
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Event, Thread
from urllib.parse import quote, unquote

ROOT_DIR = Path(__file__).resolve().parents[2]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ai_agent_v2.ingestion.live_incremental import DEFAULT_STATE_SOURCE_KEY
from ai_agent_v2.runtime_host import BackgroundServiceRunner, DEFAULT_BASE_URL, build_service_config, emit_json


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

    handler_class = build_handler(runtime_root=Path(config.runtime_paths.runtime_root), reports_dir=Path(config.runtime_paths.output_dir))
    server = ThreadingHTTPServer((args.host, args.port), handler_class)
    emit_json(
        "report_service_started",
        host=args.host,
        port=args.port,
        runtime=runner.start_event()["runtime"],
        routes=["/", "/healthz", "/api/reports", "/reports/<name>", "/raw/<name>", "/downloads/<name>"],
    )
    try:
        server.serve_forever()
    finally:
        stop_event.set()
        server.server_close()
    return 0


def build_handler(*, runtime_root: Path, reports_dir: Path):
    exports_dir = runtime_root / "exports"

    class ReportHandler(BaseHTTPRequestHandler):
        server_version = "AIAgentReportServer/1.0"

        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            if path == "/healthz":
                self._write_json(HTTPStatus.OK, {"ok": True, "reports_dir": str(reports_dir), "exports_dir": str(exports_dir)})
                return
            if path == "/api/reports":
                self._write_json(HTTPStatus.OK, {"reports": report_entries(reports_dir), "bundles": bundle_entries(exports_dir)})
                return
            if path == "/":
                self._write_html(HTTPStatus.OK, render_index_html(reports_dir=reports_dir, exports_dir=exports_dir))
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

        def log_message(self, format: str, *args) -> None:  # noqa: A003
            return

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
        entries.append(
            {
                "name": path.name,
                "size_bytes": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
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


def safe_child(parent: Path, name: str) -> Path | None:
    candidate = (parent / name).resolve()
    try:
        candidate.relative_to(parent.resolve())
    except ValueError:
        return None
    return candidate


def render_index_html(*, reports_dir: Path, exports_dir: Path) -> str:
    reports = report_entries(reports_dir)
    bundles = bundle_entries(exports_dir)
    report_items = "\n".join(
        (
            f'<li><a href="/reports/{quote(item["name"])}">{html.escape(str(item["name"]))}</a> '
            f'(<a href="/raw/{quote(item["name"])}">raw</a>) '
            f'<span>{html.escape(str(item["modified_at"]))}</span></li>'
        )
        for item in reports
    ) or "<li>No reports found.</li>"
    bundle_items = "\n".join(
        (
            f'<li><a href="/downloads/{quote(item["name"])}">{html.escape(str(item["name"]))}</a> '
            f'<span>{html.escape(str(item["modified_at"]))}</span></li>'
        )
        for item in bundles
    ) or "<li>No bundles found yet.</li>"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AI Agent V2 Reports</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 0; background: #f7f5ef; color: #222; }}
    main {{ max-width: 980px; margin: 0 auto; padding: 32px 20px 48px; }}
    h1, h2 {{ margin-bottom: 12px; }}
    .card {{ background: #fffdf8; border: 1px solid #e8dfcf; border-radius: 16px; padding: 20px; margin-bottom: 20px; }}
    a {{ color: #8a3b12; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    li {{ margin: 8px 0; }}
    span {{ color: #666; font-size: 0.92rem; }}
    code {{ background: #f0eadc; padding: 2px 6px; border-radius: 6px; }}
  </style>
</head>
<body>
  <main>
    <h1>AI Agent V2 Reports</h1>
    <div class="card">
      <p>Browse the markdown reports generated on the Render runtime disk.</p>
      <p>Health endpoint: <a href="/healthz"><code>/healthz</code></a> | JSON listing: <a href="/api/reports"><code>/api/reports</code></a></p>
    </div>
    <div class="card">
      <h2>Reports</h2>
      <ul>{report_items}</ul>
    </div>
    <div class="card">
      <h2>Bundles</h2>
      <ul>{bundle_items}</ul>
    </div>
  </main>
</body>
</html>"""


def render_report_html(path: Path) -> str:
    content = html.escape(path.read_text(encoding="utf-8"))
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(path.name)}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 0; background: #fcfbf7; color: #222; }}
    main {{ max-width: 980px; margin: 0 auto; padding: 24px 20px 40px; }}
    a {{ color: #8a3b12; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    pre {{ white-space: pre-wrap; word-wrap: break-word; background: #fffdf8; border: 1px solid #e8dfcf; border-radius: 16px; padding: 20px; overflow-x: auto; }}
  </style>
</head>
<body>
  <main>
    <p><a href="/">Back to report index</a> | <a href="/raw/{quote(path.name)}">Raw markdown</a></p>
    <h1>{html.escape(path.name)}</h1>
    <pre>{content}</pre>
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
