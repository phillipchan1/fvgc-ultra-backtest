"""Pure FVG primitives.

Both fvgc/ and ifvg_reversal/ detect 3-candle Fair Value Gaps the same way.
They differ in *filters* (min size, time-of-day window) and in the per-model
state attached to each FVG (FVGC tracks taps/retaps; IFVG-reversal tracks
multi-TF source and inversion candle). This module owns only the universal
primitives — the filters and state extensions live in each caller.

fvgc/model.py currently has its own copy of `detect_fvg` predating this
module; it stays untouched for stability. Future cleanup may consolidate.
"""

from dataclasses import dataclass
from typing import Optional
import pandas as pd


@dataclass(frozen=True)
class FVG:
    """Minimal universal FVG record."""
    direction: str          # 'bullish' or 'bearish'
    top: float              # upper bound of the gap body
    bottom: float           # lower bound of the gap body
    mid: float              # (top + bottom) / 2
    size: float             # top - bottom, in price units
    created_ts: pd.Timestamp  # timestamp of C3 (the candle that completes the gap)


def detect_fvg(c1, c2, c3, min_size: float = 0.0) -> Optional[FVG]:
    """Detect a 3-candle FVG.

    Bullish: c1.high < c3.low  (gap body = [c1.high, c3.low]).
    Bearish: c1.low  > c3.high (gap body = [c3.high, c1.low]).

    Args:
        c1, c2, c3: three consecutive candles as pd.Series with at least
                    'high', 'low', 'timestamp_ny' columns. c2 is unused for
                    geometry but kept in signature for clarity / future rules.
        min_size:   minimum gap size in price units. 0.0 disables the filter.

    Returns:
        FVG record, or None if no gap or below min_size.
    """
    _ = c2  # reserved; some FVG variants gate on c2 body characteristics

    if c1['high'] < c3['low']:
        size = c3['low'] - c1['high']
        if size < min_size:
            return None
        top = c3['low']
        bottom = c1['high']
        return FVG(
            direction='bullish',
            top=top,
            bottom=bottom,
            mid=(top + bottom) / 2.0,
            size=size,
            created_ts=c3['timestamp_ny'],
        )

    if c1['low'] > c3['high']:
        size = c1['low'] - c3['high']
        if size < min_size:
            return None
        top = c1['low']
        bottom = c3['high']
        return FVG(
            direction='bearish',
            top=top,
            bottom=bottom,
            mid=(top + bottom) / 2.0,
            size=size,
            created_ts=c3['timestamp_ny'],
        )

    return None


def inverts_fvg(direction: str, top: float, bottom: float, close_price: float) -> bool:
    """Check whether a candle close inverts an FVG.

    Bullish FVG is inverted when a close drops below `bottom` — flipping it
    into bearish resistance. Bearish FVG is inverted when a close rises above
    `top` — flipping it into bullish support.

    Takes scalar fields rather than an FVG instance so callers using a
    different record type (e.g. IFVG-reversal's MultiTFGap) can use it
    without coercion.
    """
    if direction == 'bullish':
        return close_price < bottom
    if direction == 'bearish':
        return close_price > top
    raise ValueError(f"unknown FVG direction: {direction!r}")
