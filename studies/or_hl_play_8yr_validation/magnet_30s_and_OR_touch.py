#!/usr/bin/env python3
"""
1. Magnet-aligned on 30s (does the rule generalize across TF?)
2. What happens when price touches the OR target?
   - Reach rate (% of trades where MFE >= dist_to_OR)
   - Continuation rate (of trades that reached OR, % that also hit 2R)
   - Reversal rate (of trades that reached OR, % that did NOT hit 2R)
   - Beyond-OR excursion (avg pts past OR for continuations)
3. The "is the play dead after one side is swept?" question — final answer.
"""

import sys
from pathlib import Path
from datetime import time as dtime, date

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import numpy as np
from fvgc.constants import NY_TZ

STUDY_DIR = Path(__file__).resolve().parent
RESULTS_DIR = STUDY_DIR / 'results'

OR_START = dtime(9, 30)
OR_END   = dtime(9, 45)
ENTRY_AFTER = dtime(9, 45)
SWEEP_WINDOW_END = dtime(11, 0)
IS_START = date(2023, 10, 1)
IS_END   = date(2025, 10, 31)

TF_PATHS = {
    '30s': {
        'trades':  ROOT / 'studies' / 'baseline'    / 'results' / 'trades.csv',
        'candles': ROOT / 'data' / 'consolidated' / 'nq-front-month.ohlcv-30s.parquet',
    },
    '1m': {
        'trades':  ROOT / 'studies' / 'baseline_1m' / 'results' / 'trades.csv',
        'candles': ROOT / 'data' / 'consolidated' / 'nq-front-month.ohlcv-1m.parquet',
    },
}


def load_candles(path):
    df = pd.read_parquet(path, columns=['timestamp_ny', 'high', 'low', 'close'])
    if df['timestamp_ny'].dt.tz is None:
        df['timestamp_ny'] = df['timestamp_ny'].dt.tz_localize(NY_TZ)
    return df.sort_values('timestamp_ny').reset_index(drop=True)


def compute_or_table(candles):
    df = candles.copy()
    df['date'] = df['timestamp_ny'].dt.date
    df['t']    = df['timestamp_ny'].dt.time
    or_m = (df['t'] >= OR_START) & (df['t'] < OR_END)
    post_m = (df['t'] >= OR_END) & (df['t'] < SWEEP_WINDOW_END)
    post_grp = {d: g for d, g in df[post_m].groupby('date')}
    rows = []
    for d, or_bars in df[or_m].groupby('date'):
        orh = or_bars['high'].max(); orl = or_bars['low'].min()
        if orh - orl <= 0: continue
        post = post_grp.get(d)
        h_t = l_t = None
        if post is not None and len(post):
            hs = post[post['high'] > orh]
            ls = post[post['low']  < orl]
            if len(hs): h_t = hs['timestamp_ny'].iloc[0]
            if len(ls): l_t = ls['timestamp_ny'].iloc[0]
        rows.append({'date': d, 'or_high': orh, 'or_low': orl,
                     'or_range': orh - orl,
                     'h_sweep_at': h_t, 'l_sweep_at': l_t})
    return pd.DataFrame(rows)


def classify(trades, or_df):
    trades = trades.copy()
    trades['timestamp'] = pd.to_datetime(trades['timestamp'])
    if trades['timestamp'].dt.tz is None:
        trades['timestamp'] = trades['timestamp'].dt.tz_localize(
            NY_TZ, ambiguous='infer', nonexistent='shift_forward')
    trades['date'] = trades['timestamp'].dt.date
    trades = trades[trades['outcome'].isin(['win', 'loss', 'eod'])]
    trades = trades[trades['timestamp'].dt.time >= ENTRY_AFTER]
    trades = trades[trades['sl_dist'].notna() & (trades['sl_dist'] > 0)]
    trades['mfe_r'] = trades['mfe_r'].fillna(0)
    trades = trades.merge(or_df, on='date', how='inner')
    long_dir = (trades['direction'] == 'long')  & (trades['entry_price'] < trades['or_high'])
    short_dir = (trades['direction'] == 'short') & (trades['entry_price'] > trades['or_low'])
    trades = trades[long_dir | short_dir].copy()

    trades['pnl_r'] = trades.apply(
        lambda r: -1.0 if r['outcome'] == 'loss'
        else (2.0 if r['mfe_r'] >= 2.0 else 0.0), axis=1)
    trades['outcome_2r'] = trades['pnl_r'].map({-1.0: 'LOSS', 2.0: 'WIN', 0.0: 'PARTIAL'})

    # sweep state at entry
    h_se = trades['h_sweep_at'].notna() & (trades['h_sweep_at'] <= trades['timestamp'])
    l_se = trades['l_sweep_at'].notna() & (trades['l_sweep_at'] <= trades['timestamp'])
    state = pd.Series('neither', index=trades.index)
    state[h_se & ~l_se] = 'only_H_swept'
    state[~h_se & l_se] = 'only_L_swept'
    state[h_se & l_se]  = 'both_swept'
    trades['sweep_state'] = state

    def _align(r):
        if r['sweep_state'] == 'neither': return 'aligned'
        if r['sweep_state'] == 'only_H_swept': return 'aligned' if r['direction']=='short' else 'against'
        if r['sweep_state'] == 'only_L_swept': return 'aligned' if r['direction']=='long' else 'against'
        return 'off_thesis'
    trades['magnet'] = trades.apply(_align, axis=1)

    # distance to OR target (the magnet-aligned side)
    def _target_dist(r):
        d = r['direction']
        if r['magnet'] == 'aligned':
            # target the UNSWEPT side
            if d == 'long':  return r['or_high'] - r['entry_price']
            else:            return r['entry_price'] - r['or_low']
        if r['magnet'] == 'against':
            # target the already-swept side (you're trading against the magnet)
            if d == 'long':  return r['or_high'] - r['entry_price']
            else:            return r['entry_price'] - r['or_low']
        return float('nan')
    trades['dist_to_target_OR'] = trades.apply(_target_dist, axis=1)
    trades['r_to_target_OR'] = trades['dist_to_target_OR'] / trades['sl_dist']
    trades['reached_OR']     = trades['mfe_r'] >= trades['r_to_target_OR']
    trades['beyond_OR_R']    = (trades['mfe_r'] - trades['r_to_target_OR']).where(trades['reached_OR'], 0)
    return trades.reset_index(drop=True)


def stats(df):
    n = len(df)
    if n == 0: return {'n': 0}
    w = int((df['outcome_2r'] == 'WIN').sum())
    l = int((df['outcome_2r'] == 'LOSS').sum())
    p = int((df['outcome_2r'] == 'PARTIAL').sum())
    dec = w + l
    wr = w/dec*100 if dec else float('nan')
    pf = (w*2.0/l) if l else float('inf')
    ev = df['pnl_r'].sum() / n
    return {'n': n, 'w': w, 'l': l, 'p': p, 'wr': wr, 'pf': pf, 'ev': ev}


def fmt(s):
    if s.get('n', 0) == 0: return "n=0"
    pf = f"{s['pf']:5.2f}" if s['pf'] != float('inf') else "  inf"
    return f"n={s['n']:4d}  WR={s['wr']:5.1f}%  PF={pf}  EV={s['ev']:+.3f}R"


def split_print(df, label):
    is_m = (df['date'] >= IS_START) & (df['date'] <= IS_END)
    print(f"  {label:42s}  IS  {fmt(stats(df[is_m]))}    OOS  {fmt(stats(df[~is_m]))}    ALL  {fmt(stats(df))}")


def or_touch_analysis(df, label):
    """For trades that reached OR, what % continued to 2R, what % reversed?"""
    print(f"\n  ── OR-touch behavior — {label} ──")
    reached = df[df['reached_OR']]
    not_reached = df[~df['reached_OR']]
    n = len(df)
    print(f"  Total: n={n}")
    if n == 0: return
    print(f"  Reached OR target: {len(reached)} ({len(reached)/n*100:.1f}%)")
    print(f"  Did NOT reach OR:  {len(not_reached)} ({len(not_reached)/n*100:.1f}%)")

    if len(reached) == 0: return
    # Of the trades that reached OR, what's the breakdown?
    cont_2r = reached[reached['mfe_r'] >= 2.0]  # continued past OR to 2R
    cont_only_OR = reached[reached['mfe_r'] < 2.0]  # touched OR but didn't make 2R = reversed near OR

    # also: trades that reached OR but then got stopped out (full loss after touching OR)
    cont_then_loss = reached[reached['outcome'] == 'loss']
    cont_then_eod  = reached[reached['outcome'] == 'eod']

    print(f"\n  Of trades that REACHED OR (n={len(reached)}):")
    print(f"    Continued past OR to 2R:        {len(cont_2r):4d} ({len(cont_2r)/len(reached)*100:5.1f}%)")
    print(f"    Hit OR but didn't make 2R:      {len(cont_only_OR):4d} ({len(cont_only_OR)/len(reached)*100:5.1f}%)")
    print(f"      ↳ reversed and got stopped:   {len(cont_then_loss):4d} ({len(cont_then_loss)/len(reached)*100:5.1f}%)")
    print(f"      ↳ closed at EOD partial:       {len(cont_then_eod):4d} ({len(cont_then_eod)/len(reached)*100:5.1f}%)")
    print(f"    Avg MFE beyond OR (cont cases): {cont_2r['beyond_OR_R'].mean():+.2f}R")

    # what if we exited AT OR (target = R-to-OR)?
    # win = reached, loss = engine loss
    or_wins = len(reached)
    or_losses = (df['outcome'] == 'loss').sum()
    or_pf = (reached['r_to_target_OR'].sum()) / (or_losses) if or_losses else float('inf')
    or_ev = (reached['r_to_target_OR'].sum() - or_losses) / n

    # vs 2R hold (current model)
    held_wins = (df['outcome_2r'] == 'WIN').sum()
    held_losses = (df['outcome_2r'] == 'LOSS').sum()
    held_pf = (held_wins * 2.0 / held_losses) if held_losses else float('inf')
    held_ev = df['pnl_r'].sum() / n

    print(f"\n  Exit-strategy comparison:")
    print(f"    Exit at OR target:  PF {or_pf:.2f}  EV {or_ev:+.3f}R/trade  (n={n})")
    print(f"    Hold to 2R:         PF {held_pf:.2f}  EV {held_ev:+.3f}R/trade")


def main():
    print("="*100)
    print("  MAGNET-ALIGNED OR PLAY — cross-TF + OR-touch behavior")
    print("="*100)

    for tf in ('30s', '1m'):
        paths = TF_PATHS[tf]
        print(f"\n\n{'#'*100}\n  TIMEFRAME: {tf}\n{'#'*100}")
        cand = load_candles(paths['candles'])
        or_df = compute_or_table(cand)
        del cand
        trades = pd.read_csv(paths['trades'])
        df = classify(trades, or_df)
        print(f"  {len(df)} post-9:45 OR-inside entries")

        print(f"\n  ── Magnet alignment (the headline) ──")
        split_print(df[df['magnet']=='aligned'],    'ALIGNED (toward unswept side)')
        split_print(df[df['magnet']=='against'],    'AGAINST (toward already-swept side)')
        split_print(df[df['magnet']=='off_thesis'], 'OFF-THESIS (both swept)')
        split_print(df,                              'ALL post-9:45 (baseline)')

        print(f"\n  ── By sweep state × magnet ──")
        for s in ('neither', 'only_H_swept', 'only_L_swept', 'both_swept'):
            for m in ('aligned', 'against', 'off_thesis'):
                sub = df[(df['sweep_state']==s) & (df['magnet']==m)]
                if len(sub) == 0: continue
                split_print(sub, f"{s} × {m}")

        # OR-touch behavior on the aligned subset
        or_touch_analysis(df[df['magnet']=='aligned'], 'magnet-aligned only')

        df.to_csv(RESULTS_DIR / f'magnet_aligned_{tf}.csv', index=False)


if __name__ == '__main__':
    main()
