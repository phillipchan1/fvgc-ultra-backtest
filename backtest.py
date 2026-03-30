#!/usr/bin/env python3
"""
Backward-compatible entry point. Prefer:

  python tools/run_backtest.py [args]

Logic lives in the `fvgc` package; the CLI is `tools/run_backtest.py`.
"""

import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
runpy.run_path(str(ROOT / "tools" / "run_backtest.py"), run_name="__main__")
