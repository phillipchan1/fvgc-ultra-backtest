#!/usr/bin/env python3
"""
Enrich baseline trades with prior-day volume profile proximity columns.

Reads: logs/baseline_trades.csv + data/levels/daily_volume_profile.csv
Writes: data/levels/trades_with_vp.csv
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

BASELINE_PATH = ROOT / 'logs' / 'baseline_trades.csv'
VP_PATH = ROOT / 'data' / 'levels' / 'daily_volume_profile.csv'
OUTPUT_PATH = ROOT / 'data' / 'levels' / 'trades_with_vp.csv'

# Proximity thresholds in NQ points
PT_THRESHOLDS = [10, 15, 20]


def main():
    print('=== Enrich Trades with Volume Profile ===')

    trades = pd.read_csv(BASELINE_PATH)
    trades['timestamp'] = pd.to_datetime(trades['timestamp'])
    trades['date'] = trades['timestamp'].dt.date
    print(f'  Loaded {len(trades)} baseline trades')

    vp = pd.read_csv(VP_PATH)
    vp['date'] = pd.to_datetime(vp['date']).dt.date
    print(f'  Loaded {len(vp)} VP rows')

    # Build prior-day VP lookup: for each trade date, use the most recent VP date before it
    vp = vp.sort_values('date').reset_index(drop=True)
    vp_dates = vp['date'].values
    vp_by_date = vp.set_index('date')

    def get_prior_vp(trade_date):
        """Find the most recent VP date strictly before trade_date."""
        prior = [d for d in vp_dates if d < trade_date]
        if not prior:
            return None
        return prior[-1]

    # Map each trade to its prior-day VP
    unique_trade_dates = sorted(trades['date'].unique())
    prior_vp_map = {}
    for td in unique_trade_dates:
        pvd = get_prior_vp(td)
        if pvd is not None and pvd in vp_by_date.index:
            row = vp_by_date.loc[pvd]
            prior_vp_map[td] = {
                'prior_vp_date': pvd,
                'prior_vp_poc': row['poc'],
                'prior_vp_vah': row['vah'],
                'prior_vp_val': row['val'],
            }

    # Apply VP data to trades
    vp_cols = []
    for _, trade in trades.iterrows():
        d = trade['date']
        if d in prior_vp_map:
            vp_cols.append(prior_vp_map[d])
        else:
            vp_cols.append({
                'prior_vp_date': None,
                'prior_vp_poc': np.nan,
                'prior_vp_vah': np.nan,
                'prior_vp_val': np.nan,
            })

    vp_df = pd.DataFrame(vp_cols, index=trades.index)
    trades = pd.concat([trades, vp_df], axis=1)

    # Coverage check
    has_vp = trades['prior_vp_poc'].notna()
    print(f'  VP coverage: {has_vp.sum()}/{len(trades)} trades '
          f'({has_vp.mean()*100:.1f}%)')

    # Compute proximity columns
    entry = trades['entry_price']
    poc = trades['prior_vp_poc']
    vah = trades['prior_vp_vah']
    val = trades['prior_vp_val']
    sl_dist = trades['sl_dist']

    # Absolute distance in points
    trades['dist_to_poc_pts'] = (entry - poc).abs()
    trades['dist_to_vah_pts'] = (entry - vah).abs()
    trades['dist_to_val_pts'] = (entry - val).abs()

    # Nearest VP level
    dist_cols = trades[['dist_to_poc_pts', 'dist_to_vah_pts', 'dist_to_val_pts']]
    trades['dist_to_nearest_vp_pts'] = dist_cols.min(axis=1)
    trades['nearest_vp_level'] = dist_cols.idxmin(axis=1).map({
        'dist_to_poc_pts': 'POC',
        'dist_to_vah_pts': 'VAH',
        'dist_to_val_pts': 'VAL',
    })

    # Distance in R-multiples
    trades['dist_to_poc_R'] = trades['dist_to_poc_pts'] / sl_dist
    trades['dist_to_vah_R'] = trades['dist_to_vah_pts'] / sl_dist
    trades['dist_to_val_R'] = trades['dist_to_val_pts'] / sl_dist
    trades['dist_to_nearest_vp_R'] = trades['dist_to_nearest_vp_pts'] / sl_dist

    # Boolean proximity flags at multiple thresholds
    for th in PT_THRESHOLDS:
        trades[f'near_poc_{th}pt'] = trades['dist_to_poc_pts'] <= th
        trades[f'near_vah_{th}pt'] = trades['dist_to_vah_pts'] <= th
        trades[f'near_val_{th}pt'] = trades['dist_to_val_pts'] <= th
        trades[f'near_any_vp_{th}pt'] = (
            trades[f'near_poc_{th}pt'] |
            trades[f'near_vah_{th}pt'] |
            trades[f'near_val_{th}pt']
        )

    # R-based proximity
    trades['near_any_vp_1R'] = trades['dist_to_nearest_vp_R'] <= 1.0
    trades['near_any_vp_half_R'] = trades['dist_to_nearest_vp_R'] <= 0.5

    # Position relative to value area
    trades['entry_in_value_area'] = (entry >= val) & (entry <= vah)
    trades['entry_above_va'] = entry > vah
    trades['entry_below_va'] = entry < val

    # Directionally aligned VP confluence
    direction = trades['direction']
    trades['long_near_val'] = (direction == 'long') & (trades['dist_to_val_pts'] <= 15)
    trades['short_near_vah'] = (direction == 'short') & (trades['dist_to_vah_pts'] <= 15)
    trades['directional_vp_aligned'] = trades['long_near_val'] | trades['short_near_vah']

    # Drop intermediate date column
    trades = trades.drop(columns=['date'])

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    trades.to_csv(OUTPUT_PATH, index=False)
    print(f'\n  Wrote {len(trades)} enriched trades to {OUTPUT_PATH}')

    # Quick summary
    tradeable = trades[trades['outcome'].isin(['win', 'loss'])]
    print(f'\n  Tradeable (win/loss): {len(tradeable)}')
    print(f'  Near any VP (15pt): {tradeable["near_any_vp_15pt"].sum()} '
          f'({tradeable["near_any_vp_15pt"].mean()*100:.1f}%)')
    print(f'  Inside VA: {tradeable["entry_in_value_area"].sum()} '
          f'({tradeable["entry_in_value_area"].mean()*100:.1f}%)')
    print(f'  Directional aligned: {tradeable["directional_vp_aligned"].sum()} '
          f'({tradeable["directional_vp_aligned"].mean()*100:.1f}%)')


if __name__ == '__main__':
    main()
