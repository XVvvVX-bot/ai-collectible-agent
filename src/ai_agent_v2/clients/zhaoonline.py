from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


def now_utc_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def build_auth_token(secret: str, timestamp_ms: str) -> str:
    return hashlib.md5((secret + timestamp_ms).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ZhaoV2RequestContext:
    url: str
    headers: dict[str, str]
    timestamp_ms: str
    token: str


@dataclass(frozen=True)
class ZhaoV2Response:
    status_code: int
    headers: dict[str, str]
    body_text: str
    body_json: dict[str, Any] | list[Any] | None
    elapsed_ms: int


@dataclass(frozen=True)
class ZhaoV2Error:
    status_code: int
    headers: dict[str, str]
    body_text: str
    elapsed_ms: int


class ZhaoV2Client:
    def __init__(
        self,
        *,
        base_url: str,
        secret: str,
        timeout_sec: int = 60,
        incremental_path: str = "/api/search/auctions/incremental",
    ):
        self.base_url = base_url.rstrip("/")
        self.secret = secret
        self.timeout_sec = timeout_sec
        self.incremental_path = incremental_path

    def search_incremental(
        self,
        *,
        from_time_ms: int,
        to_time_ms: int,
        page: int = 1,
        page_size: int = 500,
    ) -> tuple[ZhaoV2RequestContext, ZhaoV2Response | None, ZhaoV2Error | None]:
        params = {
            "fromTime": int(from_time_ms),
            "toTime": int(to_time_ms),
            "page": int(page),
            "pageSize": int(page_size),
        }
        return self._request(self.incremental_path, params)

    def _request(
        self,
        path: str,
        params: dict[str, Any],
    ) -> tuple[ZhaoV2RequestContext, ZhaoV2Response | None, ZhaoV2Error | None]:
        timestamp_ms = str(int(time.time() * 1000))
        token = build_auth_token(self.secret, timestamp_ms)
        query = urllib.parse.urlencode(params)
        url = f"{self.base_url}{path}?{query}"
        headers = {
            "X-Auth-Timestamp": timestamp_ms,
            "X-Auth-Token": token,
            "Content-Type": "application/json",
            "User-Agent": "ai-collectibles-agent-v2/0.1.0",
        }
        ctx = ZhaoV2RequestContext(url=url, headers=headers, timestamp_ms=timestamp_ms, token=token)
        request = urllib.request.Request(url=url, method="GET", headers=headers)
        started = time.time()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_sec) as response:
                elapsed_ms = int((time.time() - started) * 1000)
                body_text = response.read().decode("utf-8", errors="replace")
                try:
                    body_json = json.loads(body_text)
                except json.JSONDecodeError:
                    body_json = None
                return (
                    ctx,
                    ZhaoV2Response(
                        status_code=response.status,
                        headers=dict(response.getheaders()),
                        body_text=body_text,
                        body_json=body_json,
                        elapsed_ms=elapsed_ms,
                    ),
                    None,
                )
        except urllib.error.HTTPError as error:
            elapsed_ms = int((time.time() - started) * 1000)
            body_text = error.read().decode("utf-8", errors="replace")
            return (
                ctx,
                None,
                ZhaoV2Error(
                    status_code=error.code,
                    headers=dict(error.headers.items()),
                    body_text=body_text,
                    elapsed_ms=elapsed_ms,
                ),
            )
