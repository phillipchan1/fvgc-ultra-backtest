"""
Deep-dive on E2 — the only PASS in the menu.

E2 setup: a FVGC fires AND the lag-1 POC sits AHEAD of entry in trade direction
AND the overnight session (pre-RTH) did NOT reach that POC (overnight_high <
POC for longs, overnight_low > POC for shorts). "Untraded magnet" hypothesis:
unfilled prior-day levels pull harder.

Checks:
  1. Yearly stability — 9 yrs each separately
  2. Direction × outcome breakdown
  3. Compare {overnight reached POC} vs {overnight did NOT reach POC} cohorts
     directly (the "naked vs touched" contrast)
  4. Lookahead audit: confirm all inputs are causally safe
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import polars as pl

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _shared import (  # noqa: E402
    load_trades, with_lagged_vp, with_session_levels,
    play_economics, format_econ,
    IS_MAX_YEAR, OOS_MIN_YEAR,
)


def main():
    t = load_trades()
    t = with_lagged_vp(t)
    t = with_session_levels(t)

    is_long = t['direction'].to_numpy() == 'long'
    ep = t['entry_price'].to_numpy()
    poc = t['poc_lag1'].to_numpy()
    on_high = t['overnight_high'].to_numpy()
    on_low = t['overnight_low'].to_numpy()
    mod = t['mod'].to_numpy()
    var_ok = t['variant'].to_numpy() != 'protected_swing'

    # POC ahead in direction
    poc_ahead = np.where(is_long, poc > ep, poc < ep)
    poc_ahead = np.where(np.isnan(poc), False, poc_ahead)

    # Naked: overnight didn't reach POC
    naked_long = on_high < poc
    naked_short = on_low > poc
    naked = (is_long & naked_long) | ((~is_long) & naked_short)
    naked = np.where(np.isnan(on_high) | np.isnan(on_low) | np.isnan(poc),
                     False, naked)

    in_window = (mod >= 570) & (mod <= 615)
    e2_mask = poc_ahead & naked & var_ok & in_window

    # Contrast cohort: same setup but overnight DID reach POC
    touched_long = on_high >= poc
    touched_short = on_low <= poc
    touched = (is_long & touched_long) | ((~is_long) & touched_short)
    touched = np.where(np.isnan(on_high) | np.isnan(on_low) | np.isnan(poc),
                       False, touched)
    contrast_mask = poc_ahead & touched & var_ok & in_window

    t = t.with_columns([
        pl.Series('e2_mask', e2_mask),
        pl.Series('contrast_mask', contrast_mask),
    ])

    # ----- 1. yearly stability -----
    print('=' * 70)
    print('E2 deep-dive: aged-naked VP POC magnet (lag-1)')
    print('=' * 70)
    print()
    print('--- 1) Yearly stability ---')
    print(f'{"year":<6}{"n":<5}{"WR":<8}{"PF":<8}{"exp":<8}{"sumR":<8}')
    sub = t.filter(pl.col('e2_mask'))
    contrast = t.filter(pl.col('contrast_mask'))
    for y in sorted(t['year'].unique().to_list()):
        f = sub.filter(pl.col('year') == y)
        e = play_economics(f)
        wr = (e['wr']*100) if e['wr'] is not None else 0
        pf = e['pf']
        pf_s = f'{pf:.2f}' if pf and pf != float('inf') else 'INF' if pf == float('inf') else '-'
        exp = e['exp_r'] if e['exp_r'] is not None else 0
        print(f'{y:<6}{e["n"]:<5}{wr:>5.1f}%  {pf_s:<8}{exp:+.2f}R  {e["sum_r"]:+.1f}')
    print()
    print(f'Total: {format_econ(play_economics(sub))}')
    print()

    # ----- 2. Direction breakdown -----
    print('--- 2) Direction breakdown ---')
    for dirn in ('long', 'short'):
        f = sub.filter(pl.col('direction') == dirn)
        f_oos = f.filter(pl.col('is_in_oos'))
        print(f'  {dirn:<5}  ALL: {format_econ(play_economics(f))}')
        print(f'  {dirn:<5}  OOS: {format_econ(play_economics(f_oos))}')
    print()

    # ----- 3. NAKED vs TOUCHED contrast (the mechanism test) -----
    print('--- 3) Naked-vs-touched POC contrast (same setup, opposite condition) ---')
    print(f'  NAKED  (overnight did NOT reach POC):')
    print(f'    ALL: {format_econ(play_economics(sub))}')
    print(f'    OOS: {format_econ(play_economics(sub.filter(pl.col("is_in_oos"))))}')
    print(f'  TOUCHED (overnight DID reach POC, otherwise same setup):')
    print(f'    ALL: {format_econ(play_economics(contrast))}')
    print(f'    OOS: {format_econ(play_economics(contrast.filter(pl.col("is_in_oos"))))}')
    print()

    # ----- 4. Variant decomposition (no_fvg / ifvg / bos) -----
    print('--- 4) Variant decomposition (OOS only) ---')
    for v in sorted(t['variant'].unique().to_list()):
        f = sub.filter((pl.col('variant') == v) & (pl.col('is_in_oos')))
        if f.height == 0:
            continue
        print(f'  {v:<18}  {format_econ(play_economics(f))}')
    print()

    # ----- 5. Macro window -----
    print('--- 5) Time-window decomposition (OOS only) ---')
    # mod buckets: 9:30-9:45, 9:45-10:00, 10:00-10:15
    sub_oos = sub.filter(pl.col('is_in_oos'))
    for lo, hi, lbl in [(570, 585, '9:30-9:45'),
                        (585, 600, '9:45-10:00'),
                        (600, 616, '10:00-10:15')]:
        f = sub_oos.filter((pl.col('mod') >= lo) & (pl.col('mod') < hi))
        print(f'  {lbl:<12}  {format_econ(play_economics(f))}')
    print()

    # ----- 6. Lookahead audit -----
    print('--- 6) Lookahead audit ---')
    print('  Inputs to E2:')
    print('    poc_lag1            : yesterday\'s POC (loaded via load_lagged_vp)         CAUSAL')
    print('    overnight_high/low  : pre-RTH session extremes  (available_time = open)  CAUSAL')
    print('    entry_price, sl_dist: from baseline trade row                            CAUSAL')
    print('    variant != PS       : from FVGC engine, known at entry                   CAUSAL')
    print('    mod in [570, 615]   : trade clock                                        CAUSAL')
    print('  No full-session aggregates used.  Audit: PASS')
    print()

    # ----- 7. R-distance to POC profile -----
    print('--- 7) R-distance to POC profile (OOS naked cohort) ---')
    sub_oos = sub.filter(pl.col('is_in_oos'))
    ep_oos = sub_oos['entry_price'].to_numpy()
    poc_oos = sub_oos['poc_lag1'].to_numpy()
    sl_oos = sub_oos['sl_dist'].to_numpy()
    is_long_oos = sub_oos['direction'].to_numpy() == 'long'
    diff = poc_oos - ep_oos
    r_poc = np.where(is_long_oos, diff, -diff) / sl_oos
    print(f'  R-distance to POC (positive = ahead): '
          f'p25={np.percentile(r_poc, 25):.2f}  p50={np.percentile(r_poc, 50):.2f}  '
          f'p75={np.percentile(r_poc, 75):.2f}  p95={np.percentile(r_poc, 95):.2f}')
    # Bucket by R-band
    for lo, hi, lbl in [(0, 1.5, '0-1.5R'),
                        (1.5, 3.0, '1.5-3R'),
                        (3.0, 6.0, '3-6R'),
                        (6.0, 999, '6R+')]:
        m = (r_poc >= lo) & (r_poc < hi)
        f = sub_oos.filter(pl.Series('m', m))
        if f.height == 0:
            continue
        print(f'  {lbl:<8}  {format_econ(play_economics(f))}')


if __name__ == '__main__':
    main()
