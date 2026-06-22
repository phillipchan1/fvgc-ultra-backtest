"""Data wick detector — §15.2 + §15.3.

For each red-folder release date (from trading_days.csv), find the 1-min candle
at the release time (08:30 or 10:00 NY). That candle's high and low are the
data wick range. Then scan subsequent candles for sweeps of either side.

Output: Sweep events using the existing dataclass from ../../detectors/sweep.py
so that downstream model.py code can compose detectors uniformly.
"""

from datetime import time as dtime, timedelta
from typing import List

import pandas as pd

from ...constants import (
    MIN_SWEEP_PENETRATION,
    SWEEP_VALIDITY_MINUTES,
)
from ...detectors.sweep import Sweep
from ..constants import (
    MIN_DATA_WICK_RANGE,
    RELEASE_TIMES_NY,
    SETUP_WINDOW_MINUTES,
)


from dataclasses import dataclass


@dataclass
class DataWickSweep:
    """A sweep event tagged with the data wick H/L (needed for §15.8 structural target)."""
    sweep: Sweep
    wick_high: float
    wick_low: float
    release_label: str   # '0830' or '1000'


def detect_data_wick_sweeps(
    candles_30s: pd.DataFrame,
    news_days: pd.DataFrame,
) -> List[DataWickSweep]:
    """Detect data-wick sweep events for red-folder release dates.

    Args:
        candles_30s: 30s candles with `timestamp_ny`.
        news_days: DataFrame with at least ['date', 'has_pre_rth_news',
                   'has_during_session_news'] from trading_days.csv.

    Returns:
        List of DataWickSweep events. Each wraps a standard Sweep (with
        `level_name` of `data_wick_high_0830` etc., tier=1) plus the wick H/L
        used to set §15.8 structural targets downstream.
    """
    if candles_30s.empty or news_days.empty:
        return []

    base = candles_30s[['timestamp_ny', 'open', 'high', 'low', 'close']].copy()
    base['date_ny'] = base['timestamp_ny'].dt.date.astype(str)

    news = news_days.copy()
    news['date'] = pd.to_datetime(news['date']).dt.date.astype(str)

    out: List[DataWickSweep] = []
    validity = pd.Timedelta(minutes=SWEEP_VALIDITY_MINUTES)
    setup_window = pd.Timedelta(minutes=SETUP_WINDOW_MINUTES)

    for _, day in news.iterrows():
        date_str = day['date']
        day_candles = base[base['date_ny'] == date_str]
        if day_candles.empty:
            continue

        if bool(day.get('has_pre_rth_news', False)):
            out.extend(_scan_release(day_candles, dtime(8, 30), '0830', setup_window, validity))

        if bool(day.get('has_during_session_news', False)):
            out.extend(_scan_release(day_candles, dtime(10, 0), '1000', setup_window, validity))

    out.sort(key=lambda dws: dws.sweep.timestamp_ny)
    return out


def _scan_release(
    day_candles: pd.DataFrame,
    release_time: dtime,
    label: str,
    setup_window: pd.Timedelta,
    validity: pd.Timedelta,
) -> List["DataWickSweep"]:
    """For one release on one day: extract data wick + scan for sweeps."""
    # The "data wick" is the 1-min candle at release_time. Aggregate from 30s.
    release_minute_start = day_candles[
        day_candles['timestamp_ny'].dt.time == release_time
    ]
    if release_minute_start.empty:
        return []
    # The 1-min bar covers release_time .. release_time + 1min. Two 30s bars.
    rt_dt = release_minute_start['timestamp_ny'].iloc[0]
    rt_end = rt_dt + pd.Timedelta(minutes=1)
    wick_bars = day_candles[
        (day_candles['timestamp_ny'] >= rt_dt) &
        (day_candles['timestamp_ny'] < rt_end)
    ]
    if wick_bars.empty:
        return []

    wick_high = float(wick_bars['high'].max())
    wick_low = float(wick_bars['low'].min())
    wick_range = wick_high - wick_low

    if wick_range < MIN_DATA_WICK_RANGE:
        return []  # data wick too small to be tradeable

    # Setup window: from after the 1-min wick bar through release + SETUP_WINDOW_MINUTES.
    window_start = rt_end
    window_end = rt_dt + setup_window
    after = day_candles[
        (day_candles['timestamp_ny'] >= window_start) &
        (day_candles['timestamp_ny'] <= window_end)
    ]
    if after.empty:
        return []

    out: List["DataWickSweep"] = []

    # High-side sweep (short setup): wick above wick_high, close back below.
    high_mask = (
        (after['high'] > wick_high + MIN_SWEEP_PENETRATION) &
        (after['close'] < wick_high)
    )
    if high_mask.any():
        first = after[high_mask].iloc[0]
        sweep = Sweep(
            timestamp_ny=first['timestamp_ny'],
            level_name=f'data_wick_high_{label}',
            tier=1,
            level_price=wick_high,
            reversal_direction='short',
            penetration_pts=float(first['high'] - wick_high),
            validity_expires_at=first['timestamp_ny'] + validity,
        )
        out.append(DataWickSweep(sweep=sweep, wick_high=wick_high, wick_low=wick_low,
                                 release_label=label))

    # Low-side sweep (long setup): wick below wick_low, close back above.
    low_mask = (
        (after['low'] < wick_low - MIN_SWEEP_PENETRATION) &
        (after['close'] > wick_low)
    )
    if low_mask.any():
        first = after[low_mask].iloc[0]
        sweep = Sweep(
            timestamp_ny=first['timestamp_ny'],
            level_name=f'data_wick_low_{label}',
            tier=1,
            level_price=wick_low,
            reversal_direction='long',
            penetration_pts=float(wick_low - first['low']),
            validity_expires_at=first['timestamp_ny'] + validity,
        )
        out.append(DataWickSweep(sweep=sweep, wick_high=wick_high, wick_low=wick_low,
                                 release_label=label))

    return out
