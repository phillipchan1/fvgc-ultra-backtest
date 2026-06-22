#!/usr/bin/env python3
"""
1m FVGC short — full validation mirroring the 30s opening-FVG study.

  - Headline + IS/OOS split
  - Year-by-year
  - 1m opening-slice: FVG created at 9:31 (involves the 9:30 1m candle)
       broader slice:  FVG created at 9:31 or 9:32
  - Slice vs rest within 1m M1
  - Same-day overlap with 30s slice — do they coincide or complement?
  - Runner sim
  - Pre-market vol_score interaction

Run from repo root:
  python studies/fvgc_plays_off_930_candle/run_1m_deep.py
"""

import sys
from datetime import time as dtime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
TRADES_1M = ROOT / 'studies' / 'baseline_1m' / 'results' / 'trades.csv'
TRADES_30S = ROOT / 'logs' / 'baseline_trades.csv'
DAYS_PATH  = ROOT / 'data' / 'trading_days' / 'trading_days.csv'

IS_END = pd.Timestamp('2024-01-01')


def stats(df):
    if len(df)==0: return dict(n=0)
    w=(df['outcome']=='win').sum(); l=(df['outcome']=='loss').sum()
    pnl = pd.to_numeric(df['pnl'], errors='coerce'); sl = pd.to_numeric(df['sl_dist'], errors='coerce')
    r = pnl/sl
    gw=pnl[pnl>0].sum(); gl=-pnl[pnl<0].sum()
    pf = (gw/gl) if gl>0 else float('inf')
    return dict(n=len(df), wins=int(w), losses=int(l),
                wr=w/(w+l)*100 if (w+l) else float('nan'),
                pf=pf, exp_r=float(r.mean()))


def fmt(label, s):
    if not s or s.get('n',0)==0: return f'  {label:55s}  n=0'
    return (f'  {label:55s}  n={s["n"]:4d}  W={s["wins"]:3d} L={s["losses"]:3d}  '
            f'WR={s["wr"]:5.1f}%  PF={s["pf"]:5.2f}  exp={s["exp_r"]:+.3f}R')


def runner_sim(df, target_R, be_after_R):
    s = df[df['outcome'].isin(['win','loss'])].copy()
    if s.empty: return {}
    tcol = f'hit_{int(target_R)}_0R' if target_R==int(target_R) else f'hit_{int(target_R)}_5R'
    if tcol not in s.columns: return {}
    bcol = None
    if be_after_R > 0:
        bcol = f'hit_{int(be_after_R)}_0R' if be_after_R==int(be_after_R) else f'hit_{int(be_after_R)}_5R'
    def tr(row):
        if bool(row[tcol]): return float(target_R)
        if bcol is not None and bool(row[bcol]): return 0.0
        return -1.0
    s['r'] = s.apply(tr, axis=1)
    w=int((s['r']>0).sum()); l=int((s['r']<0).sum()); b=int((s['r']==0).sum())
    gw=s['r'][s['r']>0].sum(); gl=-s['r'][s['r']<0].sum()
    pf=(gw/gl) if gl>0 else float('inf')
    return dict(n=len(s), wins=w, losses=l, bes=b, avg_r=float(s['r'].mean()), pf=pf)


def main():
    print('='*100); print('1m M1 SHORT — full validation (8yr ES)'); print('='*100)

    t = pd.read_csv(TRADES_1M)
    t['timestamp'] = pd.to_datetime(t['timestamp'])
    t['fvg_created_at'] = pd.to_datetime(t['fvg_created_at'], errors='coerce')
    t['date'] = t['timestamp'].dt.normalize()
    t['entry_time'] = t['timestamp'].dt.time
    t['fvg_t'] = t['fvg_created_at'].dt.time

    m1 = t[(t['direction']=='short') & (t['entry_time']>=dtime(9,30)) & (t['entry_time']<dtime(9,45))
           & (t['variant']!='protected_swing') & t['outcome'].isin(['win','loss'])].copy()
    # 1m opening slice: FVG completed at 9:31 (involves the 9:30 candle)
    m1['slice_tight']  = m1['fvg_t'] == dtime(9,31)
    # broader slice: 9:31 or 9:32 (also includes FVGs centered on 9:31 candle)
    m1['slice_broad']  = m1['fvg_t'].isin([dtime(9,31), dtime(9,32)])

    print(f'\nTotal 1m M1 short (no PS): n={len(m1)}')
    print(f'  variants: {m1.variant.value_counts().to_dict()}')

    print(fmt('  All',                        stats(m1)))
    print(fmt('  Slice TIGHT (fvg @ 9:31)',   stats(m1[m1.slice_tight])))
    print(fmt('  Slice BROAD (fvg 9:31-9:32)',stats(m1[m1.slice_broad])))
    print(fmt('  Rest (broad)',               stats(m1[~m1.slice_broad])))

    # IS / OOS
    is_ = m1[m1['timestamp'] < IS_END]
    oos = m1[m1['timestamp'] >= IS_END]
    print(f'\n-- IS (< {IS_END.date()}) --')
    print(fmt('  All',                        stats(is_)))
    print(fmt('  Slice TIGHT',                stats(is_[is_.slice_tight])))
    print(fmt('  Slice BROAD',                stats(is_[is_.slice_broad])))
    print(fmt('  Rest (broad)',               stats(is_[~is_.slice_broad])))
    print(f'\n-- OOS (>= {IS_END.date()}) --')
    print(fmt('  All',                        stats(oos)))
    print(fmt('  Slice TIGHT',                stats(oos[oos.slice_tight])))
    print(fmt('  Slice BROAD',                stats(oos[oos.slice_broad])))
    print(fmt('  Rest (broad)',               stats(oos[~oos.slice_broad])))

    # Year-by-year (slice broad)
    print('\n-- Year-by-year SLICE BROAD (1m, fvg @ 9:31-9:32) --')
    m1['year'] = m1['timestamp'].dt.year
    for y, g in m1[m1.slice_broad].groupby('year'):
        print(fmt(f'  {y}', stats(g)))

    # Overlap with 30s slice — same day, same direction
    print('\n' + '='*100); print('Overlap with 30s opening-FVG slice'); print('='*100)
    t30 = pd.read_csv(TRADES_30S)
    t30['timestamp'] = pd.to_datetime(t30['timestamp'])
    t30['fvg_created_at'] = pd.to_datetime(t30['fvg_created_at'], errors='coerce')
    t30['date'] = t30['timestamp'].dt.normalize()
    t30['entry_time'] = t30['timestamp'].dt.time
    t30['fvg_t'] = t30['fvg_created_at'].dt.time
    t30_slice_dates = set(t30[(t30.direction=='short')
                              & (t30.entry_time>=dtime(9,30)) & (t30.entry_time<dtime(9,45))
                              & (t30.variant!='protected_swing')
                              & t30.outcome.isin(['win','loss'])
                              & t30.fvg_t.between(dtime(9,29,30), dtime(9,31,0))
                              & t30.fvg_t.notna()]['date'])

    m1['day_has_30s_slice'] = m1['date'].isin(t30_slice_dates)
    print(f'\nDays w/ 30s slice trade (no-PS): {len(t30_slice_dates)}')
    print(f'1m M1 trades on those days: {m1.day_has_30s_slice.sum()}')

    # 1m slice trades — how many days OVERLAP with 30s slice days?
    sl1m_b = m1[m1.slice_broad]
    sl1m_dates = set(sl1m_b['date'])
    overlap = sl1m_dates & t30_slice_dates
    print(f'1m slice trade-days: {len(sl1m_dates)}')
    print(f'  also a 30s-slice day: {len(overlap)} ({len(overlap)/max(len(sl1m_dates),1)*100:.1f}%)')
    print(f'  NEW dump days (1m caught, 30s missed): {len(sl1m_dates - t30_slice_dates)}')

    # On 1m-slice days that 30s slice DIDN'T fire — what's the trade outcome?
    print(fmt('  1m slice on days WITHOUT 30s slice (new captures)',
              stats(sl1m_b[~sl1m_b.day_has_30s_slice])))
    print(fmt('  1m slice on days WITH 30s slice (redundant)',
              stats(sl1m_b[sl1m_b.day_has_30s_slice])))

    # Runner sim on 1m slice broad
    print('\n' + '='*100); print('Runner sim on 1m slice BROAD'); print('='*100)
    print(f'  {"strategy":40s}    n  W   L  BE  avg_R    PF')
    for tgt, be in [(1.0,0.0),(1.5,1.0),(2.0,1.0),(3.0,1.0),(5.0,1.0),(5.0,0.0)]:
        r = runner_sim(sl1m_b, tgt, be)
        if not r: continue
        lbl = f'TP {tgt}R no BE' if be==0 else f'TP {tgt}R + BE@{int(be)}R'
        print(f'  {lbl:40s}  {r["n"]:3d} {r["wins"]:3d} {r["losses"]:3d} {r["bes"]:3d}  '
              f'{r["avg_r"]:+.3f}  {r["pf"]:5.2f}')

    # vol_score interaction
    print('\n' + '='*100); print('vol_score interaction on 1m slice BROAD'); print('='*100)
    d = pd.read_csv(DAYS_PATH); d['date']=pd.to_datetime(d['date'])
    d = d.sort_values('date').reset_index(drop=True)
    d['gap_abs']=d['gap_from_prior_close'].abs()
    d['gap_q75']=d['gap_abs'].rolling(90,min_periods=30).quantile(0.75)
    d['on_q75']=d['overnight_range'].rolling(90,min_periods=30).quantile(0.75)
    d['pd_q75']=d['prior_day_range'].rolling(90,min_periods=30).quantile(0.75)
    d['vol_score']=((d['overnight_range']>=d['on_q75']).astype(int)
                    +(d['prior_day_range']>=d['pd_q75']).astype(int)
                    +(d['gap_abs']>=d['gap_q75']).astype(int))
    sl1m_b = sl1m_b.merge(d[['date','vol_score']], on='date', how='left')
    for s in [0,1,2,3]:
        sub = sl1m_b[sl1m_b.vol_score==s]
        print(fmt(f'  vol_score={s}', stats(sub)))

    OUT = Path(__file__).resolve().parent / 'results'
    OUT.mkdir(exist_ok=True)
    sl1m_b.to_csv(OUT/'trades_1m_slice_broad.csv', index=False)
    print(f'\nWrote {OUT/"trades_1m_slice_broad.csv"} ({len(sl1m_b)} rows)')


if __name__ == '__main__':
    main()
