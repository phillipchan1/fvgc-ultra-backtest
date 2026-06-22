"""IFVG Reversal trade simulation engine — §8-§10.

Spec: ifvg_reversal/SPEC.md v0.3.1.

v0.3.1 ships target config A (fixed 1R) only. Configs B (scaled Tempo trim
ladder) and C (structural opposite-range) are future work — wire when the
A baseline is stable and we have enough trades to compare.

Stop logic (§9):
  - Hard stop: sweep wick extreme + HARD_STOP_BUFFER (intracandle).
  - Soft stop: a candle CLOSE that re-inverts the target gap (close above
    gap.top for shorts; close below gap.bottom for longs). Checked at
    candle close, per Tempo "wait for candle close".

Intracandle ambiguity: if a candle's high/low touches both hard_stop and
target, assume the stop fired first (pessimistic — standard backtest convention).
"""

from dataclasses import dataclass, field
from datetime import time as dtime
from enum import Enum
from typing import Dict, List, Optional

import pandas as pd

from .constants import HARD_STOP_BUFFER
from .model import Signal


# Session close — flat any trade still open at this NY time.
_EOD_TIME = dtime(16, 0)


class TargetConfig(str, Enum):
    FIXED_1R = "A_fixed_1r"
    SCALED = "B_scaled"
    STRUCTURAL = "C_structural"


@dataclass
class TradeResult:
    signal: Signal
    target_config: TargetConfig
    entry_timestamp_ny: pd.Timestamp
    entry_price: float
    exit_timestamp_ny: pd.Timestamp
    exit_price: float
    exit_reason: str          # 'target' | 'hard_stop' | 'soft_stop' | 'eod' | 'no_data'
    direction: str            # 'long' | 'short'
    stop_distance_pts: float  # initial 1R in NQ points
    r_multiple: float
    pnl_pts: float
    bars_held: int
    notes: Dict = field(default_factory=dict)


def simulate_trades(
    signals: List[Signal],
    candles_30s: pd.DataFrame,
    target_config: TargetConfig = TargetConfig.FIXED_1R,
) -> List[TradeResult]:
    """Walk each Signal forward; return realized TradeResults."""
    if target_config != TargetConfig.FIXED_1R:
        raise NotImplementedError(
            f"Target config {target_config.value} — v0.3.1 ships A only."
        )

    base = candles_30s[['timestamp_ny', 'open', 'high', 'low', 'close']].copy()
    base['date_ny'] = base['timestamp_ny'].dt.date.astype(str)

    results: List[TradeResult] = []
    for sig in signals:
        results.append(_simulate_one_fixed_1r(sig, base))
    return results


def _simulate_one_fixed_1r(sig: Signal, base: pd.DataFrame) -> TradeResult:
    direction = sig.direction
    entry_ts = sig.timestamp_ny
    entry = sig.entry_price
    gap = sig.target_gap
    sweep = sig.triggering_sweep

    # §9.2 v0.3.3 — hard stop = far edge of target gap + buffer (gap-based, not sweep-wick).
    # Rationale: the IFVG defines invalidation, not how deep the sweep went. Sweep-wick
    # stops produced absurd 50-85pt R denominators on deep-penetration sweeps.
    if direction == 'short':
        soft_level = gap.top                  # close above => re-invert
        hard_stop = gap.top + HARD_STOP_BUFFER
        stop_distance = hard_stop - entry
        target = entry - stop_distance        # 1R below
    else:  # long
        soft_level = gap.bottom               # close below => re-invert
        hard_stop = gap.bottom - HARD_STOP_BUFFER
        stop_distance = entry - hard_stop
        target = entry + stop_distance

    # Walk forward 30s candles in same NY date, after entry, up to EOD.
    date_str = str(entry_ts.date())
    forward = base[
        (base['date_ny'] == date_str) &
        (base['timestamp_ny'] > entry_ts) &
        (base['timestamp_ny'].dt.time <= _EOD_TIME)
    ]
    if forward.empty:
        return _close_at(sig, entry_ts, entry, 'no_data', direction,
                         stop_distance, 0, gap, sweep)

    for i, c in enumerate(forward.itertuples(index=False), start=1):
        ts = c.timestamp_ny

        if direction == 'short':
            hit_stop = c.high >= hard_stop
            hit_tgt = c.low <= target
        else:
            hit_stop = c.low <= hard_stop
            hit_tgt = c.high >= target

        if hit_stop and hit_tgt:
            return _close_at(sig, ts, hard_stop, 'hard_stop', direction,
                             stop_distance, i, gap, sweep,
                             notes={'ambiguous_candle': True})
        if hit_stop:
            return _close_at(sig, ts, hard_stop, 'hard_stop', direction,
                             stop_distance, i, gap, sweep)
        if hit_tgt:
            return _close_at(sig, ts, target, 'target', direction,
                             stop_distance, i, gap, sweep)

        # §9.1 soft stop on close
        if direction == 'short' and c.close > soft_level:
            return _close_at(sig, ts, c.close, 'soft_stop', direction,
                             stop_distance, i, gap, sweep)
        if direction == 'long' and c.close < soft_level:
            return _close_at(sig, ts, c.close, 'soft_stop', direction,
                             stop_distance, i, gap, sweep)

    # Reached end of session — flat at last candle's close.
    last = forward.iloc[-1]
    return _close_at(sig, last['timestamp_ny'], float(last['close']),
                     'eod', direction, stop_distance, len(forward), gap, sweep)


def _close_at(
    sig: Signal,
    ts: pd.Timestamp,
    exit_price: float,
    reason: str,
    direction: str,
    stop_distance: float,
    bars: int,
    gap,
    sweep,
    notes: Optional[Dict] = None,
) -> TradeResult:
    if direction == 'short':
        pnl = sig.entry_price - exit_price
    else:
        pnl = exit_price - sig.entry_price
    r = pnl / stop_distance if stop_distance > 0 else 0.0
    return TradeResult(
        signal=sig,
        target_config=TargetConfig.FIXED_1R,
        entry_timestamp_ny=sig.timestamp_ny,
        entry_price=sig.entry_price,
        exit_timestamp_ny=ts,
        exit_price=float(exit_price),
        exit_reason=reason,
        direction=direction,
        stop_distance_pts=float(stop_distance),
        r_multiple=float(r),
        pnl_pts=float(pnl),
        bars_held=bars,
        notes=notes or {},
    )


# =====================================================================
# Summary
# =====================================================================

def summarize_results(trades: List[TradeResult]) -> Dict:
    if not trades:
        return {'total': 0}

    wins = [t for t in trades if t.r_multiple > 0]
    losses = [t for t in trades if t.r_multiple < 0]
    flat = [t for t in trades if t.r_multiple == 0]
    total_pnl = sum(t.pnl_pts for t in trades)
    wr = (len(wins) / (len(wins) + len(losses)) * 100) if (wins or losses) else None
    gross_win = sum(t.pnl_pts for t in wins)
    gross_loss = abs(sum(t.pnl_pts for t in losses)) or 1e-9
    pf = gross_win / gross_loss if losses else float('inf')

    by_reason: Dict[str, int] = {}
    for t in trades:
        by_reason[t.exit_reason] = by_reason.get(t.exit_reason, 0) + 1

    by_grade: Dict[str, Dict] = {}
    for t in trades:
        g = t.signal.grade
        d = by_grade.setdefault(g, {'wins': 0, 'losses': 0, 'pnl': 0.0})
        if t.r_multiple > 0:
            d['wins'] += 1
        elif t.r_multiple < 0:
            d['losses'] += 1
        d['pnl'] += t.pnl_pts

    return {
        'total': len(trades),
        'wins': len(wins),
        'losses': len(losses),
        'flat': len(flat),
        'win_rate': wr,
        'total_pnl_pts': total_pnl,
        'profit_factor': pf,
        'avg_r': sum(t.r_multiple for t in trades) / len(trades),
        'by_exit_reason': by_reason,
        'by_grade': by_grade,
    }


def print_summary(stats: Dict) -> None:
    if stats.get('total', 0) == 0:
        print("\n  No trades.")
        return
    print(f"\n  Trades:      {stats['total']}")
    print(f"  Wins/Losses: {stats['wins']} / {stats['losses']}  (flat: {stats['flat']})")
    if stats['win_rate'] is not None:
        print(f"  Win rate:    {stats['win_rate']:.1f}%")
    print(f"  Avg R:       {stats['avg_r']:+.2f}")
    print(f"  Total P&L:   {stats['total_pnl_pts']:+.1f} pts")
    pf = stats['profit_factor']
    pf_str = f"{pf:.2f}" if pf != float('inf') else "inf"
    print(f"  Profit factor: {pf_str}")
    print(f"  By exit reason: {stats['by_exit_reason']}")
    if stats.get('by_grade'):
        print("  By grade:")
        for g, d in stats['by_grade'].items():
            print(f"    {g}: W={d['wins']} L={d['losses']}  P&L={d['pnl']:+.1f}")
