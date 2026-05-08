#!/usr/bin/env python3
"""
Enrich trades with prior-day 50% midpoint levels.

Adds two candidate midpoint definitions and their proximity / directional
interaction columns:
  - pd_hl_mid = (prev_day_high + prev_day_low) / 2       (geometric)
  - pd_va_mid = (prior_vp_vah  + prior_vp_val) / 2       (volume-area)

Reads:
  data/levels/trades_with_vp.csv   (base table; already has VP + trade fields)
  data/levels/session_levels.csv   (source of prev_day_high / prev_day_low)
Writes:
  data/levels/trades_with_pd_mid.csv
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

TRADES_PATH = ROOT / 'data' / 'levels' / 'trades_with_vp.csv'
SESSION_LEVELS_PATH = ROOT / 'data' / 'levels' / 'session_levels.csv'
OUTPUT_PATH = ROOT / 'data' / 'levels' / 'trades_with_pd_mid.csv'

PT_THRESHOLDS = [5, 10, 15, 20]
POC_COINCIDE_THRESHOLDS = [5, 10, 15]


def load_prev_day_hl() -> pd.DataFrame:
    """Pivot session_levels into (date, prev_day_high, prev_day_low)."""
    df = pd.read_csv(SESSION_LEVELS_PATH)
    df = df[df['level_name'].isin(['prev_day_high', 'prev_day_low'])].copy()
    df['date'] = pd.to_datetime(df['date']).dt.date
    df['price'] = pd.to_numeric(df['price'], errors='coerce')
    pivot = df.pivot_table(
        index='date', columns='level_name', values='price', aggfunc='first'
    ).reset_index()
    pivot.columns.name = None
    return pivot[['date', 'prev_day_high', 'prev_day_low']]


def add_mid_columns(trades: pd.DataFrame, mid_name: str, mid_series: pd.Series):
    """Add distance / proximity / directional columns for a given mid level."""
    entry = trades['entry_price']
    direction = trades['direction']
    sl_dist = trades['sl_dist']

    trades[mid_name] = mid_series
    dist_pts = (entry - mid_series).abs()
    trades[f'dist_to_{mid_name}_pts'] = dist_pts
    trades[f'dist_to_{mid_name}_R'] = dist_pts / sl_dist

    for th in PT_THRESHOLDS:
        trades[f'near_{mid_name}_{th}pt'] = dist_pts <= th

    trades[f'entry_above_{mid_name}'] = entry > mid_series
    trades[f'entry_below_{mid_name}'] = entry < mid_series

    # "Trading into" the mid = trade direction carries price toward the mid.
    # - Long entering BELOW mid targets UP through mid
    # - Short entering ABOVE mid targets DOWN through mid
    is_long = direction == 'long'
    is_short = direction == 'short'
    trades[f'trading_into_{mid_name}'] = (
        (is_long & (entry < mid_series)) | (is_short & (entry > mid_series))
    )
    trades[f'trading_away_{mid_name}'] = (
        (is_long & (entry > mid_series)) | (is_short & (entry < mid_series))
    )

    # POC coincidence flags — does the prior-day POC sit close to this mid?
    poc = trades['prior_vp_poc']
    poc_dist = (poc - mid_series).abs()
    for th in POC_COINCIDE_THRESHOLDS:
        trades[f'poc_coincides_{mid_name}_{th}pt'] = poc_dist <= th


def main():
    print('=== Enrich Trades with Prior-Day 50% Midpoints ===')

    trades = pd.read_csv(TRADES_PATH)
    trades['timestamp'] = pd.to_datetime(trades['timestamp'])
    trades['date'] = trades['timestamp'].dt.date
    print(f'  Loaded {len(trades)} VP-enriched trades')

    hl = load_prev_day_hl()
    print(f'  Loaded prev-day H/L for {len(hl)} dates '
          f'({hl["prev_day_high"].notna().sum()} with non-null high)')

    trades = trades.merge(hl, on='date', how='left')

    # --- pd_hl_mid ----------------------------------------------------------
    pd_hl_mid = (trades['prev_day_high'] + trades['prev_day_low']) / 2.0
    add_mid_columns(trades, 'pd_hl_mid', pd_hl_mid)

    # --- pd_va_mid ----------------------------------------------------------
    pd_va_mid = (trades['prior_vp_vah'] + trades['prior_vp_val']) / 2.0
    add_mid_columns(trades, 'pd_va_mid', pd_va_mid)

    # Coverage summary
    hl_cov = trades['pd_hl_mid'].notna()
    va_cov = trades['pd_va_mid'].notna()
    print(f'  pd_hl_mid coverage: {hl_cov.sum()}/{len(trades)} '
          f'({hl_cov.mean()*100:.1f}%)')
    print(f'  pd_va_mid coverage: {va_cov.sum()}/{len(trades)} '
          f'({va_cov.mean()*100:.1f}%)')

    # Sanity asserts (plan verification section)
    va_null_matches_poc_null = (
        trades['pd_va_mid'].isna() == trades['prior_vp_poc'].isna()
    ).all()
    assert va_null_matches_poc_null, \
        'pd_va_mid null pattern must match prior_vp_poc null pattern'

    sample = trades.dropna(subset=['pd_hl_mid']).sample(
        n=min(100, hl_cov.sum()), random_state=1
    )
    recomputed = (sample['entry_price'] - sample['pd_hl_mid']).abs()
    diff = (sample['dist_to_pd_hl_mid_pts'] - recomputed).abs()
    assert (diff < 1e-6).all(), 'dist_to_pd_hl_mid_pts recomputation mismatch'

    # Drop helper column
    trades = trades.drop(columns=['date'])

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    trades.to_csv(OUTPUT_PATH, index=False)
    print(f'\n  Wrote {len(trades)} enriched trades to {OUTPUT_PATH}')

    # Quick prevalence summary on tradeable rows
    tradeable = trades[trades['outcome'].isin(['win', 'loss'])]
    print(f'\n  Tradeable (win/loss): {len(tradeable)}')
    for mid in ('pd_hl_mid', 'pd_va_mid'):
        near15 = tradeable[f'near_{mid}_15pt'].sum()
        into = tradeable[f'trading_into_{mid}'].sum()
        print(f'  {mid}: near_15pt={near15} '
              f'({near15/len(tradeable)*100:.1f}%), '
              f'trading_into={into} ({into/len(tradeable)*100:.1f}%)')

    # POC coincidence (day-level)
    daily = trades.drop_duplicates(subset=['prior_vp_date']).dropna(
        subset=['prior_vp_poc', 'pd_hl_mid', 'pd_va_mid']
    )
    if len(daily) > 0:
        for mid in ('pd_hl_mid', 'pd_va_mid'):
            for th in POC_COINCIDE_THRESHOLDS:
                col = f'poc_coincides_{mid}_{th}pt'
                pct = daily[col].mean() * 100
                print(f'  POC within {th}pt of {mid}: '
                      f'{daily[col].sum()}/{len(daily)} days ({pct:.1f}%)')


if __name__ == '__main__':
    main()
