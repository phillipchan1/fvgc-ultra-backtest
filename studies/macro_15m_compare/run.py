#!/usr/bin/env python3
"""
Compare win rates across 15-minute macro windows from 9:30 through 11:00 ET.

Six windows: 9:30–9:45, 9:45–10:00, 10:00–10:15, 10:15–10:30, 10:30–10:45, 10:45–11:00.
Uses minutes after 9:30 from entry time (same base as enrich_trade_properties).

Run from repo root:
  python studies/macro_15m_compare/run.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd

from analysis.permutation_test import enrich_trade_properties

TRADES_PATH = ROOT / 'logs' / 'baseline_trades.csv'
STUDY_DIR = Path(__file__).resolve().parent
RESULTS_DIR = STUDY_DIR / 'results'

# macro_15m 1..6 = consecutive 15m blocks from RTH open; 7 = entry at/after 11:00
MACRO_LABELS = {
    1: '9:30-9:45',
    2: '9:45-10:00',
    3: '10:00-10:15',
    4: '10:15-10:30',
    5: '10:30-10:45',
    6: '10:45-11:00',
    7: 'after_11:00',
}


def assign_macro_15m(m) -> int:
    """Minutes after 9:30 -> bucket 1-6 for [0,90), 7 if >= 90, -1 if invalid."""
    if pd.isna(m):
        return -1
    if m < 0:
        return -1
    if m >= 90:
        return 7
    return int(m // 15) + 1


def main():
    print('=' * 60)
    print('15m macros 9:30–11:00 — win rate comparison (baseline trades)')
    print('=' * 60)

    trades = pd.read_csv(TRADES_PATH)
    trades['timestamp'] = pd.to_datetime(trades['timestamp'])
    trades['date'] = trades['timestamp'].dt.date
    trades['entry_time'] = trades['timestamp'].dt.time

    tradeable = trades[trades['outcome'].isin(['win', 'loss'])].copy()
    df = enrich_trade_properties(tradeable)
    df['macro_15m'] = df['minutes_into_session'].apply(assign_macro_15m)
    df['macro_label'] = df['macro_15m'].map(MACRO_LABELS)

    bad = df[df['macro_15m'] < 0]
    if len(bad):
        print(f"\nWarning: {len(bad)} rows with invalid minutes_into_session (skipped).")

    after_11 = df[df['macro_15m'] == 7]
    n_after = len(after_11)
    if n_after:
        print(f"\nNote: {n_after} tradeable entries at/after 11:00 ET (bucket 7, listed separately).")

    main = df[df['macro_15m'].isin(range(1, 7))].copy()

    rows = []
    for m in range(1, 7):
        sub = main[main['macro_15m'] == m]
        wins = (sub['outcome'] == 'win').sum()
        losses = (sub['outcome'] == 'loss').sum()
        n = len(sub)
        wr = wins / (wins + losses) * 100 if (wins + losses) else 0
        pnl = pd.to_numeric(sub['pnl'], errors='coerce').sum()
        rows.append({
            'macro_15m': m,
            'label': MACRO_LABELS[m],
            'n': n,
            'wins': wins,
            'losses': losses,
            'win_rate_pct': round(wr, 2),
            'total_pnl': round(pnl, 2),
        })

    summary = pd.DataFrame(rows)
    print('\n--- All directions (tradeable, 9:30–11:00 window) ---')
    print(summary.to_string(index=False))

    print('\n--- By direction ---')
    for direction in ['long', 'short']:
        print(f'\n  {direction.upper()}')
        for m in range(1, 7):
            sub = main[(main['macro_15m'] == m) & (main['direction'] == direction)]
            wins = (sub['outcome'] == 'win').sum()
            losses = (sub['outcome'] == 'loss').sum()
            wr = wins / (wins + losses) * 100 if (wins + losses) else 0
            pnl = pd.to_numeric(sub['pnl'], errors='coerce').sum()
            print(f"    {MACRO_LABELS[m]:15s}  n={len(sub):4d}  WR={wr:5.1f}%  PnL={pnl:+.1f}")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    for m in range(1, 7):
        sub = main[main['macro_15m'] == m]
        path = RESULTS_DIR / f'trades_macro_{m}.csv'
        sub.to_csv(path, index=False)
        print(f"\n  Wrote {path.relative_to(ROOT)} ({len(sub)} rows)")

    if n_after:
        p = RESULTS_DIR / 'trades_after_11am.csv'
        after_11.to_csv(p, index=False)
        print(f"\n  Wrote {p.relative_to(ROOT)} ({n_after} rows)")

    summary_path = RESULTS_DIR / 'summary_by_macro.csv'
    summary.to_csv(summary_path, index=False)
    print(f"\n  Wrote {summary_path.relative_to(ROOT)}")

    best = summary.loc[summary['win_rate_pct'].idxmax()]
    print(
        f"\nHighest WR (9:30–11:00, six 15m buckets): "
        f"bucket {int(best['macro_15m'])} ({best['label']}) at {best['win_rate_pct']}%"
    )
    print('Done.')


if __name__ == '__main__':
    main()
