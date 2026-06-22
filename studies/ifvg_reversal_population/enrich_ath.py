#!/usr/bin/env python3
"""Enrich population with ATH (all-time-high) / drawn-liquidity factors.

Per Tempo recaps R5, R7, R8, R9: ATH is "the strongest drawn liquidity in ICT".
Strategy shifts at ATH — long-only bias, smaller R targets (1R only), DOL plays
(enter TOWARD ATH when within 30-40pt).

Adds columns:
  ath_at_entry          float — running max(high) from cohort start up to entry candle
  distance_to_ath_pts   float — entry_price below ATH (positive = below)
  pct_below_ath         float — distance / ath
  is_near_ath_30pt      bool — within 30pt
  is_near_ath_50pt      bool — within 50pt
  is_near_ath_100pt     bool — within 100pt
  ath_swept_today       bool — today's high exceeded prior cohort ATH
  session_high_at_entry float — today's session high so far at entry time
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pandas as pd

from fvgc.data import load_candles

DATA_PATH = Path('data/consolidated/nq-front-month.ohlcv-30s.csv')
POP_PATH = Path('studies/ifvg_reversal_population/results/population_enriched.csv')
OUT_PATH = POP_PATH


def main():
    print("=== ATH / drawn-liquidity enrichment ===\n")
    t0 = time.time()

    pop = pd.read_csv(POP_PATH)
    print(f"  population: {len(pop)} rows")
    if 'date' not in pop.columns:
        pop['date'] = pd.to_datetime(pop['entry_ts'], utc=True, format='mixed').dt.date.astype(str)

    candles = load_candles(DATA_PATH)
    cohort_min = pop['date'].min()
    cohort_max = pop['date'].max()
    candles = candles[
        (candles['timestamp_ny'].dt.tz_localize(None) >= pd.Timestamp(cohort_min)) &
        (candles['timestamp_ny'].dt.tz_localize(None) <= pd.Timestamp(cohort_max) + pd.Timedelta(days=1))
    ].copy()
    candles['date_ny'] = candles['timestamp_ny'].dt.date.astype(str)
    candles_by_date = {d: g[['timestamp_ny', 'open', 'high', 'low', 'close']].reset_index(drop=True)
                       for d, g in candles.groupby('date_ny', sort=False)}
    print(f"  candles loaded in {time.time()-t0:.1f}s")

    # Pre-compute running-max ATH per date (= max high through end of that day).
    # For "ATH at entry" within a day, we need running max up to the entry candle.
    daily_max_high = candles.groupby('date_ny', sort=False)['high'].max().reset_index()
    daily_max_high.columns = ['date_ny', 'day_max_high']
    daily_max_high['cohort_ath_through_day'] = daily_max_high['day_max_high'].cummax()
    daily_max_high['cohort_ath_through_PRIOR_day'] = (
        daily_max_high['cohort_ath_through_day'].shift(1).fillna(daily_max_high['day_max_high'].iloc[0])
    )
    prior_day_ath = dict(zip(daily_max_high['date_ny'], daily_max_high['cohort_ath_through_PRIOR_day']))

    t = time.time()
    rows_data = []
    for _, row in pop.iterrows():
        date_str = row['date']
        entry_ts = pd.to_datetime(row['entry_ts'], utc=True, format='mixed')
        entry_price = row['entry_price']

        prior_ath = prior_day_ath.get(date_str, entry_price)

        # Session high up to entry candle (intraday running)
        day = candles_by_date.get(date_str)
        if day is None or day.empty:
            session_high = entry_price
        else:
            prior_bars = day[day['timestamp_ny'] < entry_ts]
            session_high = prior_bars['high'].max() if not prior_bars.empty else entry_price

        ath_at_entry = max(prior_ath, session_high)
        distance = ath_at_entry - entry_price
        pct = distance / max(ath_at_entry, 1e-9)
        ath_swept_today = session_high > prior_ath

        rows_data.append({
            'ath_at_entry': float(ath_at_entry),
            'distance_to_ath_pts': float(distance),
            'pct_below_ath': float(pct),
            'is_near_ath_30pt': bool(distance <= 30),
            'is_near_ath_50pt': bool(distance <= 50),
            'is_near_ath_100pt': bool(distance <= 100),
            'ath_swept_today': bool(ath_swept_today),
            'session_high_at_entry': float(session_high),
        })

    add_df = pd.DataFrame(rows_data)
    for col in add_df.columns:
        pop[col] = add_df[col].values

    pop.to_csv(OUT_PATH, index=False)
    print(f"  enriched in {time.time()-t:.1f}s\n")

    # Sanity preview + quick lift
    print(f"Distance-to-ATH distribution:")
    print(f"  median: {pop['distance_to_ath_pts'].median():.0f}pt")
    print(f"  p25:    {pop['distance_to_ath_pts'].quantile(0.25):.0f}pt")
    print(f"  p75:    {pop['distance_to_ath_pts'].quantile(0.75):.0f}pt")
    print()
    print(f"Near-ATH flags:")
    for col in ('is_near_ath_30pt', 'is_near_ath_50pt', 'is_near_ath_100pt'):
        n = pop[col].sum()
        print(f"  {col:25} {n:4} / {len(pop)} ({n/len(pop)*100:.0f}%)")
    print()
    print(f"Quick WR/PF lift — near ATH (50pt) by direction:")
    for direction in ('long', 'short'):
        for label, mask in (('near_ath_50', pop['is_near_ath_50pt'] & (pop['direction']==direction)),
                            ('far_from_ath', ~pop['is_near_ath_50pt'] & (pop['direction']==direction))):
            sub = pop[mask]
            if len(sub) == 0:
                continue
            w = (sub['r_multiple']>0).sum(); l = (sub['r_multiple']<0).sum()
            gw = sub.loc[sub['r_multiple']>0, 'pnl_pts'].sum()
            gl = abs(sub.loc[sub['r_multiple']<0, 'pnl_pts'].sum()) or 1e-9
            wr = w/max(w+l,1)*100
            print(f"  {direction:5} {label:15} N={len(sub):4} WR={wr:5.1f}% PF={gw/gl:.2f}")

    print(f"\nWrote {OUT_PATH}")


if __name__ == '__main__':
    main()
