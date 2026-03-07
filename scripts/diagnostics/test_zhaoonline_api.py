#!/usr/bin/env python3
"""Zhaoonline API connectivity and auth diagnostic."""

from __future__ import annotations

import argparse
import json
import socket
import sys
import time
import traceback
import urllib.parse
from datetime import datetime
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ai_agent.clients.zhaoonline import ZhaoClient, now_utc_iso
from ai_agent.config import ZhaoConfig

DEFAULT_BASE_URL = ZhaoConfig.from_env().base_url
DEFAULT_PATH = ZhaoConfig.from_env().search_path


def resolve_host_info(base_url: str) -> tuple[str, list[str]]:
    host = urllib.parse.urlparse(base_url).hostname or ""
    resolved = []
    if host:
        infos = socket.getaddrinfo(host, None)
        resolved = sorted({entry[4][0] for entry in infos})
    return host, resolved


def run_once(
    client: ZhaoClient,
    status: int,
    page: int,
    page_size: int,
) -> int:
    ctx, resp, err = client.search(status=status, page=page, page_size=page_size)

    print("=" * 78)
    print("Zhaoonline API Diagnostic")
    print(f"utc_now:            {now_utc_iso()}")
    print(f"url:                {ctx.url}")
    print(f"auth_timestamp_ms:  {ctx.timestamp_ms}")
    print(f"auth_token_md5:     {ctx.token}")
    print("request_headers:")
    for k, v in ctx.headers.items():
        print(f"  {k}: {v}")
    print("-" * 78)
    try:
        if resp is not None:
            print(f"http_status:        {resp.status_code}")
            print(f"elapsed_ms:         {resp.elapsed_ms}")
            print("response_headers:")
            for k, v in resp.headers.items():
                print(f"  {k}: {v}")
            print("-" * 78)
            print("response_body:")
            try:
                if resp.body_json is not None:
                    print(json.dumps(resp.body_json, ensure_ascii=False, indent=2))
                else:
                    print(resp.body_text)
            except Exception:
                print(resp.body_text)
            return 0
        if err is not None:
            print(f"http_status:        {err.status_code}")
            print(f"elapsed_ms:         {err.elapsed_ms}")
            print("response_headers:")
            for k, v in err.headers.items():
                print(f"  {k}: {v}")
            print("-" * 78)
            print("error_body:")
            try:
                print(json.dumps(json.loads(err.body_text), ensure_ascii=False, indent=2))
            except Exception:
                print(err.body_text)
            return 2
        print("request_exception:")
        print("  message: Unknown result state (no response and no error).")
        return 3
    except Exception as e:
        print("request_exception:")
        print(f"  type: {type(e).__name__}")
        print(f"  message: {e}")
        print("traceback:")
        print(traceback.format_exc())
        return 3


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a diagnostic call to Zhaoonline /api/search."
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--path", default=DEFAULT_PATH)
    parser.add_argument("--secret", default=ZhaoConfig.from_env().secret)
    parser.add_argument("--status", type=int, default=2, choices=[1, 2, 3, 0])
    parser.add_argument("--page", type=int, default=1)
    parser.add_argument("--page-size", type=int, default=10)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--interval-sec", type=float, default=2.0)
    args = parser.parse_args()

    print("Local environment:")
    print(f"  python: {sys.version.split()[0]}")
    print(f"  platform: {sys.platform}")
    print(f"  local_time: {datetime.now().isoformat()}")
    print(f"  utc_time:   {now_utc_iso()}")
    print("-" * 78)

    host, ips = resolve_host_info(args.base_url)
    print("DNS resolution:")
    print(f"  host: {host}")
    if ips:
        for ip in ips:
            print(f"  resolved_ip: {ip}")
    else:
        print("  resolved_ip: <none>")

    client = ZhaoClient(
        base_url=args.base_url,
        search_path=args.path,
        secret=args.secret,
        timeout_sec=args.timeout,
    )
    exit_codes = []
    for i in range(args.repeats):
        if i > 0:
            time.sleep(args.interval_sec)
        print(f"\nAttempt {i + 1}/{args.repeats}")
        code = run_once(
            client=client,
            status=args.status,
            page=args.page,
            page_size=args.page_size,
        )
        exit_codes.append(code)

    final_code = 0 if all(code == 0 for code in exit_codes) else max(exit_codes)
    print("\n" + "=" * 78)
    print(f"Final exit code: {final_code}")
    return final_code


if __name__ == "__main__":
    raise SystemExit(main())
