#!/usr/bin/env python3
"""DOL Continuation v3 — fixed path-clear logic.

KEY CHANGE: an opposing FVG is only an obstruction if its body has NEVER been
WICKED into since formation (i.e., truly fresh/untouched).

This matches the user's visual mental model: a bullish FVG you've already
traded through (price came down to your entry past that level) doesn't count
as a remaining obstruction below.

Previous v2 was too strict — counted partially-mitigated FVGs as obstructions.
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
    find_nearest_dol, get_pd_levels,
    DATA_PATH, LEVELS_PATH, COHORT_START, COHORT_END,
    KILLZONE_START, KILLZONE_END, MIN_FVG_SIZE, HARD_STOP_BUFFER,
    simulate_dol_trade, _TF_FREQ_EXT,
)
from ifvg_reversal.detectors.multi_tf_fvg import _resample_ohlc

RESULTS_DIR = Path(__file__).resolve().parent / 'results'
TRADING_DAYS_PATH = Path('data/trading_days/trading_days.csv')

MIN_DOL_DISTANCE_R = 1.0
MAX_DOL_DISTANCE_R = 4.0       # widened slightly
MIN_BODY_FRACTION = 0.55
MIN_OR_15 = 67.0


def fvg_was_wicked_since_formation(g, candles_30s, up_to_ts) -> bool:
    """Did any candle since the FVG formed wick INTO its body, before up_to_ts?

    For a bullish FVG, body is [bottom, top]. We consider it wicked-into if
    any subsequent candle has low <= top (i.e., price entered the gap body).
    Mirror for bearish.

    This represents the user's mental "this gap has been visited / mitigated"
    even without a full close-through inversion.
    """
    subsequent = candles_30s[
        (candles_30s['timestamp_ny'] > g.created_at) &
        (candles_30s['timestamp_ny'] < up_to_ts)
    ]
    if subsequent.empty:
        return False
    if g.direction == 'bullish':
        # Wicked into if any low has entered the gap body
        return bool((subsequent['low'] <= g.top).any())
    else:
        return bool((subsequent['high'] >= g.bottom).any())


def path_clear_v3(direction, entry_price, target_price, entry_ts,
                   excluded_gap, all_gaps, candles_30s,
                   overlap_pts=2.0):
    """v3 path-clear: only count FVGs that are STILL FRESH (never wicked into).

    Also: ignore FVGs whose body overlaps the inverted gap's body by overlap_pts
    (treats them as the same zone).
    """
    obstructions = []
    opposing_dir = 'bullish' if direction == 'short' else 'bearish'

    ex_top = excluded_gap.top; ex_bot = excluded_gap.bottom

    for g in all_gaps:
        if g is excluded_gap:
            continue
        if g.direction != opposing_dir:
            continue
        if g.created_at >= entry_ts:
            continue

        # Skip FVGs that overlap with the inverted gap's body (same zone)
        # Two FVGs overlap if their [bot, top] intervals intersect within tolerance
        if not (g.top + overlap_pts < ex_bot or g.bottom - overlap_pts > ex_top):
            continue

        # Body must sit in the path
        if direction == 'short':
            if not (target_price < g.top < entry_price or target_price < g.bottom < entry_price):
                continue
        else:
            if not (entry_price < g.top < target_price or entry_price < g.bottom < target_price):
                continue

        # NEW: only count if FVG is still FRESH (never wicked into)
        if fvg_was_wicked_since_formation(g, candles_30s, entry_ts):
            continue  # already mitigated, not an obstruction

        obstructions.append(f"{g.tf} {g.direction} @ [{g.bottom:.1f}, {g.top:.1f}]")

    return (len(obstructions) == 0, obstructions)


def main():
    print("=== DOL Continuation v3 (relaxed path-clear) ===\n")
    t0 = time.time()

    candles = load_candles(DATA_PATH)
    levels = pd.read_csv(LEVELS_PATH)
    td = pd.read_csv(TRADING_DAYS_PATH)
    td['date'] = pd.to_datetime(td['date']).dt.date.astype(str)
    td_by_date = td.set_index('date')[['prior_day_type','prior_day_close_position',
                                        'or_15min_range','prior_day_range_atr_ratio']].to_dict('index')

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

        or15 = ctx.get('or_15min_range') or 0
        if or15 < MIN_OR_15:
            rejections['day_or15_too_low'] += 1
            continue

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

            clear, obstructions = path_clear_v3(
                direction, entry_price, dol_price, inv_ts, g, gaps_full, day_full,
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
                **outcome,
                'pnl_pts': outcome['r_multiple'] * stop_d,
            })

    print(f"Signals emitted: {len(signals)}")
    print(f"Rejections: {dict(rejections)}\n")

    if not signals:
        return

    df = pd.DataFrame(signals)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(RESULTS_DIR / 'dol_trades_v3.csv', index=False)

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
        print(f"  {tf:5}  N={len(sub):3}  WR={w_tf/max(w_tf+l_tf,1)*100:5.1f}%  PF={gw_tf/gl_tf:.2f}  totR={sub['r_multiple'].sum():+.1f}")

    print(f"\n=== By DOL target ===")
    for tgt, sub in df.groupby('target_source'):
        w_t = (sub['r_multiple']>0).sum(); l_t = (sub['r_multiple']<0).sum()
        gw_t = sub.loc[sub['r_multiple']>0, 'pnl_pts'].sum()
        gl_t = abs(sub.loc[sub['r_multiple']<0, 'pnl_pts'].sum()) or 1e-9
        print(f"  {tgt:18}  N={len(sub):3}  WR={w_t/max(w_t+l_t,1)*100:5.1f}%  PF={gw_t/gl_t:.2f}  totR={sub['r_multiple'].sum():+.1f}")

    # Check 5/13 specifically
    print(f"\n=== Trades on 2026-05-13 ===")
    sub = df[df['date'] == '2026-05-13']
    cols = ['entry_ts','direction','gap_tf','gap_size_pts','inversion_body_fraction',
            'target_source','r_planned','exit_reason','r_multiple']
    if len(sub):
        print(sub[cols].to_string(index=False))
    else:
        print("  Still no trade on 2026-05-13. Need to investigate further.")

    print(f"\nTotal runtime: {time.time()-t0:.1f}s")


if __name__ == '__main__':
    main()
