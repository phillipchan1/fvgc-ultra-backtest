#!/usr/bin/env python3
"""Step 1 — population generator.

Runs the model with deliberately loose defaults on the full cohort. Each
emitted row carries per-factor metadata for Step 2 bucketing. The model in
this script is intentionally over-inclusive — not a trading strategy.

See ifvg_reversal/METHODOLOGY.md for the loose-default rationale.
"""

import argparse
import sys
import time
from datetime import time as dtime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pandas as pd

from fvgc.data import load_candles
from ifvg_reversal.constants import (
    ACTIVE_SWEEP_LEVELS,
    HARD_STOP_BUFFER,
    SWEEP_CANDLE_SECONDS,
    SWEEP_LEVEL_TIER,
    TF_SECONDS,
    TRADING_WINDOW_END,
    TRADING_WINDOW_START,
)
from ifvg_reversal.detectors.chop import assess_all_days
from ifvg_reversal.detectors.multi_tf_fvg import (
    MultiTFGap,
    build_fvg_inventory,
    mark_inversions,
)
from ifvg_reversal.detectors.sweep import Sweep, detect_sweeps

DATA_PATH = Path('data/consolidated/nq-front-month.ohlcv-30s.csv')
LEVELS_PATH = Path('data/levels/session_levels.csv')
RESULTS_DIR = Path(__file__).resolve().parent / 'results'

# Step 1 loose defaults (deltas from v0.3.2 — see METHODOLOGY.md).
LOOSE_MIN_FVG_SIZE = 6.0
LOOSE_CONFIRMATION_WINDOW_SECONDS = 600
LOOSE_BODY_MIN = 0.30


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--days', type=int, default=180,
                    help="Use last N days of available data. Default 180. Use 0 for full.")
    args = ap.parse_args()

    print("=== IFVG Reversal — Step 1 population generator ===\n")

    t0 = time.time()
    candles = load_candles(DATA_PATH)
    levels = pd.read_csv(LEVELS_PATH)
    print(f"  loaded in {time.time()-t0:.1f}s")

    # Cohort: intersect candles ∩ levels, optionally tail to last N days.
    candle_max = pd.Timestamp(candles['timestamp_ny'].max().date())
    levels_max = pd.Timestamp(levels['date'].max())
    candle_min = pd.Timestamp(candles['timestamp_ny'].min().date())
    levels_min = pd.Timestamp(levels['date'].min())
    cohort_end = min(candle_max, levels_max)
    cohort_start_full = max(candle_min, levels_min)
    if args.days > 0:
        cohort_start = max(cohort_start_full, cohort_end - timedelta(days=args.days))
    else:
        cohort_start = cohort_start_full
    print(f"Cohort: {cohort_start.date()} -> {cohort_end.date()}  "
          f"({(cohort_end - cohort_start).days} days)")

    candles = candles[
        (candles['timestamp_ny'].dt.tz_localize(None) >= cohort_start) &
        (candles['timestamp_ny'].dt.tz_localize(None) <= cohort_end + timedelta(days=1))
    ].copy()
    levels = levels[
        (pd.to_datetime(levels['date']) >= cohort_start) &
        (pd.to_datetime(levels['date']) <= cohort_end)
    ].copy()
    print(f"  {len(candles):,} candles, {levels['date'].nunique()} sessions in levels")

    # --- detectors with loose params ---
    t = time.time()
    print("\nBuilding FVG inventory (loose size=6.0)...")
    gaps = build_fvg_inventory(candles, min_size=LOOSE_MIN_FVG_SIZE)
    print(f"  built {len(gaps):,} candidate FVGs in {time.time()-t:.1f}s")

    t = time.time()
    print("Marking inversions...")
    mark_inversions(gaps, candles)
    print(f"  marked in {time.time()-t:.1f}s")

    t = time.time()
    print("Detecting sweeps...")
    sweeps = detect_sweeps(candles, levels)
    print(f"  {len(sweeps):,} sweeps in killzone  ({time.time()-t:.1f}s)")

    t = time.time()
    print("Assessing chop per day (tagged, not filtered)...")
    chop = assess_all_days(candles)
    print(f"  assessed in {time.time()-t:.1f}s")

    pre_rth_all_swept = _pre_rth_all_swept_map(levels)

    # --- index candles per day for fast lookup (O(1) per sweep, not O(N)) ---
    base = candles[['timestamp_ny', 'open', 'high', 'low', 'close']].copy()
    base['date_ny'] = base['timestamp_ny'].dt.date.astype(str)
    base_by_date = {d: g for d, g in base.groupby('date_ny', sort=False)}

    # --- iterate sweeps, emit one row per (sweep, first-loose-qualified-gap) ---
    t = time.time()
    print("\nEmitting population rows...")
    rows = []
    for sweep in sweeps:
        target = _pick_loose_target(sweep, gaps)
        if target is None:
            continue

        entry_ts = target.inverted_at + pd.Timedelta(seconds=TF_SECONDS[target.tf])
        if not _in_killzone(entry_ts):
            continue

        date_str = str(sweep.timestamp_ny.date())
        day_candles = base_by_date.get(date_str)
        if day_candles is None or day_candles.empty:
            continue

        trade = _simulate_fixed_1r(sweep, target, day_candles)
        meta = _compute_factors(
            sweep, target, day_candles, chop.get(date_str),
            pre_rth_all_swept.get(date_str, False),
        )

        rows.append({**trade, **meta})

    df = pd.DataFrame(rows)
    print(f"\nEmitted {len(df)} population rows in {time.time()-t:.1f}s.")
    if df.empty:
        print("No rows emitted — check loose defaults.")
        return

    out_path = RESULTS_DIR / 'population.csv'
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)
    print(f"Wrote {out_path}\n")

    _print_summary(df)


# =====================================================================
# Loose target-gap picker (mirror of model._pick_target_gap, with overrides)
# =====================================================================

def _pick_loose_target(sweep: Sweep, gaps):
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


# =====================================================================
# Trade simulator (mirror of engine fixed-1R, simplified for loose study)
# =====================================================================

_EOD_TIME = dtime(16, 0)


def _simulate_fixed_1r(sweep: Sweep, gap: MultiTFGap, day_candles: pd.DataFrame):
    direction = 'short' if sweep.reversal_direction == 'short' else 'long'
    entry_ts = gap.inverted_at + pd.Timedelta(seconds=TF_SECONDS[gap.tf])
    entry = gap.inversion_close_price

    # v0.3.3: gap-based hard stop (see SPEC §9.2)
    if direction == 'short':
        soft_level = gap.top
        hard_stop = gap.top + HARD_STOP_BUFFER
        stop_distance = hard_stop - entry
        target = entry - stop_distance
    else:
        soft_level = gap.bottom
        hard_stop = gap.bottom - HARD_STOP_BUFFER
        stop_distance = entry - hard_stop
        target = entry + stop_distance

    forward = day_candles[
        (day_candles['timestamp_ny'] > entry_ts) &
        (day_candles['timestamp_ny'].dt.time <= _EOD_TIME)
    ]
    if forward.empty or stop_distance <= 0:
        return _row(sweep, gap, direction, entry_ts, entry, entry_ts, entry,
                    'no_data', 0.0, 0.0, 0, stop_distance)

    for i, c in enumerate(forward.itertuples(index=False), start=1):
        ts = c.timestamp_ny
        if direction == 'short':
            hit_stop = c.high >= hard_stop
            hit_tgt = c.low <= target
        else:
            hit_stop = c.low <= hard_stop
            hit_tgt = c.high >= target

        if hit_stop:
            exit_p = hard_stop
            pnl = entry - exit_p if direction == 'short' else exit_p - entry
            return _row(sweep, gap, direction, entry_ts, entry, ts, exit_p,
                        'hard_stop', pnl / stop_distance, pnl, i, stop_distance)
        if hit_tgt:
            exit_p = target
            pnl = entry - exit_p if direction == 'short' else exit_p - entry
            return _row(sweep, gap, direction, entry_ts, entry, ts, exit_p,
                        'target', pnl / stop_distance, pnl, i, stop_distance)
        # Soft stop (close-based)
        if direction == 'short' and c.close > soft_level:
            exit_p = c.close
            pnl = entry - exit_p
            return _row(sweep, gap, direction, entry_ts, entry, ts, exit_p,
                        'soft_stop', pnl / stop_distance, pnl, i, stop_distance)
        if direction == 'long' and c.close < soft_level:
            exit_p = c.close
            pnl = exit_p - entry
            return _row(sweep, gap, direction, entry_ts, entry, ts, exit_p,
                        'soft_stop', pnl / stop_distance, pnl, i, stop_distance)

    last = forward.iloc[-1]
    exit_p = float(last['close'])
    pnl = entry - exit_p if direction == 'short' else exit_p - entry
    return _row(sweep, gap, direction, entry_ts, entry, last['timestamp_ny'],
                exit_p, 'eod', pnl / stop_distance, pnl, len(forward), stop_distance)


def _row(sweep, gap, direction, entry_ts, entry, exit_ts, exit_p,
         reason, r, pnl, bars, stop_distance):
    return {
        'entry_ts': entry_ts,
        'direction': direction,
        'entry_price': float(entry),
        'exit_ts': exit_ts,
        'exit_price': float(exit_p),
        'exit_reason': reason,
        'r_multiple': float(r),
        'pnl_pts': float(pnl),
        'bars_held': int(bars),
        'stop_distance_pts': float(stop_distance),
        'gap_top': float(gap.top),         # v0.3.3 — for future stop-rule re-sims
        'gap_bottom': float(gap.bottom),
    }


# =====================================================================
# Factor metadata (the point of this whole study)
# =====================================================================

def _compute_factors(sweep, gap, day_candles, chop_verdict, pre_rth_all_swept):
    # Dealing range at sweep time
    rth_at = day_candles[
        (day_candles['timestamp_ny'].dt.time >= TRADING_WINDOW_START) &
        (day_candles['timestamp_ny'] <= sweep.timestamp_ny)
    ]
    if rth_at.empty:
        dr_low = dr_high = sweep.level_price
    else:
        dr_low = float(rth_at['low'].min())
        dr_high = float(rth_at['high'].max())
    mid = (dr_low + dr_high) / 2.0
    span = max(dr_high - dr_low, 1e-9)
    pd_position = (sweep.level_price - dr_low) / span  # 0=at low, 1=at high
    distance_to_50pct = abs(sweep.level_price - mid)   # v0.3.4 — 50% gravity factor

    if sweep.reversal_direction == 'short':
        pd_correct_side = pd_position >= 0.5
    else:
        pd_correct_side = pd_position <= 0.5

    equilibrium = pre_rth_all_swept and abs(sweep.level_price - mid) <= 5.0

    # Reaction-quality flags (raw measurements over next 2 30s candles)
    after = day_candles[day_candles['timestamp_ny'] > sweep.timestamp_ny].head(2)
    nuked = stalled = insufficient_move = False
    if not after.empty:
        lvl = sweep.level_price
        if sweep.reversal_direction == 'short':
            nuked = bool((after['close'] >= lvl + 5.0).any())
            stalled = bool((after['close'] >= lvl - 2.0).any())
            insufficient_move = not bool((after['close'] <= lvl - 5.0).any())
        else:
            nuked = bool((after['close'] <= lvl - 5.0).any())
            stalled = bool((after['close'] <= lvl + 2.0).any())
            insufficient_move = not bool((after['close'] >= lvl + 5.0).any())

    # Inversion latency in seconds (sweep close → inversion bar close)
    sweep_close = sweep.timestamp_ny + pd.Timedelta(seconds=SWEEP_CANDLE_SECONDS)
    tf_sec = TF_SECONDS[gap.tf]
    inv_close_time = gap.inverted_at + pd.Timedelta(seconds=tf_sec)
    inversion_latency_s = (inv_close_time - sweep_close).total_seconds()

    # Killzone position
    entry_ts = inv_close_time
    minute_offset = (entry_ts.hour - 9) * 60 + entry_ts.minute - 30  # minutes after 09:30

    return {
        # sweep factors
        'sweep_level': sweep.level_name,
        'sweep_tier': SWEEP_LEVEL_TIER[sweep.level_name],
        'sweep_penetration_pts': float(sweep.penetration_pts),
        'sweep_ts': sweep.timestamp_ny,
        # gap factors
        'gap_size_pts': float(gap.size_pts),
        'gap_tf': gap.tf,
        'gap_direction': gap.direction,
        'gap_created_at': gap.created_at,
        'inversion_body_fraction': float(gap.inversion_body_fraction or 0.0),
        'inversion_latency_s': float(inversion_latency_s),
        # range / P/D
        'dealing_range_low': dr_low,
        'dealing_range_high': dr_high,
        'pd_position': float(pd_position),
        'pd_correct_side': bool(pd_correct_side),
        'distance_to_50pct_at_sweep': float(distance_to_50pct),
        # day quality
        'is_chop_day': bool(chop_verdict.is_chop_day) if chop_verdict else False,
        'am_range_at_1030': float(chop_verdict.am_range_at_1030) if chop_verdict and chop_verdict.am_range_at_1030 else 0.0,
        'or_contained': bool(chop_verdict.or_contained_at_deadline) if chop_verdict else False,
        'equilibrium': bool(equilibrium),
        # reaction
        'reacted_nuked': nuked,
        'reacted_stalled': stalled,
        'reacted_insufficient_move': insufficient_move,
        'reaction_clean': not (nuked or stalled or insufficient_move),
        # time
        'killzone_minute': int(minute_offset),
        'day_of_week': sweep.timestamp_ny.day_name(),
    }


# =====================================================================
# Helpers
# =====================================================================

def _in_killzone(ts: pd.Timestamp) -> bool:
    t = ts.time()
    return TRADING_WINDOW_START <= t <= TRADING_WINDOW_END


def _pre_rth_all_swept_map(levels: pd.DataFrame):
    out = {}
    active = levels[levels['level_name'].isin(ACTIVE_SWEEP_LEVELS)]
    for date_str, day in active.groupby('date'):
        valid = day[day['price'].notna()]
        if valid.empty:
            out[date_str] = False
            continue
        out[date_str] = bool((valid['swept_pre_rth'] == True).all())
    return out


def _print_summary(df: pd.DataFrame) -> None:
    wins = (df['r_multiple'] > 0).sum()
    losses = (df['r_multiple'] < 0).sum()
    flat = (df['r_multiple'] == 0).sum()
    wr = (wins / (wins + losses) * 100) if (wins + losses) else 0
    gross_win = df.loc[df['r_multiple'] > 0, 'pnl_pts'].sum()
    gross_loss = abs(df.loc[df['r_multiple'] < 0, 'pnl_pts'].sum()) or 1e-9
    pf = gross_win / gross_loss

    print(f"Population: N={len(df)}")
    print(f"  Wins/Losses/Flat: {wins} / {losses} / {flat}")
    print(f"  WR: {wr:.1f}%   Avg R: {df['r_multiple'].mean():+.2f}   PF: {pf:.2f}")
    print(f"  Total P&L: {df['pnl_pts'].sum():+.1f} pts")
    print(f"  By exit reason: {df['exit_reason'].value_counts().to_dict()}")
    print(f"  By direction:   {df['direction'].value_counts().to_dict()}")
    print(f"  By gap TF:      {df['gap_tf'].value_counts().to_dict()}")
    print(f"  By sweep tier:  {df['sweep_tier'].value_counts().to_dict()}")
    print(f"  P/D correct side: {df['pd_correct_side'].sum()} / {len(df)}  "
          f"({df['pd_correct_side'].mean()*100:.0f}%)")
    print(f"  Chop days:        {df['is_chop_day'].sum()} / {len(df)}")
    print(f"  Reaction clean:   {df['reaction_clean'].sum()} / {len(df)}")


if __name__ == '__main__':
    main()
