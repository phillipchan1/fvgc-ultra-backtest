#!/usr/bin/env python3
"""Sweep-continuation study.

Pass A: Unconditional base rates for RUN/REVERSE/CHOP after a sweep,
broken down by level type, time-of-day, and runway.

Pass B: FVGC-conditional lift — take the standard FVGC baseline trades
and tag each with the most recent same-direction sweep within a lookback
window. Measure win rate vs baseline by level type and time-of-day.

Outputs CSVs to studies/sweep_continuation/results/.
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
from studies.sweep_continuation.sweeps import (
    compute_atr, detect_sweeps, label_outcomes,
)
from studies.sweep_continuation.features import attach_features


# -------------------------------------------------------------------
# Tunables
# -------------------------------------------------------------------
ATR_LEN = 14
RUN_THRESHOLD_ATR = 1.0
REV_THRESHOLD_ATR = 1.0
RUN_THROUGH_EPS_ATR = 0.25
LOOKBACK_SWEEP_TO_ENTRY_BARS = 40  # 20min on 30s
HORIZONS_BARS = [10, 60, 120]       # 5min, 30min, 60min

DEFAULT_DATA_PATH = Path('data/consolidated/nq-front-month.ohlcv-30s.csv')
STUDY_DIR = Path(__file__).resolve().parent
RESULTS_DIR = STUDY_DIR / 'results'


def _pct(n, d):
    return (n / d * 100.0) if d else float('nan')


# -------------------------------------------------------------------
# Pass A — unconditional base rates
# -------------------------------------------------------------------

def _rate_table(df: pd.DataFrame, group_cols, label_col: str,
                min_n: int = 10) -> pd.DataFrame:
    rows = []
    for keys, grp in df.groupby(group_cols):
        n = len(grp)
        if n < min_n:
            continue
        run = (grp[label_col] == 'RUN').sum()
        rev = (grp[label_col] == 'REVERSE').sum()
        chop = (grp[label_col] == 'CHOP').sum()
        if not isinstance(keys, tuple):
            keys = (keys,)
        row = dict(zip(group_cols, keys))
        row.update({
            'n': n,
            'run_pct': _pct(run, n),
            'rev_pct': _pct(rev, n),
            'chop_pct': _pct(chop, n),
        })
        rows.append(row)
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.sort_values(
        [c for c in group_cols] + ['n'],
        ascending=[True] * len(group_cols) + [False],
    )


def pass_a_base_rates(sweeps: pd.DataFrame) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    sweeps.to_csv(RESULTS_DIR / 'sweep_events.csv', index=False)

    for h in HORIZONS_BARS:
        lbl = f'label_h{h}'
        by_type = _rate_table(sweeps, ['level_type'], lbl)
        by_type['horizon_bars'] = h
        by_type.to_csv(RESULTS_DIR / f'base_rates_by_type_h{h}.csv',
                       index=False)

        by_type_tod = _rate_table(sweeps, ['level_type', 'tod_bucket'], lbl)
        by_type_tod['horizon_bars'] = h
        by_type_tod.to_csv(RESULTS_DIR / f'base_rates_by_type_tod_h{h}.csv',
                           index=False)

        # Runway quintile — only rows with runway defined
        rw = sweeps.dropna(subset=['runway_to_next_level_atr']).copy()
        if not rw.empty:
            rw['runway_q'] = pd.qcut(rw['runway_to_next_level_atr'], 5,
                                     labels=False, duplicates='drop')
            by_rw = _rate_table(rw, ['runway_q'], lbl)
            by_rw['horizon_bars'] = h
            by_rw.to_csv(RESULTS_DIR / f'base_rates_by_runway_h{h}.csv',
                         index=False)

    # Kind breakdown (wick_only vs run_through)
    for h in HORIZONS_BARS:
        by_kind = _rate_table(sweeps, ['kind', 'level_type'], f'label_h{h}')
        by_kind['horizon_bars'] = h
        by_kind.to_csv(RESULTS_DIR / f'base_rates_by_kind_h{h}.csv',
                       index=False)

    print("\n--- PASS A: Unconditional base rates ---")
    for h in HORIZONS_BARS:
        lbl = f'label_h{h}'
        n = len(sweeps)
        run = (sweeps[lbl] == 'RUN').sum()
        rev = (sweeps[lbl] == 'REVERSE').sum()
        chop = (sweeps[lbl] == 'CHOP').sum()
        print(f"  horizon={h:>4} bars   N={n:>6}   "
              f"RUN={_pct(run,n):5.1f}%  REV={_pct(rev,n):5.1f}%  "
              f"CHOP={_pct(chop,n):5.1f}%")


# -------------------------------------------------------------------
# Pass B — FVGC conditional lift
# -------------------------------------------------------------------

def pass_b_fvgc_lift(
    trades: pd.DataFrame,
    sweeps: pd.DataFrame,
    lookback_bars: int = LOOKBACK_SWEEP_TO_ENTRY_BARS,
) -> None:
    # Only trades with a real W/L outcome contribute to win rate
    live = trades[trades['outcome'].isin(['win', 'loss'])].copy()
    if live.empty:
        print("\n--- PASS B: no tradeable FVGC results ---")
        return

    # Index sweeps by sweep_idx for efficient lookback matching
    sweeps_sorted = sweeps.sort_values('sweep_idx').reset_index(drop=True)
    sweep_idx_arr = sweeps_sorted['sweep_idx'].values

    tag_rows = []
    for row in live.itertuples(index=False):
        entry_idx = int(row.entry_idx)
        lo = entry_idx - lookback_bars
        # Candidate sweeps in [lo, entry_idx]
        left = np.searchsorted(sweep_idx_arr, lo, side='left')
        right = np.searchsorted(sweep_idx_arr, entry_idx, side='right')
        window = sweeps_sorted.iloc[left:right]

        # Same direction: long trades look for bullish sweeps, shorts for bearish
        want_dir = 'bullish' if row.direction == 'long' else 'bearish'
        window = window[window['sweep_direction'] == want_dir]

        if window.empty:
            tag_rows.append({'tagged': False})
            continue

        # Most recent
        last = window.iloc[-1]
        tag_rows.append({
            'tagged': True,
            'sweep_level_type': last['level_type'],
            'sweep_level_side': last['level_side'],
            'sweep_kind': last['kind'],
            'sweep_tod_bucket': last['tod_bucket'],
            'sweep_idx': int(last['sweep_idx']),
            'sweep_age_bars': entry_idx - int(last['sweep_idx']),
            'sweep_runway_atr': last.get('runway_to_next_level_atr', np.nan),
        })

    tag_df = pd.DataFrame(tag_rows)
    tagged = pd.concat([live.reset_index(drop=True), tag_df], axis=1)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    tagged.to_csv(RESULTS_DIR / 'fvgc_with_sweep_trades.csv', index=False)

    # Baseline
    base_n = len(live)
    base_w = (live['outcome'] == 'win').sum()
    base_wr = _pct(base_w, base_n)

    def wr(sub):
        n = len(sub)
        w = (sub['outcome'] == 'win').sum()
        return n, w, _pct(w, n)

    # Overall: tagged vs untagged vs baseline
    t_sub = tagged[tagged['tagged']]
    u_sub = tagged[~tagged['tagged']]
    t_n, t_w, t_wr = wr(t_sub)
    u_n, u_w, u_wr = wr(u_sub)

    summary_rows = [
        {'cohort': 'baseline', 'n': base_n, 'wins': base_w, 'wr_pct': base_wr,
         'delta_vs_base': 0.0},
        {'cohort': 'sweep_tagged', 'n': t_n, 'wins': t_w, 'wr_pct': t_wr,
         'delta_vs_base': t_wr - base_wr},
        {'cohort': 'untagged', 'n': u_n, 'wins': u_w, 'wr_pct': u_wr,
         'delta_vs_base': u_wr - base_wr},
    ]
    pd.DataFrame(summary_rows).to_csv(
        RESULTS_DIR / 'fvgc_lift_overall.csv', index=False)

    # Feature lifts
    feat_rows = []

    def add_feature_lift(feat_col: str, bucket_fn=None):
        if feat_col not in tagged.columns:
            return
        working = tagged[tagged['tagged']].copy()
        if bucket_fn is not None:
            working[feat_col] = working[feat_col].map(bucket_fn)
        for v, grp in working.groupby(feat_col, dropna=False):
            n, w, r = wr(grp)
            if n < 10:
                continue
            feat_rows.append({
                'feature': feat_col, 'value': v,
                'n': n, 'wins': w, 'wr_pct': r,
                'delta_vs_base': r - base_wr,
            })

    add_feature_lift('sweep_level_type')
    add_feature_lift('sweep_kind')
    add_feature_lift('sweep_tod_bucket')
    add_feature_lift('variant')

    feat_df = pd.DataFrame(feat_rows)
    if not feat_df.empty:
        feat_df = feat_df.sort_values('delta_vs_base', ascending=False)
    feat_df.to_csv(RESULTS_DIR / 'fvgc_lift_by_feature.csv', index=False)

    # Cross: level_type x tod
    cross_rows = []
    if not t_sub.empty and 'sweep_level_type' in t_sub.columns:
        for (lt, tod), grp in t_sub.groupby(
                ['sweep_level_type', 'sweep_tod_bucket'], dropna=False):
            n, w, r = wr(grp)
            if n < 10:
                continue
            cross_rows.append({
                'level_type': lt, 'tod_bucket': tod,
                'n': n, 'wins': w, 'wr_pct': r,
                'delta_vs_base': r - base_wr,
            })
    pd.DataFrame(cross_rows).to_csv(
        RESULTS_DIR / 'fvgc_lift_by_type_tod.csv', index=False)

    # Console summary
    print("\n--- PASS B: FVGC conditional lift ---")
    print(f"  baseline     N={base_n:>5}  WR={base_wr:5.1f}%")
    print(f"  sweep_tagged N={t_n:>5}  WR={t_wr:5.1f}%  "
          f"delta={t_wr - base_wr:+.1f}pp")
    print(f"  untagged     N={u_n:>5}  WR={u_wr:5.1f}%  "
          f"delta={u_wr - base_wr:+.1f}pp")

    if not feat_df.empty:
        big = feat_df[(feat_df['n'] >= 30)
                      & (feat_df['delta_vs_base'].abs() >= 5.0)]
        if not big.empty:
            print("\n  Notable feature lifts (|delta|>=5pp, N>=30):")
            for row in big.itertuples(index=False):
                print(f"    {row.feature:20s} = {str(row.value):15s}  "
                      f"N={row.n:<4} WR={row.wr_pct:5.1f}%  "
                      f"delta={row.delta_vs_base:+.1f}pp")


# -------------------------------------------------------------------
# Correctness checks
# -------------------------------------------------------------------

def _sanity_checks(sweeps: pd.DataFrame, levels: pd.DataFrame,
                   candles: pd.DataFrame) -> None:
    assert (sweeps['sweep_idx'] >= sweeps['level_created_idx']).all(), \
        "sweep_idx must be >= level_created_idx"

    # ORH/ORL become active after their window ends.
    for minutes, min_total in [(5, 9 * 60 + 35),
                               (15, 9 * 60 + 45),
                               (30, 10 * 60 + 0)]:
        t = f'ORH_{minutes}'
        sub = levels[levels['type'] == t]
        if sub.empty:
            continue
        for row in sub.itertuples(index=False):
            ts = row.created_ts
            mins = ts.hour * 60 + ts.minute
            assert mins >= min_total, (
                f"{t} active too early: {ts}"
            )

    # Spot-check a few random sweep events by printing bar context
    if len(sweeps) == 0:
        return
    sample = sweeps.sample(min(5, len(sweeps)), random_state=0)
    print("\n--- Sanity spot-check (5 random sweeps) ---")
    for row in sample.itertuples(index=False):
        i = row.sweep_idx
        lo = max(0, i - 2)
        hi = min(len(candles), i + 3)
        print(f"\n  {row.level_type} @ {row.level_price:.2f}  "
              f"swept at idx={i} ({row.sweep_ts})  kind={row.kind}")
        for j in range(lo, hi):
            marker = ' <-- sweep' if j == i else ''
            c = candles.iloc[j]
            print(f"    idx={j}  O={c['open']:.2f} H={c['high']:.2f} "
                  f"L={c['low']:.2f} C={c['close']:.2f}{marker}")


# -------------------------------------------------------------------
# Main
# -------------------------------------------------------------------

def run(data_path: Path = DEFAULT_DATA_PATH) -> dict:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    candles = load_candles(data_path)
    print(f"Loaded {len(candles):,} candles "
          f"({candles['timestamp_ny'].iloc[0]} -> "
          f"{candles['timestamp_ny'].iloc[-1]})")

    # Build levels
    print("Building liquidity levels ...")
    levels = build_levels(candles)
    print(f"  {len(levels):,} levels constructed "
          f"({levels['type'].nunique() if not levels.empty else 0} types)")
    levels.to_csv(RESULTS_DIR / 'levels.csv', index=False)

    # Sweep detection + labeling
    print("Detecting sweeps ...")
    sweeps = detect_sweeps(candles, levels, RUN_THROUGH_EPS_ATR)
    print(f"  {len(sweeps):,} sweep events detected")
    sweeps = label_outcomes(sweeps, candles, HORIZONS_BARS,
                             RUN_THRESHOLD_ATR, REV_THRESHOLD_ATR)

    # Features
    print("Attaching features ...")
    atr = compute_atr(candles, ATR_LEN)
    sweeps = attach_features(sweeps, candles, levels, atr)

    _sanity_checks(sweeps, levels, candles)

    # Pass A
    pass_a_base_rates(sweeps)

    # Pass B
    print("\nRunning FVGC baseline for Pass B ...")
    signals, _fvgs = generate_signals(candles)
    results = simulate_trades(signals, candles)
    trades = pd.DataFrame(results)
    pass_b_fvgc_lift(trades, sweeps)

    return {
        'n_candles': len(candles),
        'n_levels': len(levels),
        'n_sweeps': len(sweeps),
        'n_trades': len(trades),
    }


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--data', type=Path, default=DEFAULT_DATA_PATH)
    args = p.parse_args()
    run(args.data)
