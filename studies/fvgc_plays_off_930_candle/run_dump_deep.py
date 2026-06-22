#!/usr/bin/env python3
"""
Deep dive on the dump-capture framing.

A. Stack the dump predictors  — can we lift dump-day probability to 50-70%
   with combos of [ON_range_high, PD_atr_high, gap_abs_top_q]? On filtered days,
   what's M1 short PF?

B. Multi-TF FVGC dump capture — re-run capture/WR analysis on 15s/1m/2m/3m
   FVGC short signals.

C. Alternative dump-day entry  — short on first 30s bar that closes below the
   9:30 candle low, SL = max(9:30 high, 5min high), targets 1R/2R/3R. Realistic
   bar-by-bar outcome computation (no 'optimistic' bookkeeping).
"""

import sys
from datetime import time as dtime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
DAYS_PATH = ROOT / 'data' / 'trading_days' / 'trading_days.csv'
DATA_30S  = ROOT / 'data' / 'consolidated' / 'es-front-month.ohlcv-30s.parquet'

TF_TRADE_PATHS = {
    '15s': ROOT / 'studies' / 'baseline_15s' / 'results' / 'trades.csv',
    '30s': ROOT / 'logs' / 'baseline_trades.csv',          # canonical 30s
    '1m':  ROOT / 'studies' / 'baseline_1m'  / 'results' / 'trades.csv',
    '2m':  ROOT / 'studies' / 'baseline_2m'  / 'results' / 'trades.csv',
    '3m':  ROOT / 'studies' / 'baseline_3m'  / 'results' / 'trades.csv',
}


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


# ============================================================================
# A. Stack dump predictors
# ============================================================================

def section_a():
    print('='*100); print('A. Stack the dump predictors'); print('='*100)
    d = pd.read_csv(DAYS_PATH)
    d['date'] = pd.to_datetime(d['date'])
    d = d.sort_values('date').reset_index(drop=True)

    d['dump_15m'] = d['rth_open'] - d['or_15min_low']
    d['dump_15m_q75'] = d['dump_15m'].rolling(90, min_periods=30).quantile(0.75)
    d['gap_abs'] = d['gap_from_prior_close'].abs()
    d['gap_q75'] = d['gap_abs'].rolling(90, min_periods=30).quantile(0.75)
    d['on_q75']  = d['overnight_range'].rolling(90, min_periods=30).quantile(0.75)
    d['pd_q75']  = d['prior_day_range'].rolling(90, min_periods=30).quantile(0.75)

    d['v_on']  = d['overnight_range'] >= d['on_q75']
    d['v_pd']  = d['prior_day_range']  >= d['pd_q75']
    d['v_gap'] = d['gap_abs']          >= d['gap_q75']
    d['vol_score'] = d['v_on'].astype(int) + d['v_pd'].astype(int) + d['v_gap'].astype(int)
    d['is_dump'] = d['dump_15m'] >= d['dump_15m_q75']
    valid = d.dropna(subset=['dump_15m_q75','on_q75','pd_q75','gap_q75'])

    print(f'\nBase rate top-25% dump: {valid["is_dump"].mean()*100:.1f}%')
    print(f'{"vol_score":12s}  n_days  dump_rate  pct_of_days')
    for s in [0,1,2,3]:
        sub = valid[valid['vol_score']==s]
        if len(sub)==0: continue
        print(f'  score={s}    {len(sub):4d}    {sub["is_dump"].mean()*100:5.1f}%    {len(sub)/len(valid)*100:5.1f}%')

    print('\n--- pairwise (which 2-factor combos work best) ---')
    pairs = [('v_on','v_pd'), ('v_on','v_gap'), ('v_pd','v_gap')]
    for a,b in pairs:
        sub = valid[valid[a] & valid[b]]
        print(f'  {a} & {b}: n={len(sub):4d}  dump_rate={sub["is_dump"].mean()*100:5.1f}%  '
              f'(coverage {len(sub)/len(valid)*100:.1f}% of days)')

    # M1 short outcomes by vol_score
    print('\n--- M1 short outcomes by pre-market vol_score (no PS) ---')
    t = pd.read_csv(ROOT / 'logs' / 'baseline_trades.csv')
    t['timestamp'] = pd.to_datetime(t['timestamp'])
    t['date'] = t['timestamp'].dt.normalize()
    t['entry_time'] = t['timestamp'].dt.time
    m1 = t[(t['direction']=='short') & (t['entry_time']>=dtime(9,30)) & (t['entry_time']<dtime(9,45))
           & (t['variant']!='protected_swing') & t['outcome'].isin(['win','loss'])].copy()
    m1 = m1.merge(d[['date','vol_score','is_dump']], on='date', how='left')
    for s in sorted(m1['vol_score'].dropna().unique()):
        sub = m1[m1['vol_score']==s]
        print(fmt(f'  vol_score={int(s)}', stats(sub)))
    print(fmt('  vol_score >= 2', stats(m1[m1['vol_score']>=2])))
    print(fmt('  vol_score >= 3', stats(m1[m1['vol_score']>=3])))

    # Multi-TF dump-capture preview (uses 30s only for now)
    return d


# ============================================================================
# B. Multi-TF FVGC dump capture
# ============================================================================

def section_b(d):
    print('\n' + '='*100); print('B. Multi-TF FVGC dump capture'); print('='*100)

    d['dump_15m_q75'] = d['dump_15m'].rolling(90, min_periods=30).quantile(0.75)
    d['dump_15m_q90'] = d['dump_15m'].rolling(90, min_periods=30).quantile(0.90)
    days_top25 = set(d[d['dump_15m'] >= d['dump_15m_q75']]['date'].dt.normalize())
    days_top10 = set(d[d['dump_15m'] >= d['dump_15m_q90']]['date'].dt.normalize())

    print(f'\nTop-25% dump days: {len(days_top25)}  |  Top-10%: {len(days_top10)}')
    print(f'\n{"TF":4s}  {"n shorts":>8s}  {"WR%":>5s}  {"PF":>5s}  '
          f'{"top25 fired":>11s}  {"capture%":>9s}  {"WR on top25":>11s}  '
          f'{"top10 fired":>11s}  {"WR on top10":>11s}')
    for tf, path in TF_TRADE_PATHS.items():
        if not path.exists(): continue
        t = pd.read_csv(path)
        t['timestamp'] = pd.to_datetime(t['timestamp'])
        t['date'] = t['timestamp'].dt.normalize()
        t['entry_time'] = t['timestamp'].dt.time
        sh = t[(t['direction']=='short') & (t['entry_time']>=dtime(9,30)) & (t['entry_time']<dtime(9,45))
               & (t['variant']!='protected_swing') & t['outcome'].isin(['win','loss'])].copy()
        if len(sh)==0: continue
        base = stats(sh)
        # Days the TF fired on
        fire_days = set(sh['date'])
        cap25_fired = len(fire_days & days_top25)
        cap10_fired = len(fire_days & days_top10)
        cap25_pct = cap25_fired / max(len(days_top25),1) * 100
        cap10_pct = cap10_fired / max(len(days_top10),1) * 100
        # WR on top25/top10
        sh25 = sh[sh['date'].isin(days_top25)]
        sh10 = sh[sh['date'].isin(days_top10)]
        s25 = stats(sh25); s10 = stats(sh10)
        print(f'  {tf:4s}  {base["n"]:8d}  {base["wr"]:5.1f}  {base["pf"]:5.2f}     '
              f'{cap25_fired:4d}({cap25_pct:4.1f}%)   {cap25_pct:5.1f}%   {s25["wr"]:5.1f}% PF{s25["pf"]:4.1f} (n={s25["n"]:3d})  '
              f'{cap10_fired:4d}({cap10_pct:4.1f}%)   {s10["wr"]:5.1f}% PF{s10["pf"]:4.1f} (n={s10["n"]:3d})')

    # Combined: union of TFs — does stacking 30s + 1m + 2m + 3m capture more?
    print('\n--- Cumulative day-coverage by stacking timeframes ---')
    cum_fire_days = set()
    for tf in ['30s','1m','2m','3m']:
        path = TF_TRADE_PATHS[tf]
        if not path.exists(): continue
        tt = pd.read_csv(path)
        tt['timestamp'] = pd.to_datetime(tt['timestamp'])
        tt['date'] = tt['timestamp'].dt.normalize()
        tt['entry_time'] = tt['timestamp'].dt.time
        sh = tt[(tt['direction']=='short') & (tt['entry_time']>=dtime(9,30)) & (tt['entry_time']<dtime(9,45))
                & (tt['variant']!='protected_swing') & tt['outcome'].isin(['win','loss'])]
        cum_fire_days |= set(sh['date'])
        cap25 = len(cum_fire_days & days_top25); cap10 = len(cum_fire_days & days_top10)
        print(f'  +{tf}: cum fire-days={len(cum_fire_days):4d}  '
              f'top25 cap={cap25}/{len(days_top25)}={cap25/max(len(days_top25),1)*100:.1f}%  '
              f'top10 cap={cap10}/{len(days_top10)}={cap10/max(len(days_top10),1)*100:.1f}%')


# ============================================================================
# C. Alternative dump-day entry (proper SL, bar-by-bar)
# ============================================================================

def section_c(d):
    print('\n' + '='*100); print('C. Alternative dump-day entry — bar-by-bar simulation'); print('='*100)
    print('\nRule: short on first 30s bar after 9:30:30 that CLOSES below 9:30 low.')
    print('  SL = 9:30 high. Targets: 1R / 2R / 3R. 15-min window. Bar-by-bar (real ordering).')
    if 'dump_15m_q90' not in d.columns:
        d['dump_15m_q90'] = d['dump_15m'].rolling(90, min_periods=30).quantile(0.90)

    cand = pd.read_parquet(DATA_30S, columns=['timestamp_ny','open','high','low','close'])
    cand['timestamp_ny'] = pd.to_datetime(cand['timestamp_ny'])
    cand['date'] = cand['timestamp_ny'].dt.normalize().dt.tz_localize(None)
    cand['t'] = cand['timestamp_ny'].dt.time

    # Build per-day 9:30 candle stats + window bars
    c930 = cand[cand['t']==dtime(9,30,0)][['date','high','low','close']].rename(
        columns={'high':'c930_high','low':'c930_low','close':'c930_close'})
    c930 = c930.groupby('date').first().reset_index()

    win = cand[(cand['t']>=dtime(9,30,30)) & (cand['t']<dtime(9,45,0))].copy()

    # Merge dump info onto window bars
    d['date_norm'] = d['date'].dt.normalize()
    dinfo = d[['date_norm','dump_15m','dump_15m_q75','dump_15m_q90','vol_score']].rename(
        columns={'date_norm':'date'})
    win = win.merge(c930, on='date', how='inner').merge(dinfo, on='date', how='inner')
    win = win.sort_values(['date','timestamp_ny']).reset_index(drop=True)

    # Per-day, walk bars and find first one closing < c930_low
    print('\nSimulating bar-by-bar...')
    rows = []
    for date, g in win.groupby('date'):
        bars = g.reset_index(drop=True)
        c930_h = bars['c930_high'].iloc[0]
        c930_l = bars['c930_low'].iloc[0]
        dump   = bars['dump_15m'].iloc[0]
        vscore = bars['vol_score'].iloc[0] if not pd.isna(bars['vol_score'].iloc[0]) else 0
        # find first bar with close < c930_low
        trig_mask = bars['close'] < c930_l
        if not trig_mask.any():
            rows.append(dict(date=date, fired=False, dump_15m=dump, vol_score=vscore))
            continue
        trig_idx = trig_mask.idxmax()
        trig_row = bars.iloc[trig_idx]
        entry = trig_row['close']
        sl    = c930_h
        sl_dist = sl - entry
        if sl_dist <= 0:
            rows.append(dict(date=date, fired=False, dump_15m=dump, vol_score=vscore))
            continue
        # Walk remaining bars: check sl hit (high >= sl) or tp hit (low <= entry - k*sl_dist) per bar
        # Resolve same-bar SL-and-TP conservatively: assume SL hit first (pessimistic).
        outcomes = {'1R': None, '2R': None, '3R': None, '5R': None}
        for k_label, k in [('1R',1),('2R',2),('3R',3),('5R',5)]:
            tp = entry - k * sl_dist
            for j in range(trig_idx, len(bars)):
                bh = bars['high'].iloc[j]; bl = bars['low'].iloc[j]
                sl_hit = bh >= sl
                tp_hit = bl <= tp
                if sl_hit and tp_hit:
                    outcomes[k_label] = 'loss'   # pessimistic
                    break
                if sl_hit:
                    outcomes[k_label] = 'loss'; break
                if tp_hit:
                    outcomes[k_label] = 'win';  break
            if outcomes[k_label] is None:
                outcomes[k_label] = 'open'      # end of window
        rows.append(dict(date=date, fired=True, dump_15m=dump, vol_score=vscore,
                          entry=entry, sl=sl, sl_dist=sl_dist,
                          o_1R=outcomes['1R'], o_2R=outcomes['2R'],
                          o_3R=outcomes['3R'], o_5R=outcomes['5R']))
    res = pd.DataFrame(rows)
    fired = res[res['fired']]
    print(f'  Days simulated: {len(res)}')
    print(f'  Days entry triggered (close < 9:30 low): {len(fired)} ({len(fired)/len(res)*100:.1f}%)')

    def tally(df, ocol, k):
        w = (df[ocol]=='win').sum(); l=(df[ocol]=='loss').sum(); o=(df[ocol]=='open').sum()
        n = len(df)
        avg_r = (w*k - l) / n if n else float('nan')
        wr = w/(w+l)*100 if (w+l) else float('nan')
        return n, w, l, o, wr, avg_r

    print(f'\n  -- All triggered days (n={len(fired)}) --')
    for ocol,k in [('o_1R',1),('o_2R',2),('o_3R',3),('o_5R',5)]:
        n,w,l,o,wr,ar = tally(fired, ocol, k)
        print(f'    TP={ocol[2:]}: W={w} L={l} open={o}  WR={wr:.1f}%  avg_R={ar:+.3f}')

    for vmin, lbl in [(2,'vol_score≥2'), (3,'vol_score≥3')]:
        sub = fired[fired['vol_score']>=vmin]
        print(f'\n  -- {lbl} triggered days (n={len(sub)}) --')
        for ocol,k in [('o_1R',1),('o_2R',2),('o_3R',3),('o_5R',5)]:
            n,w,l,o,wr,ar = tally(sub, ocol, k)
            print(f'    TP={ocol[2:]}: W={w} L={l} open={o}  WR={wr:.1f}%  avg_R={ar:+.3f}')

    # Top-25% dump days SUBSET (in-session knowledge — counterfactual upper bound)
    top = fired[fired['dump_15m'] >= 50]  # rough top-25% threshold from earlier
    print(f'\n  -- Days where actual dump_15m >= 50pt (n={len(top)}) [post-hoc top-25% identification] --')
    for ocol,k in [('o_1R',1),('o_2R',2),('o_3R',3),('o_5R',5)]:
        n,w,l,o,wr,ar = tally(top, ocol, k)
        print(f'    TP={ocol[2:]}: W={w} L={l} open={o}  WR={wr:.1f}%  avg_R={ar:+.3f}')

    OUT = Path(__file__).resolve().parent / 'results'
    OUT.mkdir(exist_ok=True)
    res.to_csv(OUT/'dump_alt_entry.csv', index=False)
    print(f'\nWrote {OUT/"dump_alt_entry.csv"} ({len(res)} rows)')


def main():
    d = section_a()
    section_b(d)
    section_c(d)


if __name__ == '__main__':
    main()
