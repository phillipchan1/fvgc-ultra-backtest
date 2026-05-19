#!/usr/bin/env python3
"""
Study: 8-year IS/OOS validation of the Notion "FVGC To Opening Range H/L" play.

Uses cached baseline trades (no signal regen). Computes OR + sweeps from candles.

Notion A+ cell (n=28, 71.4% WR, 5.00 PF, tuned 2023-10..2025-10):
  1. OR set at 9:45 (15-min OR from 9:30:00-9:44:59 ET)
  2. Neither OR side swept at entry time (loose: any wick beyond)
  3. OR close bias:
       bias = (close_at_9:45 - OR.L) / (OR.H - OR.L)
       bias >= 0.60  -> short toward OR.L
       bias <= 0.40  -> long  toward OR.H
       else          -> skip (middle 20%)
  4. R-to-OR < 1.0 (dist_to_opposite_OR / sl_dist)
  5. SL 25-35 pts inclusive
  6. Entry 9:45-10:15 ET
  7. Target = 2R, hold original SL

Splits:
  IS  = 2023-10-01 .. 2025-10-31  (Notion training window)
  OOS = everything else  (2018 .. 2023-09  +  2025-11 .. 2026-05)

Run from repo root:
  python studies/or_hl_play_8yr_validation/run.py
"""

import sys
from pathlib import Path
from datetime import time as dtime, date

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd

from fvgc.constants import NY_TZ

STUDY_DIR = Path(__file__).resolve().parent
RESULTS_DIR = STUDY_DIR / 'results'

TIMEFRAMES = {
    '30s': {
        'trades': ROOT / 'studies' / 'baseline' / 'results' / 'trades.csv',
        'candles': ROOT / 'data' / 'consolidated' / 'nq-front-month.ohlcv-30s.parquet',
    },
    '1m': {
        'trades': ROOT / 'studies' / 'baseline_1m' / 'results' / 'trades.csv',
        'candles': ROOT / 'data' / 'consolidated' / 'nq-front-month.ohlcv-1m.parquet',
    },
}

OR_START = dtime(9, 30)
OR_END = dtime(9, 45)
SWEEP_WINDOW_END = dtime(10, 15)
ENTRY_AFTER = dtime(9, 45)
ENTRY_END = dtime(10, 15)

BIAS_HIGH = 0.60
BIAS_LOW  = 0.40
R_TO_OR_MAX = 1.0
SL_MIN_PTS = 25
SL_MAX_PTS = 35
TARGET_R = 2.0

IS_START = date(2023, 10, 1)
IS_END   = date(2025, 10, 31)


def load_candles(path: Path) -> pd.DataFrame:
    df = pd.read_parquet(path, columns=['timestamp_ny', 'open', 'high', 'low', 'close'])
    if df['timestamp_ny'].dt.tz is None:
        df['timestamp_ny'] = df['timestamp_ny'].dt.tz_localize(NY_TZ)
    df = df.sort_values('timestamp_ny').reset_index(drop=True)
    return df


def compute_or_table(candles: pd.DataFrame) -> pd.DataFrame:
    """Per day OR.H/L, OR close bias, first H/L sweep time (loose)."""
    df = candles.copy()
    df['date'] = df['timestamp_ny'].dt.date
    df['t'] = df['timestamp_ny'].dt.time

    or_mask = (df['t'] >= OR_START) & (df['t'] < OR_END)
    post_mask = (df['t'] >= OR_END) & (df['t'] < SWEEP_WINDOW_END)

    rows = []
    or_grp = df[or_mask].groupby('date')
    post_grp = {d: g for d, g in df[post_mask].groupby('date')}

    for date_, or_bars in or_grp:
        orh = or_bars['high'].max()
        orl = or_bars['low'].min()
        or_range = orh - orl
        if or_range <= 0:
            continue
        or_close = or_bars['close'].iloc[-1]
        bias = (or_close - orl) / or_range

        post = post_grp.get(date_)
        h_sweep_t = None
        l_sweep_t = None
        if post is not None and len(post):
            hs = post[post['high'] > orh]
            ls = post[post['low']  < orl]
            if len(hs):
                h_sweep_t = hs['timestamp_ny'].iloc[0]
            if len(ls):
                l_sweep_t = ls['timestamp_ny'].iloc[0]

        rows.append({
            'date': date_, 'or_high': orh, 'or_low': orl, 'or_range': or_range,
            'or_close': or_close, 'or_close_bias': bias,
            'h_sweep_at': h_sweep_t, 'l_sweep_at': l_sweep_t,
        })
    return pd.DataFrame(rows)


def select_play_trades(trades: pd.DataFrame, or_df: pd.DataFrame) -> pd.DataFrame:
    trades = trades.copy()
    trades['timestamp'] = pd.to_datetime(trades['timestamp'])
    if trades['timestamp'].dt.tz is None:
        trades['timestamp'] = trades['timestamp'].dt.tz_localize(NY_TZ, ambiguous='infer', nonexistent='shift_forward')
    trades['date'] = trades['timestamp'].dt.date
    trades['t'] = trades['timestamp'].dt.time

    # filter to tradeable + window + valid SL
    trades = trades[trades['outcome'].isin(['win', 'loss', 'eod'])]
    trades = trades[(trades['t'] >= ENTRY_AFTER) & (trades['t'] < ENTRY_END)]
    trades = trades[trades['sl_dist'].notna() & (trades['sl_dist'] > 0)]
    trades['mfe_r'] = trades['mfe_r'].fillna(0)

    # SL bucket
    trades = trades[(trades['sl_dist'] >= SL_MIN_PTS) & (trades['sl_dist'] <= SL_MAX_PTS)]

    # join OR
    trades = trades.merge(or_df, on='date', how='inner')

    # neither side swept by entry
    h_not = trades['h_sweep_at'].isna() | (trades['h_sweep_at'] > trades['timestamp'])
    l_not = trades['l_sweep_at'].isna() | (trades['l_sweep_at'] > trades['timestamp'])
    trades = trades[h_not & l_not]

    # bias-aligned direction
    long_ok  = (trades['or_close_bias'] <= BIAS_LOW)  & (trades['direction'] == 'long')
    short_ok = (trades['or_close_bias'] >= BIAS_HIGH) & (trades['direction'] == 'short')
    trades = trades[long_ok | short_ok]

    # dist to opposite OR + R-to-OR < 1.0
    trades['dist_to_target'] = trades.apply(
        lambda r: (r['or_high'] - r['entry_price']) if r['direction'] == 'long'
        else (r['entry_price'] - r['or_low']), axis=1)
    trades = trades[trades['dist_to_target'] > 0]
    trades['r_to_or'] = trades['dist_to_target'] / trades['sl_dist']
    trades = trades[trades['r_to_or'] < R_TO_OR_MAX]

    # 2R outcome from MFE
    def outcome_2r(row):
        if row['outcome'] == 'loss':
            return 'LOSS', -1.0
        if row['mfe_r'] >= TARGET_R:
            return 'WIN', TARGET_R
        return 'PARTIAL', 0.0

    o2r = trades.apply(outcome_2r, axis=1, result_type='expand')
    o2r.columns = ['outcome_2r', 'pnl_r']
    trades = pd.concat([trades.reset_index(drop=True), o2r.reset_index(drop=True)], axis=1)

    keep = ['timestamp', 'date', 'direction', 'variant', 'entry_price',
            'sl_dist', 'or_high', 'or_low', 'or_close_bias', 'dist_to_target',
            'r_to_or', 'mfe_r', 'outcome', 'outcome_2r', 'pnl_r']
    return trades[keep].sort_values('timestamp').reset_index(drop=True)


def stats(df: pd.DataFrame) -> dict:
    n = len(df)
    if n == 0:
        return {'n': 0, 'wins': 0, 'losses': 0, 'partial': 0,
                'wr': float('nan'), 'pf': float('nan'), 'ev_r': float('nan'),
                'sum_r': 0.0}
    wins   = int((df['outcome_2r'] == 'WIN').sum())
    losses = int((df['outcome_2r'] == 'LOSS').sum())
    part   = int((df['outcome_2r'] == 'PARTIAL').sum())
    decided = wins + losses
    wr = wins / decided * 100 if decided else float('nan')
    gross_w = wins * TARGET_R
    gross_l = losses * 1.0
    pf = (gross_w / gross_l) if gross_l > 0 else float('inf')
    sum_r = float(df['pnl_r'].sum())
    return {'n': n, 'wins': wins, 'losses': losses, 'partial': part,
            'wr': wr, 'pf': pf, 'ev_r': sum_r / n, 'sum_r': sum_r}


def fmt(s: dict) -> str:
    if s['n'] == 0:
        return "n=0"
    pf_str = f"{s['pf']:5.2f}" if s['pf'] != float('inf') else "  inf"
    return (f"n={s['n']:4d}  W={s['wins']:3d} L={s['losses']:3d} P={s['partial']:3d}  "
            f"WR={s['wr']:5.1f}%  PF={pf_str}  EV={s['ev_r']:+.3f}R  sumR={s['sum_r']:+6.1f}")


def run_tf(tf: str, paths: dict):
    print(f"\n{'#'*72}")
    print(f"  TIMEFRAME: {tf}")
    print(f"{'#'*72}")
    print(f"  Trades CSV: {paths['trades'].name}")
    trades = pd.read_csv(paths['trades'])
    print(f"  Loaded {len(trades):,} trade rows")

    print(f"  Candles: {paths['candles'].name}")
    candles = load_candles(paths['candles'])
    print(f"  Loaded {len(candles):,} bars  "
          f"{candles['timestamp_ny'].min()} -> {candles['timestamp_ny'].max()}")

    or_df = compute_or_table(candles)
    print(f"  OR table: {len(or_df)} trading days")

    play = select_play_trades(trades, or_df)
    print(f"  Qualifying play trades: {len(play)}")
    if not len(play):
        return

    out = RESULTS_DIR / f'play_trades_{tf}.csv'
    play.to_csv(out, index=False)
    print(f"  Wrote {out}")

    # Splits
    is_mask = (play['date'] >= IS_START) & (play['date'] <= IS_END)
    is_df, oos_df = play[is_mask], play[~is_mask]

    print(f"\n  {'─'*70}")
    print(f"  IS  ({IS_START} .. {IS_END}):  {fmt(stats(is_df))}")
    print(f"  OOS (rest of 8yr)         :  {fmt(stats(oos_df))}")
    print(f"  ALL 8yr                   :  {fmt(stats(play))}")
    print(f"  {'─'*70}")

    print(f"\n  --- Direction (ALL 8yr) ---")
    for d in ('long', 'short'):
        print(f"  {d:6s}  {fmt(stats(play[play['direction'] == d]))}")

    print(f"\n  --- Variant (ALL 8yr) ---")
    for v in sorted(play['variant'].unique()):
        print(f"  {v:18s}  {fmt(stats(play[play['variant'] == v]))}")

    print(f"\n  --- OOS yearly ---")
    oos = oos_df.copy()
    oos['year'] = oos['date'].apply(lambda x: x.year)
    for y in sorted(oos['year'].unique()):
        print(f"  {y}  {fmt(stats(oos[oos['year'] == y]))}")

    print(f"\n  --- IS yearly (sanity) ---")
    iy = is_df.copy()
    iy['year'] = iy['date'].apply(lambda x: x.year)
    for y in sorted(iy['year'].unique()):
        print(f"  {y}  {fmt(stats(iy[iy['year'] == y]))}")

    # monthly
    m = play.copy()
    m['month'] = m['date'].apply(lambda x: x.strftime('%Y-%m'))
    monthly = (m.groupby('month').apply(stats).apply(pd.Series))
    monthly.to_csv(RESULTS_DIR / f'monthly_{tf}.csv')
    print(f"\n  Wrote monthly_{tf}.csv  ({len(monthly)} months)")


def main():
    print("=" * 72)
    print("  FVGC -> OR H/L  —  Notion play 8-year IS/OOS validation")
    print(f"  IS: {IS_START} .. {IS_END}   (Notion training window)")
    print(f"  Stack: bias [<= {BIAS_LOW} | >= {BIAS_HIGH}]  +  R-to-OR < {R_TO_OR_MAX}  "
          f"+  SL {SL_MIN_PTS}-{SL_MAX_PTS}pts  +  neither swept")
    print(f"  Target: {TARGET_R}R, hold SL  |  PARTIAL = MFE<{TARGET_R}R and SL not hit (count as 0R)")
    print("=" * 72)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    for tf, paths in TIMEFRAMES.items():
        if not paths['trades'].exists():
            print(f"\n  Skipping {tf}: {paths['trades']} missing")
            continue
        run_tf(tf, paths)
    print("\nDone.")


if __name__ == '__main__':
    main()
