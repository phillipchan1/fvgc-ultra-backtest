"""Phase A: Build the analysis frame from mfe_trades_enriched.csv.

Adds:
- macro_window (M1/M2/M3/M4 derived from timestamp)
- ret_60d, regime_60d (NQ 60-trading-day return + bull/bear/neutral label)
- split (IS / OOS based on OOS_SPLIT_DATE)

Filters:
- Keeps only tradeable rows (outcome in {win, loss})
- Keeps only rows with macro_window assigned (9:30-10:30 entries)

Output: studies/multi_cell_confluence/results/trades_analysis.csv
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pandas as pd

from studies.multi_cell_confluence.utils import (  # noqa: E402
    ANALYSIS_FRAME_PATH,
    OOS_SPLIT_DATE,
    RESULTS_DIR,
    TRADES_PATH,
    TRADING_DAYS_PATH,
    compute_60d_regime,
    derive_macro_window,
)


def main():
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    print('Loading mfe_trades_enriched.csv...')
    df = pd.read_csv(TRADES_PATH)
    print(f'  Raw rows: {len(df)}')

    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df['date'] = pd.to_datetime(df['date'])

    # Keep tradeable only
    df = df[df['outcome'].isin(['win', 'loss'])].copy()
    print(f'  After outcome filter: {len(df)}')

    # Derive macro_window
    df['macro_window'] = derive_macro_window(df['timestamp'])
    pre_filter = len(df)
    df = df[df['macro_window'].notna()].copy()
    print(f'  After macro_window filter (9:30-10:30): {len(df)} (dropped {pre_filter - len(df)} outside window)')

    # 60d regime
    print('Loading trading_days for 60d regime...')
    td = pd.read_csv(TRADING_DAYS_PATH)
    regime = compute_60d_regime(td)
    print(f'  Computed regime for {regime["regime_60d"].notna().sum()} trading days')

    df = df.merge(regime, on='date', how='left')
    missing_regime = df['regime_60d'].isna().sum()
    if missing_regime:
        print(f'  WARNING: {missing_regime} trades missing regime_60d (likely first 60 days of data)')

    # IS/OOS split
    df['split'] = 'IS'
    df.loc[df['timestamp'] >= OOS_SPLIT_DATE, 'split'] = 'OOS'

    print('\n=== Summary ===')
    print(f'Total trades:       {len(df)}')
    print(f'Date range:         {df["timestamp"].min().date()} -> {df["timestamp"].max().date()}')
    print(f'IS / OOS counts:    {(df["split"] == "IS").sum()} / {(df["split"] == "OOS").sum()}')
    print(f'\nBy macro_window:')
    print(df['macro_window'].value_counts().sort_index().to_string())
    print(f'\nBy direction:')
    print(df['direction'].value_counts().to_string())
    print(f'\nBy variant:')
    print(df['variant'].value_counts().to_string())
    print(f'\nBy regime_60d:')
    print(df['regime_60d'].value_counts(dropna=False).to_string())
    print(f'\n(window x direction) cell counts (protected_swing excluded):')
    cell_counts = (df[df['variant'] != 'protected_swing']
                   .groupby(['macro_window', 'direction']).size().unstack(fill_value=0))
    print(cell_counts.to_string())

    df.to_csv(ANALYSIS_FRAME_PATH, index=False)
    print(f'\nWrote {ANALYSIS_FRAME_PATH}')


if __name__ == '__main__':
    main()
