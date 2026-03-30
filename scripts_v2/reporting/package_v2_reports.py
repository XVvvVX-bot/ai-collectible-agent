#!/usr/bin/env python3
"""Package V2 report files into a zip archive for easy transfer."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT_DIR = Path(__file__).resolve().parents[2]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ai_agent_v2.clients.zhaoonline import now_utc_iso


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Package V2 report files into a zip archive.")
    parser.add_argument("--reports-dir", default=str(Path("reports_v2")))
    parser.add_argument("--output-dir", default=str(Path("exports")))
    parser.add_argument("--limit", type=int, default=20, help="Maximum number of newest markdown reports to include.")
    args = parser.parse_args()

    reports_dir = Path(args.reports_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if not reports_dir.exists():
        raise SystemExit(
            json.dumps(
                {
                    "ok": False,
                    "error": f"reports directory not found: {reports_dir}",
                },
                ensure_ascii=False,
            )
        )

    report_files = sorted(
        [path for path in reports_dir.glob("*.md") if path.is_file()],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if args.limit > 0:
        report_files = report_files[: args.limit]

    timestamp = now_utc_iso().replace(":", "").replace("-", "").replace("+00:00", "Z")
    archive_path = output_dir / f"v2_reports_bundle_{timestamp}.zip"

    with ZipFile(archive_path, mode="w", compression=ZIP_DEFLATED) as zf:
        manifest = []
        for report_path in report_files:
            zf.write(report_path, arcname=report_path.name)
            manifest.append(
                {
                    "name": report_path.name,
                    "size_bytes": report_path.stat().st_size,
                    "modified_at_epoch": report_path.stat().st_mtime,
                }
            )
        zf.writestr("manifest.json", json.dumps({"files": manifest}, ensure_ascii=False, indent=2))

    print(
        json.dumps(
            {
                "ok": True,
                "reports_dir": str(reports_dir),
                "output_path": str(archive_path),
                "included_count": len(report_files),
                "included_files": [path.name for path in report_files],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
