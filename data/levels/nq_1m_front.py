"""
Load validated front-month NQ OHLCV from the same consolidated file the backtest uses.

Primary entry point: load_nq_consolidated(). load_nq_1m is an alias for backward compatibility.

`date_ny` is the calendar date in America/New_York for each bar (never the UTC calendar date).

The CSV `timestamp_ny` values are ISO8601 strings with per-row offsets (EST/EDT). Parsing with
`utc=True` converts each string to the correct UTC instant, then `tz_convert(America/New_York)`
recovers the intended NY wall-clock time — equivalent to `pd.Timestamp(s).tz_convert(NY_TZ)` on
every row (verified: 0 mismatches on the full file). Naive `utc=False` without `format='mixed'`
breaks on mixed-offset columns.
"""

from datetime import date
from pathlib import Path

import pandas as pd
import pytz

NY_TZ = pytz.timezone('America/New_York')
PRICE_FLOOR = 10_000

ROOT = Path(__file__).resolve().parent.parent.parent
CONSOLIDATED_NQ_PATH = ROOT / 'data' / 'consolidated' / 'nq-front-month.ohlcv-30s.csv'


def _diagnostic_early_session(df: pd.DataFrame, verbose: bool) -> None:
    """Bars with local hour in [0, 8) — should roll up to the same session `date_ny` as the London window."""
    if not verbose:
        return
    sub = df[(df['ts_ny'].dt.hour >= 0) & (df['ts_ny'].dt.hour < 8)]
    target_dates: list[date] = [date(2026, 2, 5), date(2026, 2, 6)]
    have = set(df['date_ny'].unique())
    use_dates = [d for d in target_dates if d in have]
    if not use_dates:
        u = sorted(have)
        use_dates = u[-5:] if len(u) >= 5 else u
    print('  Diagnostic: bars with ts_ny hour in [0, 8) by date_ny:')
    for d in use_dates:
        n = len(sub[sub['date_ny'] == d])
        print(f'    {d}: {n:,}')


def load_nq_consolidated(verbose: bool = True) -> pd.DataFrame:
    """Load `nq-front-month.ohlcv-30s.csv` — same validated series as the engine."""
    if verbose:
        print('Loading consolidated NQ front-month (30s)...')
    df = pd.read_csv(CONSOLIDATED_NQ_PATH)
    if verbose:
        print(f'  {len(df):,} rows')

    raw0 = df['timestamp_ny'].iloc[0]
    probe = pd.to_datetime(raw0, utc=False)
    tz_kind = 'naive' if getattr(probe, 'tzinfo', None) is None else str(probe.tzinfo)
    if verbose:
        print(f'  Sample raw timestamp_ny (first row): {raw0!r}')
        print(f'  pd.to_datetime(utc=False) probe tz: {tz_kind}')

    # Offset-aware ISO strings → UTC instant → America/New_York (correct NY calendar date)
    df['ts_ny'] = pd.to_datetime(df['timestamp_ny'], utc=True).dt.tz_convert(NY_TZ)
    df['date_ny'] = df['ts_ny'].dt.date

    mask = (df['open'] >= PRICE_FLOOR) & (df['close'] >= PRICE_FLOOR) & \
           (df['low'] >= PRICE_FLOOR) & (df['high'] >= PRICE_FLOOR)
    n_dropped = (~mask).sum()
    if n_dropped and verbose:
        print(f'  Dropped {n_dropped:,} sub-floor rows')
    df = df[mask].copy()

    df = df.sort_values('ts_ny').reset_index(drop=True)

    if verbose:
        sample = df[['ts_ny', 'date_ny']].head(5)
        print('  First 5 rows (ts_ny, date_ny) after derivation + price filter:')
        for _, row in sample.iterrows():
            print(f'    {row["ts_ny"]}  ->  {row["date_ny"]}')
        _diagnostic_early_session(df, verbose=True)

    if verbose:
        print(
            f'  {len(df):,} bars, {df["date_ny"].nunique()} calendar dates '
            f'(ts_ny, date_ny, OHLCV)',
        )
    return df


def load_nq_1m(verbose: bool = True) -> pd.DataFrame:
    """Alias for load_nq_consolidated() — same validated consolidated 30s data."""
    return load_nq_consolidated(verbose=verbose)
