#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ai_agent.importers.user_data_import import import_user_items_file


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(
        description="Import user holdings/watchlist rows from CSV/Excel with preview or commit mode."
    )
    parser.add_argument("--db-path", default="data/agent.db")
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--file-path", required=True)
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Apply writes. Omit for preview-only mode.",
    )
    args = parser.parse_args()

    result = import_user_items_file(
        db_path=args.db_path,
        user_id=args.user_id,
        file_path=args.file_path,
        commit=args.commit,
    )
    print(json.dumps({"ok": True, **result.to_dict()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
