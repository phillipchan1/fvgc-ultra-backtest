#!/usr/bin/env python3
"""
Consolidate multiple Databento NQ OHLCV-1s CSV files into clean
front-month 15s and 30s candle files.

Steps:
  1. Load all raw ohlcv-1s CSVs from data/raw/
  2. Drop calendar-spread rows (symbol contains '-')
  3. Keep only the front-month contract per calendar date (by volume)
  4. Apply price floor + outlier filters (same logic as backtest)
  5. Aggregate to 15s and 30s OHLCV candles
  6. Write compact output files

Run:
  python consolidate_data.py
"""

import pandas as pd
import pytz
from pathlib import Path

DATA_DIR = Path('data/raw')
OUTPUT_DIR = Path('data/consolidated')

NQ_QUARTERLY_ORDER = ['H', 'M', 'U', 'Z']
NY_TZ = pytz.timezone('America/New_York')
PRICE_FLOOR = 10_000
OUTLIER_THRESHOLD = 100


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


def clean_front_month(df: pd.DataFrame) -> pd.DataFrame:
    before = len(df)

    spread_mask = df['symbol'].str.contains('-', na=False)
    n_spreads = spread_mask.sum()
    df = df[~spread_mask].copy()
    print(f"\nDropped {n_spreads:,} spread rows")

    df['ts_event'] = pd.to_datetime(df['ts_event'], utc=True)

    fm_schedule = determine_front_month_schedule(df)
    df['_date'] = df['ts_event'].dt.date
    df = df.merge(fm_schedule, on='_date', how='left')
    non_front = df['symbol'] != df['front_month']
    n_back = non_front.sum()
    df = df[~non_front].copy()
    print(f"Dropped {n_back:,} back-month rows")
    df = df.drop(columns=['_date', 'front_month'])

    df = df.sort_values('ts_event')
    dupes = df.duplicated(subset='ts_event', keep='first').sum()
    if dupes:
        df = df.drop_duplicates(subset='ts_event', keep='first')
        print(f"Dropped {dupes:,} duplicate-timestamp rows")

    df = df.reset_index(drop=True)
    print(f"Clean 1s rows: {len(df):,}  (from {before:,} raw)")
    return df


def apply_filters(df: pd.DataFrame) -> pd.DataFrame:
    """Apply price floor and outlier filters (mirrors backtest logic)."""
    before = len(df)

    floor_mask = (
        (df['open'] >= PRICE_FLOOR) & (df['close'] >= PRICE_FLOOR) &
        (df['low'] >= PRICE_FLOOR) & (df['high'] >= PRICE_FLOOR)
    )
    df = df[floor_mask].copy()
    n_floor = before - len(df)
    if n_floor:
        print(f"Dropped {n_floor:,} sub-floor rows (OHLC < {PRICE_FLOOR})")

    df['_ts_30s'] = df['ts_event'].dt.floor('30s')
    df['_mid'] = (df['open'] + df['close']) / 2
    group_median = df.groupby('_ts_30s')['_mid'].transform('median')
    outlier_mask = (df['_mid'] - group_median).abs() > OUTLIER_THRESHOLD
    n_outliers = outlier_mask.sum()
    if n_outliers:
        print(f"Dropped {n_outliers:,} outlier rows (>{OUTLIER_THRESHOLD} pts from 30s median)")
    df = df[~outlier_mask].copy()
    df = df.drop(columns=['_ts_30s', '_mid'])

    print(f"After filters: {len(df):,} clean 1s rows")
    return df


def aggregate(df: pd.DataFrame, interval: str) -> pd.DataFrame:
    """Aggregate 1s bars into OHLCV candles at the given interval."""
    ts_col = f'_ts_{interval}'
    df[ts_col] = df['ts_event'].dt.floor(interval)

    candles = (
        df.groupby(ts_col)
        .agg(
            open=('open', 'first'),
            high=('high', 'max'),
            low=('low', 'min'),
            close=('close', 'last'),
            volume=('volume', 'sum'),
        )
        .reset_index()
        .rename(columns={ts_col: 'timestamp_utc'})
    )
    candles['timestamp_ny'] = candles['timestamp_utc'].dt.tz_convert(NY_TZ)
    candles = candles.sort_values('timestamp_utc').reset_index(drop=True)
    return candles


def report(candles: pd.DataFrame, label: str):
    print(f"\n--- {label} ---")
    print(f"  Candles: {len(candles):,}")
    print(f"  Range:   {candles['timestamp_utc'].min()} -> {candles['timestamp_utc'].max()}")


def main():
    print("=" * 60)
    print("NQ Front-Month Data Consolidation")
    print("=" * 60)

    df = load_raw_files()
    df = clean_front_month(df)
    df = apply_filters(df)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for interval, suffix in [('15s', '15s'), ('30s', '30s')]:
        candles = aggregate(df, interval)
        report(candles, f"{interval} candles")

        out_path = OUTPUT_DIR / f'nq-front-month.ohlcv-{suffix}.csv'
        candles.to_csv(out_path, index=False)
        size_mb = out_path.stat().st_size / 1e6
        print(f"  Wrote: {out_path}  ({size_mb:.1f} MB)")

    print("\nDone.")


if __name__ == '__main__':
    main()
