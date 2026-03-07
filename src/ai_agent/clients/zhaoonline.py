from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_auth_token(secret: str, timestamp_ms: str) -> str:
    return hashlib.md5((secret + timestamp_ms).encode("utf-8")).hexdigest()


@dataclass
class ZhaoRequestContext:
    url: str
    headers: dict[str, str]
    timestamp_ms: str
    token: str


@dataclass
class ZhaoResponse:
    status_code: int
    headers: dict[str, str]
    body_text: str
    body_json: dict[str, Any] | None
    elapsed_ms: int


@dataclass
class ZhaoError:
    status_code: int
    headers: dict[str, str]
    body_text: str
    elapsed_ms: int


class ZhaoClient:
    def __init__(self, base_url: str, search_path: str, secret: str, timeout_sec: int = 30):
        self.base_url = base_url.rstrip("/")
        self.search_path = search_path
        self.secret = secret
        self.timeout_sec = timeout_sec

    def _build_context(self, status: int, page: int, page_size: int) -> ZhaoRequestContext:
        timestamp_ms = str(int(time.time() * 1000))
        token = build_auth_token(self.secret, timestamp_ms)
        query = urllib.parse.urlencode({"status": status, "page": page, "pageSize": page_size})
        url = f"{self.base_url}{self.search_path}?{query}"
        headers = {
            "X-Auth-Timestamp": timestamp_ms,
            "X-Auth-Token": token,
            "Content-Type": "application/json",
            "User-Agent": "ai-collectibles-agent/0.1.0",
        }
        return ZhaoRequestContext(url=url, headers=headers, timestamp_ms=timestamp_ms, token=token)

    def search(self, status: int, page: int = 1, page_size: int = 50) -> tuple[ZhaoRequestContext, ZhaoResponse | None, ZhaoError | None]:
        ctx = self._build_context(status=status, page=page, page_size=page_size)
        req = urllib.request.Request(url=ctx.url, method="GET", headers=ctx.headers)
        started = time.time()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                elapsed_ms = int((time.time() - started) * 1000)
                body_text = resp.read().decode("utf-8", errors="replace")
                try:
                    body_json = json.loads(body_text)
                except json.JSONDecodeError:
                    body_json = None
                return (
                    ctx,
                    ZhaoResponse(
                        status_code=resp.status,
                        headers=dict(resp.getheaders()),
                        body_text=body_text,
                        body_json=body_json,
                        elapsed_ms=elapsed_ms,
                    ),
                    None,
                )
        except urllib.error.HTTPError as e:
            elapsed_ms = int((time.time() - started) * 1000)
            body_text = e.read().decode("utf-8", errors="replace")
            return (
                ctx,
                None,
                ZhaoError(
                    status_code=e.code,
                    headers=dict(e.headers.items()),
                    body_text=body_text,
                    elapsed_ms=elapsed_ms,
                ),
            )

