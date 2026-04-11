#!/usr/bin/env python3
"""Hold-vs-bank analysis.

For winning FVGC trades that were in the same direction as a recent
sweep, measure MFE in units of the distance to the NEXT same-direction
level beyond the swept one. Answers: if I took profits at the swept
level, how often did I leave a bigger move on the table?
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import numpy as np
import pandas as pd

from fvgc.data import load_candles
from fvgc.model import generate_signals
from fvgc.engine import simulate_trades

from studies.sweep_continuation.levels import build_levels
from studies.sweep_continuation.sweeps import compute_atr, detect_sweeps, label_outcomes
from studies.sweep_continuation.features import attach_features
from studies.sweep_continuation.run import (
    RUN_THROUGH_EPS_ATR, HORIZONS_BARS, RUN_THRESHOLD_ATR, REV_THRESHOLD_ATR,
    LOOKBACK_SWEEP_TO_ENTRY_BARS, ATR_LEN, DEFAULT_DATA_PATH, RESULTS_DIR,
)


def _next_level_beyond(levels: pd.DataFrame, swept_price: float,
                        direction: str, as_of_idx: int) -> float | None:
    """Next same-side level beyond swept_price in the direction of travel."""
    active = levels[levels['created_idx'] <= as_of_idx]
    if direction == 'bullish':
        up = active[(active['side'] == 'high') & (active['price'] > swept_price)]
        if up.empty:
            return None
        return float(up['price'].min())
    else:
        dn = active[(active['side'] == 'low') & (active['price'] < swept_price)]
        if dn.empty:
            return None
        return float(dn['price'].max())


def run(data_path: Path = DEFAULT_DATA_PATH) -> None:
    candles = load_candles(data_path)
    levels = build_levels(candles)
    sweeps = detect_sweeps(candles, levels, RUN_THROUGH_EPS_ATR)
    sweeps = label_outcomes(sweeps, candles, HORIZONS_BARS,
                             RUN_THRESHOLD_ATR, REV_THRESHOLD_ATR)
    atr = compute_atr(candles, ATR_LEN)
    sweeps = attach_features(sweeps, candles, levels, atr)

    signals, _ = generate_signals(candles)
    results = simulate_trades(signals, candles)
    trades = pd.DataFrame(results)
    trades = trades[trades['outcome'].isin(['win', 'loss'])]

    sweeps_sorted = sweeps.sort_values('sweep_idx').reset_index(drop=True)
    sweep_idx_arr = sweeps_sorted['sweep_idx'].values

    rows = []
    for row in trades.itertuples(index=False):
        entry_idx = int(row.entry_idx)
        lo = entry_idx - LOOKBACK_SWEEP_TO_ENTRY_BARS
        left = np.searchsorted(sweep_idx_arr, lo, side='left')
        right = np.searchsorted(sweep_idx_arr, entry_idx, side='right')
        window = sweeps_sorted.iloc[left:right]
        want_dir = 'bullish' if row.direction == 'long' else 'bearish'
        window = window[window['sweep_direction'] == want_dir]
        if window.empty:
            continue
        last = window.iloc[-1]

        next_lvl = _next_level_beyond(
            levels, float(last['level_price']),
            last['sweep_direction'], entry_idx,
        )
        if next_lvl is None:
            continue

        if row.direction == 'long':
            dist_to_next = next_lvl - float(row.entry_price)
        else:
            dist_to_next = float(row.entry_price) - next_lvl
        if dist_to_next <= 0:
            continue

        mfe = float(row.mfe_pts) if row.mfe_pts not in ('', None) else 0.0
        reach = mfe / dist_to_next
        rows.append({
            'entry_idx': entry_idx,
            'direction': row.direction,
            'variant': row.variant,
            'outcome': row.outcome,
            'swept_level_type': last['level_type'],
            'swept_level_price': float(last['level_price']),
            'next_level_price': next_lvl,
            'dist_to_next_pts': dist_to_next,
            'trade_mfe_pts': mfe,
            'mfe_as_frac_of_next': reach,
            'reached_next': reach >= 1.0,
        })

    df = pd.DataFrame(rows)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(RESULTS_DIR / 'hold_vs_bank.csv', index=False)

    if df.empty:
        print("No qualifying sweep-tagged trades for hold-vs-bank.")
        return

    winners = df[df['outcome'] == 'win']
    print("\n--- Hold vs Bank ---")
    print(f"  sweep-tagged trades with next-level defined: {len(df)}")
    print(f"    winners: {len(winners)}")
    if not winners.empty:
        q = winners['mfe_as_frac_of_next'].quantile([0.25, 0.5, 0.75, 0.9])
        print(f"  MFE/next-level quantiles (winners):")
        print(f"    p25={q.loc[0.25]:.2f}  p50={q.loc[0.5]:.2f}  "
              f"p75={q.loc[0.75]:.2f}  p90={q.loc[0.9]:.2f}")
        reached = winners['reached_next'].mean() * 100.0
        print(f"  % winners reaching next level: {reached:.1f}%")


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--data', type=Path, default=DEFAULT_DATA_PATH)
    args = p.parse_args()
    run(args.data)
