"""Build the 8yr analysis frame from mfe_trades_enriched.csv (regenerated on 8yr baseline).

Adds:
- macro_window (M1/M2/M3/M4 from timestamp)
- ret_60d, regime_60d
- split (IS / OOS at 2025-01-01)
- year (for year-floor checks)

Output: studies/multi_cell_8yr_v2/results/trades_analysis_8yr.csv
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pandas as pd

from studies.multi_cell_confluence.utils import (  # noqa: E402
    compute_60d_regime,
    derive_macro_window,
)
from studies.multi_cell_8yr_v2.utils import (  # noqa: E402
    ANALYSIS_FRAME_PATH,
    OOS_SPLIT_DATE,
    RESULTS_DIR,
    TRADES_PATH,
    TRADING_DAYS_PATH,
)


def main():
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    print('Loading mfe_trades_enriched.csv (8yr)...')
    df = pd.read_csv(TRADES_PATH)
    print(f'  Raw rows: {len(df)}')

    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df['date'] = pd.to_datetime(df['date'])

    # Tradeable only
    df = df[df['outcome'].isin(['win', 'loss'])].copy()
    print(f'  After outcome filter: {len(df)}')

    # Macro window (M1-M4)
    df['macro_window'] = derive_macro_window(df['timestamp'])
    pre = len(df)
    df = df[df['macro_window'].notna()].copy()
    print(f'  After macro_window filter (9:30-10:30): {len(df)} (dropped {pre - len(df)})')

    # 60d regime
    td = pd.read_csv(TRADING_DAYS_PATH)
    regime = compute_60d_regime(td)
    df = df.merge(regime, on='date', how='left')
    missing = df['regime_60d'].isna().sum()
    if missing:
        print(f'  WARNING: {missing} trades missing regime_60d (first 60d of data)')

    # IS / OOS split
    df['split'] = 'IS'
    df.loc[df['timestamp'] >= OOS_SPLIT_DATE, 'split'] = 'OOS'
    df['year'] = df['timestamp'].dt.year

    print('\n=== Summary ===')
    print(f'Date range: {df["timestamp"].min().date()} -> {df["timestamp"].max().date()}')
    print(f'IS / OOS: {(df["split"] == "IS").sum()} / {(df["split"] == "OOS").sum()}')
    print('\nBy year:')
    print(df['year'].value_counts().sort_index().to_string())
    print('\n(window x direction) cell counts (protected_swing excluded):')
    cell_counts = (df[df['variant'] != 'protected_swing']
                   .groupby(['macro_window', 'direction'])
                   .size().unstack(fill_value=0))
    print(cell_counts.to_string())

    df.to_csv(ANALYSIS_FRAME_PATH, index=False)
    print(f'\nWrote {ANALYSIS_FRAME_PATH}')


if __name__ == '__main__':
    main()
