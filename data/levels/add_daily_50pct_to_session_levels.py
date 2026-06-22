#!/usr/bin/env python3
"""Append daily_50pct_high/low rows to data/levels/session_levels.csv.

Each row uses the daily_50pct value as the level price; high/low names mark
which side of the mid the sweep wick must come from (mirrors running_50pct).
"""

from pathlib import Path
import pandas as pd

LEVELS = Path('data/levels/session_levels.csv')
DAILY  = Path('data/levels/daily_50pct.csv')


def main():
    levels = pd.read_csv(LEVELS)
    d50 = pd.read_csv(DAILY)
    print(f"Existing session_levels rows: {len(levels)}")
    print(f"daily_50pct dates available:  {len(d50)}")

    # Drop any pre-existing daily_50pct rows (idempotent re-run)
    before = len(levels)
    levels = levels[~levels['level_name'].isin(['daily_50pct_high', 'daily_50pct_low'])].copy()
    if len(levels) != before:
        print(f"Removed {before - len(levels)} prior daily_50pct rows")

    new_rows = []
    for _, r in d50.iterrows():
        mid = float(r['daily_50pct'])
        for side_name, side in [('daily_50pct_high', 'resistance'),
                                 ('daily_50pct_low', 'support')]:
            new_rows.append({
                'date': r['date'],
                'level_name': side_name,
                'group': 'daily_50pct',
                'side': side,
                'price': mid,
                'available_time': 'open',     # known at RTH open
                'swept_pre_rth': False,
                'swept_pre_rth_time': None,
                'timeframe': '1D',
                'fvg_direction': None,
                'fvg_top': None,
                'fvg_bottom': None,
                'fvg_mid': None,
                'created_date': r['prior_cme_day'],
                'bars_old': None,
                'notes': 'CME daily candle midpoint (prior day 18:00 -> 17:00)',
            })

    new_df = pd.DataFrame(new_rows)
    out = pd.concat([levels, new_df], ignore_index=True)
    out.to_csv(LEVELS, index=False)
    print(f"\nAdded {len(new_rows)} rows ({len(d50)} dates x 2 sides)")
    print(f"Total session_levels rows now: {len(out)}")

    # Verify
    sample = out[(out['date'] == '2026-05-21') & (out['level_name'].str.startswith('daily_50pct'))]
    print("\n5/21 daily_50pct rows:")
    print(sample[['date','level_name','price','notes']].to_string(index=False))


if __name__ == '__main__':
    main()
