#!/usr/bin/env python3
"""v0.4 candidate emitter — multi-gap inversion aware.

Differences from population/run.py:
  1. PER-TF MIN SIZE filter (drops invisible micro-gaps that don't appear on chart).
  2. ONE candidate per (inversion candle, direction). When multiple same-dir FVGs
     are inverted by the same candle close, they collapse into ONE trade with
     multi_gap_count = N as a confluence factor.
  3. Stop = outermost top/bottom of all inverted FVGs (Option B from user
     manual review on 2026-05-25): multi-gap inversion validates the merge
     empirically, so the 40pt cap does NOT apply at the inversion event.
  4. Sweep-level dedup: a single setup matched against multiple co-located
     levels (within DEDUPE_TOLERANCE pts) becomes one candidate with
     stacked_levels_count = N as a confluence factor.

Output: studies/ifvg_reversal_population/results/v0_4/candidates_3wk.csv
Use for manual eyeballing during refinement, not as the validated population.
"""

import sys
from collections import defaultdict
from datetime import time as dtime
from pathlib import Path
from typing import Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import numpy as np
import pandas as pd

from fvgc.data import load_candles
from ifvg_reversal.constants import (
    HARD_STOP_BUFFER, MOMENTUM_BODY_FRACTION,
    SWEEP_LEVEL_TIER, TRADING_WINDOW_END, TRADING_WINDOW_START,
)
from ifvg_reversal.detectors.multi_tf_fvg import (
    MultiTFGap, build_fvg_inventory, mark_inversions,
)
from ifvg_reversal.detectors.sweep import Sweep, detect_sweeps

DATA_PATH = Path('data/consolidated/nq-front-month.ohlcv-30s.csv')
LEVELS_PATH = Path('data/levels/session_levels.csv')
OUT_DIR = Path(__file__).resolve().parent / 'results' / 'v0_4'
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Per-TF gap floor (NQ pts) — "visible on chart" threshold
PER_TF_MIN_SIZE = {'30s': 6.0, '1min': 10.0, '2min': 15.0, '3min': 18.0}

# When a setup matches multiple sweep levels within this distance, dedupe
DEDUPE_TOLERANCE_PTS = 5.0

# Loose floor for population BUILD (we filter per-TF inside)
BUILD_MIN_SIZE = 6.0

# How far back to allow a recent sweep to qualify a setup
SWEEP_VALIDITY_MIN = 40


def emit_candidates_for_day(date_str: str, candles_day: pd.DataFrame, levels: pd.DataFrame):
    """Return list of candidate dicts for one NY date."""
    gaps_raw = build_fvg_inventory(candles_day, min_size=BUILD_MIN_SIZE)
    mark_inversions(gaps_raw, candles_day)

    # Per-TF min size filter
    gaps = [g for g in gaps_raw if g.size_pts >= PER_TF_MIN_SIZE.get(g.tf, 9999)]

    sweeps = detect_sweeps(candles_day, levels)

    # Group by (inversion candle ts, reversal direction)
    by_event: Dict[Tuple[pd.Timestamp, str], List[MultiTFGap]] = defaultdict(list)
    for g in gaps:
        if not g.is_inverted:
            continue
        if (g.inversion_body_fraction or 0) < MOMENTUM_BODY_FRACTION:
            continue
        rev = 'short' if g.direction == 'bullish' else 'long'
        by_event[(g.inverted_at, rev)].append(g)

    candidates = []
    for (inv_ts, direction), inv_gaps in by_event.items():
        ny_t = inv_ts.tz_convert('America/New_York') if inv_ts.tz else inv_ts
        ny_hhmm = ny_t.strftime('%H:%M')
        if ny_hhmm < TRADING_WINDOW_START.strftime('%H:%M'):
            continue
        if ny_hhmm > TRADING_WINDOW_END.strftime('%H:%M'):
            continue

        # Outermost stop bound (Option B)
        if direction == 'short':
            # Inverting bullish gaps; stop above the highest top
            stop_anchor = max(g.top for g in inv_gaps)
            stop_price = stop_anchor + HARD_STOP_BUFFER
        else:
            stop_anchor = min(g.bottom for g in inv_gaps)
            stop_price = stop_anchor - HARD_STOP_BUFFER

        entry_price = inv_gaps[0].inversion_close_price
        stop_distance = abs(stop_price - entry_price)

        # Find sweeps before this inversion that match the direction and are valid
        valid_sweeps = [
            s for s in sweeps
            if s.reversal_direction == direction
            and s.timestamp_ny <= inv_ts
            and s.timestamp_ny >= inv_ts - pd.Timedelta(minutes=SWEEP_VALIDITY_MIN)
        ]
        if not valid_sweeps:
            sweep_level = '(no sweep)'
            sweep_price = None
            sweep_tier = 0
            stacked_count = 0
            stacked_levels = ''
            sweep_ts = None
        else:
            # Pick most recent sweep
            valid_sweeps.sort(key=lambda s: s.timestamp_ny, reverse=True)
            primary = valid_sweeps[0]
            sweep_level = primary.level_name
            sweep_price = primary.level_price
            sweep_tier = primary.tier
            sweep_ts = primary.timestamp_ny
            # Stacked level dedup — count how many other recent sweeps are within tolerance
            others = [s for s in valid_sweeps
                      if s is not primary and abs(s.level_price - primary.level_price) <= DEDUPE_TOLERANCE_PTS]
            stacked_count = 1 + len(others)
            stacked_levels = '+'.join([primary.level_name] + [s.level_name for s in others])

        # Multi-TF count
        tfs = sorted({g.tf for g in inv_gaps})
        # Dominant TF = TF with the largest single gap among inverted
        dom = max(inv_gaps, key=lambda g: g.size_pts)

        candidates.append({
            'date': date_str,
            'entry_ts_ny': ny_t.strftime('%Y-%m-%d %H:%M:%S'),
            'direction': direction,
            'entry_price': entry_price,
            'stop_price': stop_price,
            'stop_distance_pts': stop_distance,
            'multi_gap_count': len(inv_gaps),
            'multi_tf_count': len(tfs),
            'tfs_inverted': '+'.join(tfs),
            'dominant_tf': dom.tf,
            'dominant_gap_size_pts': dom.size_pts,
            'outermost_gap_top': max(g.top for g in inv_gaps),
            'outermost_gap_bottom': min(g.bottom for g in inv_gaps),
            'sweep_level': sweep_level,
            'sweep_price': sweep_price,
            'sweep_tier': sweep_tier,
            'sweep_ts_ny': sweep_ts.tz_convert('America/New_York').strftime('%H:%M:%S') if sweep_ts is not None else '',
            'stacked_levels_count': stacked_count,
            'stacked_levels': stacked_levels,
            'inversion_body_fraction': inv_gaps[0].inversion_body_fraction,
        })

    return sorted(candidates, key=lambda c: c['entry_ts_ny'])


def main():
    print("=== v0.4 candidate emitter — multi-gap inversion aware ===")
    print(f"Per-TF min sizes: {PER_TF_MIN_SIZE}")
    print(f"Dedupe tolerance (sweep levels): {DEDUPE_TOLERANCE_PTS}pt")
    print()

    candles = load_candles(DATA_PATH)
    candles['date_ny'] = candles['timestamp_ny'].dt.date.astype(str)
    levels = pd.read_csv(LEVELS_PATH, low_memory=False)

    cohort = sorted(candles['date_ny'].unique())
    cohort = [d for d in cohort if d >= '2026-05-04']
    print(f"Cohort: {len(cohort)} sessions ({cohort[0]} → {cohort[-1]})")

    all_candidates = []
    for d in cohort:
        day = candles[candles['date_ny'] == d].reset_index(drop=True)
        if day.empty:
            continue
        cands = emit_candidates_for_day(d, day, levels)
        all_candidates.extend(cands)

    df = pd.DataFrame(all_candidates)
    if df.empty:
        print("No candidates emitted.")
        return

    out_csv = OUT_DIR / 'candidates_3wk.csv'
    df.to_csv(out_csv, index=False)
    print(f"\nEmitted {len(df)} candidates → {out_csv}")
    print(f"  Multi-gap events (count >= 2): {(df['multi_gap_count'] >= 2).sum()}")
    print(f"  Multi-TF events  (count >= 2): {(df['multi_tf_count']  >= 2).sum()}")
    print(f"  Stacked-level events (count >= 2): {(df['stacked_levels_count'] >= 2).sum()}")
    print(f"  Direction split: {df['direction'].value_counts().to_dict()}")

    # Show all candidates
    print(f"\n=== All candidates ===")
    cols = ['date', 'entry_ts_ny', 'direction', 'multi_gap_count', 'multi_tf_count',
            'tfs_inverted', 'dominant_tf', 'dominant_gap_size_pts',
            'stop_distance_pts', 'sweep_level', 'sweep_tier', 'stacked_levels_count']
    with pd.option_context('display.width', 240, 'display.max_columns', None):
        print(df[cols].to_string(index=False))


if __name__ == '__main__':
    main()
