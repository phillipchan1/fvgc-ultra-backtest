#!/usr/bin/env python3
"""
Level-behavior comparison: prior-day 50% mid vs VAH / VAL / POC.

Answers two questions:
  Q1. As a target magnet, does the 50% mid behave like other level types?
      → reach rate by R-distance bucket, side-by-side.
  Q2. Does the mid act like resistance (tag-then-reverse) or transparency
      (tag-then-continue)?
      → among trades that reach a level, what fraction eventually LOSE,
        and what's the median MFE-beyond-level.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
TRADES = ROOT / 'data' / 'levels' / 'trades_with_pd_mid.csv'

LEVELS = {
    'pd_hl_mid': 'pd_hl_mid',
    'pd_va_mid': 'pd_va_mid',
    'prior_vp_poc': 'prior_vp_poc',
    'prior_vp_vah': 'prior_vp_vah',
    'prior_vp_val': 'prior_vp_val',
}
BUCKETS = [(0.0, 1.0), (1.0, 2.0), (2.0, 3.0)]


def direction_aligned(level: str, direction: pd.Series,
                      level_val: pd.Series, entry: pd.Series) -> pd.Series:
    """Keep rows where the level sits in the trade direction beyond entry.
    Needed so 'reach' means 'reached as a TP', not 'price crossed it backwards'.
    """
    long_ok = (direction == 'long') & (level_val > entry)
    short_ok = (direction == 'short') & (level_val < entry)
    return long_ok | short_ok


def main():
    df = pd.read_csv(TRADES)
    df = df[df['outcome'].isin(['win', 'loss'])].copy()
    entry = df['entry_price']
    direction = df['direction']
    sl_dist = df['sl_dist']
    mfe = pd.to_numeric(df['mfe_pts'], errors='coerce')

    print('=' * 78)
    print('  Q1 — REACH RATE BY DISTANCE BUCKET (directionally aligned)')
    print('=' * 78)

    reach_rows = []
    for label, col in LEVELS.items():
        lvl = df[col]
        in_dir = direction_aligned(label, direction, lvl, entry)
        dist_pts = (lvl - entry).abs()
        dist_r = dist_pts / sl_dist
        reached = mfe >= dist_pts

        # Overall
        sub = df[df[col].notna() & in_dir]
        if len(sub) > 0:
            m = mfe[sub.index] >= (lvl - entry).abs()[sub.index]
            reach_rows.append({
                'level': label,
                'bucket': 'all dir-aligned',
                'n': len(sub),
                'reach_rate': round(m.mean() * 100, 1),
            })
        for lo, hi in BUCKETS:
            mask = df[col].notna() & in_dir & (dist_r >= lo) & (dist_r < hi)
            cell = df[mask]
            if len(cell) == 0:
                continue
            m = (mfe[cell.index] >= dist_pts[cell.index])
            reach_rows.append({
                'level': label,
                'bucket': f'{lo:.1f}-{hi:.1f}R',
                'n': len(cell),
                'reach_rate': round(m.mean() * 100, 1),
            })

    reach_df = pd.DataFrame(reach_rows)
    pivot = reach_df.pivot_table(
        index='level', columns='bucket', values='reach_rate', aggfunc='first'
    )
    n_pivot = reach_df.pivot_table(
        index='level', columns='bucket', values='n', aggfunc='first'
    )
    print('\n  Reach rate (%):')
    print(pivot.to_string())
    print('\n  Sample sizes (n):')
    print(n_pivot.to_string())

    print('\n' + '=' * 78)
    print('  Q2 — RESISTANCE BEHAVIOR: do trades that TAG the level then LOSE?')
    print('  (Null = 51.7% baseline loss rate. Elevated = level acts as resistance.)')
    print('=' * 78)

    rows = []
    for label, col in LEVELS.items():
        lvl = df[col]
        in_dir = direction_aligned(label, direction, lvl, entry)
        dist_pts = (lvl - entry).abs()
        dist_r = dist_pts / sl_dist
        reached = mfe >= dist_pts

        # Within each bucket: among reached trades, what % ultimately lose?
        # Plus median MFE-beyond-level to see if price bounces tightly or continues
        for lo, hi in BUCKETS:
            mask = df[col].notna() & in_dir & (dist_r >= lo) & (dist_r < hi) & reached
            cell = df[mask]
            if len(cell) == 0:
                continue
            loss_rate = (cell['outcome'] == 'loss').mean() * 100
            mfe_beyond = mfe[cell.index] - dist_pts[cell.index]
            # In R terms
            mfe_beyond_r = mfe_beyond / sl_dist[cell.index]
            rows.append({
                'level': label,
                'bucket': f'{lo:.1f}-{hi:.1f}R',
                'n_reached': len(cell),
                'loss_rate_after_tag': round(loss_rate, 1),
                'median_mfe_beyond_R': round(float(mfe_beyond_r.median()), 2),
                'p75_mfe_beyond_R': round(float(mfe_beyond_r.quantile(0.75)), 2),
            })
    tag_df = pd.DataFrame(rows)
    print('\n  Loss rate AFTER tagging level (higher = more resistance-like):')
    loss_pivot = tag_df.pivot_table(
        index='level', columns='bucket', values='loss_rate_after_tag', aggfunc='first'
    )
    print(loss_pivot.to_string())
    print('\n  Median MFE beyond the level in R (lower = tighter stop-and-reverse):')
    mfe_pivot = tag_df.pivot_table(
        index='level', columns='bucket', values='median_mfe_beyond_R', aggfunc='first'
    )
    print(mfe_pivot.to_string())

    # Save
    out_dir = ROOT / 'studies' / 'pd_50pct_level' / 'results'
    out_dir.mkdir(parents=True, exist_ok=True)
    reach_df.to_csv(out_dir / 'level_comparison_reach.csv', index=False)
    tag_df.to_csv(out_dir / 'level_comparison_resistance.csv', index=False)
    print(f'\n  Wrote results to {out_dir}/level_comparison_*.csv')


if __name__ == '__main__':
    main()
