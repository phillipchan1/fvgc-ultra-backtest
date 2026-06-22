"""Data wick — trade simulation. §15.7 stop + §15.8 target.

v0.4.1 changes:
  - target_mode: 'fixed_1r' OR 'structural' (opposite wick side). Pick per call.
  - Hybrid stop: gap-edge by default, but if entry is within PROXIMITY_TO_WICK_PTS
    of the swept wick extreme, fall back to wick-side stop (structurally meaningful).
"""

from dataclasses import dataclass, field
from datetime import time as dtime
from enum import Enum
from typing import Dict, List, Optional

import pandas as pd

from ..constants import HARD_STOP_BUFFER, TF_SECONDS
from .constants import PROXIMITY_TO_WICK_PTS
from .model import DataWickSignal


_EOD_TIME = dtime(16, 0)


class TargetMode(str, Enum):
    FIXED_1R = "fixed_1r"
    STRUCTURAL = "structural"  # opposite wick side, §15.8


@dataclass
class DataWickTrade:
    signal: DataWickSignal
    target_mode: TargetMode
    entry_timestamp_ny: pd.Timestamp
    entry_price: float
    exit_timestamp_ny: pd.Timestamp
    exit_price: float
    exit_reason: str          # 'target' | 'hard_stop' | 'soft_stop' | 'eod' | 'no_data'
    direction: str
    stop_distance_pts: float
    target_distance_pts: float
    stop_kind: str            # 'gap_edge' | 'wick_side' — which §15.7 branch fired
    r_multiple: float
    pnl_pts: float
    bars_held: int
    notes: Dict = field(default_factory=dict)


def simulate_trades(
    signals: List[DataWickSignal],
    candles_30s: pd.DataFrame,
    target_mode: TargetMode = TargetMode.STRUCTURAL,
) -> List[DataWickTrade]:
    base = candles_30s[['timestamp_ny', 'open', 'high', 'low', 'close']].copy()
    base['date_ny'] = base['timestamp_ny'].dt.date.astype(str)
    return [_simulate_one(sig, base, target_mode) for sig in signals]


def _simulate_one(
    sig: DataWickSignal,
    base: pd.DataFrame,
    target_mode: TargetMode,
) -> DataWickTrade:
    direction = sig.direction
    entry_ts = sig.timestamp_ny
    entry = sig.entry_price
    gap = sig.target_gap

    # --- §15.7 v0.4.1 — hybrid stop ---
    if direction == 'short':
        swept_wick_extreme = sig.wick_high
        gap_edge_stop = gap.top + HARD_STOP_BUFFER
        wick_side_stop = swept_wick_extreme + HARD_STOP_BUFFER
        soft_level = gap.top
    else:
        swept_wick_extreme = sig.wick_low
        gap_edge_stop = gap.bottom - HARD_STOP_BUFFER
        wick_side_stop = swept_wick_extreme - HARD_STOP_BUFFER
        soft_level = gap.bottom

    if abs(entry - swept_wick_extreme) <= PROXIMITY_TO_WICK_PTS:
        hard_stop = wick_side_stop
        stop_kind = 'wick_side'
    else:
        hard_stop = gap_edge_stop
        stop_kind = 'gap_edge'

    stop_distance = (hard_stop - entry) if direction == 'short' else (entry - hard_stop)

    # --- §15.8 v0.4.1 — target ---
    if target_mode == TargetMode.STRUCTURAL:
        target = sig.wick_low if direction == 'short' else sig.wick_high
        target_distance = (entry - target) if direction == 'short' else (target - entry)
    else:  # FIXED_1R
        if direction == 'short':
            target = entry - stop_distance
            target_distance = stop_distance
        else:
            target = entry + stop_distance
            target_distance = stop_distance

    date_str = str(entry_ts.date())
    forward = base[
        (base['date_ny'] == date_str) &
        (base['timestamp_ny'] > entry_ts) &
        (base['timestamp_ny'].dt.time <= _EOD_TIME)
    ]
    if forward.empty or stop_distance <= 0 or target_distance <= 0:
        return _close(sig, target_mode, stop_kind, entry_ts, entry, 'no_data',
                      direction, stop_distance, target_distance, 0.0, 0.0, 0)

    for i, c in enumerate(forward.itertuples(index=False), start=1):
        ts = c.timestamp_ny
        if direction == 'short':
            hit_stop = c.high >= hard_stop
            hit_tgt = c.low <= target
        else:
            hit_stop = c.low <= hard_stop
            hit_tgt = c.high >= target

        if hit_stop and hit_tgt:
            return _close(sig, target_mode, stop_kind, ts, hard_stop, 'hard_stop',
                          direction, stop_distance, target_distance,
                          _r(direction, entry, hard_stop, stop_distance),
                          _pnl(direction, entry, hard_stop), i,
                          notes={'ambiguous_candle': True})
        if hit_stop:
            return _close(sig, target_mode, stop_kind, ts, hard_stop, 'hard_stop',
                          direction, stop_distance, target_distance,
                          _r(direction, entry, hard_stop, stop_distance),
                          _pnl(direction, entry, hard_stop), i)
        if hit_tgt:
            return _close(sig, target_mode, stop_kind, ts, target, 'target',
                          direction, stop_distance, target_distance,
                          _r(direction, entry, target, stop_distance),
                          _pnl(direction, entry, target), i)

        if direction == 'short' and c.close > soft_level:
            return _close(sig, target_mode, stop_kind, ts, c.close, 'soft_stop',
                          direction, stop_distance, target_distance,
                          _r(direction, entry, c.close, stop_distance),
                          _pnl(direction, entry, c.close), i)
        if direction == 'long' and c.close < soft_level:
            return _close(sig, target_mode, stop_kind, ts, c.close, 'soft_stop',
                          direction, stop_distance, target_distance,
                          _r(direction, entry, c.close, stop_distance),
                          _pnl(direction, entry, c.close), i)

    last = forward.iloc[-1]
    exit_p = float(last['close'])
    return _close(sig, target_mode, stop_kind, last['timestamp_ny'], exit_p, 'eod',
                  direction, stop_distance, target_distance,
                  _r(direction, entry, exit_p, stop_distance),
                  _pnl(direction, entry, exit_p), len(forward))


def _pnl(direction, entry, exit_p) -> float:
    return entry - exit_p if direction == 'short' else exit_p - entry


def _r(direction, entry, exit_p, stop_distance) -> float:
    if stop_distance <= 0:
        return 0.0
    return _pnl(direction, entry, exit_p) / stop_distance


def _close(sig, target_mode, stop_kind, ts, exit_p, reason, direction,
           stop_d, target_d, r, pnl, bars, notes=None):
    return DataWickTrade(
        signal=sig,
        target_mode=target_mode,
        entry_timestamp_ny=sig.timestamp_ny,
        entry_price=sig.entry_price,
        exit_timestamp_ny=ts,
        exit_price=float(exit_p),
        exit_reason=reason,
        direction=direction,
        stop_distance_pts=float(stop_d),
        target_distance_pts=float(target_d),
        stop_kind=stop_kind,
        r_multiple=float(r),
        pnl_pts=float(pnl),
        bars_held=int(bars),
        notes=notes or {},
    )
