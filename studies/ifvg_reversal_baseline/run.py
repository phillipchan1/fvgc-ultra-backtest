#!/usr/bin/env python3
"""Baseline IFVG Reversal study — SPEC.md §1-§14 v0.3.1 defaults, target config A (1R).

Cohort: last 2 weeks of NQ 30s data available in BOTH candles AND levels.

Until detectors are implemented, this script reports what's wired. Each
NotImplementedError below tells you exactly which SPEC section needs code next.
"""

import sys
from collections import Counter
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pandas as pd

from fvgc.data import load_candles
from ifvg_reversal import __version__ as model_version
from ifvg_reversal.constants import ACTIVE_SWEEP_LEVELS, TARGET_GAP_TIMEFRAMES as TF_LABELS
from ifvg_reversal.detectors.sweep import detect_sweeps
from ifvg_reversal.detectors.multi_tf_fvg import build_fvg_inventory, mark_inversions
from ifvg_reversal.detectors.chop import assess_all_days
from ifvg_reversal.model import generate_signals
from ifvg_reversal.engine import simulate_trades, summarize_results, print_summary

DATA_PATH = Path('data/consolidated/nq-front-month.ohlcv-30s.csv')
LEVELS_PATH = Path('data/levels/session_levels.csv')
STUDY_DIR = Path(__file__).resolve().parent
RESULTS_DIR = STUDY_DIR / 'results'

COHORT_DAYS = 60


def main():
    print(f"=== IFVG Reversal baseline — model v{model_version} ===\n")

    candles = load_candles(DATA_PATH)
    levels = pd.read_csv(LEVELS_PATH)

    # Cohort = last COHORT_DAYS of dates that exist in BOTH candles and levels.
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

    print(f"Cohort:        {cohort_start.date()} -> {cohort_end.date()}")
    print(f"  candles:     {len(cohort_candles):,}")
    print(f"  level rows:  {len(cohort_levels):,} ({cohort_levels['date'].nunique()} sessions)")
    print(f"  active set:  {ACTIVE_SWEEP_LEVELS}")
    if levels_max < candle_max:
        print(f"  NOTE: levels file ends {levels_max.date()}, candles end {candle_max.date()} -- using levels cap")

    # --- §4 sweep detection ---
    sweeps = detect_sweeps(cohort_candles, cohort_levels)
    print(f"\n§4 sweeps detected: {len(sweeps)}")
    if sweeps:
        by_level = Counter(s.level_name for s in sweeps)
        by_dir = Counter(s.reversal_direction for s in sweeps)
        print(f"  by level: {dict(by_level)}")
        print(f"  by reversal direction: {dict(by_dir)}")
        print("\n  First 5:")
        for s in sweeps[:5]:
            print(f"    {s.timestamp_ny}  {s.level_name:18}  @{s.level_price:>9.2f}  "
                  f"pen={s.penetration_pts:5.1f}pt  -> {s.reversal_direction}")

    # --- §6 multi-TF FVG inventory ---
    gaps = build_fvg_inventory(cohort_candles)
    mark_inversions(gaps, cohort_candles)
    print(f"\n§6 FVG inventory: {len(gaps)} gaps across {len(TF_LABELS)} TFs")
    by_tf = Counter(g.tf for g in gaps)
    by_dir = Counter(g.direction for g in gaps)
    inverted = [g for g in gaps if g.is_inverted]
    print(f"  by TF: {dict(by_tf)}")
    print(f"  by direction: {dict(by_dir)}")
    print(f"  inverted (before killzone end): {len(inverted)} / {len(gaps)}")
    if gaps:
        sizes = sorted(g.size_pts for g in gaps)
        n = len(sizes)
        print(f"  size pts — min {sizes[0]:.1f}, p50 {sizes[n//2]:.1f}, p90 {sizes[int(n*0.9)]:.1f}, max {sizes[-1]:.1f}")
        print("\n  First 5 inverted gaps:")
        for g in inverted[:5]:
            print(f"    {g.created_at}  tf={g.tf:5}  {g.direction:8}  "
                  f"size={g.size_pts:5.1f}  inv@{g.inversion_candle_ts}  "
                  f"body={g.inversion_body_fraction:.2f}")

    # --- §11 chop filter ---
    verdicts = assess_all_days(cohort_candles)
    chop_days = [v for v in verdicts.values() if v.is_chop_day]
    clean_days = [v for v in verdicts.values() if not v.is_chop_day]
    print(f"\n§11 chop assessment: {len(chop_days)} chop / {len(clean_days)} clean of {len(verdicts)} sessions")
    for date, v in sorted(verdicts.items()):
        tag = "CHOP" if v.is_chop_day else "OK  "
        r = f"{v.am_range_at_1030:.0f}pt" if v.am_range_at_1030 is not None else "n/a"
        print(f"  {date}  {tag}  am_range={r:>7}  reason: {v.reason}")

    # --- §1 pipeline ---
    signals, rejections = generate_signals(cohort_candles, cohort_levels, return_rejections=True)
    print(f"\n§1 pipeline: {len(signals)} signals, {len(rejections)} rejections")
    if rejections:
        by_reason = Counter(r.reason for r in rejections)
        print(f"  rejection reasons: {dict(by_reason)}")
    if signals:
        by_grade = Counter(s.grade for s in signals)
        by_dir = Counter(s.direction for s in signals)
        print(f"  by grade: {dict(by_grade)}  by direction: {dict(by_dir)}")
        print("\n  Signals:")
        for s in signals:
            g = s.target_gap
            print(f"    {s.timestamp_ny}  {s.grade:2}  {s.direction:5}  @{s.entry_price:>9.2f}  "
                  f"gap tf={g.tf:5} size={g.size_pts:5.1f} body={g.inversion_body_fraction:.2f}  "
                  f"sweep={s.triggering_sweep.level_name}")

    # --- §8-§10 trade simulation (target config A: fixed 1R) ---
    trades = simulate_trades(signals, cohort_candles)
    print(f"\n§8-§10 trades: {len(trades)} (target config = fixed 1R)")
    for t in trades:
        print(f"  {t.entry_timestamp_ny}  {t.direction:5} {t.signal.grade:2}  "
              f"entry={t.entry_price:>9.2f}  exit={t.exit_price:>9.2f} "
              f"({t.exit_reason:<10}) R={t.r_multiple:+.2f}  bars={t.bars_held}")
    stats = summarize_results(trades)
    print_summary(stats)


if __name__ == '__main__':
    main()
