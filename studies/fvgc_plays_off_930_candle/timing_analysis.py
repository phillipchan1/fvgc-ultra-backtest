#!/usr/bin/env python3
"""
Timing analysis for 930 gap shorts:
- When do entries actually happen after FVG creation?
- Are they concentrated in first 5 min, 10 min?
- What's the average delay from FVG to entry?

Run from repo root:
  python studies/fvgc_plays_off_930_candle/timing_analysis.py
"""

import sys
from datetime import time as dtime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd
from fvgc.constants import NY_TZ

TRADES_PATH = ROOT / 'logs' / 'baseline_trades.csv'
STUDY_DIR = Path(__file__).resolve().parent
RESULTS_DIR = STUDY_DIR / 'results'


def fvg_in_opening_window(ts_ny: pd.Timestamp) -> bool:
    if pd.isna(ts_ny):
        return False
    t = ts_ny.time()
    return dtime(9, 29, 30) <= t <= dtime(9, 31, 0)


def minutes_from_fvg_to_entry(fvg_ts, entry_ts) -> float:
    """Minutes between FVG creation and entry execution."""
    if pd.isna(fvg_ts) or pd.isna(entry_ts):
        return float('nan')
    delta = entry_ts - fvg_ts
    return delta.total_seconds() / 60


def entry_time_in_session(ts: pd.Timestamp) -> float:
    """Minutes after 9:30 ET."""
    if pd.isna(ts):
        return float('nan')
    m = (ts.hour - 9) * 60 + (ts.minute - 30) + ts.second / 60
    return m


def main():
    print('=' * 80)
    print('930 Gap Shorts: Entry Timing Analysis')
    print('=' * 80)

    trades = pd.read_csv(TRADES_PATH)
    trades['timestamp'] = pd.to_datetime(trades['timestamp'])
    trades['fvg_created_at'] = pd.to_datetime(trades['fvg_created_at'], errors='coerce')

    # Localize to NY timezone
    if trades['fvg_created_at'].dt.tz is None:
        trades['fvg_created_ny'] = trades['fvg_created_at'].dt.tz_localize(
            NY_TZ, ambiguous='infer', nonexistent='shift_forward'
        )
    else:
        trades['fvg_created_ny'] = trades['fvg_created_at'].dt.tz_convert(NY_TZ)

    if trades['timestamp'].dt.tz is None:
        trades['timestamp_ny'] = trades['timestamp'].dt.tz_localize(
            NY_TZ, ambiguous='infer', nonexistent='shift_forward'
        )
    else:
        trades['timestamp_ny'] = trades['timestamp'].dt.tz_convert(NY_TZ)

    # Filter: tradeable, in opening window, shorts only
    trades['in_opening_fvg_window'] = trades['fvg_created_ny'].apply(fvg_in_opening_window)
    base = trades[trades['outcome'].isin(['win', 'loss'])].copy()
    shorts_930 = base[(base['in_opening_fvg_window']) & (base['direction'] == 'short')].copy()

    if len(shorts_930) == 0:
        print("\nNo 930 shorts found in baseline.")
        return

    # Calculate timing metrics
    shorts_930['delay_fvg_to_entry_min'] = shorts_930.apply(
        lambda r: minutes_from_fvg_to_entry(r['fvg_created_ny'], r['timestamp_ny']),
        axis=1
    )
    shorts_930['entry_time_into_session'] = shorts_930['timestamp_ny'].apply(entry_time_in_session)
    shorts_930['entry_time'] = shorts_930['timestamp_ny'].dt.time
    shorts_930['entry_time_str'] = shorts_930['timestamp_ny'].dt.strftime('%H:%M:%S')

    print(f"\nTotal 930 shorts (tradeable): {len(shorts_930)}")
    print("\n" + "=" * 80)
    print("DELAY: FVG Creation → Entry Execution")
    print("=" * 80)

    delay = pd.to_numeric(shorts_930['delay_fvg_to_entry_min'], errors='coerce')
    print(f"\n  Mean delay:        {delay.mean():.2f} minutes")
    print(f"  Median delay:      {delay.median():.2f} minutes")
    print(f"  Min delay:         {delay.min():.2f} minutes")
    print(f"  Max delay:         {delay.max():.2f} minutes")
    print(f"  Std dev:           {delay.std():.2f} minutes")

    print("\n" + "=" * 80)
    print("ENTRY TIMING IN SESSION (minutes after 9:30)")
    print("=" * 80)

    entry_mins = pd.to_numeric(shorts_930['entry_time_into_session'], errors='coerce')
    print(f"\n  Mean entry time:   {entry_mins.mean():.2f} min after 9:30 (≈ {9 + entry_mins.mean()/60:.2f} ET)")
    print(f"  Median entry time: {entry_mins.median():.2f} min after 9:30 (≈ {9 + entry_mins.median()/60:.2f} ET)")
    print(f"  Min entry time:    {entry_mins.min():.2f} min after 9:30")
    print(f"  Max entry time:    {entry_mins.max():.2f} min after 9:30")

    print("\n" + "=" * 80)
    print("DISTRIBUTION: When do entries occur?")
    print("=" * 80)

    # Buckets
    buckets = [
        (0, 5, "First 5 min (9:30-9:35)"),
        (5, 10, "6-10 min (9:35-9:40)"),
        (10, 15, "11-15 min (9:40-9:45)"),
        (15, 30, "16-30 min (9:45-10:00)"),
        (30, 60, "31-60 min (10:00-10:30)"),
        (60, float('inf'), "After 60 min (10:30+)"),
    ]

    for min_m, max_m, label in buckets:
        count = ((entry_mins >= min_m) & (entry_mins < max_m)).sum()
        pct = (count / len(entry_mins) * 100) if len(entry_mins) > 0 else 0

        # WR for this bucket
        bucket_shorts = shorts_930[(entry_mins >= min_m) & (entry_mins < max_m)]
        if len(bucket_shorts) > 0:
            wins = (bucket_shorts['outcome'] == 'win').sum()
            losses = (bucket_shorts['outcome'] == 'loss').sum()
            wr = wins / (wins + losses) * 100 if (wins + losses) > 0 else 0
            print(f"  {label:30s}  n={count:2d} ({pct:5.1f}%)  WR={wr:5.1f}%")
        else:
            print(f"  {label:30s}  n={count:2d} ({pct:5.1f}%)")

    print("\n" + "=" * 80)
    print("ENTRY CLOCK TIMES (actual times of day)")
    print("=" * 80)

    time_buckets = [
        (dtime(9, 30), dtime(9, 35), "9:30-9:35"),
        (dtime(9, 35), dtime(9, 40), "9:35-9:40"),
        (dtime(9, 40), dtime(9, 45), "9:40-9:45"),
        (dtime(9, 45), dtime(10, 0), "9:45-10:00"),
        (dtime(10, 0), dtime(10, 15), "10:00-10:15"),
        (dtime(10, 15), dtime(10, 30), "10:15-10:30"),
    ]

    for start_t, end_t, label in time_buckets:
        count = ((shorts_930['entry_time'] >= start_t) & (shorts_930['entry_time'] < end_t)).sum()
        pct = (count / len(shorts_930) * 100) if len(shorts_930) > 0 else 0

        bucket_shorts = shorts_930[(shorts_930['entry_time'] >= start_t) & (shorts_930['entry_time'] < end_t)]
        if len(bucket_shorts) > 0:
            wins = (bucket_shorts['outcome'] == 'win').sum()
            losses = (bucket_shorts['outcome'] == 'loss').sum()
            wr = wins / (wins + losses) * 100 if (wins + losses) > 0 else 0
            print(f"  {label:15s}  n={count:2d} ({pct:5.1f}%)  WR={wr:5.1f}%")
        else:
            print(f"  {label:15s}  n={count:2d} ({pct:5.1f}%)")

    # Export detailed timing data
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    export_cols = ['timestamp_ny', 'entry_time_str', 'fvg_created_ny', 'delay_fvg_to_entry_min',
                   'entry_time_into_session', 'outcome', 'direction', 'pnl', 'entry_price', 'fvg_bottom', 'fvg_top']
    export_cols = [c for c in export_cols if c in shorts_930.columns]

    export_df = shorts_930[export_cols].copy()
    export_path = RESULTS_DIR / '930_shorts_timing_detail.csv'
    export_df.to_csv(export_path, index=False)
    print(f"\n\nExported detailed timing data to: {export_path.relative_to(ROOT)}")

    print('\nDone.')


if __name__ == '__main__':
    main()
