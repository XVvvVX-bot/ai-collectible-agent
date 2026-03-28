from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ZhaoV2Config:
    database_path: str

    @classmethod
    def from_env(cls) -> "ZhaoV2Config":
        return cls(database_path=os.getenv("ZHAO_V2_DATABASE_PATH", "data/agent_v2.db"))
