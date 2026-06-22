#!/usr/bin/env python3
"""
Near-miss liquidity tagger.

For each trading day, scan W1 bars (9:30–10:15 ET) on 30s candles and emit
a per-day record indicating whether a "near miss draw" event occurred:
  - price made an impulsive move (≥15 pts within a rolling 10-bar / 5-min window)
  - toward a named liquidity level — either a pre-market session level
    (asia_high/low, 6am_high/low, prev_day_high/low) OR a large in-session
    15m/5m FVG (≥15 pts) that formed during W1
  - came within 20 pts of the level without touching it
  - then reversed ≥5 pts before end of W1

In-session FVG levels are time-gated: a 15m or 5m FVG is only eligible as a
near-miss target from windows that start AFTER the FVG's bar closed (causal).

Outputs:
  results/near_miss_days.csv     — one row per trading day
  results/insession_fvgs.csv     — all in-session FVGs detected (for stacked-draw check)

Run from repo root:
  python studies/near_miss_draw/tagger.py
"""

import sys
from datetime import time as dtime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from fvgc.data import load_candles
from fvgc.model import detect_fvg

DATA_PATH = ROOT / 'data' / 'consolidated' / 'nq-front-month.ohlcv-30s.csv'
LEVELS_PATH = ROOT / 'data' / 'levels' / 'session_levels.csv'
STUDY_DIR = Path(__file__).resolve().parent
RESULTS_DIR = STUDY_DIR / 'results'

W1_START = dtime(9, 30, 0)
W1_END = dtime(10, 15, 0)

WINDOW_BARS = 10            # 10 × 30s = 5 minutes
MIN_MOVE_PTS = 15.0         # minimum impulsive leg size
NEAR_MISS_THRESHOLD = 20.0  # max distance from level to qualify
MIN_REVERSAL_PTS = 5.0      # reversal required to confirm near miss

INSESSION_FVG_MIN_SIZE = 15.0   # minimum gap for in-session 15m/5m FVGs

TARGET_LEVEL_NAMES = frozenset({
    'asia_high', 'asia_low',
    '6am_high', '6am_low',
    'prev_day_high', 'prev_day_low',
})


# ---------------------------------------------------------------------------
# In-session FVG detection
# ---------------------------------------------------------------------------

def _resample_day(candles_day: pd.DataFrame, minutes: int) -> pd.DataFrame:
    """Resample a single day's 30s candles to N-minute bars."""
    df = candles_day[['timestamp_ny', 'open', 'high', 'low', 'close']].copy()
    df = df.set_index('timestamp_ny')
    g = df.resample(f'{minutes}min', label='right', closed='right').agg(
        open=('open', 'first'),
        high=('high', 'max'),
        low=('low', 'min'),
        close=('close', 'last'),
    ).dropna(subset=['open']).reset_index()
    return g


def detect_insession_fvgs(candles_day: pd.DataFrame) -> list:
    """
    Detect 15m and 5m FVGs ≥INSESSION_FVG_MIN_SIZE whose bar closes during W1.

    Returns a list of level dicts (compatible with the day_levels format used in
    scan_day) plus an 'available_time' field (the time the FVG bar closed).

    Bearish FVG (gap above current price) → resistance target for upward near misses.
      price to check: bottom of gap = c3_high  (first level price reaches going up)
    Bullish FVG (gap below current price) → support target for downward near misses.
      price to check: top of gap = c3_low  (first level price reaches going down)
    """
    levels = []
    for minutes, tf in [(15, '15m'), (5, '5m')]:
        resampled = _resample_day(candles_day, minutes)
        if len(resampled) < 3:
            continue

        for i in range(2, len(resampled)):
            bar_ts = resampled.iloc[i]['timestamp_ny']
            bar_t = bar_ts.time() if hasattr(bar_ts, 'time') else bar_ts.to_pydatetime().time()

            # Only bars that close within W1
            if not (W1_START <= bar_t < W1_END):
                continue

            c1 = resampled.iloc[i - 2]
            c3 = resampled.iloc[i]

            # Bearish FVG: c1_low > c3_high  →  gap sits ABOVE c3 price
            # Near-miss from below: upward move approaches c3_high (bottom of gap)
            gap = float(c1['low']) - float(c3['high'])
            if gap >= INSESSION_FVG_MIN_SIZE:
                levels.append({
                    'level_name': f'insession_{tf}_bearish',
                    'side': 'resistance',
                    'price': float(c3['high']),      # bottom of gap = first resistance level
                    'fvg_top': float(c1['low']),
                    'fvg_bottom': float(c3['high']),
                    'gap_size': round(gap, 2),
                    'timeframe': tf,
                    'fvg_direction': 'bearish',
                    'available_time': bar_t,          # causal gate
                })

            # Bullish FVG: c1_high < c3_low  →  gap sits BELOW c3 price
            # Near-miss from above: downward move approaches c3_low (top of gap)
            gap = float(c3['low']) - float(c1['high'])
            if gap >= INSESSION_FVG_MIN_SIZE:
                levels.append({
                    'level_name': f'insession_{tf}_bullish',
                    'side': 'support',
                    'price': float(c3['low']),        # top of gap = first support level
                    'fvg_top': float(c3['low']),
                    'fvg_bottom': float(c1['high']),
                    'gap_size': round(gap, 2),
                    'timeframe': tf,
                    'fvg_direction': 'bullish',
                    'available_time': bar_t,
                })

    return levels


# ---------------------------------------------------------------------------
# Near-miss scan
# ---------------------------------------------------------------------------

def count_fvgs_in_window(
    candles: pd.DataFrame,
    start_global: int,
    end_global: int,
    direction: str,
) -> int:
    """Count FVGs of matching direction created between start_global and end_global (inclusive)."""
    fvg_dir = 'bullish' if direction == 'up' else 'bearish'
    count = 0
    for i in range(max(2, start_global), end_global + 1):
        fvg = detect_fvg(candles, i)
        if fvg is not None and fvg['direction'] == fvg_dir:
            count += 1
    return count


def scan_day(
    w1_idx: list,
    candles: pd.DataFrame,
    day_levels: pd.DataFrame,
) -> Optional[dict]:
    """
    Scan one day's W1 bars for a near-miss event.

    day_levels must have columns: level_name, side, price, and optionally
    available_time (dtime or None/NaN). Pre-market levels have available_time=None
    (always eligible). In-session FVG levels have a specific available_time — they
    are only eligible for windows whose start bar closes AFTER that time.

    Returns the nearest confirmed near-miss dict, or None if none found.
    """
    if len(w1_idx) < WINDOW_BARS:
        return None

    best: Optional[dict] = None

    for i in range(WINDOW_BARS - 1, len(w1_idx)):
        window_global = w1_idx[i - WINDOW_BARS + 1 : i + 1]
        window_start_time = candles.loc[window_global[0]]['time_ny']

        window_df = candles.loc[window_global]
        win_high = float(window_df['high'].max())
        win_low = float(window_df['low'].min())

        if win_high - win_low < MIN_MOVE_PTS:
            continue

        high_pos = int(window_df['high'].values.argmax())
        low_pos = int(window_df['low'].values.argmin())

        if high_pos == low_pos:
            continue

        if low_pos < high_pos:
            direction = 'up'
            extreme = win_high
            extreme_global = window_global[high_pos]
            leg_start_global = window_global[0]
        else:
            direction = 'down'
            extreme = win_low
            extreme_global = window_global[low_pos]
            leg_start_global = window_global[0]

        extreme_w1_pos = w1_idx.index(extreme_global)
        remaining_global = w1_idx[extreme_w1_pos + 1:]

        if not remaining_global:
            continue

        remaining_df = candles.loc[remaining_global]

        if direction == 'up':
            reversal_extent = extreme - float(remaining_df['low'].min())
            confirmed_mask = remaining_df['low'] <= extreme - MIN_REVERSAL_PTS
        else:
            reversal_extent = float(remaining_df['high'].max()) - extreme
            confirmed_mask = remaining_df['high'] >= extreme + MIN_REVERSAL_PTS

        if reversal_extent < MIN_REVERSAL_PTS:
            continue

        confirmed_rows = remaining_df[confirmed_mask]
        if confirmed_rows.empty:
            continue
        confirmed_time = confirmed_rows.iloc[0]['timestamp_ny']

        # Filter levels available at this window's start time
        for _, lv in day_levels.iterrows():
            at = lv.get('available_time')
            if at is not None and not (isinstance(at, float) and np.isnan(at)):
                if at > window_start_time:
                    continue  # FVG formed after window start — not yet known

            lx = float(lv['price'])
            lside = str(lv['side'])
            lname = str(lv['level_name'])

            if direction == 'up':
                if lside != 'resistance':
                    continue
                distance = lx - extreme
            else:
                if lside != 'support':
                    continue
                distance = extreme - lx

            if not (0 < distance <= NEAR_MISS_THRESHOLD):
                continue

            gap_count = count_fvgs_in_window(candles, leg_start_global, extreme_global, direction)

            candidate = {
                'near_miss_present': True,
                'near_miss_direction': direction,
                'near_miss_level_type': lname,
                'near_miss_level_price': round(lx, 4),
                'near_miss_distance_pts': round(distance, 2),
                'near_miss_gap_count': gap_count,
                'near_miss_confirmed_time': confirmed_time.strftime('%Y-%m-%d %H:%M:%S'),
            }

            if best is None or distance < best['near_miss_distance_pts']:
                best = candidate

    return best


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print('Loading 30s candles...')
    candles = load_candles(DATA_PATH)
    candles = candles.reset_index(drop=True)
    candles['date_ny'] = candles['timestamp_ny'].dt.date
    candles['time_ny'] = candles['timestamp_ny'].dt.time

    print('Loading session levels...')
    levels_df = pd.read_csv(LEVELS_PATH, low_memory=False)
    levels_df['date'] = pd.to_datetime(levels_df['date']).dt.date
    levels_df['price'] = pd.to_numeric(levels_df['price'], errors='coerce')
    levels_df = levels_df[
        levels_df['level_name'].isin(TARGET_LEVEL_NAMES) &
        levels_df['price'].notna() &
        (levels_df['swept_pre_rth'] != True)  # noqa: E712
    ].copy()
    levels_df['available_time'] = None  # pre-market: always available

    levels_by_date = {d: g for d, g in levels_df.groupby('date')}

    all_dates = sorted(candles['date_ny'].unique())
    w1_mask = (candles['time_ny'] >= W1_START) & (candles['time_ny'] < W1_END)

    day_rows = []
    insession_fvg_rows = []

    for d in all_dates:
        day_mask = candles['date_ny'] == d
        day_candles = candles[day_mask].copy()
        w1_idx = candles[day_mask & w1_mask].index.tolist()

        null_row = {
            'date': d,
            'near_miss_present': False,
            'near_miss_direction': None,
            'near_miss_level_type': None,
            'near_miss_level_price': None,
            'near_miss_distance_pts': None,
            'near_miss_gap_count': 0,
            'near_miss_confirmed_time': None,
        }

        if not w1_idx:
            day_rows.append(null_row)
            continue

        # Pre-market levels
        premarket = levels_by_date.get(d)

        # In-session FVGs (15m + 5m, ≥15pts)
        insession = detect_insession_fvgs(day_candles)
        for fvg in insession:
            insession_fvg_rows.append({'date': d, **fvg})

        # Merge into one levels DataFrame for the scan
        level_frames = []
        if premarket is not None and not premarket.empty:
            pm = premarket[['level_name', 'side', 'price', 'available_time']].copy()
            level_frames.append(pm)
        if insession:
            is_df = pd.DataFrame([{
                'level_name': f['level_name'],
                'side': f['side'],
                'price': f['price'],
                'available_time': f['available_time'],
            } for f in insession])
            level_frames.append(is_df)

        if not level_frames:
            day_rows.append(null_row)
            continue

        day_levels = pd.concat(level_frames, ignore_index=True)

        result = scan_day(w1_idx, candles, day_levels)
        if result is None:
            day_rows.append(null_row)
        else:
            day_rows.append({'date': d, **result})

    # Write near_miss_days.csv
    out = pd.DataFrame(day_rows)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / 'near_miss_days.csv'
    out.to_csv(out_path, index=False)

    # Write insession_fvgs.csv
    fvg_out = pd.DataFrame(insession_fvg_rows) if insession_fvg_rows else pd.DataFrame(
        columns=['date', 'level_name', 'side', 'price', 'fvg_top', 'fvg_bottom',
                 'gap_size', 'timeframe', 'fvg_direction', 'available_time'])
    fvg_path = RESULTS_DIR / 'insession_fvgs.csv'
    fvg_out.to_csv(fvg_path, index=False)

    n_present = int(out['near_miss_present'].sum())
    n_is_fvgs = len(fvg_out)
    n_is_hits = int(out['near_miss_level_type'].astype(str).str.startswith('insession').sum())
    print(f'Processed {len(out)} days — near miss present on {n_present} days '
          f'({100 * n_present / len(out):.1f}%)')
    print(f'  of which {n_is_hits} near misses are against in-session FVGs')
    print(f'  {n_is_fvgs} total in-session FVGs detected and written to {fvg_path}')
    print(f'Wrote {out_path}')


if __name__ == '__main__':
    main()
