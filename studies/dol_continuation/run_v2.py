#!/usr/bin/env python3
"""DOL Continuation v2 — adds quality + regime filters that capture the user's
visual checks:
  - Direction bias must match (prior_day or prior_day_close_position)
  - DOL distance bounded [1R, 3R]
  - Inversion body fraction >= 0.6 (strong close-through)
  - OR-15 >= 67 (skip dead days; uses 5min OR proxy here since OR-15 needs
    trading_days join — using same-day 15min range from candles)
  - killzone 9:45-11:00
"""

import sys
import time
from collections import Counter
from datetime import time as dtime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import numpy as np
import pandas as pd

from fvgc.data import load_candles

# Reuse v1 building blocks
sys.path.insert(0, str(Path(__file__).resolve().parent))
from run import (
    build_full_fvg_inventory, mark_inversion_times,
    find_nearest_dol, path_is_clear,
    simulate_dol_trade, compute_or, get_pd_levels,
    DATA_PATH, LEVELS_PATH, COHORT_START, COHORT_END,
    KILLZONE_START, KILLZONE_END, MIN_FVG_SIZE, HARD_STOP_BUFFER,
)

RESULTS_DIR = Path(__file__).resolve().parent / 'results'
TRADING_DAYS_PATH = Path('data/trading_days/trading_days.csv')

# v2 filters
MIN_DOL_DISTANCE_R = 1.0
MAX_DOL_DISTANCE_R = 3.0
MIN_BODY_FRACTION = 0.6
MIN_OR_15 = 67.0


def main():
    print("=== DOL Continuation v2 (with quality filters) ===\n")
    t0 = time.time()

    candles = load_candles(DATA_PATH)
    levels = pd.read_csv(LEVELS_PATH)
    td = pd.read_csv(TRADING_DAYS_PATH)
    td['date'] = pd.to_datetime(td['date']).dt.date.astype(str)
    td_by_date = td.set_index('date')[['prior_day_type', 'prior_day_close_position',
                                        'or_15min_range', 'prior_day_range_atr_ratio']].to_dict('index')

    candles = candles[
        (candles['timestamp_ny'].dt.tz_localize(None) >= COHORT_START) &
        (candles['timestamp_ny'].dt.tz_localize(None) <= COHORT_END + pd.Timedelta(days=1))
    ].copy()
    candles['date_ny'] = candles['timestamp_ny'].dt.date.astype(str)
    print(f"Cohort: {COHORT_START.date()} -> {COHORT_END.date()}, "
          f"{candles['date_ny'].nunique()} sessions, loaded in {time.time()-t0:.1f}s\n")

    signals = []
    rejections = Counter()

    for date_str, day_full in candles.groupby('date_ny', sort=True):
        day_full = day_full.reset_index(drop=True)
        ctx = td_by_date.get(date_str, {})

        # Day-level regime gates
        or15 = ctx.get('or_15min_range') or 0
        if or15 < MIN_OR_15:
            rejections['day_or15_too_low'] += 1
            continue
        atr_ratio = ctx.get('prior_day_range_atr_ratio') or 0
        if atr_ratio < 0.5:
            rejections['day_low_vol'] += 1
            continue

        # Direction biases for the day
        pd_type = ctx.get('prior_day_type') or ''
        pd_close_pos = ctx.get('prior_day_close_position') or 0.5
        short_ok = pd_type in ('reversal_down', 'trend_down') or pd_close_pos <= 0.40
        long_ok = pd_type in ('reversal_up', 'trend_up') or pd_close_pos >= 0.60

        pdh, pdl = get_pd_levels(levels, date_str)

        gaps_full = build_full_fvg_inventory(day_full, min_size=MIN_FVG_SIZE)
        if not gaps_full:
            continue
        mark_inversion_times(gaps_full, day_full)

        for g in gaps_full:
            if not g.is_inverted:
                continue
            inv_ts = g.inverted_at
            if inv_ts.time() < KILLZONE_START or inv_ts.time() > KILLZONE_END:
                continue

            direction = 'short' if g.direction == 'bullish' else 'long'

            # Direction bias gate
            if direction == 'short' and not short_ok:
                rejections['wrong_dir_bias_short'] += 1
                continue
            if direction == 'long' and not long_ok:
                rejections['wrong_dir_bias_long'] += 1
                continue

            # Inversion body fraction
            if (g.inversion_body_fraction or 0) < MIN_BODY_FRACTION:
                rejections['weak_body'] += 1
                continue

            entry_price = g.inversion_close_price
            if direction == 'short':
                stop_price = g.top + HARD_STOP_BUFFER
            else:
                stop_price = g.bottom - HARD_STOP_BUFFER
            stop_d = abs(stop_price - entry_price)
            if stop_d <= 0:
                rejections['bad_stop'] += 1
                continue

            dol = find_nearest_dol(direction, entry_price, inv_ts, day_full, pdh, pdl)
            if dol is None:
                rejections['no_dol'] += 1
                continue
            dol_name, dol_price = dol
            target_d = abs(dol_price - entry_price)
            r_distance = target_d / stop_d
            if r_distance < MIN_DOL_DISTANCE_R:
                rejections['dol_too_close'] += 1
                continue
            if r_distance > MAX_DOL_DISTANCE_R:
                rejections['dol_too_far'] += 1
                continue

            clear, obstructions = path_is_clear(
                direction, entry_price, dol_price, inv_ts, g, gaps_full,
            )
            if not clear:
                rejections['path_obstructed'] += 1
                continue

            outcome = simulate_dol_trade(
                direction, entry_price, inv_ts, stop_price, dol_price, day_full, g,
            )

            signals.append({
                'date': date_str,
                'entry_ts': inv_ts,
                'direction': direction,
                'entry_price': entry_price,
                'stop_price': stop_price,
                'target_price': dol_price,
                'target_source': dol_name,
                'gap_tf': g.tf,
                'gap_size_pts': g.size_pts,
                'inversion_body_fraction': g.inversion_body_fraction,
                'stop_distance_pts': stop_d,
                'target_distance_pts': target_d,
                'r_planned': r_distance,
                'prior_day_type': pd_type,
                'prior_day_close_position': pd_close_pos,
                'or_15min_range': or15,
                **outcome,
                'pnl_pts': outcome['r_multiple'] * stop_d,
            })

    print(f"Signals emitted: {len(signals)}")
    print(f"Rejections: {dict(rejections)}\n")

    if not signals:
        print("No trades emitted.")
        return

    df = pd.DataFrame(signals)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(RESULTS_DIR / 'dol_trades_v2.csv', index=False)
    print(f"Wrote {RESULTS_DIR / 'dol_trades_v2.csv'}\n")

    w = (df['r_multiple'] > 0).sum(); l = (df['r_multiple'] < 0).sum()
    wr = w / max(w + l, 1) * 100
    gw = df.loc[df['r_multiple'] > 0, 'pnl_pts'].sum()
    gl = abs(df.loc[df['r_multiple'] < 0, 'pnl_pts'].sum()) or 1e-9

    print("=== Overall ===")
    print(f"  N: {len(df)}  WR: {wr:.1f}%  PF: {gw/gl:.2f}")
    print(f"  Avg R: {df['r_multiple'].mean():+.3f}  Total R: {df['r_multiple'].sum():+.1f}")
    print(f"  Exit reason: {df['exit_reason'].value_counts().to_dict()}")
    print(f"  Direction: {df['direction'].value_counts().to_dict()}")

    print(f"\n=== By gap TF ===")
    for tf, sub in df.groupby('gap_tf'):
        w_tf = (sub['r_multiple']>0).sum(); l_tf = (sub['r_multiple']<0).sum()
        gw_tf = sub.loc[sub['r_multiple']>0, 'pnl_pts'].sum()
        gl_tf = abs(sub.loc[sub['r_multiple']<0, 'pnl_pts'].sum()) or 1e-9
        wr_tf = w_tf/max(w_tf+l_tf,1)*100
        print(f"  {tf:5}  N={len(sub):3}  WR={wr_tf:5.1f}%  PF={gw_tf/gl_tf:.2f}  totR={sub['r_multiple'].sum():+.1f}")

    print(f"\n=== By DOL target ===")
    for tgt, sub in df.groupby('target_source'):
        w_t = (sub['r_multiple']>0).sum(); l_t = (sub['r_multiple']<0).sum()
        gw_t = sub.loc[sub['r_multiple']>0, 'pnl_pts'].sum()
        gl_t = abs(sub.loc[sub['r_multiple']<0, 'pnl_pts'].sum()) or 1e-9
        wr_t = w_t/max(w_t+l_t,1)*100
        print(f"  {tgt:18}  N={len(sub):3}  WR={wr_t:5.1f}%  PF={gw_t/gl_t:.2f}  totR={sub['r_multiple'].sum():+.1f}")

    # Sample recent winners + losers for human review
    print(f"\n=== Recent 10 trades ===")
    cols = ['date','entry_ts','direction','gap_tf','gap_size_pts','inversion_body_fraction',
            'target_source','r_planned','exit_reason','r_multiple']
    print(df[cols].tail(10).to_string(index=False))

    # Specifically look for 2026-05-13
    print(f"\n=== Trades on 2026-05-13 (your example day) ===")
    sub = df[df['date'] == '2026-05-13']
    if len(sub):
        print(sub[cols].to_string(index=False))
    else:
        print("  No trades emitted on 2026-05-13. Could be filtered out — investigating below.")


if __name__ == '__main__':
    main()
