#!/usr/bin/env python3
"""
FVGC plays off the 9:30 candle — win rate for trades whose FVG was created
during the RTH opening window (fvg_created_at), plus optional overlap with
the 9:29:30→9:30:00 micro-gap from 30s candles.

Run from repo root:
  python studies/fvgc_plays_off_930_candle/run.py
  python studies/fvgc_plays_off_930_candle/run.py --window tight   # 9:29:30–9:30:30 only
  python studies/fvgc_plays_off_930_candle/run.py --no-candle-gap   # skip 30s overlap
"""

import argparse
import sys
from datetime import time as dtime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd

from fvgc.data import load_candles
from fvgc.constants import NY_TZ

TRADES_PATH = ROOT / 'logs' / 'baseline_trades.csv'
DATA_30S = ROOT / 'data' / 'consolidated' / 'nq-front-month.ohlcv-30s.csv'

STUDY_DIR = Path(__file__).resolve().parent
RESULTS_DIR = STUDY_DIR / 'results'

# Opening windows (ET) — FVG creation time must fall inside [start, end] inclusive
WINDOW_DEFAULT = (dtime(9, 29, 30), dtime(9, 31, 0))
WINDOW_TIGHT = (dtime(9, 29, 30), dtime(9, 30, 30))


def parse_args():
    p = argparse.ArgumentParser(description='FVGC 9:30 opening FVG study')
    p.add_argument('--window', choices=['default', 'tight'], default='default',
                   help='default = 9:29:30–9:31:00 ET; tight = 9:29:30–9:30:30 ET')
    p.add_argument('--no-candle-gap', action='store_true',
                   help='Skip loading 30s data and micro-gap overlap stats')
    return p.parse_args()


def fvg_in_opening_window(ts_ny: pd.Timestamp, start: dtime, end: dtime) -> bool:
    if pd.isna(ts_ny):
        return False
    t = ts_ny.time()
    return start <= t <= end


def write_trade_csv(df: pd.DataFrame, path: Path) -> None:
    """Write study trade list for verification (same columns as source + study flags)."""
    out = df.copy()
    if 'fvg_created_ny' in out.columns:
        def _fmt_ts(x):
            if pd.isna(x) or x == '':
                return ''
            return x.isoformat() if hasattr(x, 'isoformat') else str(x)
        out['fvg_created_ny'] = out['fvg_created_ny'].apply(_fmt_ts)
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(path, index=False)
    print(f"\n  Wrote {path.relative_to(ROOT)} ({len(out)} rows)")


def win_rate_stats(df: pd.DataFrame, label: str) -> None:
    sub = df[df['outcome'].isin(['win', 'loss'])]
    if sub.empty:
        print(f"  {label}: no tradeable trades")
        return
    wins = (sub['outcome'] == 'win').sum()
    losses = (sub['outcome'] == 'loss').sum()
    wr = wins / (wins + losses) * 100 if (wins + losses) else 0
    pnl = pd.to_numeric(sub['pnl'], errors='coerce').sum()
    print(f"  {label}: n={len(sub)}  W={wins} L={losses}  WR={wr:.1f}%  PnL={pnl:+.1f}")


def intervals_overlap(a_lo, a_hi, b_lo, b_hi) -> bool:
    return a_lo <= b_hi and b_lo <= a_hi


def build_daily_open_gap(candles: pd.DataFrame) -> pd.DataFrame:
    """Per calendar date: gap between 9:29:30 bar close and 9:30:00 bar open."""
    c = candles.copy()
    c['_d'] = c['timestamp_ny'].dt.date
    c['_t'] = c['timestamp_ny'].dt.time

    t929 = dtime(9, 29, 30)
    t930 = dtime(9, 30, 0)

    rows = []
    for d, g in c.groupby('_d'):
        r929 = g[g['_t'] == t929]
        r930 = g[g['_t'] == t930]
        if r929.empty or r930.empty:
            continue
        c929 = float(r929.iloc[0]['close'])
        o930 = float(r930.iloc[0]['open'])
        gap_lo = min(c929, o930)
        gap_hi = max(c929, o930)
        rows.append({'date': d, 'gap_lo': gap_lo, 'gap_hi': gap_hi})
    return pd.DataFrame(rows)


def main():
    args = parse_args()
    wstart, wend = WINDOW_TIGHT if args.window == 'tight' else WINDOW_DEFAULT

    print('=' * 60)
    print('FVGC plays off the 9:30 candle')
    print(f'Opening window (FVG created): {wstart} – {wend} ET')
    print('=' * 60)

    trades = pd.read_csv(TRADES_PATH)
    trades['timestamp'] = pd.to_datetime(trades['timestamp'])
    trades['fvg_created_at'] = pd.to_datetime(trades['fvg_created_at'], errors='coerce')

    # Assume naive times in CSV are America/New_York (matches backtest logging)
    if trades['fvg_created_at'].dt.tz is None:
        trades['fvg_created_ny'] = trades['fvg_created_at'].dt.tz_localize(
            NY_TZ, ambiguous='infer', nonexistent='shift_forward'
        )
    else:
        trades['fvg_created_ny'] = trades['fvg_created_at'].dt.tz_convert(NY_TZ)

    trades['date'] = trades['timestamp'].dt.date
    trades['in_opening_fvg_window'] = trades['fvg_created_ny'].apply(
        lambda x: fvg_in_opening_window(x, wstart, wend)
    )

    base = trades[trades['outcome'].isin(['win', 'loss'])].copy()
    opening = base[base['in_opening_fvg_window']]

    print('\n--- All tradeable baseline ---')
    win_rate_stats(base, 'All')

    print('\n--- FVG created in opening window (fvg_created_at) ---')
    win_rate_stats(opening, 'Opening-window FVG (all directions)')

    for direction in ['long', 'short']:
        win_rate_stats(opening[opening['direction'] == direction], f'  {direction} only')

    window_tag = 'tight_92930_093030' if args.window == 'tight' else 'default_92930_093100'
    opening_export = opening.copy()
    opening_export['study_window'] = window_tag
    write_trade_csv(
        opening_export,
        RESULTS_DIR / f'trades_opening_fvg_window_{window_tag}.csv',
    )

    # Optional: FVG bounds overlap micro-gap from 30s candles
    if not args.no_candle_gap:
        print('\n--- Loading 30s candles for micro-gap overlap ---')
        candles = load_candles(DATA_30S)
        gaps = build_daily_open_gap(candles)
        gaps['date'] = pd.to_datetime(gaps['date']).dt.date

        m = base.merge(gaps, on='date', how='left')
        m['fvg_top'] = pd.to_numeric(m['fvg_top'], errors='coerce')
        m['fvg_bottom'] = pd.to_numeric(m['fvg_bottom'], errors='coerce')

        def overlap_row(r):
            if pd.isna(r['gap_lo']) or pd.isna(r['fvg_top']) or pd.isna(r['fvg_bottom']):
                return False
            return intervals_overlap(r['fvg_bottom'], r['fvg_top'], r['gap_lo'], r['gap_hi'])

        m['fvg_overlaps_open_gap'] = m.apply(overlap_row, axis=1)
        ov = m[m['fvg_overlaps_open_gap'] & m['in_opening_fvg_window']]

        print('\n--- FVG in opening window AND FVG [bottom,top] overlaps 9:29:30→9:30 open gap ---')
        win_rate_stats(ov, 'Overlap cohort')
        for direction in ['long', 'short']:
            win_rate_stats(ov[ov['direction'] == direction], f'  {direction} only')

        n_no_gap = m['gap_lo'].isna().sum()
        if n_no_gap:
            print(f'\n  (Note: {n_no_gap} trade rows missing candle gap for that date — merged left)')

        ov_export = ov.copy()
        ov_export['study_window'] = window_tag
        write_trade_csv(
            ov_export,
            RESULTS_DIR / f'trades_opening_fvg_and_micro_gap_{window_tag}.csv',
        )

    print('\nDone.')


if __name__ == '__main__':
    main()
