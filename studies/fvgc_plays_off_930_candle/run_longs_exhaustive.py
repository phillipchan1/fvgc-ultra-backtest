#!/usr/bin/env python3
"""
Exhaustive long-side slice/confluence mine on the 8yr opening-FVG cohort.

Answers: "with 8 years, is there ANY slice or confluence that makes longs
tradeable?" Brute-forces single / pair / triple factor combos over a wide
binary factor matrix (day-level + trade-level slices), then forces every
candidate through an IS/OOS split and reports an expected-false-positive
count so we don't get fooled by multiple comparisons.

Run from repo root:
  python studies/fvgc_plays_off_930_candle/run_longs_exhaustive.py
"""

import sys
from datetime import time as dtime
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
from fvgc.constants import NY_TZ

TRADES_PATH = ROOT / 'logs' / 'baseline_trades.csv.preserve'
DAYS_PATH   = ROOT / 'data' / 'trading_days' / 'trading_days.csv'
WIN_START, WIN_END = dtime(9, 29, 30), dtime(9, 31, 0)
IS_END_YEAR = 2022          # IS <=2022, OOS >=2023

# Survivor gates (must hold on the FULL sample AND out-of-sample)
MIN_N_FULL = 30
MIN_N_OOS  = 12
FULL_WR    = 55.0
OOS_WR     = 53.0
OOS_PF     = 1.20


def rstats(s):
    s = s[s.outcome.isin(['win', 'loss'])]
    if len(s) == 0:
        return dict(n=0, wr=np.nan, pf=np.nan, exp=np.nan)
    w = int((s.outcome == 'win').sum()); l = int((s.outcome == 'loss').sum())
    pnl = pd.to_numeric(s.pnl); sl = pd.to_numeric(s.sl_dist)
    r = pnl / sl
    gw = pnl[pnl > 0].sum(); gl = -pnl[pnl < 0].sum()
    pf = gw / gl if gl > 0 else float('inf')
    return dict(n=len(s), wr=w / (w + l) * 100, pf=pf, exp=float(r.mean()))


def main():
    t = pd.read_csv(TRADES_PATH)
    t['timestamp'] = pd.to_datetime(t['timestamp'])
    fc = pd.to_datetime(t['fvg_created_at'], errors='coerce')
    t['fvg_ny'] = (fc.dt.tz_localize(NY_TZ, ambiguous='infer', nonexistent='shift_forward')
                   if fc.dt.tz is None else fc.dt.tz_convert(NY_TZ))
    t['date'] = t['timestamp'].dt.normalize()
    t['ft'] = t['fvg_ny'].dt.time
    t['in_win'] = t['fvg_ny'].notna() & t['ft'].between(WIN_START, WIN_END)
    t['year'] = t['timestamp'].dt.year

    base = t[t.outcome.isin(['win', 'loss'])].copy()
    L = base[(base.direction == 'long') & base.in_win].copy()

    days = pd.read_csv(DAYS_PATH); days['date'] = pd.to_datetime(days['date'])
    L = L.merge(days, on='date', how='left', suffixes=('', '_day'))

    # ---- build a WIDE binary factor matrix ------------------------------
    f = {}
    # trade-level slices
    f['var_bos']     = (L.variant == 'bos').astype(int)
    f['var_nofvg']   = (L.variant == 'no_fvg').astype(int)
    f['var_ifvg']    = (L.variant == 'ifvg').astype(int)
    f['var_ps']      = (L.variant == 'protected_swing').astype(int)
    fvg_size = (L.fvg_top - L.fvg_bottom).abs()
    f['fvg_big']     = (fvg_size >= fvg_size.median()).astype(int)
    f['fvg_small']   = (fvg_size <  fvg_size.median()).astype(int)
    f['sl_tight']    = (L.sl_dist <= L.sl_dist.median()).astype(int)
    f['sl_wide']     = (L.sl_dist >  L.sl_dist.median()).astype(int)
    entry_delay = (L.timestamp - L.fvg_ny.dt.tz_localize(None)).dt.total_seconds()
    f['entry_fast']  = (entry_delay <= entry_delay.median()).astype(int)
    f['entry_slow']  = (entry_delay >  entry_delay.median()).astype(int)
    # day-level slices
    gap = L.gap_from_prior_close
    f['gap_up']      = (gap >= 10).astype(int)
    f['gap_up_big']  = (gap >= 100).astype(int)
    f['gap_down']    = (gap <= -10).astype(int)
    f['gap_flat']    = (gap.abs() < 10).astype(int)
    f['pd_strong']   = (L.prior_day_close_position >= 0.667).astype(int)
    f['pd_weak']     = (L.prior_day_close_position <= 0.333).astype(int)
    f['c930_wide']   = (L.candle_930_body >= L.candle_930_body.median()).astype(int)
    f['c930_narrow'] = (L.candle_930_body <  L.candle_930_body.median()).astype(int)
    f['or5_wide']    = (L.or_5min_range >= L.or_5min_range.median()).astype(int)
    f['or5_narrow']  = (L.or_5min_range <  L.or_5min_range.median()).astype(int)
    f['on_wide']     = (L.overnight_range >= L.overnight_range.median()).astype(int)
    f['no_news']     = (~L.has_red_folder_news.astype(bool)).astype(int)
    f['has_news']    = (L.has_red_folder_news.astype(bool)).astype(int)
    for dname in ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']:
        f[f'dow_{dname[:3].lower()}'] = (L.day_of_week_name == dname).astype(int)
    f['fomc']        = L.is_fomc_week.astype(int)
    f['opex']        = L.is_opex_week.astype(int)
    f['vixy_hi']     = (L.vixy_prior_close >= L.vixy_prior_close.median()).astype(int)
    f['vixy_lo']     = (L.vixy_prior_close <  L.vixy_prior_close.median()).astype(int)
    f['on_dir_up']   = (L.overnight_direction == 'up').astype(int)
    f['on_dir_down'] = (L.overnight_direction == 'down').astype(int)

    F = pd.DataFrame(f, index=L.index)
    names = [c for c in F.columns if 2 <= F[c].sum() <= len(L) - 2]  # drop degenerate

    base_full = rstats(L)
    print('=' * 96)
    print(f'Opening-FVG LONGS 8yr  —  base n={base_full["n"]}  WR={base_full["wr"]:.1f}%  '
          f'PF={base_full["pf"]:.2f}')
    print(f'IS<=2022 / OOS>=2023.  Survivor gate: full n>={MIN_N_FULL} & WR>={FULL_WR}, '
          f'OOS n>={MIN_N_OOS} & WR>={OOS_WR} & PF>={OOS_PF}')
    print('=' * 96)

    oos_mask = (L.year >= IS_END_YEAR + 1).values

    def eval_combo(cols):
        m = np.ones(len(L), dtype=bool)
        for c in cols:
            m &= F[c].values.astype(bool)
        sub = L[m]
        sfull = rstats(sub)
        if sfull['n'] < MIN_N_FULL:
            return None
        soos = rstats(L[m & oos_mask])
        sis  = rstats(L[m & ~oos_mask])
        return sfull, sis, soos, m.sum()

    # enumerate 1, 2, 3-way combos
    candidates, n_tested = [], 0
    for k in (1, 2, 3):
        for cols in combinations(names, k):
            n_tested += 1
            res = eval_combo(cols)
            if res is None:
                continue
            sfull, sis, soos, _ = res
            candidates.append((cols, sfull, sis, soos))

    survivors = [c for c in candidates
                 if c[1]['wr'] >= FULL_WR
                 and c[3]['n'] >= MIN_N_OOS and c[3]['wr'] >= OOS_WR and c[3]['pf'] >= OOS_PF]

    # expected false positives: P(OOS WR>=53% by chance at base ~47%) per test, ×tests
    from math import comb
    p_base = base_full['wr'] / 100.0
    def p_atleast(n, thresh_wr):
        need = int(np.ceil(thresh_wr / 100.0 * n))
        return sum(comb(n, k) * p_base**k * (1 - p_base)**(n - k) for k in range(need, n + 1))
    # rough: use median OOS n among candidates
    oos_ns = [c[3]['n'] for c in candidates if c[3]['n'] >= MIN_N_OOS]
    med_oos = int(np.median(oos_ns)) if oos_ns else MIN_N_OOS
    exp_fp = len(candidates) * p_atleast(med_oos, OOS_WR)

    print(f'\nCombos tested: {n_tested:,}   |   passed n-floor: {len(candidates)}   '
          f'|   SURVIVORS: {len(survivors)}')
    print(f'Expected false-positive survivors by chance (~base {base_full["wr"]:.0f}% WR, '
          f'median OOS n={med_oos}): ~{exp_fp:.1f}')

    print('\n--- SURVIVORS (full / IS / OOS) ---')
    if not survivors:
        print('  (none)')
    survivors.sort(key=lambda c: c[3]['pf'], reverse=True)
    for cols, sf, si, so in survivors[:25]:
        print(f'  {"+".join(cols):42s} '
              f'FULL n={sf["n"]:3d} WR={sf["wr"]:4.1f}% PF={sf["pf"]:4.2f} | '
              f'IS n={si["n"]:3d} WR={si["wr"]:4.1f}% | '
              f'OOS n={so["n"]:3d} WR={so["wr"]:4.1f}% PF={so["pf"]:4.2f}')

    # Also show the top-15 by FULL WR regardless of OOS, to see the overfit gallery
    print('\n--- Top 15 by FULL WR (n>=30) — note IS->OOS decay ---')
    by_wr = sorted([c for c in candidates], key=lambda c: c[1]['wr'], reverse=True)[:15]
    for cols, sf, si, so in by_wr:
        print(f'  {"+".join(cols):42s} '
              f'FULL n={sf["n"]:3d} WR={sf["wr"]:4.1f}% PF={sf["pf"]:4.2f} | '
              f'IS WR={si["wr"]:4.1f}% | OOS n={so["n"]:3d} WR={so["wr"]:4.1f}% PF={so["pf"]:4.2f}')


if __name__ == '__main__':
    main()
