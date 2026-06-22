#!/usr/bin/env python3
"""Sanity-check tool — for each sweep that didn't produce a signal, show
exactly why each candidate FVG was excluded.

Use this to catch over-strict defaults or detector bugs. Focus on
'no_target_gap' rejections first — that's where the model is silently
discarding setups that might be real.
"""

import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pandas as pd

from fvgc.data import load_candles
from ifvg_reversal.constants import (
    CONFIRMATION_WINDOW_CANDLES,
    MIN_FVG_SIZE,
    SWEEP_CANDLE_SECONDS,
    TF_SECONDS,
)
from ifvg_reversal.detectors.multi_tf_fvg import build_fvg_inventory, mark_inversions
from ifvg_reversal.detectors.sweep import detect_sweeps
from ifvg_reversal.model import generate_signals

DATA_PATH = Path('data/consolidated/nq-front-month.ohlcv-30s.csv')
LEVELS_PATH = Path('data/levels/session_levels.csv')
COHORT_DAYS = 60

FOCUS = ('no_target_gap',)   # which rejection reasons to drill into
MAX_PER_REASON = 5


def main():
    candles = load_candles(DATA_PATH)
    levels = pd.read_csv(LEVELS_PATH)

    candle_max = pd.Timestamp(candles['timestamp_ny'].max().date())
    levels_max = pd.Timestamp(levels['date'].max())
    cohort_end = min(candle_max, levels_max)
    cohort_start = cohort_end - timedelta(days=COHORT_DAYS)

    cohort_candles = candles[
        (candles['timestamp_ny'].dt.tz_localize(None) >= cohort_start) &
        (candles['timestamp_ny'].dt.tz_localize(None) <= cohort_end + timedelta(days=1))
    ].copy()
    cohort_levels = levels[
        (pd.to_datetime(levels['date']) >= cohort_start) &
        (pd.to_datetime(levels['date']) <= cohort_end)
    ].copy()

    print(f"Cohort: {cohort_start.date()} -> {cohort_end.date()}")

    # Build full state so we can introspect.
    gaps = build_fvg_inventory(cohort_candles)
    mark_inversions(gaps, cohort_candles)
    sweeps = detect_sweeps(cohort_candles, cohort_levels)
    _, rejections = generate_signals(cohort_candles, cohort_levels, return_rejections=True)

    by_reason = {}
    for r in rejections:
        by_reason.setdefault(r.reason, []).append(r)

    for reason in FOCUS:
        rs = by_reason.get(reason, [])
        print(f"\n{'='*70}\n  Reason: {reason}  ({len(rs)} sweeps)\n{'='*70}")
        for r in rs[:MAX_PER_REASON]:
            _diagnose_no_target(r.sweep, gaps)


def _diagnose_no_target(sweep, all_gaps):
    needed_dir = 'bullish' if sweep.reversal_direction == 'short' else 'bearish'
    same_day = str(sweep.timestamp_ny.date())
    sweep_close = sweep.timestamp_ny + pd.Timedelta(seconds=SWEEP_CANDLE_SECONDS)

    print(f"\nSweep: {sweep.timestamp_ny}  {sweep.level_name} @ {sweep.level_price:.2f} "
          f"(pen={sweep.penetration_pts:.1f}pt -> {sweep.reversal_direction})")
    print(f"  Looking for {needed_dir} FVG inverted in ({sweep_close.time()}, "
          f"{(sweep_close + pd.Timedelta(seconds=CONFIRMATION_WINDOW_CANDLES * 180)).time()}] "
          f"(window depends on TF; max 6m for 3min FVG)")

    candidates = [
        g for g in all_gaps
        if g.direction == needed_dir and str(g.created_at.date()) == same_day
    ]
    if not candidates:
        print(f"  ** No same-day {needed_dir} FVGs at all. **")
        return

    print(f"  Same-day {needed_dir} FVGs (size>={MIN_FVG_SIZE:.0f}): {len(candidates)}")

    # Categorize each
    near_misses = []
    for g in candidates:
        verdict, detail = _classify(g, sweep, sweep_close)
        if verdict == 'PASS':
            print(f"    !! UNEXPECTED PASS: {g.created_at} {g.tf:5} size={g.size_pts:.1f}  {detail}")
        elif verdict == 'NEAR_MISS':
            near_misses.append((g, detail))

    if near_misses:
        print(f"  Near-misses ({len(near_misses)}):")
        for g, detail in sorted(near_misses, key=lambda x: x[0].created_at)[:6]:
            print(f"    {g.created_at}  {g.tf:5}  size={g.size_pts:5.1f}  body="
                  f"{g.inversion_body_fraction if g.inversion_body_fraction else 0:.2f}  -> {detail}")
    else:
        print("  No near-misses — all candidates excluded for clear structural reasons.")


def _classify(gap, sweep, sweep_close):
    if gap.created_at >= sweep.timestamp_ny:
        return 'OUT', f"created AFTER sweep (+{(gap.created_at - sweep.timestamp_ny).total_seconds()/60:.1f}m)"
    if not gap.is_inverted:
        return 'OUT', "never inverted"
    if gap.inverted_at <= sweep.timestamp_ny:
        return 'OUT', f"inverted BEFORE sweep (-{(sweep.timestamp_ny - gap.inverted_at).total_seconds()/60:.1f}m, already consumed)"
    tf_sec = TF_SECONDS[gap.tf]
    inv_close = gap.inverted_at + pd.Timedelta(seconds=tf_sec)
    window_end = sweep_close + pd.Timedelta(seconds=CONFIRMATION_WINDOW_CANDLES * tf_sec)
    if inv_close > window_end:
        late_by = (inv_close - window_end).total_seconds()
        return 'NEAR_MISS', f"inverted late by {late_by:.0f}s (window for {gap.tf} = {CONFIRMATION_WINDOW_CANDLES * tf_sec}s)"
    return 'PASS', "should qualify"


if __name__ == '__main__':
    main()
