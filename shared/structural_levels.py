"""Structural target levels — equal H/L clusters + N-day rolling magnets.

Used as:
  - Factor source (distance_to_nearest_magnet_in_trade_direction) for any setup type
  - Engine structural target mode (target = nearest magnet, not fixed-R)
  - DOL setup-pipeline triggers (within X pts of magnet → enter toward)

Shared between fvgc/ and ifvg_reversal/ — these levels are universal.

Equal H/L:
  - Swing highs/lows detected via 3-candle fractal (h[i] > h[i-1] AND h[i] > h[i+1]).
  - Clusters: 2+ swings of same side within `tolerance_pts` price distance.
  - "Active" until a candle closes past the cluster price.

N-day rolling highs/lows:
  - 5-day and 20-day highs/lows from session highs/lows.
  - "Active" until a NEW session high/low exceeds (then it advances).
"""

from dataclasses import dataclass
from typing import List, Optional, Tuple
import pandas as pd


# ----- Equal H/L clusters -----

@dataclass
class EqualLevel:
    """A cluster of nearby swing highs OR lows that price has repeatedly tested."""
    price: float                        # Average price of the cluster's touches
    side: str                           # 'high' or 'low'
    touch_count: int                    # Number of swings forming the cluster
    first_touch_ts: pd.Timestamp        # Earliest swing timestamp
    last_touch_ts: pd.Timestamp         # Most recent swing timestamp (before broken)
    broken_at: Optional[pd.Timestamp] = None  # Timestamp when a close passed the cluster


def detect_swing_pivots(candles: pd.DataFrame, n: int = 2) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Return (swing_highs_df, swing_lows_df) using N-bar fractal.

    A bar at index i is a swing high if its `high` is the max of [i-n .. i+n].
    Mirror for lows.
    """
    h = candles['high'].values
    l = candles['low'].values
    n_bars = len(candles)

    sw_high = []
    sw_low = []
    for i in range(n, n_bars - n):
        window_high = h[i-n:i+n+1]
        window_low = l[i-n:i+n+1]
        if h[i] == window_high.max() and h[i] > h[i-1]:  # strict to avoid plateaus
            sw_high.append(i)
        if l[i] == window_low.min() and l[i] < l[i-1]:
            sw_low.append(i)

    highs = candles.iloc[sw_high][['timestamp_ny', 'high']].copy() if sw_high else candles.iloc[0:0][['timestamp_ny','high']].copy()
    lows = candles.iloc[sw_low][['timestamp_ny', 'low']].copy() if sw_low else candles.iloc[0:0][['timestamp_ny','low']].copy()
    highs.columns = ['ts', 'price']
    lows.columns = ['ts', 'price']
    highs['side'] = 'high'
    lows['side'] = 'low'
    return highs.reset_index(drop=True), lows.reset_index(drop=True)


def cluster_swings(swings: pd.DataFrame, tolerance_pts: float = 3.0,
                   min_touches: int = 2) -> List[EqualLevel]:
    """Greedy cluster swings of the same side that are within tolerance_pts.

    Returns clusters with ≥ min_touches.
    """
    if swings.empty:
        return []
    side = swings['side'].iloc[0]
    work = swings.sort_values('price').reset_index(drop=True)

    clusters: List[List[int]] = []
    current: List[int] = [0]
    for i in range(1, len(work)):
        if work['price'].iloc[i] - work['price'].iloc[current[-1]] <= tolerance_pts:
            current.append(i)
        else:
            if len(current) >= min_touches:
                clusters.append(current)
            current = [i]
    if len(current) >= min_touches:
        clusters.append(current)

    out: List[EqualLevel] = []
    for idxs in clusters:
        sub = work.iloc[idxs]
        out.append(EqualLevel(
            price=float(sub['price'].mean()),
            side=side,
            touch_count=len(idxs),
            first_touch_ts=sub['ts'].min(),
            last_touch_ts=sub['ts'].max(),
        ))
    return out


def mark_broken_clusters(clusters: List[EqualLevel], candles: pd.DataFrame,
                         buffer_pts: float = 1.0) -> None:
    """Set broken_at for each cluster when a close definitively passes the level.

    For high-clusters: close > cluster.price + buffer_pts.
    For low-clusters: close < cluster.price - buffer_pts.
    Only considers candles AFTER last_touch_ts.
    """
    for c in clusters:
        future = candles[candles['timestamp_ny'] > c.last_touch_ts]
        if c.side == 'high':
            broken = future[future['close'] > c.price + buffer_pts]
        else:
            broken = future[future['close'] < c.price - buffer_pts]
        if not broken.empty:
            c.broken_at = broken['timestamp_ny'].iloc[0]


def nearest_active_cluster(
    clusters: List[EqualLevel],
    at_ts: pd.Timestamp,
    at_price: float,
    direction: str,  # 'above' (return nearest high above price) or 'below'
) -> Optional[EqualLevel]:
    """Return the nearest unbroken cluster of opposite side, in the queried direction."""
    if direction == 'above':
        needed_side = 'high'
    elif direction == 'below':
        needed_side = 'low'
    else:
        raise ValueError(f"direction must be 'above' or 'below', got {direction!r}")

    candidates = []
    for c in clusters:
        if c.side != needed_side:
            continue
        if c.first_touch_ts > at_ts:
            continue  # not yet formed
        if c.broken_at is not None and c.broken_at <= at_ts:
            continue  # already broken before this lookup
        if direction == 'above' and c.price <= at_price:
            continue
        if direction == 'below' and c.price >= at_price:
            continue
        candidates.append(c)

    if not candidates:
        return None

    if direction == 'above':
        return min(candidates, key=lambda c: c.price - at_price)
    return min(candidates, key=lambda c: at_price - c.price)


# ----- N-day rolling H/L -----

def rolling_high_low(candles: pd.DataFrame, n_days: int) -> pd.DataFrame:
    """Compute rolling N-day high and low at each timestamp.

    Resamples to daily highs/lows, then rolling-max/min, then back to candle grid.
    """
    df = candles[['timestamp_ny', 'high', 'low']].copy()
    df['date_ny'] = df['timestamp_ny'].dt.date.astype(str)
    daily = df.groupby('date_ny').agg(day_high=('high', 'max'), day_low=('low', 'min')).reset_index()
    daily['n_day_high'] = daily['day_high'].rolling(window=n_days, min_periods=1).max().shift(1)
    daily['n_day_low']  = daily['day_low'].rolling(window=n_days, min_periods=1).min().shift(1)
    return daily[['date_ny', 'n_day_high', 'n_day_low']]
