"""Feature engineering for the OR-width predictor study.

The trading_days.csv table already carries most static features (gap,
overnight_range, prior_day_range, candle_930_*, vixy_*, calendar flags).
This module adds the missing high-value features computed from raw 5m
candles + rolling daily series.
"""

from datetime import time as dtime
from pathlib import Path

import numpy as np
import pandas as pd

NY_TZ = 'America/New_York'


def load_5m_candles(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=['timestamp_utc'])
    df['timestamp_ny'] = df['timestamp_utc'].dt.tz_convert(NY_TZ)
    df['date'] = df['timestamp_ny'].dt.date
    df['t'] = df['timestamp_ny'].dt.time
    return df


def compute_premarket_range(candles_5m: pd.DataFrame) -> pd.DataFrame:
    """Range from 8:00 to 9:30 ET (the most recent pre-RTH slice)."""
    mask = (candles_5m['t'] >= dtime(8, 0)) & (candles_5m['t'] < dtime(9, 30))
    pm = candles_5m[mask].groupby('date').agg(
        pm_high=('high', 'max'),
        pm_low=('low', 'min'),
        pm_volume=('volume', 'sum'),
    )
    pm['pm_range'] = pm['pm_high'] - pm['pm_low']
    return pm.reset_index()


def compute_overnight_close_position(candles_5m: pd.DataFrame) -> pd.DataFrame:
    """Where did the ON session close (last bar before 9:30) sit within
    the ON range? 0.0 = at ON low, 1.0 = at ON high.
    """
    mask = candles_5m['t'] < dtime(9, 30)
    on = candles_5m[mask].copy()
    last_idx = on.groupby('date')['timestamp_ny'].idxmax()
    on_close = on.loc[last_idx, ['date', 'close']].rename(columns={'close': 'on_close'})

    on_hl = on.groupby('date').agg(on_high=('high', 'max'), on_low=('low', 'min')).reset_index()
    out = on_close.merge(on_hl, on='date')
    rng = (out['on_high'] - out['on_low']).replace(0, np.nan)
    out['on_close_position'] = (out['on_close'] - out['on_low']) / rng
    return out[['date', 'on_close_position']]


def add_rolling_atr(df: pd.DataFrame) -> pd.DataFrame:
    """ATR over prior N RTH days (uses prior_day_range as TR proxy — gap
    captured separately via gap_from_prior_close).
    """
    df = df.sort_values('date').copy()
    pdr = df['prior_day_range']
    for n in (5, 10, 20):
        df[f'atr_{n}d'] = pdr.rolling(n, min_periods=n).mean()
    df['atr_ratio_5_20'] = df['atr_5d'] / df['atr_20d']
    return df


def add_compression_flags(df: pd.DataFrame) -> pd.DataFrame:
    """NR4 / NR7 / inside-day-streak flags computed from prior_day_range
    (i.e. observable at 9:30 today)."""
    df = df.sort_values('date').copy()
    pdr = df['prior_day_range']
    df['nr4_flag'] = (pdr == pdr.rolling(4, min_periods=4).min()).astype(int)
    df['nr7_flag'] = (pdr == pdr.rolling(7, min_periods=7).min()).astype(int)
    # prior_day_range percentile within last 20 days
    df['pdr_pctile_20d'] = pdr.rolling(20, min_periods=20).rank(pct=True)
    return df


def add_vix_features(df: pd.DataFrame) -> pd.DataFrame:
    """VIX 1d / 5d delta and 20d z-score from vixy_prior_close."""
    df = df.sort_values('date').copy()
    v = df['vixy_prior_close']
    df['vix_1d_chg'] = v.diff(1)
    df['vix_5d_chg'] = v.diff(5)
    mu = v.rolling(20, min_periods=20).mean()
    sd = v.rolling(20, min_periods=20).std()
    df['vix_zscore_20d'] = (v - mu) / sd
    return df


def add_efficiency_features(df: pd.DataFrame) -> pd.DataFrame:
    """Directional efficiency of the 9:30 1-min candle (|body|/range).
    Low efficiency = chop = often predicts narrower full-day OR."""
    df = df.copy()
    rng = df['candle_930_range'].replace(0, np.nan)
    df['candle_930_efficiency'] = df['candle_930_body'].abs() / rng
    return df


def add_gap_features(df: pd.DataFrame) -> pd.DataFrame:
    """Gap absolute size + gap normalized by 20d ATR."""
    df = df.copy()
    df['gap_abs'] = df['gap_from_prior_close'].abs()
    df['gap_atr_ratio'] = df['gap_abs'] / df['atr_20d']
    return df


def build_feature_table(
    trading_days_path: Path,
    candles_5m_path: Path,
) -> pd.DataFrame:
    """Load trading_days.csv, augment with computed features, return one
    row per trading day. Target: or_45min_range."""
    td = pd.read_csv(trading_days_path, parse_dates=['date'])
    td['date'] = td['date'].dt.date

    candles = load_5m_candles(candles_5m_path)
    pm = compute_premarket_range(candles)
    on_pos = compute_overnight_close_position(candles)

    df = td.merge(pm, on='date', how='left').merge(on_pos, on='date', how='left')
    df = add_rolling_atr(df)
    df = add_compression_flags(df)
    df = add_vix_features(df)
    df = add_efficiency_features(df)
    df = add_gap_features(df)
    return df
