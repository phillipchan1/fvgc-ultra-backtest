#!/usr/bin/env python3
"""Diagnose 2025-2026 weakness in the core OR H/L play.

Compares 2018-2024 ("strong") vs 2025-2026 ("weak") cells across:
  direction, variant, OR range bucket, entry time bucket, day-of-week,
  SL bucket, R-to-OR bucket, MFE excursion behaviour.

Run: python studies/or_hl_play_8yr_validation/diag_recent.py
"""

import sys
from pathlib import Path
from datetime import date

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import numpy as np

STUDY_DIR = Path(__file__).resolve().parent
RESULTS_DIR = STUDY_DIR / 'results'


def load(tf: str) -> pd.DataFrame:
    df = pd.read_csv(RESULTS_DIR / f'core_play_{tf}.csv')
    df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True).dt.tz_convert('America/New_York')
    df['date'] = pd.to_datetime(df['date']).dt.date
    df['year'] = df['date'].apply(lambda d: d.year)
    df['regime'] = np.where(df['year'] >= 2025, 'WEAK_25_26', 'STRONG_18_24')
    df['or_range'] = df['or_high'] - df['or_low']
    df['hour']    = df['timestamp'].dt.hour
    df['minute']  = df['timestamp'].dt.minute
    df['time_bucket'] = pd.cut(
        df['hour'] + df['minute'] / 60,
        bins=[9.74, 9.85, 9.95, 10.05, 10.15, 11.0],
        labels=['09:45-09:51', '09:51-09:57', '09:57-10:03', '10:03-10:09', '10:09+'],
    )
    df['dow'] = df['timestamp'].dt.day_name().str[:3]
    df['or_bucket'] = pd.qcut(df['or_range'], q=4, labels=['Q1<25%', 'Q2', 'Q3', 'Q4>75%'])
    df['sl_bucket'] = pd.cut(df['sl_dist'], bins=[0, 20, 30, 45, 200],
                              labels=['<=20', '21-30', '31-45', '>45'])
    df['rto_bucket'] = pd.cut(df['r_to_or'], bins=[0, 0.5, 1.0, 1.5, 99],
                                labels=['<0.5', '0.5-1', '1-1.5', '>1.5'])
    return df


def stats_2r(df: pd.DataFrame) -> dict:
    n = len(df)
    if n == 0:
        return None
    wins   = int((df['outcome_2r'] == 'WIN').sum())
    losses = int((df['outcome_2r'] == 'LOSS').sum())
    part   = int((df['outcome_2r'] == 'PARTIAL').sum())
    dec = wins + losses
    wr  = wins / dec * 100 if dec else float('nan')
    pf  = (wins * 2.0 / losses) if losses else float('inf')
    ev  = (wins * 2.0 - losses * 1.0) / n
    return {'n': n, 'wins': wins, 'losses': losses, 'partial': part,
            'wr': wr, 'pf': pf, 'ev': ev}


def fmt(s):
    if s is None: return "  n=0"
    pf = f"{s['pf']:5.2f}" if s['pf'] != float('inf') else "  inf"
    return (f"  n={s['n']:4d}  WR={s['wr']:5.1f}%  PF={pf}  EV={s['ev']:+.3f}R")


def cross(df: pd.DataFrame, col: str, label: str):
    print(f"\n  ── {label} ──")
    cats = df[col].cat.categories if hasattr(df[col], 'cat') else sorted(df[col].dropna().unique())
    print(f"  {'cell':18s}  {'STRONG (18-24)':>40s}     {'WEAK (25-26)':>40s}     Δ(PF)")
    for c in cats:
        sub = df[df[col] == c]
        if len(sub) == 0: continue
        strong = sub[sub['regime'] == 'STRONG_18_24']
        weak   = sub[sub['regime'] == 'WEAK_25_26']
        ss = stats_2r(strong)
        ws = stats_2r(weak)
        s_str = fmt(ss) if ss else "  n=0"
        w_str = fmt(ws) if ws else "  n=0"
        delta = (ws['pf'] - ss['pf']) if (ss and ws and ss['pf'] != float('inf') and ws['pf'] != float('inf')) else 0
        print(f"  {str(c):18s}  {s_str}    {w_str}    {delta:+.2f}")


def main():
    for tf in ('30s', '1m'):
        path = RESULTS_DIR / f'core_play_{tf}.csv'
        if not path.exists():
            print(f"  missing {path}"); continue
        df = load(tf)
        print(f"\n{'='*84}\n  TIMEFRAME: {tf}  (n={len(df)})\n{'='*84}")

        # Overall
        print(f"\n  ── Overall regime comparison ──")
        print(f"  STRONG (18-24): {fmt(stats_2r(df[df['regime']=='STRONG_18_24']))}")
        print(f"  WEAK   (25-26): {fmt(stats_2r(df[df['regime']=='WEAK_25_26']))}")

        # Year-by-year
        print(f"\n  ── Per year ──")
        for y in sorted(df['year'].unique()):
            print(f"  {y}  {fmt(stats_2r(df[df['year']==y]))}")

        cross(df, 'direction',    'Direction')
        cross(df, 'variant',      'Variant')
        cross(df, 'or_bucket',    'OR range bucket')
        cross(df, 'sl_bucket',    'SL bucket')
        cross(df, 'rto_bucket',   'R-to-OR bucket')
        cross(df, 'time_bucket',  'Entry time bucket')
        cross(df, 'dow',          'Day of week')


if __name__ == '__main__':
    main()
