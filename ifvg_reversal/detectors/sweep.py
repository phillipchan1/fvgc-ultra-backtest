"""Liquidity sweep detector — §4.

Emits Sweep events when a candle wicks beyond a tier-2/3 liquidity level
(`ACTIVE_SWEEP_LEVELS` in ifvg_reversal.constants) and closes back through it
in the same candle (§4.2).

The detector does NOT decide whether a sweep is "nuked" (§5.2) — that's the
job of the reaction-quality check in model.py, which has access to subsequent
candles. The Sweep.validity_expires_at field carries the static §4.3 expiry.
"""

from dataclasses import dataclass
from datetime import time as dtime
from typing import List
import pandas as pd

from ..constants import (
    ACTIVE_SWEEP_LEVELS,
    SWEEP_LEVEL_TIER,
    SWEEP_LEVEL_SIDE,
    MIN_SWEEP_PENETRATION,
    SWEEP_VALIDITY_MINUTES,
    TRADING_WINDOW_START,
    TRADING_WINDOW_END,
)


@dataclass
class Sweep:
    """§4 v0.3.1 sweep event."""
    timestamp_ny: pd.Timestamp
    level_name: str                   # 'overnight_high', 'prev_day_low', ...
    tier: int                         # 2 or 3 in v0.3.1
    level_price: float
    reversal_direction: str           # 'short' (high swept) or 'long' (low swept)
    penetration_pts: float            # how far the wick went beyond the level
    validity_expires_at: pd.Timestamp


def detect_sweeps(candles: pd.DataFrame, levels: pd.DataFrame) -> List[Sweep]:
    """Detect §4 sweeps inside the killzone (TRADING_WINDOW_START..END).

    v0.3.4: includes both static session levels (from `levels` CSV) and the
    dynamic running-50% equilibrium level (computed per-candle from candles).

    Args:
        candles: 30s OHLC candles with `timestamp_ny`. Any date range.
        levels:  Long-format per-day levels (one row per (date, level_name)) with
                 columns ['date', 'level_name', 'price', 'swept_pre_rth'].
                 Levels with `price=NaN` or `swept_pre_rth=True` are excluded.

    Returns:
        List of Sweep events, ordered by timestamp. At most one sweep per
        (date, level_name) — first qualifying candle wins, since once swept
        the level is consumed for the session.
    """
    if candles.empty:
        return []

    rth_mask = candles['timestamp_ny'].dt.time.between(
        TRADING_WINDOW_START, TRADING_WINDOW_END, inclusive='both'
    )
    rth = candles.loc[rth_mask, ['timestamp_ny', 'open', 'high', 'low', 'close']].copy()
    rth['date_ny'] = rth['timestamp_ny'].dt.date.astype(str)
    if rth.empty:
        return []

    sweeps: List[Sweep] = []
    validity = pd.Timedelta(minutes=SWEEP_VALIDITY_MINUTES)

    # --- Static levels from the levels CSV ---
    active = levels[levels['level_name'].isin(ACTIVE_SWEEP_LEVELS)].copy()
    active = active[active['price'].notna()]
    active = active[active['swept_pre_rth'] != True]  # keep False and NaN

    for date_str, day_levels in active.groupby('date'):
        day = rth[rth['date_ny'] == date_str]
        if day.empty:
            continue

        for _, lvl in day_levels.iterrows():
            name = lvl['level_name']
            price = float(lvl['price'])
            side = SWEEP_LEVEL_SIDE[name]

            if side == 'high':
                mask = (day['high'] > price + MIN_SWEEP_PENETRATION) & (day['close'] < price)
                reversal = 'short'
            else:
                mask = (day['low'] < price - MIN_SWEEP_PENETRATION) & (day['close'] > price)
                reversal = 'long'

            hits = day[mask]
            if hits.empty:
                continue

            first = hits.iloc[0]
            pen = first['high'] - price if side == 'high' else price - first['low']

            sweeps.append(Sweep(
                timestamp_ny=first['timestamp_ny'],
                level_name=name,
                tier=SWEEP_LEVEL_TIER[name],
                level_price=price,
                reversal_direction=reversal,
                penetration_pts=float(pen),
                validity_expires_at=first['timestamp_ny'] + validity,
            ))

    # v0.3.6: daily_50pct is now loaded from session_levels.csv like other
    # static levels (overnight, asia, london, prev_day) above — no dynamic
    # per-candle detection needed.

    sweeps.sort(key=lambda s: s.timestamp_ny)
    return sweeps
