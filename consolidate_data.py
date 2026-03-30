#!/usr/bin/env python3
"""
Consolidate multiple Databento NQ OHLCV-1s CSV files into a single
clean front-month continuous series.

Steps:
  1. Load all raw ohlcv-1s CSVs from data/raw/
  2. Drop calendar-spread rows (symbol contains '-')
  3. Drop back-month / low-volume contracts when multiple outrights share a timestamp
  4. Deduplicate, sort, and write one consolidated file

Run:
  python consolidate_data.py
"""

import pandas as pd
from pathlib import Path
from datetime import datetime

DATA_DIR = Path('data/raw')
OUTPUT_PATH = DATA_DIR / 'nq-front-month-consolidated.ohlcv-1s.csv'

NQ_QUARTERLY_ORDER = ['H', 'M', 'U', 'Z']

def contract_sort_key(symbol: str) -> tuple:
    """Parse NQ contract symbol (e.g. NQH6) into (year, quarter_idx) for ordering."""
    if not isinstance(symbol, str) or len(symbol) < 4 or not symbol.startswith('NQ'):
        return (9999, 9)
    month_code = symbol[2]
    year_suffix = symbol[3:]
    try:
        year = int(year_suffix)
    except ValueError:
        return (9999, 9)
    q_idx = NQ_QUARTERLY_ORDER.index(month_code) if month_code in NQ_QUARTERLY_ORDER else 9
    return (year, q_idx)


def load_raw_files() -> pd.DataFrame:
    files = sorted(DATA_DIR.glob('glbx-mdp3-*.ohlcv-1s.csv'))
    if not files:
        raise FileNotFoundError(f"No ohlcv-1s CSVs found in {DATA_DIR}")

    print(f"Found {len(files)} raw OHLCV-1s files:")
    frames = []
    for f in files:
        print(f"  {f.name}  ({f.stat().st_size / 1e6:.1f} MB)")
        df = pd.read_csv(f, dtype={'symbol': str})
        frames.append(df)
        print(f"    rows: {len(df):,}")

    combined = pd.concat(frames, ignore_index=True)
    print(f"\nCombined raw rows: {len(combined):,}")
    return combined


def determine_front_month_schedule(df: pd.DataFrame) -> pd.DataFrame:
    """
    Build a per-date front-month contract map based on daily volume dominance.
    The contract with the most volume on a given calendar date is front month
    for that entire date, giving a clean once-per-day roll.
    """
    df['_date'] = df['ts_event'].dt.date
    daily_vol = (
        df.groupby(['_date', 'symbol'])['volume']
        .sum()
        .reset_index()
        .sort_values(['_date', 'volume'], ascending=[True, False])
    )
    front_month = daily_vol.drop_duplicates(subset='_date', keep='first')[['_date', 'symbol']]
    front_month = front_month.rename(columns={'symbol': 'front_month'})

    # Smooth out one-off flickers: if contract A is front month on day D-1 and D+1
    # but not D, it's a data artifact — keep A on day D too.
    fm = front_month.sort_values('_date').reset_index(drop=True)
    for i in range(1, len(fm) - 1):
        if fm.loc[i - 1, 'front_month'] == fm.loc[i + 1, 'front_month'] and \
           fm.loc[i, 'front_month'] != fm.loc[i - 1, 'front_month']:
            fm.loc[i, 'front_month'] = fm.loc[i - 1, 'front_month']

    print("\nFront-month schedule (by daily volume):")
    prev_sym = None
    for _, row in fm.iterrows():
        if row['front_month'] != prev_sym:
            print(f"  {row['_date']}  ->  {row['front_month']}")
            prev_sym = row['front_month']

    return fm


def clean(df: pd.DataFrame) -> pd.DataFrame:
    before = len(df)

    # 1. Drop spreads (symbols with '-')
    spread_mask = df['symbol'].str.contains('-', na=False)
    n_spreads = spread_mask.sum()
    df = df[~spread_mask].copy()
    print(f"\nDropped {n_spreads:,} spread rows (symbols with '-')")

    # 2. Parse timestamps
    df['ts_event'] = pd.to_datetime(df['ts_event'], utc=True)

    # 3. Determine front month per calendar date by volume
    fm_schedule = determine_front_month_schedule(df)
    df['_date'] = df['ts_event'].dt.date
    df = df.merge(fm_schedule, on='_date', how='left')
    non_front = df['symbol'] != df['front_month']
    n_back = non_front.sum()
    df = df[~non_front].copy()
    print(f"\nDropped {n_back:,} back-month rows (not front month for that date)")
    df = df.drop(columns=['_date', 'front_month'])

    # 4. Deduplicate any remaining same-timestamp rows
    df = df.sort_values('ts_event')
    dupes = df.duplicated(subset='ts_event', keep='first').sum()
    if dupes:
        df = df.drop_duplicates(subset='ts_event', keep='first')
        print(f"Dropped {dupes:,} duplicate-timestamp rows")

    df = df.reset_index(drop=True)
    print(f"\nFinal row count: {len(df):,}  (from {before:,} raw)")
    return df


def report(df: pd.DataFrame):
    print("\n" + "=" * 60)
    print("CONSOLIDATION REPORT")
    print("=" * 60)
    print(f"Total rows:  {len(df):,}")
    print(f"Date range:  {df['ts_event'].min()} -> {df['ts_event'].max()}")

    symbols = df['symbol'].unique()
    print(f"Contracts:   {', '.join(sorted(symbols, key=contract_sort_key))}")

    # Contract transitions
    df_sym = df[['ts_event', 'symbol']].copy()
    df_sym['prev_symbol'] = df_sym['symbol'].shift(1)
    transitions = df_sym[df_sym['symbol'] != df_sym['prev_symbol']].iloc[1:]
    if not transitions.empty:
        print("\nContract roll points:")
        for _, row in transitions.iterrows():
            print(f"  {row['prev_symbol']} -> {row['symbol']}  at  {row['ts_event']}")

    # Gap detection (gaps > 2 hours during trading days)
    ts = df['ts_event'].sort_values().reset_index(drop=True)
    diffs = ts.diff()
    gap_threshold = pd.Timedelta(hours=26)
    gaps = diffs[diffs > gap_threshold]
    if not gaps.empty:
        print(f"\nData gaps (>{gap_threshold}):")
        for idx in gaps.index:
            gap_start = ts.iloc[idx - 1]
            gap_end = ts.iloc[idx]
            print(f"  {gap_start} -> {gap_end}  ({diffs.iloc[idx]})")
    else:
        print("\nNo significant data gaps detected.")

    # Per-contract stats
    print("\nPer-contract breakdown:")
    for sym in sorted(symbols, key=contract_sort_key):
        sub = df[df['symbol'] == sym]
        print(f"  {sym}: {len(sub):>10,} rows  "
              f"({sub['ts_event'].min().strftime('%Y-%m-%d %H:%M')} -> "
              f"{sub['ts_event'].max().strftime('%Y-%m-%d %H:%M')})")


def main():
    print("=" * 60)
    print("NQ Front-Month Data Consolidation")
    print("=" * 60)

    df = load_raw_files()
    df = clean(df)
    report(df)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_PATH, index=False)
    print(f"\nWrote consolidated file: {OUTPUT_PATH}")
    print(f"Size: {OUTPUT_PATH.stat().st_size / 1e6:.1f} MB")


if __name__ == '__main__':
    main()
