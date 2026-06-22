#!/usr/bin/env python3
"""
Reframe the M1 short question: instead of "which FVGCs win",
ask "when does the market DUMP in the first 15 min, and does FVGC catch it?"

Phase 1 — Characterize the dump:
  - dump_15m_pts = rth_open - or_15min_low  (max drawdown from 9:30 open by 9:45)
  - dump_5m_pts  = rth_open - or_5min_low   (max drawdown by 9:35)
  - Quartile + ATR-normalized distributions

Phase 2 — Did FVGC catch the dumps?
  - For each top-quartile dump day: did any M1 short FVGC fire in 9:30-9:45?
  - Hit rate, win rate, MFE captured vs total dump magnitude
  - Bottom-quartile (no-dump) days: false-positive rate of FVGC shorts

Phase 3 — Pre-market predictors of dump days:
  - Single-factor lift analysis on pre-market features
  - Which combos identify the dump day pre-market?

Phase 4 — Counterfactual: simple-entry hit rate on dump days vs FVGC
  - Short at 9:30:30 close (after first 30s bar) with SL = 9:30 high, target 1R
  - Compare WR/EV vs the FVGC fires

Run from repo root:
  python studies/fvgc_plays_off_930_candle/run_dump_capture.py
"""

import sys
from datetime import time as dtime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

TRADES_PATH = ROOT / 'logs' / 'baseline_trades.csv'
DAYS_PATH   = ROOT / 'data' / 'trading_days' / 'trading_days.csv'
DATA_30S    = ROOT / 'data' / 'consolidated' / 'es-front-month.ohlcv-30s.parquet'


def stats(df: pd.DataFrame) -> dict:
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


def main():
    # ---- Load days + compute dump metrics ----
    d = pd.read_csv(DAYS_PATH)
    d['date'] = pd.to_datetime(d['date'])
    d['dump_15m'] = d['rth_open'] - d['or_15min_low']      # >= 0
    d['dump_5m']  = d['rth_open'] - d['or_5min_low']
    # ATR-normalized (use prior_day_range as proxy)
    d['dump_15m_atr'] = d['dump_15m'] / d['prior_day_range'].clip(lower=1)
    # 90-day rolling quartile (causal)
    d = d.sort_values('date').reset_index(drop=True)
    d['dump_15m_q75'] = d['dump_15m'].rolling(90, min_periods=30).quantile(0.75)
    d['dump_15m_q90'] = d['dump_15m'].rolling(90, min_periods=30).quantile(0.90)
    d['dump_15m_q25'] = d['dump_15m'].rolling(90, min_periods=30).quantile(0.25)

    print('='*100)
    print('PHASE 1 — Dump magnitude distribution')
    print('='*100)
    desc = d['dump_15m'].describe(percentiles=[.25,.5,.75,.9,.95,.99])
    print('\nDistribution of dump_15m (rth_open - low[9:30-9:45]):')
    for k in ['count','mean','std','min','25%','50%','75%','90%','95%','99%','max']:
        if k in desc.index: print(f'  {k:>6s}: {desc[k]:8.1f}')

    print('\n--- Dump magnitude by year (median, 75th, 90th pct in pts) ---')
    d['year'] = d['date'].dt.year
    for y, g in d.groupby('year'):
        print(f'  {y}  n={len(g):3d}  med={g.dump_15m.median():6.1f}  p75={g.dump_15m.quantile(.75):6.1f}  '
              f'p90={g.dump_15m.quantile(.90):6.1f}  max={g.dump_15m.max():7.1f}')

    # ---- Pull trades, identify M1 shorts per day ----
    t = pd.read_csv(TRADES_PATH)
    t['timestamp'] = pd.to_datetime(t['timestamp'])
    t['fvg_created_at'] = pd.to_datetime(t['fvg_created_at'], errors='coerce')
    t['date'] = t['timestamp'].dt.normalize()
    t['entry_time'] = t['timestamp'].dt.time
    t['fvg_t'] = t['fvg_created_at'].dt.time

    m1 = t[(t['direction']=='short')
           & (t['entry_time']>=dtime(9,30)) & (t['entry_time']<dtime(9,45))
           & (t['variant']!='protected_swing')
           & t['outcome'].isin(['win','loss'])].copy()
    m1['in_open_win'] = m1['fvg_t'].between(dtime(9,29,30), dtime(9,31,0)) & m1['fvg_t'].notna()
    m1 = m1.merge(d[['date','dump_15m','dump_5m','dump_15m_q75','dump_15m_q90','dump_15m_q25',
                     'or_15min_low','rth_open','prior_day_range']],
                  on='date', how='left')
    m1['day_is_top_dump']  = m1['dump_15m'] >= m1['dump_15m_q75']
    m1['day_is_top10_dump']= m1['dump_15m'] >= m1['dump_15m_q90']
    m1['day_is_no_dump']   = m1['dump_15m'] <= m1['dump_15m_q25']

    print('\n' + '='*100)
    print('PHASE 2 — Does FVGC catch the dumps?')
    print('='*100)

    # First: how many trading days had an M1 short FVGC fire at all
    fire_dates = set(m1['date'].unique())
    d['m1_short_fired'] = d['date'].isin(fire_dates)
    print(f'\nTotal trading days: {len(d)}')
    print(f'Days with at least 1 M1 short FVGC fire: {d["m1_short_fired"].sum()} ({d["m1_short_fired"].sum()/len(d)*100:.1f}%)')

    # By dump-magnitude bucket
    print('\n--- M1 short fire rate by dump-magnitude (90d rolling quartile) ---')
    d['dump_bucket'] = pd.cut(
        d['dump_15m'].rank(pct=True),
        bins=[0,0.25,0.50,0.75,0.90,1.01],
        labels=['Q1 (lowest)','Q2','Q3','Q4 (top25%)','Top10%']
    )
    for buck, g in d.groupby('dump_bucket', observed=True):
        nday = len(g); nfire = g['m1_short_fired'].sum()
        med = g['dump_15m'].median()
        print(f'  {buck!s:15s}  n_days={nday:4d}  fired={nfire:4d} ({nfire/nday*100:5.1f}%)  med_dump={med:5.1f}pt')

    # On top-quartile dump days, what's the M1 short trade outcome?
    print('\n--- M1 short trade outcome by day-level dump bucket (all variants no-PS) ---')
    for buck, g in m1.groupby(pd.cut(
        m1['dump_15m'].rank(pct=True),
        bins=[0,0.25,0.50,0.75,0.90,1.01],
        labels=['Q1','Q2','Q3','Q4','Top10']
    ), observed=True):
        print(fmt(f'  day-dump {buck!s}', stats(g)))

    # Slice-only (opening-FVG)
    print('\n--- SLICE (opening-FVG) outcomes by day-level dump bucket ---')
    sl = m1[m1.in_open_win]
    for buck, g in sl.groupby(pd.cut(
        sl['dump_15m'].rank(pct=True),
        bins=[0,0.25,0.50,0.75,0.90,1.01],
        labels=['Q1','Q2','Q3','Q4','Top10']
    ), observed=True):
        print(fmt(f'  day-dump {buck!s}', stats(g)))

    # Rest (non-slice)
    print('\n--- REST (non-slice) outcomes by day-level dump bucket ---')
    rs = m1[~m1.in_open_win]
    for buck, g in rs.groupby(pd.cut(
        rs['dump_15m'].rank(pct=True),
        bins=[0,0.25,0.50,0.75,0.90,1.01],
        labels=['Q1','Q2','Q3','Q4','Top10']
    ), observed=True):
        print(fmt(f'  day-dump {buck!s}', stats(g)))

    # ---- KEY: among top-quartile dump days, what % had a FIRING M1 short FVGC? ----
    print('\n--- Top-25% dump days: capture rate ---')
    top25 = d[d['dump_15m'] >= d['dump_15m_q75']].dropna(subset=['dump_15m_q75'])
    print(f'  Top-25% dump days (post-warmup): {len(top25)}')
    print(f'  Of those, days with at least 1 M1 short FVGC fire: {top25["m1_short_fired"].sum()} '
          f'({top25["m1_short_fired"].sum()/len(top25)*100:.1f}%)')
    print(f'  Top-10% dump days: {(d["dump_15m"]>=d["dump_15m_q90"]).sum()}, '
          f'fired on {((d["dump_15m"]>=d["dump_15m_q90"]) & d["m1_short_fired"]).sum()}')

    # For top-25% dump days WITHOUT a fire — what was the dump magnitude we missed?
    missed = top25[~top25['m1_short_fired']]
    caught = top25[ top25['m1_short_fired']]
    print(f'\n  Top-25% dump days FVGC missed: n={len(missed)}, '
          f'med dump={missed["dump_15m"].median():.1f}pt, mean={missed["dump_15m"].mean():.1f}pt')
    print(f'  Top-25% dump days FVGC caught: n={len(caught)}, '
          f'med dump={caught["dump_15m"].median():.1f}pt, mean={caught["dump_15m"].mean():.1f}pt')

    # ---- PHASE 3 — Pre-market predictors of top-quartile dump days ----
    print('\n' + '='*100)
    print('PHASE 3 — Pre-market predictors of TOP-25% dump days')
    print('='*100)
    # Use causal features only
    d['vixy_q75_90'] = d['vixy_prior_close'].rolling(90, min_periods=30).quantile(0.75)
    d['vixy_q25_90'] = d['vixy_prior_close'].rolling(90, min_periods=30).quantile(0.25)
    d['gap_abs'] = d['gap_from_prior_close'].abs()
    d['gap_q75_90'] = d['gap_abs'].rolling(90, min_periods=30).quantile(0.75)
    d['on_range_q75_90'] = d['overnight_range'].rolling(90, min_periods=30).quantile(0.75)
    d['pd_range_q75_90'] = d['prior_day_range'].rolling(90, min_periods=30).quantile(0.75)
    d['is_top25_dump'] = d['dump_15m'] >= d['dump_15m_q75']

    features = {
        'gap_large_down (≤-100)':      d['gap_from_prior_close'] <= -100,
        'gap_med_down (-30 to -100)':  (d['gap_from_prior_close'] <= -30) & (d['gap_from_prior_close'] > -100),
        'gap_up (≥+30)':               d['gap_from_prior_close'] >= 30,
        'gap_large_up (≥+100)':        d['gap_from_prior_close'] >= 100,
        'gap_abs top quartile':        d['gap_abs'] >= d['gap_q75_90'],
        'prior_day_weak (≤0.333)':     d['prior_day_close_position'] <= 0.333,
        'prior_day_strong (≥0.667)':   d['prior_day_close_position'] >= 0.667,
        'prior_day_atr_high':          d['prior_day_range'] >= d['pd_range_q75_90'],
        'overnight_range_high':        d['overnight_range'] >= d['on_range_q75_90'],
        'overnight_dir=down':          d['overnight_direction'] == 'down',
        'overnight_dir=up':            d['overnight_direction'] == 'up',
        'vixy_high':                   d['vixy_prior_close'] >= d['vixy_q75_90'],
        'vixy_low':                    d['vixy_prior_close'] <= d['vixy_q25_90'],
        'is_fomc_week':                d['is_fomc_week']==1,
        'is_opex_week':                d['is_opex_week']==1,
        'dow_monday':                  d['day_of_week_name']=='Monday',
        'dow_tuesday':                 d['day_of_week_name']=='Tuesday',
        'dow_wednesday':               d['day_of_week_name']=='Wednesday',
        'dow_thursday':                d['day_of_week_name']=='Thursday',
        'dow_friday':                  d['day_of_week_name']=='Friday',
        'has_pre_rth_news':            d.get('has_pre_rth_news', pd.Series([False]*len(d)))==1,
    }

    dvalid = d.dropna(subset=['dump_15m_q75']).copy()
    base_rate = dvalid['is_top25_dump'].mean()
    print(f'\nBase rate (top-25% dump): {base_rate*100:.1f}%')
    print(f'Valid days (post warmup): {len(dvalid)}\n')

    print(f'  {"feature":35s}  n_on  on_dump%  n_off  off_dump%  lift_pp')
    rows = []
    for name, mask in features.items():
        m = mask.loc[dvalid.index].fillna(False)
        on  = dvalid[m]
        off = dvalid[~m]
        if len(on) < 30: continue
        p_on  = on['is_top25_dump'].mean()
        p_off = off['is_top25_dump'].mean()
        lift  = (p_on - p_off) * 100
        rows.append((name, len(on), p_on*100, len(off), p_off*100, lift))
    rows.sort(key=lambda r: r[-1], reverse=True)
    for r in rows:
        print(f'  {r[0]:35s}  {r[1]:4d}   {r[2]:5.1f}%   {r[3]:4d}    {r[4]:5.1f}%    {r[5]:+5.1f}')

    # ---- PHASE 4 — Counterfactual: simple short at 9:30:30 on top-quartile dump days ----
    print('\n' + '='*100)
    print('PHASE 4 — Counterfactual: short at 9:30 candle close, SL=9:30 high, TP=1R')
    print('='*100)
    print('(Loading 30s data to compute 9:30 candle close + high)')
    cand = pd.read_parquet(DATA_30S, columns=['timestamp_ny','open','high','low','close'])
    cand['timestamp_ny'] = pd.to_datetime(cand['timestamp_ny'])
    cand['date'] = cand['timestamp_ny'].dt.normalize().dt.tz_localize(None)
    cand['t'] = cand['timestamp_ny'].dt.time

    # 9:30:00-9:30:30 candle: the bar that STARTS at 9:30:00
    c930 = cand[cand['t']==dtime(9,30,0)].copy()
    c930 = c930.groupby('date').first().reset_index()
    c930 = c930[['date','open','high','low','close']].rename(
        columns={'open':'c930_open','high':'c930_high','low':'c930_low','close':'c930_close'})

    # 9:30-9:45 lowest low for outcome (15-min window)
    win = cand[(cand['t']>=dtime(9,30,0)) & (cand['t']<dtime(9,45,0))]
    win_low = win.groupby('date')['low'].min().reset_index().rename(columns={'low':'win_low'})
    win_high= win.groupby('date')['high'].max().reset_index().rename(columns={'high':'win_high'})

    # Build the counterfactual short
    cf = c930.merge(win_low, on='date', how='inner').merge(win_high, on='date', how='inner')
    cf = cf.merge(d[['date','dump_15m','dump_15m_q75','dump_15m_q90','rth_open']],
                  on='date', how='inner')
    cf['entry'] = cf['c930_close']
    cf['sl']    = cf['c930_high']        # 9:30 candle high
    cf['sl_dist'] = cf['sl'] - cf['entry']
    # 1R target
    cf['tp_1R'] = cf['entry'] - cf['sl_dist']
    cf['tp_2R'] = cf['entry'] - 2*cf['sl_dist']
    cf['tp_3R'] = cf['entry'] - 3*cf['sl_dist']
    cf['tp_5R'] = cf['entry'] - 5*cf['sl_dist']

    # Outcome: did win_high reach sl BEFORE win_low reached tp?
    # We can't know order from min/max alone — use simple "hit SL"/"hit TP" with
    # conservative tiebreak: if both hit, treat as loss (SL is closer to entry by definition? no — TPs differ)
    # For 1R: SL hit if win_high >= sl. TP hit if win_low <= tp_1R.
    # Both hit: ambiguous; we'll record as both and report.
    cf['hit_sl']   = cf['win_high'] >= cf['sl']
    cf['hit_1R']   = cf['win_low']  <= cf['tp_1R']
    cf['hit_2R']   = cf['win_low']  <= cf['tp_2R']
    cf['hit_3R']   = cf['win_low']  <= cf['tp_3R']
    cf['hit_5R']   = cf['win_low']  <= cf['tp_5R']
    # Optimistic-tp & pessimistic-sl outcome:
    def cf_outcome_optimistic(row, tp_col):
        if row[tp_col]: return 'win'
        if row['hit_sl']: return 'loss'
        return 'open'
    def cf_outcome_pessimistic(row, tp_col):
        if row['hit_sl']: return 'loss'
        if row[tp_col]: return 'win'
        return 'open'
    cf['o_1R_opt']  = cf.apply(lambda r: cf_outcome_optimistic(r, 'hit_1R'), axis=1)
    cf['o_1R_pess'] = cf.apply(lambda r: cf_outcome_pessimistic(r, 'hit_1R'), axis=1)

    # Subset to days where sl_dist > 0 (9:30 candle was bullish or doji — but for short, SL above entry)
    # Actually for a SHORT, SL > entry. c930_high >= c930_close, so sl_dist >= 0.
    # If sl_dist == 0 (close == high), trade is impossible (instant stop).
    cf = cf[cf['sl_dist'] > 0].copy()

    def cf_stats(df, ocol):
        w = (df[ocol]=='win').sum(); l=(df[ocol]=='loss').sum(); o=(df[ocol]=='open').sum()
        if w+l == 0: return dict(n=len(df), w=w, l=l, open=o, wr=float('nan'), avg_r=float('nan'))
        # PnL: win = +1R, loss = -1R, open = 0
        avg_r = (w - l) / len(df)
        wr = w/(w+l)*100
        return dict(n=len(df), w=int(w), l=int(l), open=int(o), wr=wr, avg_r=avg_r)

    print(f'\nCounterfactual short entered at 9:30 candle CLOSE on EVERY day (n={len(cf)}):')
    print('  (SL = 9:30 candle high, target = 1R, optimistic = TP hit first if both hit)')
    print(f'\n  ALL DAYS  -- 1R TP --')
    a = cf_stats(cf, 'o_1R_opt')
    print(f'    optimistic: n={a["n"]}  W={a["w"]} L={a["l"]} open={a["open"]}  WR={a["wr"]:.1f}%  avg_R={a["avg_r"]:+.3f}')
    a = cf_stats(cf, 'o_1R_pess')
    print(f'    pessimistic: n={a["n"]}  W={a["w"]} L={a["l"]} open={a["open"]}  WR={a["wr"]:.1f}%  avg_R={a["avg_r"]:+.3f}')

    # Top-25% dump days
    top = cf[cf['dump_15m'] >= cf['dump_15m_q75']].dropna(subset=['dump_15m_q75'])
    print(f'\n  TOP-25% DUMP DAYS  (n={len(top)})')
    a = cf_stats(top, 'o_1R_opt')
    print(f'    optimistic: n={a["n"]}  W={a["w"]} L={a["l"]} open={a["open"]}  WR={a["wr"]:.1f}%  avg_R={a["avg_r"]:+.3f}')
    a = cf_stats(top, 'o_1R_pess')
    print(f'    pessimistic: n={a["n"]}  W={a["w"]} L={a["l"]} open={a["open"]}  WR={a["wr"]:.1f}%  avg_R={a["avg_r"]:+.3f}')

    # And what about 2R / 3R / 5R targets on dump days?
    print(f'\n  TOP-25% DUMP DAYS — target sweep (optimistic, both-hit favors TP):')
    for tp_col, lbl in [('hit_1R','1R'), ('hit_2R','2R'), ('hit_3R','3R'), ('hit_5R','5R')]:
        ocol = f'o_{lbl}_opt'
        top[ocol] = top.apply(lambda r: cf_outcome_optimistic(r, tp_col), axis=1)
        st = cf_stats(top, ocol)
        avg_r_correct = (st['w']*float(lbl[:-1]) - st['l'])/st['n'] if st['n'] else float('nan')
        print(f'    TP={lbl}: n={st["n"]}  W={st["w"]} L={st["l"]} open={st["open"]}  '
              f'WR={st["wr"]:.1f}%  avg_R={avg_r_correct:+.3f}')

    # Save the counterfactual trade list
    OUT = Path(__file__).resolve().parent / 'results'
    OUT.mkdir(exist_ok=True)
    cf.to_csv(OUT/'counterfactual_930close_short.csv', index=False)
    print(f'\nWrote {OUT/"counterfactual_930close_short.csv"} ({len(cf)} rows)')

if __name__ == '__main__':
    main()
