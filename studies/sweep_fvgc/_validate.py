#!/usr/bin/env python3
"""Quick validation: detect sweeps on first 100 entered trades and spot-check."""
import sys
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from studies.sweep_fvgc.run import load_trades, load_bsl_ssl, load_bars, compute_sweep_flags

trades = load_trades().head(100)
bsl_ssl = load_bsl_ssl()
bars = load_bars()
out = compute_sweep_flags(trades, bsl_ssl, bars)
print(out[['timestamp', 'direction', 'date', 'bsl_level', 'ssl_level',
          'bsl_swept_min_ago', 'ssl_swept_min_ago']].to_string(index=False))
print('\nrows with any sweep within 10min:',
      ((out['bsl_swept_min_ago'] <= 10) | (out['ssl_swept_min_ago'] <= 10)).sum())
