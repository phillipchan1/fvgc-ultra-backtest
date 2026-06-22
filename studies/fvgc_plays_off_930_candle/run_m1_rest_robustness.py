#!/usr/bin/env python3
"""
Test whether M1 SHORT (entry 9:30-9:45, no PS) is robust as a play on its own —
specifically whether M1 minus the opening-FVG slice still has the runner edge
the M1 page claims (TP@5R no-BE, PF 3+ at conf 2+).

If M1-rest collapses to ~PF 1 even with runners, then "M1 short" reduces to
"the opening-FVG slice" and the M1 page needs a major rewrite.

Run from repo root:
  python studies/fvgc_plays_off_930_candle/run_m1_rest_robustness.py
"""

import sys
from datetime import time as dtime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
from fvgc.constants import NY_TZ

TRADES_PATH = ROOT / 'logs' / 'baseline_trades.csv'
DAYS_PATH   = ROOT / 'data' / 'trading_days' / 'trading_days.csv'

WIN_START = dtime(9, 29, 30)
WIN_END   = dtime(9, 31, 0)


def compute_per_day_factors(d: pd.DataFrame) -> pd.DataFrame:
    d = d.sort_values('date').reset_index(drop=True).copy()
    d['vixy_q25_90'] = d['vixy_prior_close'].rolling(90, min_periods=30).quantile(0.25)
    d['vixy_q75_90'] = d['vixy_prior_close'].rolling(90, min_periods=30).quantile(0.75)
    d['c930_body_q75_90'] = d['candle_930_body'].rolling(90, min_periods=30).quantile(0.75)

    d['c_gap_large_down']   = (d['gap_from_prior_close'] <= -100).astype(int)
    d['c_prior_day_weak']   = (d['prior_day_close_position'] <= 0.333).astype(int)
    d['c_is_fomc_week']     = d['is_fomc_week'].astype(int)
    d['c_vixy_high']        = (d['vixy_prior_close'] >= d['vixy_q75_90']).astype(int)
    d['c_dow_friday']       = (d['day_of_week_name'] == 'Friday').astype(int)
    d['c_bear_930']         = (d['candle_930_direction'] == 'bearish').astype(int)
    d['c_c930_body_top_q']  = (d['candle_930_body'] >= d['c930_body_q75_90']).astype(int)
    factor_cols = ['c_gap_large_down','c_prior_day_weak','c_is_fomc_week','c_vixy_high',
                   'c_dow_friday','c_bear_930','c_c930_body_top_q']
    d['confluence_count'] = d[factor_cols].sum(axis=1)
    d['v_vixy_low']    = (d['vixy_prior_close'] <= d['vixy_q25_90']).astype(int)
    d['v_dow_monday']  = (d['day_of_week_name'] == 'Monday').astype(int)
    d['veto_any']      = ((d['v_vixy_low'] + d['v_dow_monday']) > 0).astype(int)
    return d


def stats_1r(df: pd.DataFrame) -> dict:
    """WR/PF at fixed 1R TP (engine outcome)."""
    s = df[df['outcome'].isin(['win','loss'])]
    if s.empty: return dict(n=0)
    w = int((s['outcome']=='win').sum()); l = int((s['outcome']=='loss').sum())
    pnl = pd.to_numeric(s['pnl'], errors='coerce'); sl = pd.to_numeric(s['sl_dist'], errors='coerce')
    r = pnl/sl
    gw=pnl[pnl>0].sum(); gl=-pnl[pnl<0].sum()
    pf = (gw/gl) if gl>0 else float('inf')
    return dict(n=len(s), wins=w, losses=l, wr=w/(w+l)*100, pf=pf, exp_r=float(r.mean()))


def fmt(label, s):
    if not s or s.get('n',0)==0:
        return f'  {label:55s}  n=0'
    return (f'  {label:55s}  n={s["n"]:4d}  W={s["wins"]:3d} L={s["losses"]:3d}  '
            f'WR={s["wr"]:5.1f}%  PF={s["pf"]:5.2f}  exp={s["exp_r"]:+.3f}R')


def runner_sim(df: pd.DataFrame, target_R: float, be_after_R: float) -> dict:
    """
    Simulate: initial stop 1R, optional BE move after `be_after_R` hits, TP at target_R.
    be_after_R = 0 means no BE move (stop stays at -1R).
    """
    s = df[df['outcome'].isin(['win','loss'])].copy()
    if s.empty: return {}
    tcol = f'hit_{int(target_R)}_0R' if target_R==int(target_R) else f'hit_{int(target_R)}_5R'
    if tcol not in s.columns: return {}
    bcol = None
    if be_after_R > 0:
        bcol = f'hit_{int(be_after_R)}_0R' if be_after_R==int(be_after_R) else f'hit_{int(be_after_R)}_5R'

    def trade_r(row):
        hit_t = bool(row[tcol])
        if hit_t: return float(target_R)
        if bcol is not None and bool(row[bcol]): return 0.0
        # no BE configured OR BE not hit: trade outcome determines
        # if original outcome was 'win' (i.e. hit 1R TP), but our target_R > 1R
        # and no BE: we assume held to original 1R stop on the failed runner.
        # Conservative: if no BE used and target not hit, take as -1R loss.
        return -1.0

    s['r'] = s.apply(trade_r, axis=1)
    wins = int((s['r']>0).sum()); losses = int((s['r']<0).sum()); bes = int((s['r']==0).sum())
    gw = s['r'][s['r']>0].sum(); gl = -s['r'][s['r']<0].sum()
    pf = (gw/gl) if gl>0 else float('inf')
    return dict(n=len(s), wins=wins, losses=losses, bes=bes,
                avg_r=float(s['r'].mean()), pf=pf,
                wr_excl_be=wins/(wins+losses)*100 if (wins+losses) else float('nan'))


def main():
    print('='*100)
    print('M1 SHORT (rest) ROBUSTNESS — does M1 minus the Opening-FVG slice stand alone?')
    print('='*100)

    t = pd.read_csv(TRADES_PATH)
    t['timestamp'] = pd.to_datetime(t['timestamp'])
    t['fvg_created_at'] = pd.to_datetime(t['fvg_created_at'], errors='coerce')
    if t['fvg_created_at'].dt.tz is None:
        t['fvg_created_ny'] = t['fvg_created_at'].dt.tz_localize(NY_TZ, ambiguous='infer',
                                                                  nonexistent='shift_forward')
    else:
        t['fvg_created_ny'] = t['fvg_created_at'].dt.tz_convert(NY_TZ)
    t['date'] = t['timestamp'].dt.normalize()
    t['entry_time'] = t['timestamp'].dt.time
    t['fvg_t'] = t['fvg_created_ny'].dt.time
    t['in_open_win'] = t['fvg_created_ny'].notna() & t['fvg_t'].between(WIN_START, WIN_END)

    base = t[t['outcome'].isin(['win','loss'])].copy()

    # M1 short cohort (entry 9:30-9:45, no PS — matches M1 page definition)
    m1 = base[(base['direction']=='short')
              & (base['entry_time']>=dtime(9,30)) & (base['entry_time']<dtime(9,45))
              & (base['variant']!='protected_swing')].copy()
    slice_ = m1[m1.in_open_win].copy()
    rest   = m1[~m1.in_open_win].copy()
    print(f'\nM1 short (no PS):          n={len(m1)}')
    print(f'  ∩ Opening-FVG (slice):    n={len(slice_)}')
    print(f'  \\ Opening-FVG (rest):     n={len(rest)}')

    # Per-day factors
    days = pd.read_csv(DAYS_PATH)
    days['date'] = pd.to_datetime(days['date'])
    days = compute_per_day_factors(days)
    factor_cols = ['date','confluence_count','veto_any',
                   'c_gap_large_down','c_prior_day_weak','c_is_fomc_week','c_vixy_high',
                   'c_dow_friday','c_bear_930','c_c930_body_top_q']
    rest = rest.merge(days[factor_cols], on='date', how='left')
    slice_ = slice_.merge(days[factor_cols], on='date', how='left')
    m1    = m1.merge(days[factor_cols], on='date', how='left')

    # --------------------------------------------------------------
    # 1. Fixed 1R TP — slice vs rest, by tier
    # --------------------------------------------------------------
    print('\n' + '='*100)
    print('1. Fixed 1R TP — slice vs rest, stratified by M1 confluence count')
    print('='*100)
    for lo,hi,lbl in [(0,7,'ALL'), (0,1,'0-1'), (2,2,'2'), (3,3,'3'), (4,7,'4+'), (2,7,'2+')]:
        sl = slice_[(slice_.confluence_count>=lo) & (slice_.confluence_count<=hi)]
        rs = rest[(rest.confluence_count>=lo)   & (rest.confluence_count<=hi)]
        print(fmt(f'slice tier {lbl}', stats_1r(sl)))
        print(fmt(f'rest  tier {lbl}', stats_1r(rs)))

    # --------------------------------------------------------------
    # 2. Runner sim on REST cohort — does the runner save it?
    # --------------------------------------------------------------
    print('\n' + '='*100)
    print('2. Runner simulations on REST cohort (M1 minus Opening-FVG)')
    print('='*100)
    for lo,hi,lbl in [(0,7,'ALL'), (2,7,'2+'), (3,7,'3+'), (4,7,'4+')]:
        sub = rest[(rest.confluence_count>=lo) & (rest.confluence_count<=hi)]
        if len(sub)==0: continue
        print(f'\n--- REST cohort, tier {lbl} (n={len(sub)}) ---')
        print(f'  {"strategy":40s}    n  W   L  BE  avg_R    PF')
        for target, be in [(1.0,0.0),(2.0,0.0),(3.0,0.0),(5.0,0.0),
                           (2.0,1.0),(3.0,1.0),(5.0,1.0)]:
            r = runner_sim(sub, target, be)
            if not r: continue
            be_str = f'TP {target}R no BE' if be==0 else f'TP {target}R + BE@{int(be)}R'
            print(f'  {be_str:40s}  {r["n"]:3d} {r["wins"]:3d} {r["losses"]:3d} {r["bes"]:3d}  '
                  f'{r["avg_r"]:+.3f}  {r["pf"]:5.2f}')

    # --------------------------------------------------------------
    # 3. Year-by-year on REST tier 2+ — stability check
    # --------------------------------------------------------------
    print('\n' + '='*100)
    print('3. Year-by-year stability — REST cohort, tier 2+, fixed 1R TP')
    print('='*100)
    rest['year'] = rest['timestamp'].dt.year
    rest_2p = rest[rest.confluence_count>=2]
    for y, g in rest_2p.groupby('year'):
        if len(g) < 3: continue
        print(fmt(f'  {y}', stats_1r(g)))

    print('\n--- Year-by-year REST tier 2+ with TP@5R no-BE (M1 page recommended exit) ---')
    for y, g in rest_2p.groupby('year'):
        if len(g) < 3: continue
        r = runner_sim(g, 5.0, 0.0)
        if not r: continue
        print(f'  {y}  n={r["n"]:3d}  hit5R={r["wins"]:3d}  -1R={r["losses"]:3d}  '
              f'avg_R={r["avg_r"]:+.3f}  PF={r["pf"]:5.2f}')

    # --------------------------------------------------------------
    # 4. Reconciliation: do my numbers reproduce the M1 page?
    # --------------------------------------------------------------
    print('\n' + '='*100)
    print('4. Reconciliation — M1 page claims (with vetoes) vs this run')
    print('='*100)
    # M1 page: n=124 at 2+ tier, 68.5% IS WR, 51-60% honest 8yr
    # Apply vetoes: no Monday, no low-VIX
    m1_postveto = m1[m1.veto_any==0]
    print(fmt('All M1 short post-veto, no PS', stats_1r(m1_postveto)))
    for lo,hi,lbl in [(2,7,'2+'),(3,7,'3+'),(4,7,'4+')]:
        sub = m1_postveto[(m1_postveto.confluence_count>=lo) & (m1_postveto.confluence_count<=hi)]
        print(fmt(f'  tier {lbl}', stats_1r(sub)))

    print('\n--- M1 post-veto with TP@5R no-BE (page recommended exit) ---')
    for lo,hi,lbl in [(0,7,'ALL'),(2,7,'2+'),(4,7,'4+')]:
        sub = m1_postveto[(m1_postveto.confluence_count>=lo) & (m1_postveto.confluence_count<=hi)]
        r = runner_sim(sub, 5.0, 0.0)
        if not r: continue
        print(f'  tier {lbl}: n={r["n"]:3d}  avg_R={r["avg_r"]:+.3f}  PF={r["pf"]:5.2f}  hit5R={r["wins"]}/{r["n"]}={r["wins"]/r["n"]*100:.1f}%')

    print('\n--- Same post-veto, BUT split into slice vs rest ---')
    slice_pv = slice_[slice_.veto_any==0]
    rest_pv  = rest[rest.veto_any==0]
    for tier_lo, tier_lbl in [(0,'ALL'),(2,'2+'),(4,'4+')]:
        sl_sub = slice_pv[slice_pv.confluence_count>=tier_lo]
        rs_sub = rest_pv [rest_pv .confluence_count>=tier_lo]
        for nm, sub in [('slice', sl_sub), ('rest ', rs_sub)]:
            r = runner_sim(sub, 5.0, 0.0)
            if not r or r["n"]==0: continue
            print(f'  {nm} tier {tier_lbl:3s}: n={r["n"]:3d}  avg_R={r["avg_r"]:+.3f}  PF={r["pf"]:5.2f}  hit5R={r["wins"]}/{r["n"]}={r["wins"]/max(r["n"],1)*100:.1f}%')

if __name__ == '__main__':
    main()
