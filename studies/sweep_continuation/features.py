"""Per-sweep feature computation.

Attaches contextual features to each sweep event so we can test which
conditions predict RUN vs REVERSE.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from datetime import time as dtime
from typing import List


# Time-of-day buckets (NY time).
#   asia    : 19:00 - 03:00 (overnight early)
#   london  : 03:00 - 08:00
#   premkt  : 08:00 - 09:30
#   open30  : 09:30 - 10:00
#   midday  : 10:00 - 14:00
#   pmdrive : 14:00 - 15:30
#   close   : 15:30 - 16:00
def _tod_bucket(t: dtime) -> str:
    if t >= dtime(19, 0) or t < dtime(3, 0):
        return 'asia'
    if t < dtime(8, 0):
        return 'london'
    if t < dtime(9, 30):
        return 'premkt'
    if t < dtime(10, 0):
        return 'open30'
    if t < dtime(14, 0):
        return 'midday'
    if t < dtime(15, 30):
        return 'pmdrive'
    if t < dtime(16, 0):
        return 'close'
    return 'evening'


_MACRO_POINTS = [dtime(8, 30), dtime(9, 30), dtime(10, 0),
                 dtime(14, 0), dtime(15, 0)]


def _macro_window(t: dtime, minutes: int = 10) -> bool:
    total = t.hour * 60 + t.minute
    for p in _MACRO_POINTS:
        delta = abs(total - (p.hour * 60 + p.minute))
        if delta <= minutes:
            return True
    return False


def _runway_to_next_level(
    sweep_row, levels: pd.DataFrame
) -> float | None:
    """Distance from swept level to the next same-side level in the
    direction of the sweep, restricted to levels active at sweep time.

    Returns distance in points, or None if no downstream level exists.
    """
    active = levels[(levels['created_idx'] <= sweep_row.sweep_idx)
                    & (levels['level_id'] != sweep_row.level_id)]
    if active.empty:
        return None
    price = sweep_row.level_price
    if sweep_row.sweep_direction == 'bullish':
        # Next high-side level above current price
        upward = active[(active['side'] == 'high') & (active['price'] > price)]
        if upward.empty:
            return None
        return float(upward['price'].min() - price)
    else:
        downward = active[(active['side'] == 'low') & (active['price'] < price)]
        if downward.empty:
            return None
        return float(price - downward['price'].max())


def attach_features(
    sweeps: pd.DataFrame,
    candles: pd.DataFrame,
    levels: pd.DataFrame,
    atr: np.ndarray,
) -> pd.DataFrame:
    """Return sweeps with additional feature columns attached."""
    if sweeps.empty:
        return sweeps

    out = sweeps.copy()
    n = len(candles)
    opens = candles['open'].values
    highs = candles['high'].values
    lows = candles['low'].values
    closes = candles['close'].values
    vols = candles['volume'].values if 'volume' in candles.columns \
        else np.zeros(n)
    ts_ny = candles['timestamp_ny']

    # Rolling volume median (20 bars)
    vol_med20 = pd.Series(vols).rolling(20, min_periods=5).median().values

    # Daily open per date
    daily_open = {}
    for day, grp in candles.groupby(ts_ny.dt.date, sort=True):
        first = grp.iloc[0]
        # First bar at/after 09:30 ET, else the first bar of the group
        rth = grp[grp['timestamp_ny'].dt.time >= dtime(9, 30)]
        if not rth.empty:
            daily_open[day] = float(rth.iloc[0]['open'])
        else:
            daily_open[day] = float(first['open'])

    # Levels-already-swept-today: group sweeps by date
    out['sweep_date'] = pd.to_datetime(out['sweep_ts']).dt.date
    out = out.sort_values(['sweep_date', 'sweep_idx']).reset_index(drop=True)
    out['levels_already_swept_today'] = out.groupby('sweep_date').cumcount()

    # ATR regime quintile over trailing 60d (~60*390*2 bars on 30s RTH).
    # Use a rolling quantile bucket on the ATR series itself, simplified.
    atr_series = pd.Series(atr)
    atr_rank = atr_series.rolling(60 * 60 * 2, min_periods=100).rank(pct=True)
    # Fallback full-series pct rank for the early window
    atr_rank = atr_rank.fillna(atr_series.rank(pct=True))
    atr_quintile = np.clip((atr_rank * 5).astype(int), 0, 4)

    rows = []
    for row in out.itertuples(index=False):
        i = row.sweep_idx
        t = row.sweep_ts.time() if hasattr(row.sweep_ts, 'time') \
            else pd.Timestamp(row.sweep_ts).time()
        dow = pd.Timestamp(row.sweep_ts).dayofweek

        breach_range = highs[i] - lows[i]
        a = atr[i] if atr[i] > 0 else 1.0
        disp_atr = breach_range / a
        body = abs(closes[i] - opens[i])
        body_ratio = (body / breach_range) if breach_range > 0 else 0.0
        vol_ratio = (vols[i] / vol_med20[i]) if vol_med20[i] and vol_med20[i] > 0 else 0.0

        date = row.sweep_date
        dopen = daily_open.get(date, float(opens[i]))
        dist_from_open_atr = (closes[i] - dopen) / a

        runway = _runway_to_next_level(row, levels)
        runway_atr = (runway / a) if runway is not None else np.nan

        rows.append({
            'tod_bucket': _tod_bucket(t),
            'day_of_week': dow,
            'macro_window': _macro_window(t, minutes=10),
            'breach_displacement_atr': float(disp_atr),
            'breach_body_ratio': float(body_ratio),
            'breach_vol_ratio_20': float(vol_ratio),
            'dist_from_daily_open_atr': float(dist_from_open_atr),
            'atr_quintile': int(atr_quintile.iloc[i])
                if not pd.isna(atr_quintile.iloc[i]) else 2,
            'runway_to_next_level_pts': runway if runway is not None else np.nan,
            'runway_to_next_level_atr': runway_atr,
        })

    feat_df = pd.DataFrame(rows)
    out = pd.concat([out.reset_index(drop=True), feat_df], axis=1)
    out = out.drop(columns=['sweep_date'])
    return out
