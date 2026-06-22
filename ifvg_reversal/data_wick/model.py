"""Data wick — pipeline. §15. Reuses FVG inventory from sibling package.

Composes:
  §15.3 sweep (data_wick.detect_data_wick_sweeps)
    -> §6 target gap (multi_tf_fvg, loose params)
    -> §7 momentum
    -> §15.6 entry (close of inverting candle)
    -> §15.7 stop (gap-edge, handed to engine.py)
    -> §15.8 target (opposite wick side — handed to engine.py)
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import pandas as pd

from ..constants import SWEEP_CANDLE_SECONDS, TF_SECONDS
from ..detectors.multi_tf_fvg import MultiTFGap, build_fvg_inventory, mark_inversions
from ..detectors.sweep import Sweep
from .constants import APLUS_DATA_WICK_RANGE, SETUP_WINDOW_MINUTES
from .detectors.data_wick import DataWickSweep, detect_data_wick_sweeps


# Loose defaults — match the population study for the main model.
LOOSE_MIN_FVG_SIZE = 6.0
LOOSE_BODY_MIN = 0.30
LOOSE_CONFIRMATION_WINDOW_SECONDS = 600
APLUS_BODY_FRACTION = 0.70


@dataclass
class DataWickSignal:
    """§15 signal."""
    timestamp_ny: pd.Timestamp     # close of inverting candle = entry time
    direction: str                 # 'long' or 'short'
    entry_price: float
    target_gap: MultiTFGap
    triggering_sweep: Sweep
    wick_high: float
    wick_low: float
    release_label: str             # '0830' or '1000'
    grade: str                     # 'A+' or 'B'
    tags: Dict = field(default_factory=dict)


def generate_signals(
    candles_30s: pd.DataFrame,
    news_days: pd.DataFrame,
    return_rejections: bool = False,
) -> Tuple[List[DataWickSignal], List[Dict]]:
    """Run the §15 data-wick pipeline."""
    signals: List[DataWickSignal] = []
    rejections: List[Dict] = []

    if candles_30s.empty:
        return signals, rejections

    # §6 FVG inventory + inversions (loose, same as population)
    gaps = build_fvg_inventory(candles_30s, min_size=LOOSE_MIN_FVG_SIZE)
    mark_inversions(gaps, candles_30s)

    # §15.3 sweeps (already time-ordered by detect_data_wick_sweeps)
    dws_list = detect_data_wick_sweeps(candles_30s, news_days)

    # v0.4.1 §15.3 — one trade per release (date + release_label). Tempo: "wait for ONE
    # side of that wick to sweep". A subsequent sweep on the other side after the first
    # was tradeable is double-counting.
    used_releases = set()

    for dws in dws_list:
        release_key = (str(dws.sweep.timestamp_ny.date()), dws.release_label)
        if release_key in used_releases:
            if return_rejections:
                rejections.append({'sweep': dws.sweep, 'reason': 'release_already_used'})
            continue

        target = _pick_target_gap(dws.sweep, gaps)
        if target is None:
            if return_rejections:
                rejections.append({'sweep': dws.sweep, 'reason': 'no_target_gap'})
            continue

        entry_ts = target.inverted_at + pd.Timedelta(seconds=TF_SECONDS[target.tf])

        # §15.4 — entry must be inside the setup window (release minute + 60).
        release_ts = pd.Timestamp(dws.sweep.timestamp_ny).normalize() + pd.Timedelta(
            hours=8 if dws.release_label == '0830' else 10,
            minutes=30 if dws.release_label == '0830' else 0,
        )
        # localize to whatever tz the sweep has
        release_ts = release_ts.tz_localize(dws.sweep.timestamp_ny.tz) \
            if release_ts.tzinfo is None else release_ts.tz_convert(dws.sweep.timestamp_ny.tz)
        window_end = release_ts + pd.Timedelta(minutes=SETUP_WINDOW_MINUTES)
        if entry_ts > window_end:
            if return_rejections:
                rejections.append({'sweep': dws.sweep, 'reason': 'entry_past_window'})
            continue

        grade = _grade(dws, target)

        signals.append(DataWickSignal(
            timestamp_ny=entry_ts,
            direction='long' if dws.sweep.reversal_direction == 'long' else 'short',
            entry_price=float(target.inversion_close_price),
            target_gap=target,
            triggering_sweep=dws.sweep,
            wick_high=dws.wick_high,
            wick_low=dws.wick_low,
            release_label=dws.release_label,
            grade=grade,
        ))
        used_releases.add(release_key)

    signals.sort(key=lambda s: s.timestamp_ny)
    return signals, rejections


def _pick_target_gap(sweep: Sweep, gaps: List[MultiTFGap]) -> Optional[MultiTFGap]:
    """§6.3 first-inverted-wins; gap-direction must equal reversal direction; loose params."""
    needed_dir = 'bullish' if sweep.reversal_direction == 'short' else 'bearish'
    same_day = str(sweep.timestamp_ny.date())
    sweep_close = sweep.timestamp_ny + pd.Timedelta(seconds=SWEEP_CANDLE_SECONDS)
    window_end = sweep_close + pd.Timedelta(seconds=LOOSE_CONFIRMATION_WINDOW_SECONDS)

    best = None
    best_inv_close = None
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
            continue
        if (g.inversion_body_fraction or 0.0) < LOOSE_BODY_MIN:
            continue

        tf_sec = TF_SECONDS[g.tf]
        inv_close = g.inverted_at + pd.Timedelta(seconds=tf_sec)
        if not (sweep_close < inv_close <= window_end):
            continue

        if best is None or inv_close < best_inv_close:
            best = g
            best_inv_close = inv_close
    return best


def _grade(dws: DataWickSweep, gap: MultiTFGap) -> str:
    """§15.9 — A+ if data wick large (≥APLUS) AND body fraction ≥APLUS_BODY_FRACTION."""
    wick_range = dws.wick_high - dws.wick_low
    big_wick = wick_range >= APLUS_DATA_WICK_RANGE
    strong_body = (gap.inversion_body_fraction or 0.0) >= APLUS_BODY_FRACTION
    return 'A+' if (big_wick and strong_body) else 'B'
