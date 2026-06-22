#!/usr/bin/env python3
"""Enrich population with MFE_R and MAE_R per trade.

For each trade, walks forward from entry through same-day candles, tracking:
  - MFE (max favorable excursion) until soft stop fires or EOD
  - MAE (max adverse excursion) over the same window

Soft stop = candle close re-inverts the target gap (Tempo's actual exit logic,
independent of our fixed-1R target). This gives the natural "potential R upside"
for each trade — what the realized R would have been with no target cap.
"""

import sys
import time
from datetime import time as dtime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pandas as pd

from fvgc.data import load_candles

DATA_PATH = Path('data/consolidated/nq-front-month.ohlcv-30s.csv')
POP_PATH = Path('studies/ifvg_reversal_population/results/population_enriched.csv')
OUT_PATH = Path('studies/ifvg_reversal_population/results/population_enriched.csv')

_EOD = dtime(16, 0)


def main():
    print("=== MFE/MAE enrichment ===\n")
    pop = pd.read_csv(POP_PATH)
    pop['date'] = pd.to_datetime(pop['entry_ts'], utc=True, format='mixed').dt.date.astype(str)
    pop['entry_ts_dt'] = pd.to_datetime(pop['entry_ts'], utc=True, format='mixed')
    print(f"  trades: {len(pop)}")

    t0 = time.time()
    candles = load_candles(DATA_PATH)
    cohort_min = pop['date'].min()
    cohort_max = pop['date'].max()
    candles = candles[
        (candles['timestamp_ny'].dt.tz_localize(None) >= pd.Timestamp(cohort_min)) &
        (candles['timestamp_ny'].dt.tz_localize(None) <= pd.Timestamp(cohort_max) + pd.Timedelta(days=1))
    ].copy()
    candles['date_ny'] = candles['timestamp_ny'].dt.date.astype(str)
    print(f"  candles loaded in {time.time()-t0:.1f}s ({len(candles):,} rows)")

    # Index candles by date for fast lookup
    candles_by_date = {d: g[['timestamp_ny', 'high', 'low', 'close']].reset_index(drop=True)
                       for d, g in candles.groupby('date_ny', sort=False)}

    # Compute per trade
    t = time.time()
    mfe_r_list = []
    mae_r_list = []
    mfe_pts_list = []
    mae_pts_list = []
    bars_to_invalidation = []

    for _, row in pop.iterrows():
        direction = row['direction']
        entry_ts = row['entry_ts_dt']
        entry = row['entry_price']
        gap_top = row['gap_top']
        gap_bottom = row['gap_bottom']
        stop_d = max(row['stop_distance_pts'], 1e-9)

        day = candles_by_date.get(row['date'])
        if day is None or day.empty:
            mfe_r_list.append(0.0); mae_r_list.append(0.0)
            mfe_pts_list.append(0.0); mae_pts_list.append(0.0)
            bars_to_invalidation.append(0)
            continue

        forward = day[
            (day['timestamp_ny'] > entry_ts) &
            (day['timestamp_ny'].dt.time <= _EOD)
        ]
        if forward.empty:
            mfe_r_list.append(0.0); mae_r_list.append(0.0)
            mfe_pts_list.append(0.0); mae_pts_list.append(0.0)
            bars_to_invalidation.append(0)
            continue

        max_fav_pts = 0.0
        max_adv_pts = 0.0
        bars = 0
        for c in forward.itertuples(index=False):
            bars += 1
            # Track MFE/MAE on this bar
            if direction == 'short':
                # favorable = price moving DOWN from entry
                fav = entry - c.low
                adv = c.high - entry
            else:
                fav = c.high - entry
                adv = entry - c.low
            if fav > max_fav_pts:
                max_fav_pts = fav
            if adv > max_adv_pts:
                max_adv_pts = adv

            # Soft stop check on close
            if direction == 'short' and c.close > gap_top:
                break
            if direction == 'long' and c.close < gap_bottom:
                break

        mfe_pts_list.append(max_fav_pts)
        mae_pts_list.append(max_adv_pts)
        mfe_r_list.append(max_fav_pts / stop_d)
        mae_r_list.append(max_adv_pts / stop_d)
        bars_to_invalidation.append(bars)

    pop['mfe_pts'] = mfe_pts_list
    pop['mae_pts'] = mae_pts_list
    pop['mfe_r'] = mfe_r_list
    pop['mae_r'] = mae_r_list
    pop['bars_to_invalidation'] = bars_to_invalidation
    pop = pop.drop(columns=['entry_ts_dt'])

    pop.to_csv(OUT_PATH, index=False)
    print(f"  enriched in {time.time()-t:.1f}s\n")

    # Quick overview
    print("MFE_R distribution:")
    print(f"  median: {pop['mfe_r'].median():.2f}")
    print(f"  p25:    {pop['mfe_r'].quantile(0.25):.2f}")
    print(f"  p75:    {pop['mfe_r'].quantile(0.75):.2f}")
    print(f"  p90:    {pop['mfe_r'].quantile(0.90):.2f}")
    print(f"  max:    {pop['mfe_r'].max():.2f}")
    print(f"  pct trades with MFE >= 1R: {(pop['mfe_r']>=1.0).mean()*100:.1f}%")
    print(f"  pct trades with MFE >= 2R: {(pop['mfe_r']>=2.0).mean()*100:.1f}%")
    print(f"  pct trades with MFE >= 3R: {(pop['mfe_r']>=3.0).mean()*100:.1f}%")

    print("\nMAE_R distribution:")
    print(f"  median: {pop['mae_r'].median():.2f}")
    print(f"  p75:    {pop['mae_r'].quantile(0.75):.2f}")
    print(f"  p90:    {pop['mae_r'].quantile(0.90):.2f}")

    print(f"\nWrote {OUT_PATH}")


if __name__ == '__main__':
    main()
