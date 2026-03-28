#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ai_agent.config import ZhaoConfig
from ai_agent.storage.sqlite_raw_store import SqliteRawStore


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(
        description="Bootstrap runtime directories, DB schema, and env validation."
    )
    parser.add_argument("--db-path", default=ZhaoConfig.from_env().database_path)
    parser.add_argument("--strict-env", action="store_true")
    args = parser.parse_args()

    checks: list[dict[str, object]] = []
    python_ok = _check_python_version(checks)
    dirs_ok = _ensure_runtime_dirs(checks)
    db_ok = _ensure_db_schema(args.db_path, checks)
    env_ok = _validate_env(args.strict_env, checks)

    ok = python_ok and dirs_ok and db_ok and env_ok
    print(
        json.dumps(
            {
                "ok": ok,
                "db_path": args.db_path,
                "checks": checks,
            },
            ensure_ascii=False,
        )
    )
    return 0 if ok else 1


def _check_python_version(checks: list[dict[str, object]]) -> bool:
    py_ok = sys.version_info >= (3, 11)
    checks.append(
        {
            "name": "python_version",
            "ok": py_ok,
            "message": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        }
    )
    return py_ok


def _ensure_runtime_dirs(checks: list[dict[str, object]]) -> bool:
    wanted = [Path("data"), Path("logs"), Path("reports")]
    for d in wanted:
        d.mkdir(parents=True, exist_ok=True)
    checks.append(
        {
            "name": "runtime_dirs",
            "ok": True,
            "message": ",".join(str(d) for d in wanted),
        }
    )
    return True


def _ensure_db_schema(db_path: str, checks: list[dict[str, object]]) -> bool:
    store = SqliteRawStore(db_path)
    store.ensure_schema()
    with sqlite3.connect(db_path) as conn:
        applied = conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
    checks.append(
        {
            "name": "db_schema",
            "ok": True,
            "message": f"applied_migrations={int(applied)}",
        }
    )
    return True


def _validate_env(strict_env: bool, checks: list[dict[str, object]]) -> bool:
    cfg = ZhaoConfig.from_env()
    placeholder_secret = cfg.secret in {"", "zhao123", "REPLACE_WITH_ASSIGNED_SECRET"}
    msg = "configured"
    ok = True
    if placeholder_secret:
        msg = "placeholder_or_default_secret"
        ok = not strict_env
    checks.append(
        {
            "name": "zhao_secret",
            "ok": ok,
            "message": msg,
        }
    )
    checks.append(
        {
            "name": "zhao_base_url",
            "ok": bool(str(cfg.base_url).strip()),
            "message": cfg.base_url,
        }
    )
    checks.append(
        {
            "name": "rate_limit_state_path",
            "ok": bool(str(cfg.rate_limit_state_path).strip()),
            "message": cfg.rate_limit_state_path,
        }
    )
    return ok


if __name__ == "__main__":
    raise SystemExit(main())
