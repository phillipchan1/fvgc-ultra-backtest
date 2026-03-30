"""Data loading and aggregation utilities."""

import pandas as pd
from pathlib import Path
from .constants import NY_TZ, TRADING_WINDOW_START, TRADING_WINDOW_END


def load_candles(path: Path, interval: str = '30s') -> pd.DataFrame:
    """Load candles — handles both pre-aggregated and raw 1s Databento CSVs."""
    print(f"Loading data from {path} ...")
    df = pd.read_csv(path)

    if 'timestamp_utc' in df.columns:
        df['timestamp_utc'] = pd.to_datetime(df['timestamp_utc'], utc=True)
        df['timestamp_ny'] = df['timestamp_utc'].dt.tz_convert(NY_TZ)
        df = df.sort_values('timestamp_utc').reset_index(drop=True)
        print(f"  {len(df):,} pre-aggregated candles loaded")
        return df

    df['ts_event'] = pd.to_datetime(df['ts_event'], utc=True)
    print(f"  {len(df):,} raw 1s rows — aggregating to {interval} ...")

    df = df[(df['open'] >= 10_000) & (df['close'] >= 10_000) &
            (df['low'] >= 10_000) & (df['high'] >= 10_000)]

    if 'symbol' in df.columns:
        df = df[~df['symbol'].str.contains('-', na=False)]

    df = df.sort_values('ts_event').reset_index(drop=True)
    ts_col = df['ts_event'].dt.floor(interval)

    df['_mid'] = (df['open'] + df['close']) / 2
    group_median = df.groupby(ts_col)['_mid'].transform('median')
    outlier_mask = (df['_mid'] - group_median).abs() > 100
    n_outliers = outlier_mask.sum()
    if n_outliers:
        print(f"  Dropped {n_outliers} outlier rows")
    df = df[~outlier_mask]

    candles = (
        df.groupby(ts_col)
        .agg(open=('open', 'first'), high=('high', 'max'),
             low=('low', 'min'), close=('close', 'last'),
             volume=('volume', 'sum'))
        .reset_index()
        .rename(columns={'ts_event': 'timestamp_utc'})
    )
    candles['timestamp_ny'] = candles['timestamp_utc'].dt.tz_convert(NY_TZ)
    candles = candles.sort_values('timestamp_utc').reset_index(drop=True)
    print(f"  {len(candles):,} {interval} candles")
    return candles


def in_trading_window(ts_ny: pd.Timestamp) -> bool:
    t = ts_ny.time()
    return TRADING_WINDOW_START <= t <= TRADING_WINDOW_END
