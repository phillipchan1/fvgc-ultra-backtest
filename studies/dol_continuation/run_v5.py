#!/usr/bin/env python3
"""DOL Continuation v5 — per-TF min size + HTF 15m structural bias.

Changes from v4:
  1. PER-TF MIN SIZE: gaps too small to see on chart no longer fire.
     30s:6 / 1m:10 / 2m:15 / 3m:18 / 5m:22 pts
  2. HTF 15M BIAS GATE: trade direction must agree with last 15m swing.
     Computed causally — uses only fully-closed 15m bars at bar_close_ts.
     "Up bias" = last closed 15m close > close N bars prior.
     N=2 bars (30 min lookback). Neutral zone (|delta| < threshold) blocks both.

Carries forward from v4:
  - Killzone 9:30–11:00 NY (bar CLOSE time)
  - DOL: OR/overnight/asia/london/PDH/PDL/running_50pct
  - Strict path-clear: FVG entirely-in-path AND not wicked into
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run import (
    build_full_fvg_inventory, mark_inversion_times,
    get_pd_levels, compute_or, running_50pct_at,
    DATA_PATH, LEVELS_PATH, COHORT_START, COHORT_END,
    HARD_STOP_BUFFER, simulate_dol_trade,
)
from run_v4 import (
    get_overnight_levels, get_asia_london_levels, session_lo_hi_so_far,
    find_nearest_dol_v4, path_clear_v4, bar_close_ts,
    TF_SECONDS,
)

RESULTS_DIR = Path(__file__).resolve().parent / 'results'
TRADING_DAYS_PATH = Path('data/trading_days/trading_days.csv')

KILLZONE_START = dtime(9, 30)
KILLZONE_END = dtime(11, 0)
OR_READY = dtime(9, 45)

MIN_DOL_DISTANCE_R = 1.0
MAX_DOL_DISTANCE_R = 5.0
MIN_BODY_FRACTION = 0.55
MIN_OR_15 = 67.0

# v5: per-TF minimum FVG size (pts) — must be visible on chart
PER_TF_MIN_SIZE = {
    '30s':  6.0,
    '1min': 10.0,
    '2min': 15.0,
    '3min': 18.0,
    '5min': 22.0,
}
# Loose floor used when building inventory; per-TF filter applied at trade time
BUILD_MIN_SIZE = 6.0

# v5: HTF bias params
BIAS_TF = '15min'
BIAS_LOOKBACK_BARS = 2   # 2 fully-closed 15m bars prior = 30 min lookback
BIAS_NEUTRAL_PTS = 8.0   # |last_close - lookback_close| < this = neutral, block both


def htf_bias_at(day_candles: pd.DataFrame, bar_close_ts: pd.Timestamp) -> str:
    """Return 'long', 'short', or 'neutral' bias from 15m structure.

    Uses ONLY 15m bars that have FULLY CLOSED before bar_close_ts.
    Compares last closed 15m close to close N bars prior.
    """
    df = day_candles.set_index('timestamp_ny').sort_index()
    m15 = df[['open', 'high', 'low', 'close']].resample(
        '15min', label='left', closed='left'
    ).agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()

    # Only fully-closed bars at bar_close_ts — bar starting at T closes at T+15min
    fully_closed = m15[m15.index + pd.Timedelta(minutes=15) <= bar_close_ts]
    if len(fully_closed) < BIAS_LOOKBACK_BARS + 1:
        return 'neutral'  # not enough history

    last_close = fully_closed['close'].iloc[-1]
    ref_close = fully_closed['close'].iloc[-1 - BIAS_LOOKBACK_BARS]
    delta = last_close - ref_close
    if delta > BIAS_NEUTRAL_PTS:
        return 'long'
    if delta < -BIAS_NEUTRAL_PTS:
        return 'short'
    return 'neutral'


def main():
    print("=== DOL Continuation v5 (per-TF min + HTF bias) ===\n")
    t0 = time.time()

    candles = load_candles(DATA_PATH)
    levels = pd.read_csv(LEVELS_PATH)
    td = pd.read_csv(TRADING_DAYS_PATH)
    td['date'] = pd.to_datetime(td['date']).dt.date.astype(str)
    td_by_date = td.set_index('date')[['or_15min_range']].to_dict('index')

    candles = candles[
        (candles['timestamp_ny'].dt.tz_localize(None) >= COHORT_START) &
        (candles['timestamp_ny'].dt.tz_localize(None) <= COHORT_END + pd.Timedelta(days=1))
    ].copy()
    candles['date_ny'] = candles['timestamp_ny'].dt.date.astype(str)
    print(f"Cohort: {COHORT_START.date()} -> {COHORT_END.date()}, "
          f"{candles['date_ny'].nunique()} sessions, loaded in {time.time()-t0:.1f}s")
    print(f"Per-TF min size: {PER_TF_MIN_SIZE}")
    print(f"HTF bias: {BIAS_TF}, lookback={BIAS_LOOKBACK_BARS} bars, "
          f"neutral if |delta|<{BIAS_NEUTRAL_PTS} pts\n")

    signals = []
    rejections = Counter()

    for date_str, day_full in candles.groupby('date_ny', sort=True):
        day_full = day_full.reset_index(drop=True)
        ctx = td_by_date.get(date_str, {})

        gaps_full = build_full_fvg_inventory(day_full, min_size=BUILD_MIN_SIZE)
        if not gaps_full:
            continue
        mark_inversion_times(gaps_full, day_full)

        for g in gaps_full:
            if not g.is_inverted:
                continue

            # v5 #1: per-TF min size — enforce before anything else
            if g.size_pts < PER_TF_MIN_SIZE.get(g.tf, 9999):
                rejections[f'too_small_{g.tf}'] += 1
                continue

            inv_ts = g.inverted_at
            inv_close_ts = bar_close_ts(inv_ts, g.tf)
            if inv_close_ts.time() < KILLZONE_START or inv_close_ts.time() > KILLZONE_END:
                continue

            direction = 'short' if g.direction == 'bullish' else 'long'

            if (g.inversion_body_fraction or 0) < MIN_BODY_FRACTION:
                rejections['weak_body'] += 1
                continue

            # v5 #2: HTF bias gate
            bias = htf_bias_at(day_full, inv_close_ts)
            if bias == 'neutral':
                rejections['htf_neutral'] += 1
                continue
            if bias != direction:
                rejections[f'htf_bias_against_{direction}'] += 1
                continue

            if inv_close_ts.time() >= OR_READY:
                or15 = ctx.get('or_15min_range') or 0
                if or15 < MIN_OR_15:
                    rejections['post_or_low_range'] += 1
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

            dol = find_nearest_dol_v4(direction, entry_price, inv_ts, day_full, levels, date_str)
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

            clear, obstr = path_clear_v4(direction, entry_price, dol_price, inv_ts, g,
                                          gaps_full, day_full)
            if not clear:
                rejections['path_obstructed'] += 1
                continue

            outcome = simulate_dol_trade(direction, entry_price, inv_ts, stop_price,
                                         dol_price, day_full, g)

            signals.append({
                'date': date_str,
                'entry_ts': inv_ts,
                'bar_close_ts': inv_close_ts,
                'direction': direction,
                'htf_bias': bias,
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
                **outcome,
                'pnl_pts': outcome['r_multiple'] * stop_d,
            })

    print(f"Signals: {len(signals)}")
    print(f"Rejections: {dict(rejections)}\n")
    if not signals:
        return

    df = pd.DataFrame(signals)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(RESULTS_DIR / 'dol_trades_v5.csv', index=False)

    w = (df['r_multiple']>0).sum(); l = (df['r_multiple']<0).sum()
    gw = df.loc[df['r_multiple']>0, 'pnl_pts'].sum()
    gl = abs(df.loc[df['r_multiple']<0, 'pnl_pts'].sum()) or 1e-9
    print("=== Overall ===")
    print(f"  N: {len(df)}  WR: {w/max(w+l,1)*100:.1f}%  PF: {gw/gl:.2f}")
    print(f"  Avg R: {df['r_multiple'].mean():+.3f}  Total R: {df['r_multiple'].sum():+.1f}")
    print(f"  Exit reason: {df['exit_reason'].value_counts().to_dict()}")
    print(f"  Direction: {df['direction'].value_counts().to_dict()}")

    print(f"\n=== By gap TF ===")
    for tf, sub in df.groupby('gap_tf'):
        w_tf = (sub['r_multiple']>0).sum(); l_tf = (sub['r_multiple']<0).sum()
        gw_tf = sub.loc[sub['r_multiple']>0, 'pnl_pts'].sum()
        gl_tf = abs(sub.loc[sub['r_multiple']<0, 'pnl_pts'].sum()) or 1e-9
        print(f"  {tf:5}  N={len(sub):3}  WR={w_tf/max(w_tf+l_tf,1)*100:5.1f}%  PF={gw_tf/gl_tf:.2f}  totR={sub['r_multiple'].sum():+.1f}")

    print(f"\n=== By DOL target ===")
    for tgt, sub in df.groupby('target_source'):
        w_t = (sub['r_multiple']>0).sum(); l_t = (sub['r_multiple']<0).sum()
        gw_t = sub.loc[sub['r_multiple']>0, 'pnl_pts'].sum()
        gl_t = abs(sub.loc[sub['r_multiple']<0, 'pnl_pts'].sum()) or 1e-9
        print(f"  {tgt:22}  N={len(sub):3}  WR={w_t/max(w_t+l_t,1)*100:5.1f}%  PF={gw_t/gl_t:.2f}  totR={sub['r_multiple'].sum():+.1f}")

    print(f"\n=== 5/13 trades ===")
    sub = df[df['date'] == '2026-05-13']
    cols = ['entry_ts','direction','htf_bias','gap_tf','gap_size_pts',
            'inversion_body_fraction','target_source','r_planned','exit_reason','r_multiple']
    print(sub[cols].to_string(index=False) if len(sub) else "  (none)")

    print(f"\n=== 5/21 trades ===")
    sub = df[df['date'] == '2026-05-21']
    print(sub[cols].to_string(index=False) if len(sub) else "  (none)")

    print(f"\nRuntime: {time.time()-t0:.1f}s")


if __name__ == '__main__':
    main()
