#!/usr/bin/env python3
"""Enrich population.csv with:
  - prior_same_dir_sweep_count  — Tempo "stacked liquidity" (cascading sweeps)
  - remaining_same_dir_unswept  — Tempo "still nearby = magnet against us"
  - news flag columns from trading_days.csv (where coverage exists)

Sweep detection re-run is fast (~9s on 5-year cohort) — no need to re-run the
full population generator.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pandas as pd

from fvgc.data import load_candles
from ifvg_reversal.constants import ACTIVE_SWEEP_LEVELS, SWEEP_LEVEL_SIDE
from ifvg_reversal.detectors.sweep import detect_sweeps

DATA_PATH = Path('data/consolidated/nq-front-month.ohlcv-30s.csv')
LEVELS_PATH = Path('data/levels/session_levels.csv')
TRADING_DAYS_PATH = Path('data/trading_days/trading_days.csv')
POP_PATH = Path('studies/ifvg_reversal_population/results/population.csv')
OUT_PATH = Path('studies/ifvg_reversal_population/results/population_enriched.csv')

# "Nearby" definition for unswept-remaining factor.
NEARBY_PTS = 50.0


def main():
    print("=== Enriching population.csv ===\n")

    pop = pd.read_csv(POP_PATH)
    pop['date'] = pd.to_datetime(pop['entry_ts'], utc=True, format='mixed').dt.date.astype(str)
    print(f"  population: {len(pop)} rows")

    # --- Load candles + levels for the population's date range ---
    t0 = time.time()
    candles = load_candles(DATA_PATH)
    levels = pd.read_csv(LEVELS_PATH)

    cohort_min = pop['date'].min()
    cohort_max = pop['date'].max()
    print(f"  cohort: {cohort_min} -> {cohort_max}")

    candles = candles[
        (candles['timestamp_ny'].dt.tz_localize(None) >= pd.Timestamp(cohort_min)) &
        (candles['timestamp_ny'].dt.tz_localize(None) <= pd.Timestamp(cohort_max) + pd.Timedelta(days=1))
    ].copy()
    levels = levels[
        (pd.to_datetime(levels['date']) >= pd.Timestamp(cohort_min)) &
        (pd.to_datetime(levels['date']) <= pd.Timestamp(cohort_max))
    ].copy()
    print(f"  loaded in {time.time()-t0:.1f}s "
          f"({len(candles):,} candles, {levels['date'].nunique()} sessions)\n")

    # --- Re-run sweep detection to get ALL sweeps (not just trade-producing) ---
    t = time.time()
    all_sweeps = detect_sweeps(candles, levels)
    print(f"  detected {len(all_sweeps):,} total sweeps in cohort ({time.time()-t:.1f}s)")

    # Index sweeps by date for fast lookup.
    sweeps_by_date = {}
    for s in all_sweeps:
        d = str(s.timestamp_ny.date())
        sweeps_by_date.setdefault(d, []).append(s)

    # Index levels by date for unswept-remaining lookup.
    levels_active = levels[levels['level_name'].isin(ACTIVE_SWEEP_LEVELS)].copy()
    levels_active = levels_active[levels_active['price'].notna()]
    levels_by_date = {}
    for d, day_levels in levels_active.groupby('date'):
        levels_by_date[d] = day_levels.to_dict('records')

    # --- Per-row enrichment ---
    t = time.time()
    prior_counts = []
    prior_lists = []
    unswept_counts = []
    unswept_lists = []

    for _, row in pop.iterrows():
        date = row['date']
        sweep_ts = pd.to_datetime(row['sweep_ts'], utc=True, format='mixed')
        sweep_level = row['sweep_level']
        # Side of the swept level: 'high' or 'low'. Same-side = same liquidity pool type.
        sweep_side = SWEEP_LEVEL_SIDE.get(sweep_level)

        day_sweeps = sweeps_by_date.get(date, [])

        # PRIOR same-side sweeps (earlier in day, same high/low type, NOT this one)
        prior_same = [
            s for s in day_sweeps
            if SWEEP_LEVEL_SIDE.get(s.level_name) == sweep_side
            and pd.Timestamp(s.timestamp_ny).tz_convert('UTC') < sweep_ts
            and s.level_name != sweep_level
        ]
        prior_counts.append(len(prior_same))
        prior_lists.append('|'.join(sorted({s.level_name for s in prior_same})))

        # REMAINING same-side unswept levels NEARBY (potential magnets continuing in sweep direction)
        # For a short setup (high swept), unswept HIGHS above current price = upside magnets
        # For a long setup (low swept), unswept LOWS below current price = downside magnets
        day_levels = levels_by_date.get(date, [])
        sweep_price = float(row['entry_price'])  # use entry price as reference
        # Already-swept set: pre-RTH from levels CSV + already-RTH-swept levels at this point
        swept_already = set()
        for lvl in day_levels:
            if lvl.get('swept_pre_rth') is True:
                swept_already.add(lvl['level_name'])
        for s in day_sweeps:
            if pd.Timestamp(s.timestamp_ny).tz_convert('UTC') <= sweep_ts:
                swept_already.add(s.level_name)

        remaining = []
        for lvl in day_levels:
            if SWEEP_LEVEL_SIDE.get(lvl['level_name']) != sweep_side:
                continue
            if lvl['level_name'] in swept_already:
                continue
            if lvl.get('price') is None:
                continue
            distance = abs(float(lvl['price']) - sweep_price)
            if distance > NEARBY_PTS:
                continue
            remaining.append(lvl['level_name'])
        unswept_counts.append(len(remaining))
        unswept_lists.append('|'.join(sorted(set(remaining))))

    pop['prior_same_dir_sweep_count'] = prior_counts
    pop['prior_same_dir_sweep_levels'] = prior_lists
    pop['remaining_same_dir_unswept'] = unswept_counts
    pop['remaining_same_dir_unswept_levels'] = unswept_lists
    print(f"  enriched in {time.time()-t:.1f}s")

    # --- News flags from trading_days.csv ---
    td = pd.read_csv(TRADING_DAYS_PATH)
    td['date'] = pd.to_datetime(td['date']).dt.date.astype(str)
    pop = pop.merge(
        td[['date', 'has_red_folder_news', 'has_pre_rth_news',
            'has_during_session_news', 'is_fomc_week', 'is_opex_week']],
        on='date', how='left',
    )
    matched = pop['has_red_folder_news'].notna().sum()
    print(f"  joined news flags: {matched}/{len(pop)} matched (news data coverage ends 2025-09-19)")

    pop.to_csv(OUT_PATH, index=False)
    print(f"\nWrote {OUT_PATH} ({len(pop.columns)} columns)")

    # --- Quick sanity checks on the new factors ---
    print("\n=== Sanity preview ===")
    print(f"prior_same_dir_sweep_count distribution:")
    print(pop['prior_same_dir_sweep_count'].value_counts().sort_index().to_string())
    print(f"\nremaining_same_dir_unswept distribution:")
    print(pop['remaining_same_dir_unswept'].value_counts().sort_index().to_string())


if __name__ == '__main__':
    main()
