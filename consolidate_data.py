#!/usr/bin/env python3
"""Backward-compatible entry point. Prefer: python tools/consolidate_data.py"""

import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parent
runpy.run_path(str(ROOT / "tools" / "consolidate_data.py"), run_name="__main__")
