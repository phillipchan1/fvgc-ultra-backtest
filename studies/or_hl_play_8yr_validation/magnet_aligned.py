#!/usr/bin/env python3
"""
Does the play actually need OR magnetism?

For each FVGC entry on 1m, ≥9:45, classify by sweep state at entry AND by
directional alignment with the unswept side:

  Sweep state at entry × direction × "is this direction toward an unswept side?"

Cells:
  - neither_swept × long  (target OR.H — H still unswept = magnet-aligned)
  - neither_swept × short (target OR.L — L still unswept = magnet-aligned)
  - only_L_swept × long   (target OR.H, H still unswept = magnet-aligned)
  - only_L_swept × short  (target OR.L, but L already swept = magnet-AGAINST)
  - only_H_swept × short  (target OR.L, L still unswept = magnet-aligned)
  - only_H_swept × long   (target OR.H, but H already swept = magnet-AGAINST)
  - both_swept  × any     (no clean draw — off-thesis)

Report PF/WR/EV per cell at 2R target. Compares magnet-aligned vs against vs off.

Run from repo root.
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


def load_candles(path: Path) -> pd.DataFrame:
    df = pd.read_parquet(path, columns=['timestamp_ny', 'open', 'high', 'low', 'close'])
    if df['timestamp_ny'].dt.tz is None:
        df['timestamp_ny'] = df['timestamp_ny'].dt.tz_localize(NY_TZ)
    return df.sort_values('timestamp_ny').reset_index(drop=True)


def compute_or_table(candles: pd.DataFrame) -> pd.DataFrame:
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


def classify(trades: pd.DataFrame, or_df: pd.DataFrame) -> pd.DataFrame:
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
    # entry must be inside or near OR range for the OR magnet thesis
    long_dir = (trades['direction'] == 'long')  & (trades['entry_price'] < trades['or_high'])
    short_dir = (trades['direction'] == 'short') & (trades['entry_price'] > trades['or_low'])
    trades = trades[long_dir | short_dir].copy()

    # 2R outcome
    trades['pnl_r'] = trades.apply(
        lambda r: -1.0 if r['outcome'] == 'loss'
        else (2.0 if r['mfe_r'] >= 2.0 else 0.0), axis=1)
    trades['outcome_2r'] = trades['pnl_r'].map({-1.0: 'LOSS', 2.0: 'WIN', 0.0: 'PARTIAL'})

    # sweep state at entry time
    h_swept_at_entry = trades['h_sweep_at'].notna() & (trades['h_sweep_at'] <= trades['timestamp'])
    l_swept_at_entry = trades['l_sweep_at'].notna() & (trades['l_sweep_at'] <= trades['timestamp'])
    sweep_state = pd.Series('neither', index=trades.index)
    sweep_state[h_swept_at_entry & ~l_swept_at_entry] = 'only_H_swept'
    sweep_state[~h_swept_at_entry & l_swept_at_entry] = 'only_L_swept'
    sweep_state[h_swept_at_entry & l_swept_at_entry]  = 'both_swept'
    trades['sweep_state'] = sweep_state

    # magnet alignment
    def _align(row):
        d = row['direction']
        s = row['sweep_state']
        if s == 'neither':
            return 'aligned'   # both sides are draws; either direction targets a draw
        if s == 'only_H_swept':
            # H already tested. L unswept = draw. Short toward L = aligned.
            return 'aligned' if d == 'short' else 'against'
        if s == 'only_L_swept':
            # L already tested. H unswept = draw. Long toward H = aligned.
            return 'aligned' if d == 'long' else 'against'
        return 'off_thesis'   # both swept
    trades['magnet'] = trades.apply(_align, axis=1)

    # Useful extras
    trades['r_to_target_OR'] = trades.apply(
        lambda r: (r['or_high'] - r['entry_price']) if r['direction'] == 'long'
        else (r['entry_price'] - r['or_low']), axis=1) / trades['sl_dist']

    return trades.reset_index(drop=True)


def stats(df: pd.DataFrame) -> dict:
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
    return f"n={s['n']:4d}  W={s['w']:3d} L={s['l']:3d}  WR={s['wr']:5.1f}%  PF={pf}  EV={s['ev']:+.3f}R"


def split_report(df: pd.DataFrame, label: str):
    is_m = (df['date'] >= IS_START) & (df['date'] <= IS_END)
    is_df, oos_df = df[is_m], df[~is_m]
    print(f"  {label:45s}  IS: {fmt(stats(is_df)):65s}  OOS: {fmt(stats(oos_df)):65s}  ALL: {fmt(stats(df))}")


def main():
    tf_label = '1m'
    cand_path = ROOT / 'data' / 'consolidated' / 'nq-front-month.ohlcv-1m.parquet'
    tr_path = ROOT / 'studies' / 'baseline_1m' / 'results' / 'trades.csv'

    print(f"Loading {tf_label} ...")
    cand = load_candles(cand_path)
    or_df = compute_or_table(cand)
    del cand

    trades = pd.read_csv(tr_path)
    df = classify(trades, or_df)
    print(f"  {len(df):,} post-9:45 OR-inside entries\n")

    print(f"  Sweep-state distribution at entry:")
    for s in ('neither', 'only_H_swept', 'only_L_swept', 'both_swept'):
        n = (df['sweep_state'] == s).sum()
        print(f"    {s:18s}  n={n}")
    print()

    print(f"  Magnet alignment distribution:")
    for m in ('aligned', 'against', 'off_thesis'):
        n = (df['magnet'] == m).sum()
        print(f"    {m:12s}  n={n}")
    print()

    print(f"\n{'='*180}")
    print(f"  Cells (each row: IS  |  OOS  |  ALL)")
    print(f"{'='*180}")
    print()

    print(f"  ── By sweep state alone ──")
    for s in ('neither', 'only_H_swept', 'only_L_swept', 'both_swept'):
        split_report(df[df['sweep_state'] == s], s)

    print(f"\n  ── By magnet alignment ──")
    for m in ('aligned', 'against', 'off_thesis'):
        split_report(df[df['magnet'] == m], m)

    print(f"\n  ── By sweep state × magnet (the real test) ──")
    for s in ('neither', 'only_H_swept', 'only_L_swept'):
        for m in ('aligned', 'against'):
            sub = df[(df['sweep_state'] == s) & (df['magnet'] == m)]
            if len(sub) == 0: continue
            split_report(sub, f"{s} × {m}")

    # The headline comparison: aligned vs against in the post-sweep subset
    print(f"\n  ── Headline: post-sweep entries (only_H or only_L), magnet-aligned vs against ──")
    post = df[df['sweep_state'].isin(['only_H_swept', 'only_L_swept'])]
    split_report(post[post['magnet'] == 'aligned'], 'post-sweep × ALIGNED')
    split_report(post[post['magnet'] == 'against'], 'post-sweep × AGAINST')

    # And the master comparison
    print(f"\n  ── Master comparison ──")
    split_report(df,                                 'ALL post-9:45 entries (baseline)')
    split_report(df[df['magnet'] == 'aligned'],       'ALL magnet-aligned (the real OR play)')
    split_report(df[df['magnet'] != 'aligned'],       'ALL non-aligned (against + off-thesis)')

    # Save
    out = RESULTS_DIR / 'magnet_aligned_1m.csv'
    df[['timestamp', 'date', 'direction', 'variant', 'entry_price', 'sl_dist',
        'or_high', 'or_low', 'or_range', 'r_to_target_OR',
        'sweep_state', 'magnet', 'mfe_r', 'outcome', 'outcome_2r', 'pnl_r']].to_csv(out, index=False)
    print(f"\n  Wrote {out}")


if __name__ == '__main__':
    main()
