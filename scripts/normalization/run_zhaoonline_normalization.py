from __future__ import annotations

import argparse

from ai_agent.normalization.zhaoonline_norm import normalize_zhaoonline_raw


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Normalize Zhaoonline raw listings into market_listings_norm."
    )
    parser.add_argument(
        "--db-path",
        default="data/agent.db",
        help="Path to SQLite DB file (default: data/agent.db).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Max raw rows to process in one run (default: 500).",
    )
    args = parser.parse_args()

    result = normalize_zhaoonline_raw(db_path=args.db_path, batch_size=args.batch_size)
    print("Normalization result:")
    print(f"  processed: {result.processed}")
    print(f"  upserted: {result.upserted}")
    print(f"  skipped: {result.skipped}")
    print(f"  last_raw_rowid: {result.last_raw_rowid}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

