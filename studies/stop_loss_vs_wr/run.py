#!/usr/bin/env python3
"""
Study: FVGC baseline win rate vs stop-loss distance (sl_dist).

Uses only logs/baseline_trades.csv — no full backtest, no candle replay.
sl_dist is the model’s rounded stop distance in points (see fvgc.constants).

Run from repo root:
  python studies/stop_loss_vs_wr/run.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd

TRADES_PATH = ROOT / 'logs' / 'baseline_trades.csv'
STUDY_DIR = Path(__file__).resolve().parent
RESULTS_DIR = STUDY_DIR / 'results'


def segment_stats(df: pd.DataFrame) -> dict:
    wins = (df['outcome'] == 'win').sum()
    losses = (df['outcome'] == 'loss').sum()
    n = len(df)
    wr = wins / (wins + losses) * 100 if (wins + losses) else 0.0
    pnl = pd.to_numeric(df['pnl'], errors='coerce')
    return {
        'n': n,
        'wins': int(wins),
        'losses': int(losses),
        'win_rate_pct': round(wr, 2),
        'total_pnl': round(float(pnl.sum()), 2),
        'avg_pnl': round(float(pnl.mean()), 4) if n else 0.0,
    }


def load_tradeable_baseline() -> pd.DataFrame:
    df = pd.read_csv(TRADES_PATH)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df[df['outcome'].isin(['win', 'loss'])].copy()
    df['sl_dist'] = pd.to_numeric(df['sl_dist'], errors='coerce')
    before = len(df)
    df = df[df['sl_dist'].notna()].copy()
    dropped = before - len(df)
    if dropped:
        print(f"  Warning: dropped {dropped} tradeable rows with missing sl_dist")
    return df


def main():
    print('=' * 60)
    print('FVGC baseline — win rate by stop-loss distance (sl_dist)')
    print('=' * 60)

    df = load_tradeable_baseline()
    print(f"\n  {len(df)} tradeable rows from {TRADES_PATH.relative_to(ROOT)}")
    print('  Tradeable = outcome in {win, loss}; rows need numeric sl_dist.')

    sl_values = sorted(df['sl_dist'].unique())
    rows = []
    for sl in sl_values:
        sub = df[df['sl_dist'] == sl]
        st = segment_stats(sub)
        rows.append({'sl_dist': int(sl) if sl == int(sl) else sl, **st})

    summary = pd.DataFrame(rows)
    print('\n--- By sl_dist (points) — all tradeable ---')
    print(summary.to_string(index=False))

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / 'summary_by_sl_dist.csv'
    summary.to_csv(out, index=False)
    print(f"\n  Wrote {out.relative_to(ROOT)}")

    for sl in sl_values:
        sub = df[df['sl_dist'] == sl]
        slug = str(int(sl)) if sl == int(sl) else str(sl).replace('.', '_')
        p = RESULTS_DIR / f'trades_sl_dist_{slug}.csv'
        sub.to_csv(p, index=False)
        print(f"  Wrote {p.relative_to(ROOT)} ({len(sub)} rows)")

    print('\nDone.')


if __name__ == '__main__':
    main()
