#!/usr/bin/env python3
"""DOL Continuation v4 — fixes from 5/13 diagnostic.

Changes from v3:
  1. Killzone start at 9:30 (was 9:45) — capture open-window setups
  2. Use bar CLOSE time (= bar_start + tf_seconds) for killzone gate, not start
  3. DOL selection enriched: pre-OR trades can use pre-market session low/high,
     overnight, asia/london, PDH/PDL. Post-OR trades add OR.
  4. Path-clear strict mode: FVG only counts as obstruction if it lies ENTIRELY
     in path (target < fvg.bottom < fvg.top < entry, for shorts; mirror).
     AND it hasn't been wicked into since formation.
  5. (Future) 15m HTF FVG as DOL — stub left for next iter.

Killzone end still 11:00 (per Tempo manual).
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
    MIN_FVG_SIZE, HARD_STOP_BUFFER, simulate_dol_trade,
)

RESULTS_DIR = Path(__file__).resolve().parent / 'results'
TRADING_DAYS_PATH = Path('data/trading_days/trading_days.csv')

KILLZONE_START = dtime(9, 30)       # v4: was 9:45
KILLZONE_END = dtime(11, 0)
OR_READY = dtime(9, 45)             # OR levels become available at 9:45

# v4 risk params
MIN_DOL_DISTANCE_R = 1.0
MAX_DOL_DISTANCE_R = 5.0
MIN_BODY_FRACTION = 0.55
MIN_OR_15 = 67.0                    # post-OR quality filter only

# Bar duration in seconds per TF (for bar-close time computation)
TF_SECONDS = {'30s': 30, '1min': 60, '2min': 120, '3min': 180, '5min': 300}


def get_overnight_levels(levels_df: pd.DataFrame, date_str: str):
    rows = levels_df[(levels_df['date'] == date_str) &
                     (levels_df['level_name'].isin(['overnight_high', 'overnight_low']))]
    oh = rows[rows['level_name'] == 'overnight_high']['price'].iloc[0] if not rows[rows['level_name']=='overnight_high'].empty else float('nan')
    ol = rows[rows['level_name'] == 'overnight_low']['price'].iloc[0] if not rows[rows['level_name']=='overnight_low'].empty else float('nan')
    return float(oh), float(ol)


def get_asia_london_levels(levels_df: pd.DataFrame, date_str: str):
    rows = levels_df[(levels_df['date'] == date_str) &
                     (levels_df['level_name'].isin(['asia_high', 'asia_low', 'london_high', 'london_low']))]
    out = {}
    for name in ['asia_high','asia_low','london_high','london_low']:
        r = rows[rows['level_name']==name]
        out[name] = float(r['price'].iloc[0]) if not r.empty else float('nan')
    return out


def session_lo_hi_so_far(day_candles: pd.DataFrame, at_ts: pd.Timestamp):
    """Running session low/high (any-time RTH bars before at_ts)."""
    rth = day_candles[
        (day_candles['timestamp_ny'].dt.time >= KILLZONE_START) &
        (day_candles['timestamp_ny'] < at_ts)
    ]
    if rth.empty:
        return float('nan'), float('nan')
    return float(rth['high'].max()), float(rth['low'].min())


def find_nearest_dol_v4(
    direction: str,
    entry_price: float,
    at_ts: pd.Timestamp,
    day_candles: pd.DataFrame,
    levels_df: pd.DataFrame,
    date_str: str,
):
    """Find nearest DOL in trade direction. v4 considers more sources, gated by what's known at at_ts."""
    candidates = []

    # OR (only if at_ts > 9:45)
    if at_ts.time() >= OR_READY:
        or_h, or_l = compute_or(day_candles)
        if direction == 'short' and not np.isnan(or_l) and or_l < entry_price:
            candidates.append(('or_low', or_l))
        if direction == 'long' and not np.isnan(or_h) and or_h > entry_price:
            candidates.append(('or_high', or_h))

    # Overnight high/low (pre-market levels — always known)
    oh, ol = get_overnight_levels(levels_df, date_str)
    if direction == 'short' and not np.isnan(ol) and ol < entry_price:
        candidates.append(('overnight_low', ol))
    if direction == 'long' and not np.isnan(oh) and oh > entry_price:
        candidates.append(('overnight_high', oh))

    # Asia / London
    al = get_asia_london_levels(levels_df, date_str)
    if direction == 'short':
        for nm in ('asia_low', 'london_low'):
            v = al.get(nm)
            if not np.isnan(v) and v < entry_price:
                candidates.append((nm, v))
    else:
        for nm in ('asia_high', 'london_high'):
            v = al.get(nm)
            if not np.isnan(v) and v > entry_price:
                candidates.append((nm, v))

    # Prior day
    pdh, pdl = get_pd_levels(levels_df, date_str)
    if direction == 'short' and not np.isnan(pdl) and pdl < entry_price:
        candidates.append(('prev_day_low', pdl))
    if direction == 'long' and not np.isnan(pdh) and pdh > entry_price:
        candidates.append(('prev_day_high', pdh))

    # Pre-trade running session extreme (only useful as proxy for OR before 9:45)
    if at_ts.time() < OR_READY:
        h, l = session_lo_hi_so_far(day_candles, at_ts)
        if direction == 'short' and not np.isnan(l) and l < entry_price:
            candidates.append(('session_low_so_far', l))
        if direction == 'long' and not np.isnan(h) and h > entry_price:
            candidates.append(('session_high_so_far', h))

    # Running 50% (only post-OR)
    if at_ts.time() >= OR_READY:
        mid = running_50pct_at(day_candles, at_ts)
        if direction == 'short' and not np.isnan(mid) and mid < entry_price:
            candidates.append(('running_50pct', mid))
        if direction == 'long' and not np.isnan(mid) and mid > entry_price:
            candidates.append(('running_50pct', mid))

    if not candidates:
        return None

    if direction == 'short':
        return max(candidates, key=lambda x: x[1])
    return min(candidates, key=lambda x: x[1])


def path_clear_v4(direction, entry_price, target_price, entry_ts,
                  excluded_gap, all_gaps, candles_30s):
    """v4 strict: FVG only counts as obstruction if it lies ENTIRELY in path
    AND has not been wicked into since formation."""
    obstructions = []
    opposing_dir = 'bullish' if direction == 'short' else 'bearish'

    for g in all_gaps:
        if g is excluded_gap:
            continue
        if g.direction != opposing_dir:
            continue
        if g.created_at >= entry_ts:
            continue
        # Entirely-in-path test (strict)
        if direction == 'short':
            if not (target_price < g.bottom and g.top < entry_price):
                continue
        else:
            if not (entry_price < g.bottom and g.top < target_price):
                continue
        # Wicked-into check
        subs = candles_30s[
            (candles_30s['timestamp_ny'] > g.created_at) &
            (candles_30s['timestamp_ny'] < entry_ts)
        ]
        if not subs.empty:
            if g.direction == 'bullish':
                if (subs['low'] <= g.top).any():
                    continue
            else:
                if (subs['high'] >= g.bottom).any():
                    continue
        obstructions.append(f"{g.tf} {g.direction} @ [{g.bottom:.1f}, {g.top:.1f}]")

    return (len(obstructions) == 0, obstructions)


def bar_close_ts(bar_start_ts, tf):
    """Compute bar-close time = start + tf duration."""
    return bar_start_ts + pd.Timedelta(seconds=TF_SECONDS[tf])


def main():
    print("=== DOL Continuation v4 (open-window + strict path) ===\n")
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
          f"{candles['date_ny'].nunique()} sessions, loaded in {time.time()-t0:.1f}s\n")

    signals = []
    rejections = Counter()

    for date_str, day_full in candles.groupby('date_ny', sort=True):
        day_full = day_full.reset_index(drop=True)
        ctx = td_by_date.get(date_str, {})

        gaps_full = build_full_fvg_inventory(day_full, min_size=MIN_FVG_SIZE)
        if not gaps_full:
            continue
        mark_inversion_times(gaps_full, day_full)

        for g in gaps_full:
            if not g.is_inverted:
                continue
            inv_ts = g.inverted_at
            # v4: use bar CLOSE time for killzone check
            inv_close_ts = bar_close_ts(inv_ts, g.tf)
            if inv_close_ts.time() < KILLZONE_START or inv_close_ts.time() > KILLZONE_END:
                continue

            direction = 'short' if g.direction == 'bullish' else 'long'

            if (g.inversion_body_fraction or 0) < MIN_BODY_FRACTION:
                rejections['weak_body'] += 1
                continue

            # Post-OR quality gate (only for post-9:45 trades)
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
    df.to_csv(RESULTS_DIR / 'dol_trades_v4.csv', index=False)

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
    cols = ['entry_ts','bar_close_ts','direction','gap_tf','gap_size_pts',
            'inversion_body_fraction','target_source','r_planned','exit_reason','r_multiple']
    print(sub[cols].to_string(index=False) if len(sub) else "  (none)")

    print(f"\nRuntime: {time.time()-t0:.1f}s")


if __name__ == '__main__':
    main()
