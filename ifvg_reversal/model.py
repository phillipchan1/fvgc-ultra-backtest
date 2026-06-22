"""IFVG Reversal model — §1 procedural pipeline.

Spec: ifvg_reversal/SPEC.md v0.3.1.

Composes the three detectors per §1 order:
  §11 chop -> §4 sweep -> §3 premium/discount -> §3.2 equilibrium veto ->
  §5 reaction -> §6 target gap -> §7 momentum -> §2 killzone (on entry) ->
  §12 grade -> emit Signal.

CHANGELOG:
  v0.3.1: initial implementation of generate_signals + helpers.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import pandas as pd

from .constants import (
    ACTIVE_SWEEP_LEVELS,
    APLUS_BODY_FRACTION,
    CONFIRMATION_WINDOW_SECONDS,
    EQUILIBRIUM_BAND,
    IDEAL_FVG_SIZE_MAX,
    IDEAL_FVG_SIZE_MIN,
    MOMENTUM_BODY_FRACTION,
    NUKE_THRESHOLD,
    REACTION_MIN_MOVE,
    REACTION_STALL_BAND,
    REACTION_WINDOW_CANDLES,
    SWEEP_CANDLE_SECONDS,
    TF_SECONDS,
    TRADING_WINDOW_END,
    TRADING_WINDOW_START,
)
from .detectors.chop import ChopVerdict, assess_all_days
from .detectors.multi_tf_fvg import MultiTFGap, build_fvg_inventory, mark_inversions
from .detectors.sweep import Sweep, detect_sweeps


@dataclass
class Signal:
    """§7 v0.3.1 entry signal."""
    timestamp_ny: pd.Timestamp    # close time of the inverting candle = entry time
    direction: str                # 'long' or 'short'
    entry_price: float            # close of inverting candle
    target_gap: MultiTFGap        # the inverted FVG (defines §9 soft stop)
    triggering_sweep: Sweep       # §4 sweep that armed this setup
    grade: str                    # 'A+' or 'B' per §12
    tags: Dict = field(default_factory=dict)


@dataclass
class RejectedSetup:
    """Diagnostic record for any sweep that didn't produce a Signal. Useful
    for tuning — tells you which gate filtered each candidate."""
    sweep: Sweep
    reason: str
    detail: Optional[str] = None


def generate_signals(
    candles_30s: pd.DataFrame,
    levels: pd.DataFrame,
    return_rejections: bool = False,
) -> Tuple[List[Signal], List[RejectedSetup]]:
    """Run the §1 pipeline over all sessions in `candles_30s`.

    Returns (signals, rejections). `rejections` is empty unless
    `return_rejections=True` — populated for diagnostics during tuning.
    """
    signals: List[Signal] = []
    rejections: List[RejectedSetup] = []

    if candles_30s.empty:
        return signals, rejections

    # §11 per-session chop verdicts
    chop = assess_all_days(candles_30s)

    # §6 FVG inventory + inversions
    gaps = build_fvg_inventory(candles_30s)
    mark_inversions(gaps, candles_30s)

    # §4 sweeps
    sweeps = detect_sweeps(candles_30s, levels)

    # Equilibrium veto needs per-day "all major liquidity swept pre-RTH" status.
    pre_rth_all_swept = _all_major_swept_pre_rth(levels)

    # Pre-index candles for fast per-session lookups.
    base = candles_30s[['timestamp_ny', 'open', 'high', 'low', 'close']].copy()
    base['date_ny'] = base['timestamp_ny'].dt.date.astype(str)

    for sweep in sweeps:
        date_str = str(sweep.timestamp_ny.date())
        day_candles = base[base['date_ny'] == date_str]

        # §11 chop gate
        verdict = chop.get(date_str)
        if verdict is None or verdict.is_chop_day:
            if return_rejections:
                rejections.append(RejectedSetup(sweep, "chop", verdict.reason if verdict else "no_verdict"))
            continue

        # §3 dealing range + premium/discount gate
        dr = _dealing_range(day_candles, sweep.timestamp_ny)
        if dr is None:
            if return_rejections:
                rejections.append(RejectedSetup(sweep, "no_dealing_range"))
            continue
        dr_low, dr_high = dr
        if not _on_correct_side(sweep.level_price, dr_low, dr_high, sweep.reversal_direction):
            if return_rejections:
                rejections.append(RejectedSetup(sweep, "wrong_side_of_range"))
            continue

        # §3.2 equilibrium veto
        if pre_rth_all_swept.get(date_str, False):
            mid = (dr_low + dr_high) / 2.0
            if abs(sweep.level_price - mid) <= EQUILIBRIUM_BAND:
                if return_rejections:
                    rejections.append(RejectedSetup(sweep, "equilibrium_veto"))
                continue

        # §5 reaction quality
        ok, reason = _passes_reaction_check(sweep, day_candles)
        if not ok:
            if return_rejections:
                rejections.append(RejectedSetup(sweep, "reaction_failed", reason))
            continue

        # §6 target gap selection
        target = _pick_target_gap(sweep, gaps)
        if target is None:
            if return_rejections:
                rejections.append(RejectedSetup(sweep, "no_target_gap"))
            continue

        # §7 momentum confirmation
        if not _confirms_momentum(target):
            if return_rejections:
                rejections.append(RejectedSetup(sweep, "momentum_insufficient",
                                                f"body={target.inversion_body_fraction:.2f}"))
            continue

        # §2 killzone — applied to the entry timestamp (= inversion bar close)
        entry_ts = target.inverted_at + pd.Timedelta(seconds=TF_SECONDS[target.tf])
        if not _in_killzone(entry_ts):
            if return_rejections:
                rejections.append(RejectedSetup(sweep, "entry_outside_killzone",
                                                str(entry_ts.time())))
            continue

        # §12 grade
        grade = _grade_signal(sweep, target, verdict)

        signals.append(Signal(
            timestamp_ny=entry_ts,
            direction='long' if sweep.reversal_direction == 'long' else 'short',
            entry_price=target.inversion_close_price,
            target_gap=target,
            triggering_sweep=sweep,
            grade=grade,
            tags={},
        ))

    signals.sort(key=lambda s: s.timestamp_ny)
    return signals, rejections


# =====================================================================
# Helpers — exposed for unit testing
# =====================================================================

def _in_killzone(ts_ny: pd.Timestamp) -> bool:
    """§2.1 — entry time inside 09:30..11:00 NY."""
    t = ts_ny.time()
    return TRADING_WINDOW_START <= t <= TRADING_WINDOW_END


def _dealing_range(
    day_candles: pd.DataFrame,
    at: pd.Timestamp,
) -> Optional[Tuple[float, float]]:
    """§3.1 v0.3.1 — current-day RTH H/L since 09:30, up to and including `at`."""
    rth = day_candles[
        (day_candles['timestamp_ny'].dt.time >= TRADING_WINDOW_START) &
        (day_candles['timestamp_ny'] <= at)
    ]
    if rth.empty:
        return None
    return float(rth['low'].min()), float(rth['high'].max())


def _on_correct_side(
    price: float,
    range_low: float,
    range_high: float,
    reversal_direction: str,
) -> bool:
    """§3.1 — short candidate in premium (≥mid), long candidate in discount (≤mid)."""
    mid = (range_low + range_high) / 2.0
    if reversal_direction == 'short':
        return price >= mid
    if reversal_direction == 'long':
        return price <= mid
    return False


def _all_major_swept_pre_rth(levels: pd.DataFrame) -> Dict[str, bool]:
    """§3.2 helper — per-day flag: were all ACTIVE_SWEEP_LEVELS already swept pre-RTH?"""
    out: Dict[str, bool] = {}
    active = levels[levels['level_name'].isin(ACTIVE_SWEEP_LEVELS)]
    for date_str, day in active.groupby('date'):
        valid = day[day['price'].notna()]
        if valid.empty:
            out[date_str] = False
            continue
        out[date_str] = bool((valid['swept_pre_rth'] == True).all())
    return out


def _passes_reaction_check(
    sweep: Sweep,
    day_candles: pd.DataFrame,
) -> Tuple[bool, str]:
    """§5.1 + §5.2.

    Within REACTION_WINDOW_CANDLES 30s candles after the sweep:
      - At least one close moves ≥ REACTION_MIN_MOVE pts away from sweep_level
        in reversal direction.
      - No close returns within REACTION_STALL_BAND of sweep_level (stall).
      - No close goes ≥ NUKE_THRESHOLD beyond sweep_level in the SWEEP direction.
    """
    after = day_candles[day_candles['timestamp_ny'] > sweep.timestamp_ny].head(
        REACTION_WINDOW_CANDLES
    )
    if len(after) < REACTION_WINDOW_CANDLES:
        return False, "insufficient_post_sweep_candles"

    closes = after['close'].values
    lvl = sweep.level_price

    if sweep.reversal_direction == 'short':
        # Reversal is down. Closes should drop below level - stall_band.
        # Move-away: any close ≤ lvl - MIN_MOVE.
        # Stall: any close ≥ lvl - STALL_BAND.
        # Nuke: any close ≥ lvl + NUKE_THRESHOLD.
        if any(c >= lvl + NUKE_THRESHOLD for c in closes):
            return False, "nuked"
        if any(c >= lvl - REACTION_STALL_BAND for c in closes):
            return False, "stalled"
        if not any(c <= lvl - REACTION_MIN_MOVE for c in closes):
            return False, "insufficient_move"
        return True, "ok"
    else:  # long
        if any(c <= lvl - NUKE_THRESHOLD for c in closes):
            return False, "nuked"
        if any(c <= lvl + REACTION_STALL_BAND for c in closes):
            return False, "stalled"
        if not any(c >= lvl + REACTION_MIN_MOVE for c in closes):
            return False, "insufficient_move"
        return True, "ok"


def _pick_target_gap(
    sweep: Sweep,
    gaps: List[MultiTFGap],
) -> Optional[MultiTFGap]:
    """§6.3 v0.3.1 — first-inverted-wins.

    Eligibility (§6.2):
      - FVG direction matches the reversal-side (bullish FVG for short setup,
        bearish FVG for long setup).
      - Created before the sweep, in the move INTO the swept extreme (same NY date).
      - Not inverted before the sweep.
      - Was inverted after the sweep, within CONFIRMATION_WINDOW_CANDLES × tf_seconds
        of the sweep's close.
      - Size ≥ MIN_FVG_SIZE is already enforced upstream by build_fvg_inventory.

    Among qualifying candidates, the FVG with the EARLIEST inversion-close wins.
    """
    needed_dir = 'bullish' if sweep.reversal_direction == 'short' else 'bearish'
    same_day = str(sweep.timestamp_ny.date())
    sweep_close = sweep.timestamp_ny + pd.Timedelta(seconds=SWEEP_CANDLE_SECONDS)

    best: Optional[MultiTFGap] = None
    best_inv_close: Optional[pd.Timestamp] = None

    for g in gaps:
        if g.direction != needed_dir:
            continue
        if str(g.created_at.date()) != same_day:
            continue
        if g.created_at >= sweep.timestamp_ny:
            continue
        if not g.is_inverted:
            continue
        if g.inverted_at <= sweep.timestamp_ny:
            continue  # inverted before sweep — already consumed

        tf_sec = TF_SECONDS[g.tf]
        inv_close = g.inverted_at + pd.Timedelta(seconds=tf_sec)
        window_end = sweep_close + pd.Timedelta(seconds=CONFIRMATION_WINDOW_SECONDS)
        if not (sweep_close < inv_close <= window_end):
            continue

        if best is None or inv_close < best_inv_close:
            best = g
            best_inv_close = inv_close

    return best


def _confirms_momentum(gap: MultiTFGap) -> bool:
    """§7.2 — inverting bar body ≥ MOMENTUM_BODY_FRACTION of range."""
    if gap.inversion_body_fraction is None:
        return False
    return gap.inversion_body_fraction >= MOMENTUM_BODY_FRACTION


def _grade_signal(
    sweep: Sweep,
    gap: MultiTFGap,
    chop_verdict: ChopVerdict,
) -> str:
    """§12 — A+ if ALL of: ideal gap size, A+ body, fast reaction, chop clean.

    "Structural target ≥ 2× stop distance" is deferred to engine.py once targets
    are computed; can be promoted to A+ post-hoc.
    """
    if chop_verdict.is_chop_day:
        return 'B'

    if not (IDEAL_FVG_SIZE_MIN <= gap.size_pts <= IDEAL_FVG_SIZE_MAX):
        return 'B'

    if gap.inversion_body_fraction is None or gap.inversion_body_fraction < APLUS_BODY_FRACTION:
        return 'B'

    # Fast reaction — inversion bar starts within 1 same-TF bar of sweep close.
    tf_sec = TF_SECONDS[gap.tf]
    sweep_close = sweep.timestamp_ny + pd.Timedelta(seconds=SWEEP_CANDLE_SECONDS)
    if gap.inverted_at > sweep_close + pd.Timedelta(seconds=tf_sec):
        return 'B'

    return 'A+'
