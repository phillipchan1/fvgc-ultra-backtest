#!/usr/bin/env python3
"""
Study: FVGC baseline performance by day of week (Monday–Friday).

Uses only logs/baseline_trades.csv — no full backtest, no candle replay.
Weekday is taken from each trade's entry timestamp (session calendar date).

Run from repo root:
  python studies/day_of_week/run.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd

TRADES_PATH = ROOT / 'logs' / 'baseline_trades.csv'
STUDY_DIR = Path(__file__).resolve().parent
RESULTS_DIR = STUDY_DIR / 'results'

DAY_ORDER = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']


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
    df['day_of_week_name'] = df['timestamp'].dt.day_name()
    return df


def main():
    print('=' * 60)
    print('FVGC baseline — performance by day of week')
    print('=' * 60)

    df = load_tradeable_baseline()
    print(f"\n  {len(df)} tradeable rows from {TRADES_PATH.relative_to(ROOT)}")
    print('  Weekday = calendar day of entry timestamp (no trading_days join).')

    rows = []
    for name in DAY_ORDER:
        sub = df[df['day_of_week_name'] == name]
        if sub.empty:
            continue
        st = segment_stats(sub)
        rows.append({'day_of_week_name': name, **st})

    summary = pd.DataFrame(rows)
    print('\n--- All directions (tradeable, Mon–Fri) ---')
    print(summary.to_string(index=False))

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / 'summary_by_day_of_week.csv'
    summary.to_csv(out, index=False)
    print(f"\n  Wrote {out.relative_to(ROOT)}")

    dir_rows = []
    for direction in ['long', 'short']:
        for name in DAY_ORDER:
            sub = df[(df['day_of_week_name'] == name) & (df['direction'] == direction)]
            if sub.empty:
                continue
            st = segment_stats(sub)
            dir_rows.append({'direction': direction, 'day_of_week_name': name, **st})

    by_dir = pd.DataFrame(dir_rows)
    print('\n--- By direction ---')
    for direction in ['long', 'short']:
        sub = by_dir[by_dir['direction'] == direction]
        if sub.empty:
            continue
        print(f"\n  {direction.upper()}")
        print(sub.to_string(index=False))

    by_dir_path = RESULTS_DIR / 'summary_by_day_of_week_by_direction.csv'
    by_dir.to_csv(by_dir_path, index=False)
    print(f"\n  Wrote {by_dir_path.relative_to(ROOT)}")

    _write_trades_by_weekday_csvs(df)

    print('\nDone.')


def _write_trades_by_weekday_csvs(df: pd.DataFrame) -> None:
    for name in DAY_ORDER:
        sub = df[df['day_of_week_name'] == name]
        if sub.empty:
            continue
        p = RESULTS_DIR / f'trades_{name.lower()}.csv'
        sub.to_csv(p, index=False)
        print(f"  Wrote {p.relative_to(ROOT)} ({len(sub)} rows)")


if __name__ == '__main__':
    main()
