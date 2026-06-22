#!/usr/bin/env python3
"""Enrich population with the FULL trading_days context (volatility regime, gap,
opening range, prior-day character, calendar effects).

Per user observation that FVGC modeling benefited from these factors. Currently
only 16 of 63 trading_days columns are joined; this brings in the rest.

Adds:
  - Volatility: prior_day_range_atr_ratio, vixy_regime, vixy_prior_close
  - Gap: gap_from_prior_close, gap_from_prior_close_pct
  - Opening Range: or_5min_range, or_15min_range, or_45min_range
  - Candle character: candle_930_range, candle_930_body, candle_930_direction
  - Prior day: prior_day_range, prior_day_close_position, prior_day_close_vs_open_pct, prior_day_type
  - Intraday character: directional_changes_30m, max_drawdown_from_open, max_drawup_from_open
  - Calendar: is_quad_witching, is_month_start, is_month_end, month, day_of_month
  - Overnight: overnight_direction, overnight_range
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pandas as pd

POP_PATH = Path('studies/ifvg_reversal_population/results/population_scored.csv')
TRADING_DAYS_PATH = Path('data/trading_days/trading_days.csv')

CONTEXT_COLS = [
    # Volatility regime
    'prior_day_range_atr_ratio',
    'vixy_regime',
    'vixy_prior_close',
    # Overnight gap
    'gap_from_prior_close',
    'gap_from_prior_close_pct',
    'overnight_direction',
    'overnight_range',
    # Opening range (multi-timeframe)
    'or_5min_range',
    'or_15min_range',
    'or_45min_range',
    # 9:30 candle character
    'candle_930_range',
    'candle_930_body',
    'candle_930_direction',
    # First-X-min FVG counts
    'fvgs_first_5min',
    'fvgs_first_15min',
    # Prior day
    'prior_day_range',
    'prior_day_close_position',
    'prior_day_close_vs_open_pct',
    'prior_day_type',
    'prior_day_directional_changes',
    # Intraday character (these may leak post-trade info — keep only if entry is pre-event)
    # 'directional_changes_30m' (computed end-of-day — leak; skip)
    # 'max_drawdown_from_open' (post-trade — skip)
    # 'max_drawup_from_open' (post-trade — skip)
    # Calendar
    'is_quad_witching',
    'is_month_start',
    'is_month_end',
    'month',
    'day_of_month',
]


def main():
    print("=== Context enrichment from trading_days.csv ===\n")
    pop = pd.read_csv(POP_PATH)
    td = pd.read_csv(TRADING_DAYS_PATH)
    print(f"  population: {len(pop)} rows")
    print(f"  trading_days: {len(td)} rows")

    # Drop any of these that are already joined to avoid double-join confusion
    already = [c for c in CONTEXT_COLS if c in pop.columns]
    if already:
        print(f"  removing already-joined columns to avoid dup: {already}")
        pop = pop.drop(columns=already)

    # Normalize date columns
    if 'date' not in pop.columns:
        pop['date'] = pd.to_datetime(pop['entry_ts'], utc=True, format='mixed').dt.date.astype(str)
    td['date'] = pd.to_datetime(td['date']).dt.date.astype(str)

    cols_to_join = ['date'] + [c for c in CONTEXT_COLS if c in td.columns]
    missing = [c for c in CONTEXT_COLS if c not in td.columns]
    if missing:
        print(f"  WARNING: missing from trading_days: {missing}")
    print(f"  joining {len(cols_to_join)-1} new context columns")

    before = len(pop.columns)
    pop = pop.merge(td[cols_to_join], on='date', how='left')
    after = len(pop.columns)
    print(f"  population now {after} columns ({after-before} new)\n")

    # Sanity preview
    print("Coverage of new columns on cohort:")
    for c in cols_to_join[1:]:
        if c not in pop.columns:
            continue
        non_null = pop[c].notna().sum()
        print(f"  {c:36}  {non_null}/{len(pop)}  ({non_null/len(pop)*100:.0f}%)")

    pop.to_csv(POP_PATH, index=False)
    print(f"\nWrote {POP_PATH}")


if __name__ == '__main__':
    main()
