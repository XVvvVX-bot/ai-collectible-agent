from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ZhaoConfig:
    base_url: str
    search_path: str
    secret: str
    timeout_sec: int = 30
    default_page_size: int = 50

    @classmethod
    def from_env(cls) -> "ZhaoConfig":
        return cls(
            base_url=os.getenv("ZHAO_BASE_URL", "http://8.218.2.12:8888"),
            search_path=os.getenv("ZHAO_SEARCH_PATH", "/api/search"),
            secret=os.getenv("ZHAO_SECRET", "zhao123"),
            timeout_sec=int(os.getenv("REQUEST_TIMEOUT_SEC", "30")),
            default_page_size=int(os.getenv("DEFAULT_PAGE_SIZE", "50")),
        )

