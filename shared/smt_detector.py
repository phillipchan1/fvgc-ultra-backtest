"""SMT (Smart Money Technique) divergence detector — ES↔NQ.

Tempo's most-cited factor (11 mentions across 10 recaps). Definition:

  Bullish SMT  =  one index sweeps a low, the OTHER does NOT make an equivalent low
                  → divergence → reversal-up signal (long bias)
  Bearish SMT  =  one index sweeps a high, the OTHER does NOT
                  → reversal-down signal (short bias)

This module is INSTRUMENT-AGNOSTIC: pass any two candle frames (e.g., NQ + ES,
or NQ + MNQ) plus a lookback window and it returns SMT events.

Implementation strategy (first pass):
  At each timestamp T on the primary instrument, define a session-range based
  "new extreme" question:
    - Did instrument A make a new session-low (since RTH open) within the last
      `lookback_seconds`?
    - Did instrument B make a new session-low in the same window?
    - If exactly one did → SMT divergence (the index that did NOT make the new
      extreme is the one to TRADE in the reversal direction).

Output per-trade signal can be queried via `smt_at(candles_a, candles_b, ts)`.
"""

from dataclasses import dataclass
from datetime import time as dtime
from typing import Optional

import pandas as pd


SESSION_OPEN = dtime(9, 30)


@dataclass
class SMTSignal:
    """Result of SMT check at a given timestamp."""
    bullish_smt: bool          # one index made new low (≤ lookback), other didn't
    bearish_smt: bool          # one made new high, other didn't
    primary_made_new_low: bool   # primary (= candles_a) made new session low in window
    primary_made_new_high: bool
    secondary_made_new_low: bool # secondary (= candles_b) made new session low in window
    secondary_made_new_high: bool
    primary_low: float
    secondary_low: float
    primary_high: float
    secondary_high: float


def session_extremes_at(candles: pd.DataFrame, ts: pd.Timestamp) -> tuple[float, float]:
    """Return (session_high, session_low) for the NY session containing `ts`,
    measured from RTH open through `ts` (exclusive of any time after ts)."""
    date = ts.date()
    session = candles[
        (candles['timestamp_ny'].dt.date == date) &
        (candles['timestamp_ny'].dt.time >= SESSION_OPEN) &
        (candles['timestamp_ny'] < ts)
    ]
    if session.empty:
        return float('nan'), float('nan')
    return float(session['high'].max()), float(session['low'].min())


def made_new_extreme_in_window(
    candles: pd.DataFrame,
    ts: pd.Timestamp,
    lookback_seconds: int,
) -> tuple[bool, bool]:
    """In the [ts - lookback, ts] window, did this instrument make a NEW session
    extreme? Returns (made_new_high, made_new_low).

    "New" = the extreme is reached during the window AND that extreme is the
    session extreme so far up to ts.
    """
    date = ts.date()
    session_start = pd.Timestamp.combine(date, SESSION_OPEN).tz_localize(ts.tz)
    if ts < session_start:
        return False, False

    window_start = ts - pd.Timedelta(seconds=lookback_seconds)
    if window_start < session_start:
        window_start = session_start

    session_so_far = candles[
        (candles['timestamp_ny'].dt.date == date) &
        (candles['timestamp_ny'].dt.time >= SESSION_OPEN) &
        (candles['timestamp_ny'] < ts)
    ]
    if session_so_far.empty:
        return False, False

    # Session extremes
    sess_high = float(session_so_far['high'].max())
    sess_low = float(session_so_far['low'].min())

    # Window subset
    window = session_so_far[session_so_far['timestamp_ny'] >= window_start]
    if window.empty:
        return False, False

    win_high = float(window['high'].max())
    win_low = float(window['low'].min())

    # "New session high" = the window's high equals the session high (it set the level)
    made_new_high = win_high == sess_high
    made_new_low = win_low == sess_low
    return made_new_high, made_new_low


def smt_at(
    candles_primary: pd.DataFrame,
    candles_secondary: pd.DataFrame,
    ts: pd.Timestamp,
    lookback_seconds: int = 300,   # 5-min default window
) -> SMTSignal:
    """Check for SMT divergence between two instruments at a single timestamp."""
    p_high, p_low = session_extremes_at(candles_primary, ts)
    s_high, s_low = session_extremes_at(candles_secondary, ts)

    p_new_high, p_new_low = made_new_extreme_in_window(candles_primary, ts, lookback_seconds)
    s_new_high, s_new_low = made_new_extreme_in_window(candles_secondary, ts, lookback_seconds)

    # Bullish SMT: exactly one made a new session low (the other didn't, so it has
    # a HIGHER low = stronger = trade direction is up on the stronger index).
    bullish = (p_new_low != s_new_low) and (p_new_low or s_new_low)
    bearish = (p_new_high != s_new_high) and (p_new_high or s_new_high)

    return SMTSignal(
        bullish_smt=bullish, bearish_smt=bearish,
        primary_made_new_low=p_new_low, primary_made_new_high=p_new_high,
        secondary_made_new_low=s_new_low, secondary_made_new_high=s_new_high,
        primary_low=p_low, secondary_low=s_low,
        primary_high=p_high, secondary_high=s_high,
    )
