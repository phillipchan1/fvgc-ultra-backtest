#!/usr/bin/env python3
"""
Confluence-model v2 — built on the magnet-aligned universe (the corrected play).

Universe: magnet=='aligned' (1m: n=704, 30s: n=1376)

Tests each candidate confluence factor for IS/OOS robustness.
Picks the cleanest 3-4 factor count.
Reports tier table.
"""

import sys
from pathlib import Path
from datetime import date

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import numpy as np

STUDY_DIR = Path(__file__).resolve().parent
RESULTS_DIR = STUDY_DIR / 'results'

IS_START = date(2023, 10, 1)
IS_END   = date(2025, 10, 31)


def load(tf: str) -> pd.DataFrame:
    df = pd.read_csv(RESULTS_DIR / f'magnet_aligned_{tf}.csv')
    df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True).dt.tz_convert('America/New_York')
    df['date'] = pd.to_datetime(df['date']).dt.date
    df = df[df['magnet'] == 'aligned'].copy()
    df['pnl_r'] = df['outcome_2r'].map({'WIN': 2.0, 'LOSS': -1.0, 'PARTIAL': 0.0})
    df['is_setup_b'] = df['sweep_state'].isin(['only_H_swept', 'only_L_swept'])  # Setup B = reversal
    df['hour'] = df['timestamp'].dt.hour + df['timestamp'].dt.minute / 60
    return df


def stats(df):
    n = len(df)
    if n == 0: return {'n': 0, 'wr': float('nan'), 'pf': float('nan'), 'ev': float('nan')}
    w = int((df['outcome_2r'] == 'WIN').sum())
    l = int((df['outcome_2r'] == 'LOSS').sum())
    p = int((df['outcome_2r'] == 'PARTIAL').sum())
    dec = w + l
    wr = w/dec*100 if dec else float('nan')
    pf = (w*2.0/l) if l else float('inf')
    ev = df['pnl_r'].sum() / n
    return {'n': n, 'w': w, 'l': l, 'p': p, 'wr': wr, 'pf': pf, 'ev': ev}


def fmt(s):
    if s.get('n', 0) == 0: return "n=0"
    pf = f"{s['pf']:5.2f}" if s['pf'] != float('inf') else "  inf"
    return f"n={s['n']:4d}  WR={s['wr']:5.1f}%  PF={pf}  EV={s['ev']:+.3f}R"


def test_factor(df: pd.DataFrame, mask: pd.Series, label: str):
    """Print PF inside vs outside the factor — both IS and OOS."""
    is_m = (df['date'] >= IS_START) & (df['date'] <= IS_END)

    inside  = df[mask]
    outside = df[~mask]

    in_is  = inside[is_m.reindex(inside.index)]
    in_oos = inside[~is_m.reindex(inside.index)]
    out_is  = outside[is_m.reindex(outside.index)]
    out_oos = outside[~is_m.reindex(outside.index)]

    print(f"\n  ── {label} ──")
    print(f"    IN  IS: {fmt(stats(in_is))}   OOS: {fmt(stats(in_oos))}   ALL: {fmt(stats(inside))}")
    print(f"    OUT IS: {fmt(stats(out_is))}   OOS: {fmt(stats(out_oos))}   ALL: {fmt(stats(outside))}")

    # Lift indicator
    in_all  = stats(inside)
    out_all = stats(outside)
    if in_all['pf'] != float('inf') and out_all['pf'] != float('inf') and out_all['pf'] > 0:
        lift = in_all['pf'] - out_all['pf']
        verdict = "✓ HELPS" if lift > 0.2 and stats(in_is)['pf'] > stats(out_is)['pf'] and stats(in_oos)['pf'] > stats(out_oos)['pf'] else ("≈ flat" if abs(lift) <= 0.2 else "✗ HURTS")
        print(f"    PF lift: {lift:+.2f}   {verdict}")


def main():
    for tf in ('30s', '1m'):
        df = load(tf)
        print(f"\n\n{'='*100}")
        print(f"  TIMEFRAME: {tf}    magnet-aligned universe n={len(df)}")
        print(f"{'='*100}")
        print(f"\n  Baseline: {fmt(stats(df))}")
        is_m = (df['date'] >= IS_START) & (df['date'] <= IS_END)
        print(f"  IS:  {fmt(stats(df[is_m]))}")
        print(f"  OOS: {fmt(stats(df[~is_m]))}")

        # ── Test each candidate factor ──
        print(f"\n  {'═'*40} FACTOR TESTS {'═'*40}")

        test_factor(df, (df['or_range'] >= 30) & (df['or_range'] <= 100),
                    'OR range 30-100pt')
        test_factor(df, (df['or_range'] >= 60) & (df['or_range'] <= 100),
                    'OR range 60-100pt (tighter)')
        test_factor(df, df['or_range'] > 150,
                    'OR range > 150pt (should HURT)')
        test_factor(df, (df['r_to_target_OR'] >= 0.25) & (df['r_to_target_OR'] <= 1.0),
                    'R-to-OR 0.25-1.0')
        test_factor(df, (df['r_to_target_OR'] >= 0.5) & (df['r_to_target_OR'] <= 0.75),
                    'R-to-OR 0.5-0.75 (tighter sweet spot)')
        test_factor(df, df['variant'] == 'ifvg',
                    'variant == ifvg (should HURT)')
        test_factor(df, df['variant'].isin(['no_fvg', 'protected_swing']),
                    'variant in (no_fvg, protected_swing)')
        test_factor(df, df['variant'] == 'no_fvg', 'variant == no_fvg')
        test_factor(df, df['direction'] == 'long', 'direction == long')
        test_factor(df, df['direction'] == 'short', 'direction == short')
        test_factor(df, df['is_setup_b'],
                    'Setup B (one side swept = sweep reversal)')
        test_factor(df, df['sweep_state'] == 'neither',
                    'Setup A (neither swept = continuation)')
        test_factor(df, df['hour'] < 10.0,
                    'Entry before 10:00 ET')
        test_factor(df, df['hour'] >= 10.0,
                    'Entry 10:00+ ET')

        # ── Build the confluence count from robust positive factors ──
        # Robust = same direction lift in both IS and OOS, sample >= 30 each
        df['c_or_30_100']      = ((df['or_range'] >= 30) & (df['or_range'] <= 100)).astype(int)
        df['c_rto_0p25_1p0']  = ((df['r_to_target_OR'] >= 0.25) & (df['r_to_target_OR'] <= 1.0)).astype(int)
        df['c_not_ifvg']       = (df['variant'] != 'ifvg').astype(int)
        df['c_no_fvg_or_ps']   = df['variant'].isin(['no_fvg', 'protected_swing']).astype(int)
        df['conf'] = df['c_or_30_100'] + df['c_rto_0p25_1p0'] + df['c_no_fvg_or_ps']

        print(f"\n\n  {'═'*40} CONFLUENCE TIERS (3 factors) {'═'*40}")
        print(f"  Confluence = OR 30-100pt + R-to-OR 0.25-1.0 + variant in (no_fvg, protected_swing)")
        for cc in (0, 1, 2, 3):
            sub = df[df['conf'] == cc]
            if len(sub) == 0: continue
            is_sub  = sub[(sub['date'] >= IS_START) & (sub['date'] <= IS_END)]
            oos_sub = sub[~((sub['date'] >= IS_START) & (sub['date'] <= IS_END))]
            print(f"\n  Conf={cc}  (n={len(sub)})")
            print(f"    IS:  {fmt(stats(is_sub))}")
            print(f"    OOS: {fmt(stats(oos_sub))}")
            print(f"    ALL: {fmt(stats(sub))}")

        # Frequency by tier
        n_years = 8.4
        print(f"\n  Trades/year by tier:")
        for cc in (0, 1, 2, 3):
            n = (df['conf'] == cc).sum()
            print(f"    Conf={cc}: {n/n_years:.1f}/yr")

        # save annotated
        df.to_csv(RESULTS_DIR / f'confluence_v2_{tf}.csv', index=False)


if __name__ == '__main__':
    main()
