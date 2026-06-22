#!/usr/bin/env python3
"""Enrich population with SMT (Smart Money Technique) divergence factors.

Tempo's most-cited factor (11 mentions across 10 recaps). Loads NQ + ES candles
(both in data/consolidated/) and at each trade's SWEEP time, checks whether the
two indices diverged on session extremes within the lookback window.

Output columns:
  smt_bullish_at_sweep       bool — one made new session low, the other didn't
  smt_bearish_at_sweep       bool — one made new session high, the other didn't
  smt_aligns_with_direction  bool — for long trades: bullish_smt present;
                                    for short trades: bearish_smt present
  nq_new_low_in_window       bool
  nq_new_high_in_window      bool
  es_new_low_in_window       bool
  es_new_high_in_window      bool
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pandas as pd

from fvgc.data import load_candles
from shared.smt_detector import smt_at

NQ_PATH = Path('data/consolidated/nq-front-month.ohlcv-30s.csv')
ES_PATH = Path('data/consolidated/es-front-month.ohlcv-30s.csv')
POP_PATH = Path('studies/ifvg_reversal_population/results/population_enriched.csv')

SMT_LOOKBACK_SECONDS = 300  # 5-min window


def main():
    print("=== SMT enrichment (ES↔NQ divergence) ===\n")
    t0 = time.time()

    if not ES_PATH.exists():
        print(f"ERROR: ES file not found at {ES_PATH}")
        print("Run `python tools/consolidate_es.py` first.")
        sys.exit(1)

    pop = pd.read_csv(POP_PATH)
    print(f"  population: {len(pop)} rows")

    # Load both NQ and ES 30s candles for the cohort range
    if 'date' not in pop.columns:
        pop['date'] = pd.to_datetime(pop['entry_ts'], utc=True, format='mixed').dt.date.astype(str)
    cohort_min = pop['date'].min()
    cohort_max = pop['date'].max()

    nq = load_candles(NQ_PATH)
    es = load_candles(ES_PATH)
    for name, df in (('NQ', nq), ('ES', es)):
        df_filt = df[
            (df['timestamp_ny'].dt.tz_localize(None) >= pd.Timestamp(cohort_min)) &
            (df['timestamp_ny'].dt.tz_localize(None) <= pd.Timestamp(cohort_max) + pd.Timedelta(days=1))
        ]
        print(f"  {name}: {len(df_filt):,} candles in cohort window")
    nq = nq[
        (nq['timestamp_ny'].dt.tz_localize(None) >= pd.Timestamp(cohort_min)) &
        (nq['timestamp_ny'].dt.tz_localize(None) <= pd.Timestamp(cohort_max) + pd.Timedelta(days=1))
    ].copy()
    es = es[
        (es['timestamp_ny'].dt.tz_localize(None) >= pd.Timestamp(cohort_min)) &
        (es['timestamp_ny'].dt.tz_localize(None) <= pd.Timestamp(cohort_max) + pd.Timedelta(days=1))
    ].copy()
    print(f"  loaded in {time.time()-t0:.1f}s")

    # Index ES by date for fast slicing in inner loop
    nq_by_date = {d: g[['timestamp_ny', 'high', 'low', 'close']].reset_index(drop=True)
                  for d, g in nq.groupby(nq['timestamp_ny'].dt.date.astype(str), sort=False)}
    es_by_date = {d: g[['timestamp_ny', 'high', 'low', 'close']].reset_index(drop=True)
                  for d, g in es.groupby(es['timestamp_ny'].dt.date.astype(str), sort=False)}

    t = time.time()
    rows_data = []
    for _, row in pop.iterrows():
        date_str = row['date']
        sweep_ts = pd.to_datetime(row['sweep_ts'], utc=True, format='mixed')
        direction = row['direction']

        nq_day = nq_by_date.get(date_str)
        es_day = es_by_date.get(date_str)

        if nq_day is None or es_day is None or nq_day.empty or es_day.empty:
            rows_data.append({
                'smt_bullish_at_sweep': False, 'smt_bearish_at_sweep': False,
                'smt_aligns_with_direction': False,
                'nq_new_low_in_window': False, 'nq_new_high_in_window': False,
                'es_new_low_in_window': False, 'es_new_high_in_window': False,
            })
            continue

        smt = smt_at(nq_day, es_day, sweep_ts, lookback_seconds=SMT_LOOKBACK_SECONDS)
        align = (direction == 'long' and smt.bullish_smt) or \
                (direction == 'short' and smt.bearish_smt)

        rows_data.append({
            'smt_bullish_at_sweep': smt.bullish_smt,
            'smt_bearish_at_sweep': smt.bearish_smt,
            'smt_aligns_with_direction': align,
            'nq_new_low_in_window': smt.primary_made_new_low,
            'nq_new_high_in_window': smt.primary_made_new_high,
            'es_new_low_in_window': smt.secondary_made_new_low,
            'es_new_high_in_window': smt.secondary_made_new_high,
        })

    add_df = pd.DataFrame(rows_data)
    for col in add_df.columns:
        pop[col] = add_df[col].values

    pop.to_csv(POP_PATH, index=False)
    print(f"  enriched in {time.time()-t:.1f}s")
    print(f"\nWrote {POP_PATH}")

    # Quick lift preview
    print("\n=== SMT factor lift preview ===\n")
    print(f"SMT-aligns-with-direction rate: {pop['smt_aligns_with_direction'].mean()*100:.1f}%")
    print(f"  Bullish SMT firing rate: {pop['smt_bullish_at_sweep'].mean()*100:.1f}%")
    print(f"  Bearish SMT firing rate: {pop['smt_bearish_at_sweep'].mean()*100:.1f}%")

    print(f"\n--- WR/PF: SMT aligns vs not (by direction) ---")
    for direction in ('long', 'short'):
        for label, mask in (('SMT_aligns', pop['smt_aligns_with_direction']),
                            ('no_SMT',     ~pop['smt_aligns_with_direction'])):
            sub = pop[(pop['direction'] == direction) & mask]
            if len(sub) == 0:
                continue
            w = (sub['r_multiple']>0).sum(); l = (sub['r_multiple']<0).sum()
            gw = sub.loc[sub['r_multiple']>0, 'pnl_pts'].sum()
            gl = abs(sub.loc[sub['r_multiple']<0, 'pnl_pts'].sum()) or 1e-9
            wr = w/max(w+l,1)*100
            print(f"  {direction:5} {label:12} N={len(sub):4} WR={wr:5.1f}%  PF={gw/gl:.2f}")


if __name__ == '__main__':
    main()
