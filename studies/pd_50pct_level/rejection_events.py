#!/usr/bin/env python3
"""
Detect rejection-wick events off prior-day 50% midpoints and tag trades.

For each trade date, scans 30s RTH bars looking for rejection wicks off
pd_hl_mid and pd_va_mid. A rejection wick is a bar whose range straddles
the mid within tolerance and closes on the away side of the approach.

Produces per-trade flags:
  rej_{mid}_tau{n}_lb{k}  — True if a rejection wick within tau pts of
                            the mid occurred in the last k bars before entry.
  first_fvgc_{mid}_tau{n}_lb{k} — True if (a) the above and (b) no earlier
                            trade in the reversal direction on the same day
                            has a closer rejection event.

Exposed as a function so run.py can call it and receive an augmented trades df.
"""

from __future__ import annotations

from datetime import time as dtime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent

BARS_PATH = ROOT / 'data' / 'consolidated' / 'nq-front-month.ohlcv-30s.csv'
SESSION_LEVELS_PATH = ROOT / 'data' / 'levels' / 'session_levels.csv'
DAILY_VP_PATH = ROOT / 'data' / 'levels' / 'daily_volume_profile.csv'

# 30s bars: 20 bars = 10 minutes
PRIMARY_LOOKBACK_BARS = 20
SENSITIVITY_LOOKBACKS = [10, 20, 40]
PRIMARY_TAU = 3.0
SENSITIVITY_TAUS = [1.0, 3.0]

RTH_START = dtime(9, 30)
RTH_END = dtime(10, 15)  # align with trading window upper bound


def _load_bars_rth() -> pd.DataFrame:
    """Load 30s bars and filter to 9:30–10:15 ET."""
    bars = pd.read_csv(BARS_PATH)
    # timestamp_ny has mixed tz offsets (EST/EDT). Parse via UTC then convert.
    ts_utc = pd.to_datetime(bars['timestamp_utc'], utc=True)
    bars['timestamp_ny'] = ts_utc.dt.tz_convert('America/New_York').dt.tz_localize(None)
    bars['date'] = bars['timestamp_ny'].dt.date
    bars['time'] = bars['timestamp_ny'].dt.time
    in_window = (bars['time'] >= RTH_START) & (bars['time'] <= RTH_END)
    rth = bars[in_window].copy().reset_index(drop=True)
    return rth


def _load_mid_levels() -> pd.DataFrame:
    """Per-date pd_hl_mid and pd_va_mid."""
    sl = pd.read_csv(SESSION_LEVELS_PATH)
    sl = sl[sl['level_name'].isin(['prev_day_high', 'prev_day_low'])].copy()
    sl['date'] = pd.to_datetime(sl['date']).dt.date
    sl['price'] = pd.to_numeric(sl['price'], errors='coerce')
    hl = sl.pivot_table(index='date', columns='level_name', values='price',
                        aggfunc='first').reset_index()
    hl.columns.name = None
    hl['pd_hl_mid'] = (hl['prev_day_high'] + hl['prev_day_low']) / 2.0

    vp = pd.read_csv(DAILY_VP_PATH)
    vp['date'] = pd.to_datetime(vp['date']).dt.date
    vp = vp.sort_values('date').reset_index(drop=True)

    # Prior-day VP: for trade date D, use the VP of the most recent date < D
    vp_dates = vp['date'].tolist()
    vp_by_date = vp.set_index('date')

    def prior_vp(d):
        prior = [x for x in vp_dates if x < d]
        if not prior:
            return (np.nan, np.nan)
        row = vp_by_date.loc[prior[-1]]
        return (row['vah'], row['val'])

    hl['__pair'] = hl['date'].apply(prior_vp)
    hl['prior_vp_vah'] = hl['__pair'].apply(lambda p: p[0])
    hl['prior_vp_val'] = hl['__pair'].apply(lambda p: p[1])
    hl['pd_va_mid'] = (hl['prior_vp_vah'] + hl['prior_vp_val']) / 2.0
    return hl[['date', 'pd_hl_mid', 'pd_va_mid']]


def _detect_rejections_for_day(
    day_bars: pd.DataFrame, mid: float, tau: float
) -> list[int]:
    """Return bar indices (into day_bars) where a rejection wick off `mid` fires.

    A rejection wick requires:
      - bar.high >= mid - tau AND bar.low <= mid + tau        (touch within tau)
      - wick-through magnitude >= 2 pts                       (not a graze)
      - close on the away side of the approach direction
    Approach direction uses mean close of bars [-5:-1] vs mid.
    """
    if len(day_bars) == 0 or np.isnan(mid):
        return []
    highs = day_bars['high'].values
    lows = day_bars['low'].values
    closes = day_bars['close'].values
    events = []
    for i in range(len(day_bars)):
        # Touch condition
        if not (highs[i] >= mid - tau and lows[i] <= mid + tau):
            continue
        # Approach direction — need at least 4 prior bars
        if i < 5:
            continue
        prior_closes = closes[i-5:i-1]
        approach_mean = prior_closes.mean()
        if approach_mean < mid:
            # Approached from below → rejection requires close < mid (down-close)
            if closes[i] >= mid:
                continue
            wick_thru = highs[i] - mid
        elif approach_mean > mid:
            # Approached from above → rejection requires close > mid (up-close)
            if closes[i] <= mid:
                continue
            wick_thru = mid - lows[i]
        else:
            continue
        if wick_thru < 2.0:
            continue
        events.append(i)
    return events


def tag_trades_with_rejections(trades: pd.DataFrame) -> pd.DataFrame:
    """Add rejection flags to trades across (mid, tau, lookback) combos.

    Trade-entry timestamp is matched to the nearest 30s bar <= entry_time
    on the same day; lookback searches the prior K bars.
    """
    trades = trades.copy()
    trades['timestamp'] = pd.to_datetime(trades['timestamp'])
    trades['date'] = trades['timestamp'].dt.date

    bars = _load_bars_rth()
    mids = _load_mid_levels()
    mids_by_date = mids.set_index('date').to_dict('index')

    # Pre-group bars by date for fast access
    bar_groups = {d: g.reset_index(drop=True) for d, g in bars.groupby('date')}

    # Precompute rejection events: dict keyed by (date, mid_name, tau) → list[bar_idx]
    print('  Detecting rejection events per day...')
    event_cache: dict[tuple, list[int]] = {}
    dates_processed = 0
    for d, day_bars in bar_groups.items():
        if d not in mids_by_date:
            continue
        m = mids_by_date[d]
        for mid_name in ('pd_hl_mid', 'pd_va_mid'):
            mid_val = m.get(mid_name, np.nan)
            for tau in SENSITIVITY_TAUS:
                events = _detect_rejections_for_day(day_bars, mid_val, tau)
                event_cache[(d, mid_name, tau)] = events
        dates_processed += 1
    print(f'  Scanned {dates_processed} trading days')

    # For each trade, find its bar index and apply lookback window
    print('  Tagging trades...')
    flag_cols: dict[str, list] = {}
    combos = [
        (mid_name, tau, lb)
        for mid_name in ('pd_hl_mid', 'pd_va_mid')
        for tau in SENSITIVITY_TAUS
        for lb in SENSITIVITY_LOOKBACKS
    ]
    for mid_name, tau, lb in combos:
        flag_cols[f'rej_{mid_name}_tau{int(tau)}_lb{lb}'] = []

    # Store bar_idx per trade to enable first-FVGC dedupe later
    trade_bar_idx = []

    for _, trade in trades.iterrows():
        d = trade['date']
        day_bars = bar_groups.get(d)
        ts = trade['timestamp']
        bar_idx = np.nan
        if day_bars is not None and not day_bars.empty:
            # Nearest bar whose timestamp_ny <= trade timestamp
            le = day_bars[day_bars['timestamp_ny'] <= ts]
            if not le.empty:
                bar_idx = le.index.max()
        trade_bar_idx.append(bar_idx)

        for mid_name, tau, lb in combos:
            col = f'rej_{mid_name}_tau{int(tau)}_lb{lb}'
            if np.isnan(bar_idx) or (d, mid_name, tau) not in event_cache:
                flag_cols[col].append(False)
                continue
            events = event_cache[(d, mid_name, tau)]
            lo = max(0, int(bar_idx) - lb)
            hi = int(bar_idx)  # rejection must be strictly before entry bar
            hit = any(lo <= e < hi for e in events)
            flag_cols[col].append(hit)

    for col, vals in flag_cols.items():
        trades[col] = vals
    trades['_bar_idx'] = trade_bar_idx

    # first_fvgc_reversal: dedupe per (date, reversal_direction) using the earliest
    # qualifying trade after each rejection event. Only compute for primary
    # combo (tau=3, lb=20) — matches plan's pre-registration.
    print('  Computing first-FVGC-reversal flags (primary combo)...')
    for mid_name in ('pd_hl_mid', 'pd_va_mid'):
        primary_col = f'rej_{mid_name}_tau{int(PRIMARY_TAU)}_lb{PRIMARY_LOOKBACK_BARS}'
        out_col = f'first_fvgc_{mid_name}_tau{int(PRIMARY_TAU)}_lb{PRIMARY_LOOKBACK_BARS}'
        flags = []
        # Group by (date, direction) so "first FVGC" is per-day, per-direction.
        trades_sorted = trades.sort_values(['date', 'timestamp']).copy()
        trades_sorted['_row'] = np.arange(len(trades_sorted))
        seen: dict[tuple, bool] = {}
        first_rows: set[int] = set()
        for _, t in trades_sorted.iterrows():
            if not t[primary_col]:
                continue
            key = (t['date'], t['direction'])
            if key in seen:
                continue
            seen[key] = True
            first_rows.add(int(t['_row']))
        # Reindex back to original order
        mask = trades_sorted['_row'].isin(first_rows)
        trades_sorted[out_col] = mask
        trades = trades_sorted.sort_index()[trades.columns.tolist() + [out_col]]

    trades = trades.drop(columns=['_bar_idx'])
    return trades


if __name__ == '__main__':
    # Smoke test
    t = pd.read_csv(ROOT / 'data' / 'levels' / 'trades_with_pd_mid.csv')
    out = tag_trades_with_rejections(t)
    primary_hl = f'rej_pd_hl_mid_tau{int(PRIMARY_TAU)}_lb{PRIMARY_LOOKBACK_BARS}'
    primary_va = f'rej_pd_va_mid_tau{int(PRIMARY_TAU)}_lb{PRIMARY_LOOKBACK_BARS}'
    print(f'\nPrimary combo tagging results:')
    print(f'  {primary_hl}: {out[primary_hl].sum()} / {len(out)}')
    print(f'  {primary_va}: {out[primary_va].sum()} / {len(out)}')
    first_hl = f'first_fvgc_pd_hl_mid_tau{int(PRIMARY_TAU)}_lb{PRIMARY_LOOKBACK_BARS}'
    first_va = f'first_fvgc_pd_va_mid_tau{int(PRIMARY_TAU)}_lb{PRIMARY_LOOKBACK_BARS}'
    print(f'  {first_hl}: {out[first_hl].sum()}')
    print(f'  {first_va}: {out[first_va].sum()}')
