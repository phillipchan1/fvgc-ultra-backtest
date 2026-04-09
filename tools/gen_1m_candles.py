#!/usr/bin/env python3
"""Resample existing 30s consolidated CSV to 1m and write output file."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytz
import pandas as pd

NY_TZ = pytz.timezone('America/New_York')

INPUT = Path('data/consolidated/nq-front-month.ohlcv-30s.csv')
OUTPUT = Path('data/consolidated/nq-front-month.ohlcv-1m.csv')


def main():
    print(f"Loading {INPUT} ...")
    df = pd.read_csv(INPUT, parse_dates=['timestamp_utc'])
    df['timestamp_utc'] = pd.to_datetime(df['timestamp_utc'], utc=True)
    print(f"  {len(df):,} 30s candles loaded")

    candles = (
        df.set_index('timestamp_utc')
        .resample('1min')
        .agg(
            open=('open', 'first'),
            high=('high', 'max'),
            low=('low', 'min'),
            close=('close', 'last'),
            volume=('volume', 'sum'),
        )
        .dropna(subset=['open'])
        .reset_index()
    )
    candles['timestamp_ny'] = candles['timestamp_utc'].dt.tz_convert(NY_TZ)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    candles.to_csv(OUTPUT, index=False)
    size_mb = OUTPUT.stat().st_size / 1e6
    print(f"  {len(candles):,} 1m candles → {OUTPUT}  ({size_mb:.1f} MB)")


if __name__ == '__main__':
    main()
