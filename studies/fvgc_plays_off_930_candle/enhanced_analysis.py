#!/usr/bin/env python3
"""
Enhanced 930 gap strategy analysis:
- Break down 930 trades into 5-minute buckets (9:30-9:35, 9:35-9:40, 9:40-9:45)
- Find other correlated factors in winning 930 trades
- Compare 930 shorts to baseline shorts across time windows

Run from repo root:
  python studies/fvgc_plays_off_930_candle/enhanced_analysis.py
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


def parse_args():
    p = argparse.ArgumentParser(description='Enhanced 930 gap strategy analysis')
    p.add_argument('--window', choices=['default', 'tight'], default='default',
                   help='default = 9:29:30–9:31:00 ET; tight = 9:29:30–9:30:30 ET')
    return p.parse_args()


def fvg_in_opening_window(ts_ny: pd.Timestamp, start: dtime, end: dtime) -> bool:
    if pd.isna(ts_ny):
        return False
    t = ts_ny.time()
    return start <= t <= end


def minutes_into_session(ts: pd.Timestamp) -> float:
    """Minutes elapsed since 9:30 ET."""
    if pd.isna(ts):
        return float('nan')
    m = (ts.hour - 9) * 60 + (ts.minute - 30) + ts.second / 60
    return m


def assign_5min_bucket(m: float) -> int:
    """Assign 5-min bucket: 1=9:30-9:35, 2=9:35-9:40, 3=9:40-9:45, etc. -1=invalid."""
    if pd.isna(m) or m < 0:
        return -1
    if m >= 15:  # Beyond first 15 min window
        return -1
    return int(m // 5) + 1


def win_rate_stats(df: pd.DataFrame, label: str) -> dict:
    """Calculate win rate and PnL. Returns dict for easy comparison."""
    sub = df[df['outcome'].isin(['win', 'loss'])]
    if sub.empty:
        return {
            'label': label,
            'n': 0,
            'wins': 0,
            'losses': 0,
            'wr': 0.0,
            'pnl': 0.0,
        }
    wins = (sub['outcome'] == 'win').sum()
    losses = (sub['outcome'] == 'loss').sum()
    wr = wins / (wins + losses) * 100 if (wins + losses) else 0
    pnl = pd.to_numeric(sub['pnl'], errors='coerce').sum()
    return {
        'label': label,
        'n': len(sub),
        'wins': wins,
        'losses': losses,
        'wr': wr,
        'pnl': pnl,
    }


def main():
    args = parse_args()
    wstart, wend = (dtime(9, 29, 30), dtime(9, 30, 30)) if args.window == 'tight' else (dtime(9, 29, 30), dtime(9, 31, 0))

    print('=' * 80)
    print('Enhanced 930 Gap Strategy Analysis')
    print(f'Opening FVG window: {wstart} – {wend} ET')
    print('=' * 80)

    # Load trades
    trades = pd.read_csv(TRADES_PATH)
    trades['timestamp'] = pd.to_datetime(trades['timestamp'])
    trades['fvg_created_at'] = pd.to_datetime(trades['fvg_created_at'], errors='coerce')

    # Localize FVG creation time to NY timezone
    if trades['fvg_created_at'].dt.tz is None:
        trades['fvg_created_ny'] = trades['fvg_created_at'].dt.tz_localize(
            NY_TZ, ambiguous='infer', nonexistent='shift_forward'
        )
    else:
        trades['fvg_created_ny'] = trades['fvg_created_at'].dt.tz_convert(NY_TZ)

    # Localize entry time
    if trades['timestamp'].dt.tz is None:
        trades['timestamp_ny'] = trades['timestamp'].dt.tz_localize(
            NY_TZ, ambiguous='infer', nonexistent='shift_forward'
        )
    else:
        trades['timestamp_ny'] = trades['timestamp'].dt.tz_convert(NY_TZ)

    trades['date'] = trades['timestamp'].dt.date
    trades['entry_time'] = trades['timestamp_ny'].dt.time

    # Add derived fields
    trades['in_opening_fvg_window'] = trades['fvg_created_ny'].apply(
        lambda x: fvg_in_opening_window(x, wstart, wend)
    )
    trades['minutes_into_session'] = trades['timestamp_ny'].apply(minutes_into_session)
    trades['bucket_5min'] = trades['minutes_into_session'].apply(assign_5min_bucket)

    base = trades[trades['outcome'].isin(['win', 'loss'])].copy()
    opening = base[base['in_opening_fvg_window']]

    # ============================================================================
    # 1. BASELINE AND OPENING WINDOW OVERVIEW
    # ============================================================================
    print('\n' + '=' * 80)
    print('1. BASELINE VS 930 OPENING WINDOW')
    print('=' * 80)

    baseline_all = win_rate_stats(base, 'All baseline trades')
    opening_all = win_rate_stats(opening, 'FVG created in 930 window (all directions)')
    print(f"\n{baseline_all['label']:40s}  n={baseline_all['n']:4d}  WR={baseline_all['wr']:5.1f}%  PnL={baseline_all['pnl']:+.1f}")
    print(f"{opening_all['label']:40s}  n={opening_all['n']:4d}  WR={opening_all['wr']:5.1f}%  PnL={opening_all['pnl']:+.1f}")

    for direction in ['long', 'short']:
        stat = win_rate_stats(opening[opening['direction'] == direction], f"  930 {direction}")
        print(f"{stat['label']:40s}  n={stat['n']:4d}  WR={stat['wr']:5.1f}%  PnL={stat['pnl']:+.1f}")

    # ============================================================================
    # 2. BREAK DOWN 930 SHORTS INTO 5-MINUTE BUCKETS (WHERE DO THE WINS COME FROM?)
    # ============================================================================
    print('\n' + '=' * 80)
    print('2. 930 SHORTS BROKEN DOWN INTO 5-MINUTE BUCKETS')
    print('   (When specifically are the 930 short wins concentrated?)')
    print('=' * 80)

    opening_shorts = opening[opening['direction'] == 'short']
    print(f"\nTotal 930 shorts: {len(opening_shorts[opening_shorts['outcome'].isin(['win', 'loss'])])}")

    for bucket in [1, 2, 3]:
        bucket_trades = opening_shorts[opening_shorts['bucket_5min'] == bucket]
        stat = win_rate_stats(bucket_trades, f"  Bucket {bucket} (9:30+{(bucket-1)*5}-{bucket*5} min)")
        if stat['n'] > 0:
            print(f"{stat['label']:40s}  n={stat['n']:4d}  WR={stat['wr']:5.1f}%  PnL={stat['pnl']:+.1f}")

    # ============================================================================
    # 3. ALL BASELINE SHORTS BY 5-MINUTE WINDOW (FOR COMPARISON)
    # ============================================================================
    print('\n' + '=' * 80)
    print('3. ALL BASELINE SHORTS BY 5-MINUTE WINDOW')
    print('   (How do 930 shorts compare to shorts in the first 15 minutes?)')
    print('=' * 80)

    base_shorts = base[base['direction'] == 'short']
    base_shorts['bucket_5min'] = base_shorts['minutes_into_session'].apply(assign_5min_bucket)

    print(f"\nTotal baseline shorts in first 15 min: {len(base_shorts[base_shorts['bucket_5min'].isin([1,2,3])])}")

    for bucket in [1, 2, 3]:
        bucket_trades = base_shorts[base_shorts['bucket_5min'] == bucket]
        stat = win_rate_stats(bucket_trades, f"  Baseline shorts bucket {bucket}")
        if stat['n'] > 0:
            print(f"{stat['label']:40s}  n={stat['n']:4d}  WR={stat['wr']:5.1f}%  PnL={stat['pnl']:+.1f}")

    # ============================================================================
    # 4. OTHER FACTORS IN WINNING 930 SHORTS
    # ============================================================================
    print('\n' + '=' * 80)
    print('4. OTHER CORRELATES IN WINNING 930 SHORTS')
    print('   (What else characterizes the winners?)')
    print('=' * 80)

    winning_930_shorts = opening_shorts[opening_shorts['outcome'] == 'win']
    losing_930_shorts = opening_shorts[opening_shorts['outcome'] == 'loss']

    if len(winning_930_shorts) > 0 and len(losing_930_shorts) > 0:
        print(f"\nWinning 930 shorts (n={len(winning_930_shorts)}):")
        for col in ['fvg_size', 'fvg_top', 'fvg_bottom', 'entry_price', 'entry_offset_from_fvg_bottom',
                    'fill_bar_count', 'stop_loss_distance', 'target_distance']:
            if col in winning_930_shorts.columns:
                val = pd.to_numeric(winning_930_shorts[col], errors='coerce')
                if not val.empty and val.notna().any():
                    print(f"  {col:35s}  mean={val.mean():8.2f}  median={val.median():8.2f}")

        print(f"\nLosing 930 shorts (n={len(losing_930_shorts)}):")
        for col in ['fvg_size', 'fvg_top', 'fvg_bottom', 'entry_price', 'entry_offset_from_fvg_bottom',
                    'fill_bar_count', 'stop_loss_distance', 'target_distance']:
            if col in losing_930_shorts.columns:
                val = pd.to_numeric(losing_930_shorts[col], errors='coerce')
                if not val.empty and val.notna().any():
                    print(f"  {col:35s}  mean={val.mean():8.2f}  median={val.median():8.2f}")

    # ============================================================================
    # 5. EXPORT DETAILED 930 SHORT TRADES FOR INSPECTION
    # ============================================================================
    print('\n' + '=' * 80)
    print('5. EXPORTING TRADE LISTS')
    print('=' * 80)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    # Export 930 shorts
    export_shorts = opening_shorts.copy()
    path_shorts = RESULTS_DIR / f'trades_930_shorts_detailed_{args.window}.csv'
    export_shorts.to_csv(path_shorts, index=False)
    print(f"\n  Wrote {path_shorts.relative_to(ROOT)} ({len(export_shorts)} rows)")

    # Export 930 shorts + 5min bucket
    export_shorts_with_bucket = opening_shorts.copy()
    export_shorts_with_bucket['bucket_5min_label'] = export_shorts_with_bucket['bucket_5min'].apply(
        lambda b: f"9:30+{(b-1)*5}-{b*5}min" if b > 0 else "out_of_window"
    )
    path_shorts_bucket = RESULTS_DIR / f'trades_930_shorts_by_bucket_{args.window}.csv'
    export_shorts_with_bucket.to_csv(path_shorts_bucket, index=False)
    print(f"  Wrote {path_shorts_bucket.relative_to(ROOT)} ({len(export_shorts_with_bucket)} rows)")

    print('\nDone.')


if __name__ == '__main__':
    main()
