#!/usr/bin/env python3
"""Smoke test: synthesize a tiny OHLCV dataset and run the full pipeline.

Not a unit test — just verifies imports wire up, level builders produce
rows, sweeps and labels come out, and the run pipeline executes end to
end without exceptions. Intended for the sandbox environment where LFS
data isn't available.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import numpy as np
import pandas as pd

from studies.sweep_continuation.levels import build_levels
from studies.sweep_continuation.sweeps import (
    compute_atr, detect_sweeps, label_outcomes,
)
from studies.sweep_continuation.features import attach_features


def make_fixture(days: int = 6, seed: int = 42) -> pd.DataFrame:
    """Generate plausible-looking NQ 30s OHLCV for N trading days.

    Uses NY time, starts at 18:00 ET Sunday-equivalent. Each day spans
    full Globex + RTH. Random walk + intraday drift so we get swings,
    breakouts, and sweeps.
    """
    rng = np.random.default_rng(seed)
    start = pd.Timestamp('2024-01-08 18:00', tz='America/New_York')
    rows = []
    price = 17000.0

    for d in range(days):
        day_start = start + pd.Timedelta(days=d)
        # Generate 24 hours of 30s bars = 2880 bars
        n = 2880
        for b in range(n):
            ts_ny = day_start + pd.Timedelta(seconds=30 * b)
            ts_utc = ts_ny.tz_convert('UTC')
            # Intraday drift: bigger moves during RTH
            t = ts_ny.time()
            if pd.Timestamp('1970-01-01 09:30').time() <= t < pd.Timestamp('1970-01-01 16:00').time():
                sigma = 3.0
            else:
                sigma = 1.2
            step = rng.normal(0, sigma)
            o = price
            c = price + step
            h = max(o, c) + abs(rng.normal(0, sigma * 0.5))
            l = min(o, c) - abs(rng.normal(0, sigma * 0.5))
            v = int(abs(rng.normal(500, 120)))
            rows.append({
                'timestamp_utc': ts_utc,
                'timestamp_ny': ts_ny,
                'open': o, 'high': h, 'low': l, 'close': c, 'volume': v,
            })
            price = c

    df = pd.DataFrame(rows)
    df = df.sort_values('timestamp_utc').reset_index(drop=True)
    return df


def main():
    print("Generating fixture ...")
    candles = make_fixture(days=6)
    print(f"  {len(candles):,} candles "
          f"({candles['timestamp_ny'].iloc[0]} -> "
          f"{candles['timestamp_ny'].iloc[-1]})")

    print("\nBuilding levels ...")
    levels = build_levels(candles)
    print(f"  {len(levels)} levels")
    print(levels['type'].value_counts().to_string())

    print("\nDetecting sweeps ...")
    sweeps = detect_sweeps(candles, levels, run_through_eps_atr=0.25)
    print(f"  {len(sweeps)} sweep events")

    if sweeps.empty:
        print("  (no sweeps detected in fixture)")
        return

    print("\nLabeling outcomes ...")
    sweeps = label_outcomes(sweeps, candles, [10, 60, 120],
                             run_threshold_atr=1.0, rev_threshold_atr=1.0)

    print("\nAttaching features ...")
    atr = compute_atr(candles, 14)
    sweeps = attach_features(sweeps, candles, levels, atr)

    print("\nLabel breakdown at h=60:")
    print(sweeps['label_h60'].value_counts().to_string())

    print("\nTop level types swept:")
    print(sweeps['level_type'].value_counts().head(10).to_string())

    print("\nColumns on the final sweeps frame:")
    print("  " + ", ".join(sweeps.columns))

    # Assertion: sweep_idx >= level_created_idx
    assert (sweeps['sweep_idx'] >= sweeps['level_created_idx']).all()
    print("\n[OK] sanity assertions passed")


if __name__ == '__main__':
    main()
