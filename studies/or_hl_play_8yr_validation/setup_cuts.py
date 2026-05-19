#!/usr/bin/env python3
"""
What are the best setups to take inside the 1m core play (neither swept)?

Cuts the 405-trade sample on:
  - OR range (size of 9:30-9:45 OR in pts, quartile + raw bands)
  - R-to-OR (dist from entry to opposite OR / sl_dist)
  - Direction (long / short)
  - Variant
  - Pairwise: direction × OR-range, direction × R-to-OR

Reports each cell IS + OOS. Highlights cells where:
    PF >= 2.0 in BOTH halves
    n  >= 25 in EACH half
    EV >= +0.4R in BOTH halves
These are the only filters worth shipping.

Run: python studies/or_hl_play_8yr_validation/setup_cuts.py
"""

import sys
from pathlib import Path
from datetime import date

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

STUDY_DIR = Path(__file__).resolve().parent
RESULTS_DIR = STUDY_DIR / 'results'

IS_START = date(2023, 10, 1)
IS_END   = date(2025, 10, 31)


def load() -> pd.DataFrame:
    df = pd.read_csv(RESULTS_DIR / 'core_play_1m.csv')
    df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True).dt.tz_convert('America/New_York')
    df['date'] = pd.to_datetime(df['date']).dt.date
    df['or_range'] = df['or_high'] - df['or_low']
    df['pnl_r'] = df['outcome_2r'].map({'WIN': 2.0, 'LOSS': -1.0, 'PARTIAL': 0.0})
    return df


def stats(df: pd.DataFrame) -> dict:
    n = len(df)
    if n == 0:
        return {'n': 0, 'wr': float('nan'), 'pf': float('nan'), 'ev': float('nan')}
    wins   = int((df['outcome_2r'] == 'WIN').sum())
    losses = int((df['outcome_2r'] == 'LOSS').sum())
    dec = wins + losses
    wr  = wins / dec * 100 if dec else float('nan')
    pf  = (wins * 2.0 / losses) if losses else float('inf')
    ev  = df['pnl_r'].sum() / n
    return {'n': n, 'wins': wins, 'losses': losses, 'wr': wr, 'pf': pf, 'ev': ev}


def row(label: str, is_s: dict, oos_s: dict, all_s: dict, flag: bool = False) -> str:
    def f(s):
        if s['n'] == 0: return f"{'n=0':>27s}"
        pf = f"{s['pf']:5.2f}" if s['pf'] != float('inf') else "  inf"
        return f"n={s['n']:3d}  WR={s['wr']:4.1f}% PF={pf} EV={s['ev']:+.2f}R"
    mark = "  ★" if flag else "   "
    return f"  {label:<28s}  {f(is_s)}   |   {f(oos_s)}   |   {f(all_s)} {mark}"


def passes(is_s: dict, oos_s: dict,
            min_n: int = 25, min_pf: float = 2.0, min_ev: float = 0.4) -> bool:
    if is_s['n'] < min_n or oos_s['n'] < min_n: return False
    if is_s['pf'] < min_pf or oos_s['pf'] < min_pf: return False
    if is_s['ev'] < min_ev or oos_s['ev'] < min_ev: return False
    return True


def cut(df: pd.DataFrame, col: str, label: str):
    print(f"\n  ── {label} ──")
    print(f"  {'cell':<28s}  {'IS (2023-10..2025-10)':<37s}   |   "
          f"{'OOS (rest of 8yr)':<37s}   |   {'ALL 8yr':<37s}")
    print(f"  {'─'*146}")

    is_m = (df['date'] >= IS_START) & (df['date'] <= IS_END)
    is_df, oos_df = df[is_m], df[~is_m]

    cats = (df[col].cat.categories
            if hasattr(df[col], 'cat')
            else sorted(df[col].dropna().unique()))
    for c in cats:
        sub_is  = is_df[is_df[col] == c]
        sub_oos = oos_df[oos_df[col] == c]
        sub_all = df[df[col] == c]
        s_is  = stats(sub_is)
        s_oos = stats(sub_oos)
        s_all = stats(sub_all)
        flag = passes(s_is, s_oos)
        print(row(str(c), s_is, s_oos, s_all, flag))


def cut2d(df: pd.DataFrame, col_a: str, col_b: str, label: str):
    print(f"\n  ── {label} ──")
    print(f"  {'cell':<28s}  {'IS':<37s}   |   {'OOS':<37s}   |   {'ALL':<37s}")
    print(f"  {'─'*146}")
    is_m = (df['date'] >= IS_START) & (df['date'] <= IS_END)
    is_df, oos_df = df[is_m], df[~is_m]
    cats_a = df[col_a].cat.categories if hasattr(df[col_a], 'cat') else sorted(df[col_a].dropna().unique())
    cats_b = df[col_b].cat.categories if hasattr(df[col_b], 'cat') else sorted(df[col_b].dropna().unique())
    for a in cats_a:
        for b in cats_b:
            sub_is  = is_df[(is_df[col_a] == a) & (is_df[col_b] == b)]
            sub_oos = oos_df[(oos_df[col_a] == a) & (oos_df[col_b] == b)]
            sub_all = df[(df[col_a] == a) & (df[col_b] == b)]
            if sub_all.empty: continue
            s_is, s_oos, s_all = stats(sub_is), stats(sub_oos), stats(sub_all)
            flag = passes(s_is, s_oos)
            print(row(f"{a} × {b}", s_is, s_oos, s_all, flag))


def main():
    df = load()
    print(f"  Loaded {len(df)} core-play 1m trades  (IS={((df['date']>=IS_START)&(df['date']<=IS_END)).sum()})")

    # Baseline
    is_m = (df['date'] >= IS_START) & (df['date'] <= IS_END)
    print(f"\n  ── Baseline (no further filter, 2R hold) ──")
    print(row('ALL trades', stats(df[is_m]), stats(df[~is_m]), stats(df)))

    # OR range — both quartile and raw bands
    df['or_quartile'] = pd.qcut(df['or_range'], q=4,
                                  labels=['Q1<25% (small)', 'Q2', 'Q3', 'Q4>75% (large)'])
    df['or_band'] = pd.cut(df['or_range'],
                            bins=[0, 30, 60, 100, 150, 1000],
                            labels=['<30pt', '30-60', '60-100', '100-150', '>150pt'])
    cut(df, 'or_quartile', 'OR range — quartiles')
    cut(df, 'or_band',     'OR range — raw bands (pts)')

    # R-to-OR
    df['rto'] = pd.cut(df['r_to_or'],
                        bins=[0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 99],
                        labels=['<0.25', '0.25-0.5', '0.5-0.75', '0.75-1.0',
                                '1.0-1.5', '1.5-2.0', '>2.0'])
    cut(df, 'rto', 'R-to-OR (dist to far OR side / SL)')

    cut(df, 'direction', 'Direction')
    cut(df, 'variant',   'Variant')

    # Pairwise — only ones likely informative
    cut2d(df, 'direction', 'or_band', 'Direction × OR-range band')
    cut2d(df, 'direction', 'rto',     'Direction × R-to-OR')
    cut2d(df, 'or_band',   'rto',     'OR-range × R-to-OR')


if __name__ == '__main__':
    main()
