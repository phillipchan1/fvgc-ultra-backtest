#!/usr/bin/env python3
"""Enrich population with structural target factors (equal H/L + N-day rolling H/L).

Per Tempo recaps (R1 'equal lows inside FVG', R2 'PDH target', R3 'low of week',
R5 'ATH magnet', R6 'data low', etc.): structural levels are universal targets/triggers.

For each trade, computes distance to:
  - Nearest unbroken equal-H cluster above entry
  - Nearest unbroken equal-L cluster below entry
  - 5-day high / 5-day low
  - 20-day high / 20-day low
  - HOD / LOD (today's running high/low at entry)

Output columns added to population_enriched.csv:
  distance_to_nearest_eq_high_pts        float (or NaN if none)
  nearest_eq_high_touch_count            int
  distance_to_nearest_eq_low_pts         float
  nearest_eq_low_touch_count             int
  distance_to_5d_high_pts                float
  distance_to_5d_low_pts                 float
  distance_to_20d_high_pts               float
  distance_to_20d_low_pts                float
  distance_to_hod_pts                    float
  distance_to_lod_pts                    float
  distance_to_target_dir_pts             float  (direction-aware: trade-direction magnet)
"""

import sys
import time
from datetime import time as dtime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pandas as pd

from fvgc.data import load_candles
from shared.structural_levels import (
    cluster_swings, detect_swing_pivots, mark_broken_clusters,
    nearest_active_cluster, rolling_high_low,
)

DATA_PATH = Path('data/consolidated/nq-front-month.ohlcv-30s.csv')
POP_PATH = Path('studies/ifvg_reversal_population/results/population_enriched.csv')
OUT_PATH = POP_PATH

# Tunables
EQ_TOLERANCE_PTS = 3.0
EQ_MIN_TOUCHES = 2
SWING_N = 2           # 3-candle fractal swing (n=2 means n bars on each side checked)

# Equal-H/L detection is heavy if run on full cohort. Restrict to recent N days
# *before* each session for the swing pool. Two weeks is plenty for equal-H/L.
EQ_LOOKBACK_DAYS = 14


def main():
    print("=== Structural target enrichment ===\n")
    t0 = time.time()

    pop = pd.read_csv(POP_PATH)
    print(f"  population: {len(pop)} rows")
    if 'date' not in pop.columns:
        pop['date'] = pd.to_datetime(pop['entry_ts'], utc=True, format='mixed').dt.date.astype(str)

    candles = load_candles(DATA_PATH)
    cohort_min = pop['date'].min()
    cohort_max = pop['date'].max()
    # Need lookback for equal-H/L
    extended_min = pd.Timestamp(cohort_min) - pd.Timedelta(days=EQ_LOOKBACK_DAYS + 5)
    candles = candles[
        (candles['timestamp_ny'].dt.tz_localize(None) >= extended_min) &
        (candles['timestamp_ny'].dt.tz_localize(None) <= pd.Timestamp(cohort_max) + pd.Timedelta(days=1))
    ].copy()
    candles['date_ny'] = candles['timestamp_ny'].dt.date.astype(str)
    print(f"  candles loaded in {time.time()-t0:.1f}s ({len(candles):,} rows)")

    # Rolling N-day H/L (precomputed once for whole cohort)
    print("  computing rolling N-day H/L...")
    t = time.time()
    roll_5 = rolling_high_low(candles, n_days=5).rename(
        columns={'n_day_high': 'h5', 'n_day_low': 'l5'})
    roll_20 = rolling_high_low(candles, n_days=20).rename(
        columns={'n_day_high': 'h20', 'n_day_low': 'l20'})
    rolling = roll_5.merge(roll_20, on='date_ny', how='outer')
    rolling_by_date = rolling.set_index('date_ny').to_dict('index')
    print(f"    done in {time.time()-t:.1f}s")

    # Per-day swing pivots + equal-H/L clusters
    # To avoid recomputing for every trade, precompute clusters per session
    # using EQ_LOOKBACK_DAYS of prior candles + same-day candles up to RTH end.
    print("  detecting swing pivots + clusters per session...")
    t = time.time()
    candles_by_date_sorted = sorted(candles['date_ny'].unique())
    clusters_by_date: dict = {}
    for date_str in candles_by_date_sorted:
        # Skip cohort warm-up days
        if date_str < cohort_min:
            continue
        # Use lookback of EQ_LOOKBACK_DAYS + same-day pre-RTH for swings
        lookback_cutoff = pd.Timestamp(date_str) - pd.Timedelta(days=EQ_LOOKBACK_DAYS)
        lb_str = lookback_cutoff.strftime('%Y-%m-%d')
        same_or_prior = candles[(candles['date_ny'] >= lb_str) & (candles['date_ny'] <= date_str)]
        # Cap at 11:00 NY on same date to avoid lookahead within the trading session
        same_day_mask = (same_or_prior['date_ny'] == date_str) & \
                        (same_or_prior['timestamp_ny'].dt.time > dtime(11, 0))
        sw_input = same_or_prior[~same_day_mask].sort_values('timestamp_ny').reset_index(drop=True)
        if len(sw_input) < 5:
            clusters_by_date[date_str] = []
            continue
        highs, lows = detect_swing_pivots(sw_input, n=SWING_N)
        eq_highs = cluster_swings(highs, tolerance_pts=EQ_TOLERANCE_PTS, min_touches=EQ_MIN_TOUCHES)
        eq_lows  = cluster_swings(lows,  tolerance_pts=EQ_TOLERANCE_PTS, min_touches=EQ_MIN_TOUCHES)
        # Mark broken using all candles up to end of session day
        end_of_day = same_or_prior[same_or_prior['date_ny'] <= date_str]
        mark_broken_clusters(eq_highs, end_of_day)
        mark_broken_clusters(eq_lows, end_of_day)
        clusters_by_date[date_str] = eq_highs + eq_lows
    print(f"    done in {time.time()-t:.1f}s ({sum(len(v) for v in clusters_by_date.values())} clusters total)")

    # Per-trade lookup
    print("  enriching trades...")
    t = time.time()
    candles_by_date = {d: g[['timestamp_ny', 'high', 'low', 'close']].reset_index(drop=True)
                       for d, g in candles.groupby('date_ny', sort=False)}

    rows_data = []
    for _, row in pop.iterrows():
        date_str = row['date']
        entry_ts = pd.to_datetime(row['entry_ts'], utc=True, format='mixed')
        entry = row['entry_price']
        direction = row['direction']

        clusters = clusters_by_date.get(date_str, [])
        eq_high = nearest_active_cluster(clusters, entry_ts, entry, 'above')
        eq_low  = nearest_active_cluster(clusters, entry_ts, entry, 'below')

        # Rolling H/L
        roll = rolling_by_date.get(date_str, {})
        h5  = roll.get('h5');  l5  = roll.get('l5')
        h20 = roll.get('h20'); l20 = roll.get('l20')

        # HOD/LOD (running, pre-entry)
        day = candles_by_date.get(date_str)
        if day is not None and not day.empty:
            prior = day[day['timestamp_ny'] < entry_ts]
            hod = prior['high'].max() if not prior.empty else entry
            lod = prior['low'].min() if not prior.empty else entry
        else:
            hod = lod = entry

        # Distances (positive = level is in that direction from entry)
        def above(p):
            return float(p - entry) if (p is not None and p > entry) else None
        def below(p):
            return float(entry - p) if (p is not None and p < entry) else None

        d_eq_high = above(eq_high.price) if eq_high else None
        d_eq_low  = below(eq_low.price)  if eq_low else None
        d_5h  = above(h5);  d_5l  = below(l5)
        d_20h = above(h20); d_20l = below(l20)
        d_hod = above(hod); d_lod = below(lod)

        # Direction-aware: nearest target in trade direction
        if direction == 'long':
            candidates = [d for d in (d_eq_high, d_5h, d_20h, d_hod) if d is not None and d > 0]
            target_dir = min(candidates) if candidates else None
        elif direction == 'short':
            candidates = [d for d in (d_eq_low, d_5l, d_20l, d_lod) if d is not None and d > 0]
            target_dir = min(candidates) if candidates else None
        else:
            target_dir = None

        rows_data.append({
            'distance_to_nearest_eq_high_pts': d_eq_high,
            'nearest_eq_high_touch_count':     eq_high.touch_count if eq_high else None,
            'distance_to_nearest_eq_low_pts':  d_eq_low,
            'nearest_eq_low_touch_count':      eq_low.touch_count if eq_low else None,
            'distance_to_5d_high_pts':  d_5h,
            'distance_to_5d_low_pts':   d_5l,
            'distance_to_20d_high_pts': d_20h,
            'distance_to_20d_low_pts':  d_20l,
            'distance_to_hod_pts':      d_hod,
            'distance_to_lod_pts':      d_lod,
            'distance_to_target_dir_pts': target_dir,
        })

    add_df = pd.DataFrame(rows_data)
    for col in add_df.columns:
        pop[col] = add_df[col].values

    pop.to_csv(OUT_PATH, index=False)
    print(f"    done in {time.time()-t:.1f}s")
    print(f"\nWrote {OUT_PATH}")

    # Quick distribution preview
    print("\n=== distance_to_target_dir_pts distribution ===")
    print(f"  median: {pop['distance_to_target_dir_pts'].median():.0f}pt")
    print(f"  p25:    {pop['distance_to_target_dir_pts'].quantile(0.25):.0f}pt")
    print(f"  p75:    {pop['distance_to_target_dir_pts'].quantile(0.75):.0f}pt")
    print(f"  null:   {pop['distance_to_target_dir_pts'].isna().sum()} / {len(pop)}")

    # Lift by distance-to-target bucket
    print("\n=== Lift by distance_to_target_dir_pts (in trade direction) ===")
    buckets = [(0, 30), (30, 60), (60, 100), (100, 200), (200, 1000)]
    for low, high in buckets:
        mask = ((pop['distance_to_target_dir_pts'] > low) &
                (pop['distance_to_target_dir_pts'] <= high))
        sub = pop[mask]
        if len(sub) == 0:
            continue
        w = (sub['r_multiple']>0).sum(); l = (sub['r_multiple']<0).sum()
        gw = sub.loc[sub['r_multiple']>0, 'pnl_pts'].sum()
        gl = abs(sub.loc[sub['r_multiple']<0, 'pnl_pts'].sum()) or 1e-9
        print(f"  {low:>4}-{high:<4}pt  N={len(sub):4}  WR={w/max(w+l,1)*100:5.1f}%  PF={gw/gl:.2f}")


if __name__ == '__main__':
    main()
