#!/usr/bin/env python3
"""Compatibility launcher for the diagnostic script."""

from pathlib import Path
import runpy


if __name__ == "__main__":
    script = Path(__file__).resolve().parent / "scripts" / "diagnostics" / "test_zhaoonline_api.py"
    runpy.run_path(str(script), run_name="__main__")

