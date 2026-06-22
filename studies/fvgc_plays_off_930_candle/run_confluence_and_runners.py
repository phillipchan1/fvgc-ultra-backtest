#!/usr/bin/env python3
"""
Three questions on the Opening-FVG short cohort (8yr ES):

  Q1. Do the 7 M1-short confluences add edge here?
  Q2. Is this a play by itself, or just a slice of M1?
  Q3. What runner strategy would actually capture the edge?

Run from repo root:
  python studies/fvgc_plays_off_930_candle/run_confluence_and_runners.py
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


# -----------------------------------------------------------------------------
# M1 confluence factors (replicated from m1_short_8yr_validation)
# -----------------------------------------------------------------------------

def compute_per_day_factors(d: pd.DataFrame) -> pd.DataFrame:
    d = d.sort_values('date').reset_index(drop=True).copy()
    d['vixy_q25_90'] = d['vixy_prior_close'].rolling(90, min_periods=30).quantile(0.25)
    d['vixy_q75_90'] = d['vixy_prior_close'].rolling(90, min_periods=30).quantile(0.75)
    d['c930_body_q75_90'] = d['candle_930_body'].rolling(90, min_periods=30).quantile(0.75)
    d['or5_q75_90'] = d['or_5min_range'].rolling(90, min_periods=30).quantile(0.75)

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

    # OR5 top-quartile — the strong fire-rate predictor from M1 8yr study
    d['c_or5_top_q']   = (d['or_5min_range'] >= d['or5_q75_90']).astype(int)
    return d


# -----------------------------------------------------------------------------
# Stats helpers
# -----------------------------------------------------------------------------

def stats(df: pd.DataFrame) -> dict:
    s = df[df['outcome'].isin(['win','loss'])]
    if s.empty:
        return dict(n=0)
    wins = int((s['outcome']=='win').sum())
    losses = int((s['outcome']=='loss').sum())
    pnl = pd.to_numeric(s['pnl'], errors='coerce')
    sl = pd.to_numeric(s['sl_dist'], errors='coerce')
    r = pnl / sl
    gw = pnl[pnl>0].sum(); gl = -pnl[pnl<0].sum()
    pf = (gw/gl) if gl>0 else float('inf')
    return dict(
        n=len(s), wins=wins, losses=losses,
        wr=wins/(wins+losses)*100 if wins+losses else float('nan'),
        pf=pf, exp_r=float(r.mean()),
    )

def fmt(label, s):
    if not s or s.get('n',0)==0:
        return f'  {label:55s}  n=0'
    return (f'  {label:55s}  n={s["n"]:4d}  W={s["wins"]:3d} L={s["losses"]:3d}  '
            f'WR={s["wr"]:5.1f}%  PF={s["pf"]:5.2f}  exp={s["exp_r"]:+.3f}R')


# -----------------------------------------------------------------------------
# Q3: runner backtest using hit_X_R columns (causal — they reflect MFE)
# -----------------------------------------------------------------------------

def simulate_runner(df: pd.DataFrame, target_R: float, be_after_R: float) -> dict:
    """
    For each trade, decide outcome under: stop initially at 1R, move to BE after
    `be_after_R` is hit (entry-level), TP at `target_R`.

    Approximation: we only know whether each R-bucket was hit, not the order.
    A trade gets full target_R R if hit_{target_R} == True.
    If hit_1R but not target_R: trade reaches at least 1R (which moves stop to BE)
      then we treat the eventual outcome as 0R (BE).
    If !hit_1R and was a 'win' (orig 1R TP): that's structurally impossible.
    If !hit_1R and was 'loss': -1R (full stop loss).

    This is the 'breakeven runner' baseline used in M1 study.
    """
    s = df[df['outcome'].isin(['win','loss'])].copy()
    n = len(s)
    if n==0: return {}
    # determine target hit column
    tcol = f'hit_{target_R:.1f}R'.replace('.0R','_0R').replace('.5R','_5R')
    tcol = f'hit_{int(target_R)}_0R' if target_R==int(target_R) else f'hit_{int(target_R)}_5R'
    if tcol not in s.columns:
        return {}
    bcol = f'hit_{int(be_after_R)}_0R' if be_after_R==int(be_after_R) else f'hit_{int(be_after_R)}_5R'

    def trade_r(row):
        hit_target = bool(row[tcol])
        hit_be     = bool(row[bcol]) if bcol in row.index else False
        if hit_target:
            return float(target_R)
        if hit_be:
            return 0.0           # ran to BE then chopped
        # didn't reach BE level — full stop
        return -1.0

    s['r'] = s.apply(trade_r, axis=1)
    wins = int((s['r'] > 0).sum())
    losses = int((s['r'] < 0).sum())
    bes = int((s['r'] == 0).sum())
    avg_r = s['r'].mean()
    gw = s['r'][s['r']>0].sum(); gl = -s['r'][s['r']<0].sum()
    pf = (gw/gl) if gl>0 else float('inf')
    return dict(n=n, wins=wins, losses=losses, bes=bes,
                wr_excl_be=wins/(wins+losses)*100 if (wins+losses) else float('nan'),
                avg_r=float(avg_r), pf=pf)


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

def main():
    print('='*100)
    print('Opening-FVG SHORTS — confluence stacking + standalone test + runner sim (8yr ES)')
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

    # Build cohorts
    base = t[t['outcome'].isin(['win','loss'])].copy()
    open_short = base[(base['direction']=='short') & base['in_open_win']].copy()
    print(f'\nOpening-FVG SHORTS (all variants): n={len(open_short)}')
    print(f'  variants: {open_short.variant.value_counts().to_dict()}')

    # M1 cohort: short, entry 9:30-9:45, exclude PS (to match M1 study)
    m1_short = base[(base['direction']=='short')
                    & (base['entry_time']>=dtime(9,30)) & (base['entry_time']<dtime(9,45))
                    & (base['variant']!='protected_swing')].copy()
    print(f'M1 SHORTS (entry <9:45, no PS):         n={len(m1_short)}')

    # Load per-day factors
    days = pd.read_csv(DAYS_PATH)
    days['date'] = pd.to_datetime(days['date'])
    days = compute_per_day_factors(days)
    factor_cols = ['date','confluence_count','veto_any',
                   'c_gap_large_down','c_prior_day_weak','c_is_fomc_week','c_vixy_high',
                   'c_dow_friday','c_bear_930','c_c930_body_top_q','c_or5_top_q']

    open_short = open_short.merge(days[factor_cols], on='date', how='left')
    m1_short   = m1_short.merge(days[factor_cols], on='date', how='left')

    # ------------------------------------------------------------------
    # Q1. Do M1 confluences add edge to opening-FVG shorts?
    # ------------------------------------------------------------------
    print('\n' + '='*100)
    print('Q1. M1 confluence stack on Opening-FVG SHORTS')
    print('='*100)
    print('\n-- Opening-FVG shorts (all variants) by confluence tier --')
    for lo, hi, lbl in [(0,1,'0-1'), (2,2,'2'), (3,3,'3'), (4,7,'4+'), (2,7,'2+')]:
        sub = open_short[(open_short.confluence_count>=lo) & (open_short.confluence_count<=hi)]
        print(fmt(f'tier {lbl}', stats(sub)))

    print('\n-- Opening-FVG shorts NO-PS (apples to apples with M1) by tier --')
    ops_nops = open_short[open_short.variant!='protected_swing']
    for lo, hi, lbl in [(0,1,'0-1'), (2,2,'2'), (3,3,'3'), (4,7,'4+'), (2,7,'2+')]:
        sub = ops_nops[(ops_nops.confluence_count>=lo) & (ops_nops.confluence_count<=hi)]
        print(fmt(f'tier {lbl}', stats(sub)))

    print('\n-- Per-factor lift (Opening-FVG shorts NO-PS, factor ON vs OFF) --')
    factor_names = ['c_gap_large_down','c_prior_day_weak','c_is_fomc_week','c_vixy_high',
                    'c_dow_friday','c_bear_930','c_c930_body_top_q','c_or5_top_q']
    rows = []
    for f in factor_names:
        on = ops_nops[ops_nops[f]==1]; off = ops_nops[ops_nops[f]==0]
        son, soff = stats(on), stats(off)
        rows.append({
            'factor': f.replace('c_',''),
            'n_on': son.get('n',0),  'wr_on':  son.get('wr',float('nan')),
            'pf_on': son.get('pf',float('nan')),
            'n_off': soff.get('n',0),'wr_off': soff.get('wr',float('nan')),
            'pf_off': soff.get('pf',float('nan')),
        })
    lift = pd.DataFrame(rows)
    lift['lift_wr_pp'] = lift['wr_on'] - lift['wr_off']
    lift = lift.sort_values('lift_wr_pp', ascending=False)
    with pd.option_context('display.width', 200, 'display.max_columns', 20,
                            'display.float_format', '{:.1f}'.format):
        print(lift.to_string(index=False))

    # ------------------------------------------------------------------
    # Q2. Opening-FVG slice vs the rest of M1 — is this a distinct play?
    # ------------------------------------------------------------------
    print('\n' + '='*100)
    print('Q2. Opening-FVG slice vs the REST of M1 shorts')
    print('='*100)
    m1_short['is_open_fvg'] = m1_short['fvg_t'].between(WIN_START, WIN_END) & m1_short['fvg_created_ny'].notna()
    in_slice  = m1_short[m1_short.is_open_fvg]
    out_slice = m1_short[~m1_short.is_open_fvg]
    print(fmt('M1 short ∩ Opening-FVG  (the slice)', stats(in_slice)))
    print(fmt('M1 short \\ Opening-FVG (the rest)', stats(out_slice)))
    print(fmt('All M1 short (union)',                stats(m1_short)))

    # Tiered comparison
    print('\n-- Tier stratification: slice vs rest --')
    for lo, hi, lbl in [(0,1,'0-1'), (2,2,'2'), (3,7,'3+'), (2,7,'2+')]:
        a = in_slice [(in_slice .confluence_count>=lo) & (in_slice .confluence_count<=hi)]
        b = out_slice[(out_slice.confluence_count>=lo) & (out_slice.confluence_count<=hi)]
        print(fmt(f'slice tier {lbl}', stats(a)))
        print(fmt(f'rest  tier {lbl}', stats(b)))

    # ------------------------------------------------------------------
    # Q3. Runner / risk-management sim on opening-FVG shorts
    # ------------------------------------------------------------------
    print('\n' + '='*100)
    print('Q3. Runner / exit strategies on Opening-FVG SHORTS (no PS)')
    print('='*100)
    # MFE distribution on winners
    wn = ops_nops[ops_nops.outcome=='win'].copy()
    print(f'\n--- MFE distribution among winners (n={len(wn)}) ---')
    for col, lbl in [('hit_1_0R','1R'),('hit_1_5R','1.5R'),('hit_2_0R','2R'),
                     ('hit_2_5R','2.5R'),('hit_3_0R','3R'),('hit_4_0R','4R'),
                     ('hit_5_0R','5R')]:
        if col in ops_nops.columns:
            n_all = ops_nops[col].sum()
            pct_all = n_all / len(ops_nops) * 100
            print(f'  hit {lbl:4s}: {int(n_all):3d}/{len(ops_nops)} = {pct_all:5.1f}% of ALL trades reach this level')

    print('\n--- Exit strategy sim (per-trade avg R, PF, hit rates) ---')
    print(f'  {"strategy":40s}    n  W   L  BE  avg_R    PF')
    for target, be in [(1.0, 0.0), (1.5, 1.0), (2.0, 1.0), (2.5, 1.0),
                       (3.0, 1.0), (4.0, 1.0), (5.0, 1.0)]:
        r = simulate_runner(ops_nops, target, be)
        if not r: continue
        be_str = 'fixed 1R TP' if target==1.0 else f'TP {target}R, BE after {be}R'
        print(f'  {be_str:40s}  {r["n"]:3d} {r["wins"]:3d} {r["losses"]:3d} {r["bes"]:3d}  '
              f'{r["avg_r"]:+.3f}  {r["pf"]:5.2f}')

    # Tier 2+ subset — the "best" cohort under stacking
    print('\n--- Same sim on tier 2+ subset (with M1 confluences) ---')
    cohort_2p = ops_nops[(ops_nops.confluence_count>=2) & (ops_nops.veto_any==0)]
    print(f'  cohort 2+ no-veto: n={len(cohort_2p)}')
    print(f'  {"strategy":40s}    n  W   L  BE  avg_R    PF')
    for target, be in [(1.0, 0.0), (1.5, 1.0), (2.0, 1.0), (2.5, 1.0),
                       (3.0, 1.0), (4.0, 1.0), (5.0, 1.0)]:
        r = simulate_runner(cohort_2p, target, be)
        if not r: continue
        be_str = 'fixed 1R TP' if target==1.0 else f'TP {target}R, BE after {be}R'
        print(f'  {be_str:40s}  {r["n"]:3d} {r["wins"]:3d} {r["losses"]:3d} {r["bes"]:3d}  '
              f'{r["avg_r"]:+.3f}  {r["pf"]:5.2f}')

if __name__ == '__main__':
    main()
