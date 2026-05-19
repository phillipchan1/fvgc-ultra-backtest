#!/usr/bin/env python3
"""
Core play (Phil's verbal description):
  - Entry >= 9:45 ET
  - Neither OR.H nor OR.L has been swept yet at entry time
  - Any FVGC signal — direction is naturally toward one OR side
  - Play dies the moment either side is swept

No bias, no R-to-OR, no SL bucket filter.

Splits IS (2023-10-01 .. 2025-10-31) vs OOS, reports both 1R and 2R outcomes.

Run from repo root:
  python studies/or_hl_play_8yr_validation/run_core.py
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
        'trades':  ROOT / 'studies' / 'baseline'    / 'results' / 'trades.csv',
        'candles': ROOT / 'data' / 'consolidated' / 'nq-front-month.ohlcv-30s.parquet',
    },
    '1m': {
        'trades':  ROOT / 'studies' / 'baseline_1m' / 'results' / 'trades.csv',
        'candles': ROOT / 'data' / 'consolidated' / 'nq-front-month.ohlcv-1m.parquet',
    },
}

OR_START = dtime(9, 30)
OR_END   = dtime(9, 45)
# Allow entries any time after OR is set, until first sweep cuts off the play.
ENTRY_AFTER = dtime(9, 45)
# We still need a sweep-tracking window; extend a bit past Notion's 10:15
# to allow the play to live a little longer if it hasn't been killed yet.
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

    or_mask   = (df['t'] >= OR_START) & (df['t'] < OR_END)
    # widen sweep tracking out to 11:00 so late "still alive" entries are covered
    post_mask = (df['t'] >= OR_END)   & (df['t'] < SWEEP_WINDOW_END)

    rows = []
    post_grp = {d: g for d, g in df[post_mask].groupby('date')}
    for date_, or_bars in df[or_mask].groupby('date'):
        orh = or_bars['high'].max()
        orl = or_bars['low'].min()
        if orh - orl <= 0:
            continue
        post = post_grp.get(date_)
        h_sweep_t = l_sweep_t = None
        if post is not None and len(post):
            hs = post[post['high'] > orh]
            ls = post[post['low']  < orl]
            if len(hs): h_sweep_t = hs['timestamp_ny'].iloc[0]
            if len(ls): l_sweep_t = ls['timestamp_ny'].iloc[0]
        rows.append({'date': date_, 'or_high': orh, 'or_low': orl,
                     'h_sweep_at': h_sweep_t, 'l_sweep_at': l_sweep_t})
    return pd.DataFrame(rows)


def select_play(trades: pd.DataFrame, or_df: pd.DataFrame) -> pd.DataFrame:
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

    # Direction-toward-OR check: long entries below OR.H, short entries above OR.L.
    # Since play requires "neither side swept" → price is inside OR → both conditions
    # are auto-satisfied; this just trims any edge case where entry sits outside OR.
    long_ok  = (trades['direction'] == 'long')  & (trades['entry_price'] < trades['or_high'])
    short_ok = (trades['direction'] == 'short') & (trades['entry_price'] > trades['or_low'])
    trades = trades[long_ok | short_ok]

    # Neither OR side swept yet at entry time
    h_not = trades['h_sweep_at'].isna() | (trades['h_sweep_at'] > trades['timestamp'])
    l_not = trades['l_sweep_at'].isna() | (trades['l_sweep_at'] > trades['timestamp'])
    trades = trades[h_not & l_not]

    # 1R outcome already in 'outcome'. Compute 2R from MFE.
    def _2r(row):
        if row['outcome'] == 'loss': return 'LOSS'
        if row['mfe_r'] >= 2.0:      return 'WIN'
        return 'PARTIAL'
    trades['outcome_2r'] = trades.apply(_2r, axis=1)
    trades['r_to_or'] = trades.apply(
        lambda r: ((r['or_high'] - r['entry_price']) if r['direction'] == 'long'
                   else (r['entry_price'] - r['or_low'])) / r['sl_dist'], axis=1)

    return trades.sort_values('timestamp').reset_index(drop=True)


def stats_1r(df: pd.DataFrame) -> dict:
    n = len(df)
    if n == 0:
        return {'n': 0}
    wins   = int((df['outcome'] == 'win').sum())
    losses = int((df['outcome'] == 'loss').sum())
    eod    = int((df['outcome'] == 'eod').sum())
    decided = wins + losses
    wr = wins / decided * 100 if decided else float('nan')
    gw = wins * 1.0
    gl = losses * 1.0
    pf = (gw / gl) if gl > 0 else float('inf')
    # EV: wins +1R, losses -1R, eod = pnl/sl_dist
    pnl_r = []
    for _, r in df.iterrows():
        if r['outcome'] == 'win':   pnl_r.append(1.0)
        elif r['outcome'] == 'loss': pnl_r.append(-1.0)
        else:                        pnl_r.append(0.0)
    ev = sum(pnl_r) / n
    return {'n': n, 'wins': wins, 'losses': losses, 'eod': eod,
            'wr': wr, 'pf': pf, 'ev_r': ev, 'sum_r': sum(pnl_r)}


def stats_2r(df: pd.DataFrame) -> dict:
    n = len(df)
    if n == 0:
        return {'n': 0}
    wins   = int((df['outcome_2r'] == 'WIN').sum())
    losses = int((df['outcome_2r'] == 'LOSS').sum())
    part   = int((df['outcome_2r'] == 'PARTIAL').sum())
    decided = wins + losses
    wr = wins / decided * 100 if decided else float('nan')
    pf = (wins * 2.0 / losses) if losses else float('inf')
    pnl = wins * 2.0 - losses * 1.0
    return {'n': n, 'wins': wins, 'losses': losses, 'partial': part,
            'wr': wr, 'pf': pf, 'ev_r': pnl / n, 'sum_r': pnl}


def fmt1(s: dict) -> str:
    if s.get('n', 0) == 0: return "n=0"
    pf = f"{s['pf']:5.2f}" if s['pf'] != float('inf') else "  inf"
    return (f"n={s['n']:4d}  W={s['wins']:3d} L={s['losses']:3d} EOD={s['eod']:3d}  "
            f"WR={s['wr']:5.1f}%  PF={pf}  EV={s['ev_r']:+.3f}R  sumR={s['sum_r']:+6.1f}")


def fmt2(s: dict) -> str:
    if s.get('n', 0) == 0: return "n=0"
    pf = f"{s['pf']:5.2f}" if s['pf'] != float('inf') else "  inf"
    return (f"n={s['n']:4d}  W={s['wins']:3d} L={s['losses']:3d} P={s['partial']:3d}  "
            f"WR={s['wr']:5.1f}%  PF={pf}  EV={s['ev_r']:+.3f}R  sumR={s['sum_r']:+6.1f}")


def run_tf(tf: str, paths: dict):
    print(f"\n{'#'*72}")
    print(f"  TIMEFRAME: {tf}")
    print(f"{'#'*72}")
    trades = pd.read_csv(paths['trades'])
    print(f"  Loaded {len(trades):,} trades ({paths['trades'].name})")
    or_df = compute_or_table(load_candles(paths['candles']))
    print(f"  OR table: {len(or_df)} days")
    play = select_play(trades, or_df)
    print(f"  Qualifying trades: {len(play)}")
    if not len(play):
        return

    play_out = play[['timestamp', 'date', 'direction', 'variant', 'entry_price',
                     'sl_dist', 'or_high', 'or_low', 'r_to_or', 'mfe_r',
                     'outcome', 'outcome_2r']].copy()
    out_path = RESULTS_DIR / f'core_play_{tf}.csv'
    play_out.to_csv(out_path, index=False)
    print(f"  Wrote {out_path}")

    is_mask = (play['date'] >= IS_START) & (play['date'] <= IS_END)
    is_df, oos_df = play[is_mask], play[~is_mask]

    print(f"\n  ── 1R target ──")
    print(f"  IS  {fmt1(stats_1r(is_df))}")
    print(f"  OOS {fmt1(stats_1r(oos_df))}")
    print(f"  ALL {fmt1(stats_1r(play))}")

    print(f"\n  ── 2R target (hold SL) ──")
    print(f"  IS  {fmt2(stats_2r(is_df))}")
    print(f"  OOS {fmt2(stats_2r(oos_df))}")
    print(f"  ALL {fmt2(stats_2r(play))}")

    print(f"\n  ── Direction (ALL 8yr) ──")
    for d in ('long', 'short'):
        sub = play[play['direction'] == d]
        print(f"  1R {d:6s}  {fmt1(stats_1r(sub))}")
        print(f"  2R {d:6s}  {fmt2(stats_2r(sub))}")

    print(f"\n  ── Variant (ALL 8yr, 1R) ──")
    for v in sorted(play['variant'].unique()):
        sub = play[play['variant'] == v]
        print(f"  {v:18s}  {fmt1(stats_1r(sub))}")

    print(f"\n  ── Yearly (1R) ──")
    p = play.copy()
    p['year'] = p['date'].apply(lambda x: x.year)
    for y in sorted(p['year'].unique()):
        flag = "IS " if (IS_START <= date(y, 6, 1) <= IS_END or
                          (y == 2023 and IS_START.year == 2023) or
                          (y == 2025 and IS_END.year == 2025)) else "OOS"
        # simpler: any trade in [IS_START, IS_END] is IS; mixed years exist
        sub = p[p['year'] == y]
        is_sub  = sub[(sub['date'] >= IS_START) & (sub['date'] <= IS_END)]
        oos_sub = sub[~((sub['date'] >= IS_START) & (sub['date'] <= IS_END))]
        if len(is_sub):
            print(f"  {y} IS   {fmt1(stats_1r(is_sub))}")
        if len(oos_sub):
            print(f"  {y} OOS  {fmt1(stats_1r(oos_sub))}")


def main():
    print("=" * 72)
    print("  FVGC -> OR H/L  —  CORE play (Phil's spec), 8-year IS/OOS")
    print("  Filter: entry >= 9:45 AND neither OR side swept yet at entry")
    print(f"  IS: {IS_START} .. {IS_END}")
    print("=" * 72)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    for tf, paths in TIMEFRAMES.items():
        if not paths['trades'].exists():
            print(f"\n  Skipping {tf}"); continue
        run_tf(tf, paths)
    print("\nDone.")


if __name__ == '__main__':
    main()
