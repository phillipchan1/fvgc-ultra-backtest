"""Chop / day-quality filter — §11.

Per-day check; runs once per session, not per-candle.

§11.1 — RTH high-low range at 10:30 NY < CHOP_AM_RANGE_MIN -> chop.
§11.2 — Price still inside the 09:30-09:45 OR by OR_CONTAINMENT_DEADLINE -> chop.

§11.3 equilibrium veto lives in model.py (depends on live price relative to
dealing range), not here.
"""

from dataclasses import dataclass
from datetime import time as dtime
from typing import Dict, Optional

import pandas as pd

from ..constants import (
    CHOP_AM_RANGE_MIN,
    OR_CONTAINMENT_DEADLINE,
    TRADING_WINDOW_START,
)


_OR_END = dtime(9, 45)
_AM_RANGE_CHECK = dtime(10, 30)


@dataclass
class ChopVerdict:
    """§11 per-day chop assessment."""
    session_date: str                 # 'YYYY-MM-DD' (NY date)
    am_range_at_1030: Optional[float] # None if insufficient data
    am_range_chop: bool               # §11.1
    or_contained_at_deadline: bool    # §11.2
    is_chop_day: bool                 # OR of the above

    @property
    def reason(self) -> str:
        reasons = []
        if self.am_range_chop:
            reasons.append(f"AM range {self.am_range_at_1030:.0f} < {CHOP_AM_RANGE_MIN:.0f}")
        if self.or_contained_at_deadline:
            reasons.append(f"OR not expanded by {OR_CONTAINMENT_DEADLINE.strftime('%H:%M')}")
        return "; ".join(reasons) or "clean"


def assess_day(candles_30s: pd.DataFrame, session_date: str) -> ChopVerdict:
    """Return a ChopVerdict for the given NY session date.

    For single-day calls; for whole-cohort use `assess_all_days` which is much faster.
    """
    df = candles_30s[['timestamp_ny', 'high', 'low']].copy()
    df = df[df['timestamp_ny'].dt.date.astype(str) == session_date]
    return _assess_day_from_session(df, session_date)


def assess_all_days(candles_30s: pd.DataFrame) -> Dict[str, ChopVerdict]:
    """Assess every NY date present in `candles_30s` — O(N) total, not O(N×D)."""
    if candles_30s.empty:
        return {}
    # Pre-extract just the columns we need + the date key, once.
    df = candles_30s[['timestamp_ny', 'high', 'low']].copy()
    df['_date'] = df['timestamp_ny'].dt.date.astype(str)
    out: Dict[str, ChopVerdict] = {}
    for date_str, day in df.groupby('_date', sort=True):
        out[date_str] = _assess_day_from_session(day, date_str)
    return out


def _assess_day_from_session(df: pd.DataFrame, session_date: str) -> ChopVerdict:
    """Compute the verdict from a pre-filtered single-day frame."""
    df = df[df['timestamp_ny'].dt.time >= TRADING_WINDOW_START]
    am = df[df['timestamp_ny'].dt.time <= _AM_RANGE_CHECK]
    if am.empty:
        return ChopVerdict(session_date, None, False, False, False)
    am_range = float(am['high'].max() - am['low'].min())
    am_range_chop = am_range < CHOP_AM_RANGE_MIN

    # §11.2 — opening range 09:30..09:45, containment at OR_CONTAINMENT_DEADLINE
    or_bars = df[df['timestamp_ny'].dt.time < _OR_END]
    or_contained = False
    if not or_bars.empty:
        or_high = or_bars['high'].max()
        or_low = or_bars['low'].min()
        post_or = df[
            (df['timestamp_ny'].dt.time >= _OR_END) &
            (df['timestamp_ny'].dt.time <= OR_CONTAINMENT_DEADLINE)
        ]
        if not post_or.empty:
            escaped = (post_or['high'] > or_high) | (post_or['low'] < or_low)
            or_contained = not bool(escaped.any())

    return ChopVerdict(
        session_date=session_date,
        am_range_at_1030=am_range,
        am_range_chop=bool(am_range_chop),
        or_contained_at_deadline=or_contained,
        is_chop_day=bool(am_range_chop or or_contained),
    )
