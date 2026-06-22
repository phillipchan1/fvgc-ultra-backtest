#!/usr/bin/env python3
"""Data wick play — first study (§15).

v0.4.1 — runs both target modes (structural vs fixed 1R) on the same signal set
so we can isolate where the edge (if any) comes from.
"""

import argparse
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pandas as pd

from fvgc.data import load_candles
from ifvg_reversal.data_wick.engine import TargetMode, simulate_trades
from ifvg_reversal.data_wick.model import generate_signals

DATA_PATH = Path('data/consolidated/nq-front-month.ohlcv-30s.csv')
TRADING_DAYS_PATH = Path('data/trading_days/trading_days.csv')
RESULTS_DIR = Path(__file__).resolve().parent / 'results'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--days', type=int, default=0,
                    help='Last N days of news-covered period. 0 = all available.')
    args = ap.parse_args()

    print("=== Data wick play (§15) — v0.4.1 ===\n")

    t0 = time.time()
    candles = load_candles(DATA_PATH)
    print(f"  candles loaded in {time.time()-t0:.1f}s ({len(candles):,} rows)")

    td = pd.read_csv(TRADING_DAYS_PATH)
    td['date'] = pd.to_datetime(td['date']).dt.date.astype(str)

    news_days = td[
        (td['has_pre_rth_news'] == True) | (td['has_during_session_news'] == True)
    ].copy()
    print(f"  news-day rows: {len(news_days)}  "
          f"({news_days['date'].min()} -> {news_days['date'].max()})")

    if args.days > 0:
        cutoff = news_days['date'].max()
        from datetime import datetime, timedelta
        start = (datetime.fromisoformat(cutoff).date() - timedelta(days=args.days)).isoformat()
        news_days = news_days[news_days['date'] >= start]
        print(f"  tailed to last {args.days} days: {len(news_days)} news days")

    start = news_days['date'].min()
    end = news_days['date'].max()
    candle_mask = (
        (candles['timestamp_ny'].dt.tz_localize(None) >= pd.Timestamp(start)) &
        (candles['timestamp_ny'].dt.tz_localize(None) <= pd.Timestamp(end) + pd.Timedelta(days=1))
    )
    candles = candles[candle_mask].copy()
    print(f"  candles in cohort: {len(candles):,}")

    print("\nGenerating signals...")
    t = time.time()
    signals, rejections = generate_signals(candles, news_days, return_rejections=True)
    print(f"  emitted {len(signals)} signals  ({time.time()-t:.1f}s)")
    if rejections:
        print(f"  rejections: {Counter(r['reason'] for r in rejections)}")
    if not signals:
        return

    by_grade = Counter(s.grade for s in signals)
    by_dir = Counter(s.direction for s in signals)
    by_release = Counter(s.release_label for s in signals)
    print(f"  by grade: {dict(by_grade)}  by direction: {dict(by_dir)}  "
          f"by release: {dict(by_release)}")

    # Run BOTH target modes on the same signal set.
    for mode in (TargetMode.STRUCTURAL, TargetMode.FIXED_1R):
        print(f"\n--- target_mode = {mode.value} ---")
        trades = simulate_trades(signals, candles, target_mode=mode)
        df = _to_df(trades)
        out = RESULTS_DIR / f'data_wick_trades_{mode.value}.csv'
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        df.to_csv(out, index=False)
        _print_summary(df, mode)
        print(f"  -> {out}")

    print()


def _to_df(trades):
    rows = []
    for t in trades:
        rows.append({
            'entry_ts': t.entry_timestamp_ny,
            'direction': t.direction,
            'entry_price': t.entry_price,
            'exit_ts': t.exit_timestamp_ny,
            'exit_price': t.exit_price,
            'exit_reason': t.exit_reason,
            'r_multiple': t.r_multiple,
            'pnl_pts': t.pnl_pts,
            'bars_held': t.bars_held,
            'stop_distance_pts': t.stop_distance_pts,
            'target_distance_pts': t.target_distance_pts,
            'stop_kind': t.stop_kind,
            'target_mode': t.target_mode.value,
            'grade': t.signal.grade,
            'release_label': t.signal.release_label,
            'wick_high': t.signal.wick_high,
            'wick_low': t.signal.wick_low,
            'wick_range_pts': t.signal.wick_high - t.signal.wick_low,
            'sweep_level': t.signal.triggering_sweep.level_name,
            'gap_tf': t.signal.target_gap.tf,
            'gap_size_pts': t.signal.target_gap.size_pts,
            'inversion_body_fraction': t.signal.target_gap.inversion_body_fraction,
        })
    return pd.DataFrame(rows)


def _print_summary(df, mode):
    wins = (df['r_multiple'] > 0).sum()
    losses = (df['r_multiple'] < 0).sum()
    flat = (df['r_multiple'] == 0).sum()
    wr = wins / max(wins + losses, 1) * 100
    gw = df.loc[df['r_multiple'] > 0, 'pnl_pts'].sum()
    gl = abs(df.loc[df['r_multiple'] < 0, 'pnl_pts'].sum()) or 1e-9
    print(f"  Trades: {len(df)}  W/L/F: {wins}/{losses}/{flat}  WR: {wr:.1f}%")
    print(f"  PF: {gw/gl:.2f}  Avg R: {df['r_multiple'].mean():+.2f}  "
          f"Total P&L: {df['pnl_pts'].sum():+.1f} pts")
    print(f"  Stop kind: {df['stop_kind'].value_counts().to_dict()}")
    print(f"  Exit reason: {df['exit_reason'].value_counts().to_dict()}")
    print(f"  Median stop / target: {df['stop_distance_pts'].median():.0f} / "
          f"{df['target_distance_pts'].median():.0f} pts")
    a_plus = df[df['grade'] == 'A+']
    if len(a_plus):
        aw = (a_plus['r_multiple']>0).sum(); al = (a_plus['r_multiple']<0).sum()
        print(f"  A+ subset (N={len(a_plus)}): {aw}W/{al}L  "
              f"WR={aw/max(aw+al,1)*100:.0f}%  P&L={a_plus['pnl_pts'].sum():+.1f}")


if __name__ == '__main__':
    main()
