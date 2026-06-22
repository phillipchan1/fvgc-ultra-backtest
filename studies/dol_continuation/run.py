#!/usr/bin/env python3
"""DOL Continuation play — MVP backtest.

Setup:
  1. Opposing-direction FVG inverts (candle closes through it in trade direction)
  2. A DOL (Draw on Liquidity) exists in trade direction at >= 1R away
  3. NO unfilled opposing-direction FVGs in the path between entry and DOL
     on ANY of: 30s / 1m / 2m / 3m / 5m
  4. Stop = gap edge + 2pt buffer
  5. Target = DOL (with optional runner to next DOL)

Tradeable TFs: 30s, 1m, 2m, 3m, 5m (each emits independently)
Killzone: 9:45 - 11:00 NY (DOL = OR requires OR-15 known by 9:45)

DOL sources (MVP):
  - or_low / or_high (9:30-9:45 H/L)
  - prev_day_low / prev_day_high
  - running_50pct (intraday midpoint)

Path-clear check: scan FVG inventory across all 5 TFs for UNFILLED
opposing-direction FVGs whose body sits between entry and target.
"""

import sys
import time
from collections import Counter
from datetime import time as dtime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import numpy as np
import pandas as pd

from fvgc.data import load_candles
from shared.fvg import detect_fvg, inverts_fvg
from ifvg_reversal.detectors.multi_tf_fvg import (
    MultiTFGap, _resample_ohlc, _TF_FREQ,
)


# ----- Config -----

DATA_PATH = Path('data/consolidated/nq-front-month.ohlcv-30s.csv')
LEVELS_PATH = Path('data/levels/session_levels.csv')
RESULTS_DIR = Path(__file__).resolve().parent / 'results'

# Cohort: last full year
COHORT_END = pd.Timestamp('2026-05-21')
COHORT_START = pd.Timestamp('2025-05-21')

# Timeframes for FVG detection + path-clear scan
TARGET_TFS = ('30s', '1min', '2min', '3min', '5min')
_TF_FREQ_EXT = {**_TF_FREQ, '5min': '5min'}

# Trade params
MIN_FVG_SIZE = 6.0     # loose; same lower bound we used for population
HARD_STOP_BUFFER = 2.0
MIN_DOL_DISTANCE_R = 1.0   # DOL must be >= 1R away to take the trade
KILLZONE_START = dtime(9, 45)  # OR-15 known
KILLZONE_END = dtime(11, 0)
EOD = dtime(16, 0)


# ----- DOL sources -----

def compute_or(day_candles: pd.DataFrame) -> tuple[float, float]:
    """Opening Range high/low from 9:30-9:45 candles."""
    or_bars = day_candles[
        (day_candles['timestamp_ny'].dt.time >= dtime(9, 30)) &
        (day_candles['timestamp_ny'].dt.time < dtime(9, 45))
    ]
    if or_bars.empty:
        return float('nan'), float('nan')
    return float(or_bars['high'].max()), float(or_bars['low'].min())


def get_pd_levels(levels_df: pd.DataFrame, date_str: str) -> tuple[float, float]:
    """Prior day high/low."""
    row = levels_df[(levels_df['date'] == date_str) &
                    (levels_df['level_name'].isin(['prev_day_high', 'prev_day_low']))]
    pdh = row[row['level_name'] == 'prev_day_high']['price'].iloc[0] if not row[row['level_name']=='prev_day_high'].empty else float('nan')
    pdl = row[row['level_name'] == 'prev_day_low']['price'].iloc[0] if not row[row['level_name']=='prev_day_low'].empty else float('nan')
    return float(pdh), float(pdl)


def running_50pct_at(day_candles: pd.DataFrame, at_ts: pd.Timestamp) -> float:
    """Running 50% from RTH open up to (but not including) at_ts."""
    rth = day_candles[
        (day_candles['timestamp_ny'].dt.time >= dtime(9, 30)) &
        (day_candles['timestamp_ny'] < at_ts)
    ]
    if rth.empty:
        return float('nan')
    h = rth['high'].max(); l = rth['low'].min()
    return (h + l) / 2.0


def find_nearest_dol(
    direction: str,
    entry_price: float,
    at_ts: pd.Timestamp,
    day_candles: pd.DataFrame,
    pdh: float,
    pdl: float,
) -> tuple[str, float] | None:
    """Find nearest DOL in trade direction. Returns (source_name, price) or None."""
    candidates = []

    # OR
    or_high, or_low = compute_or(day_candles)
    if direction == 'short' and not np.isnan(or_low) and or_low < entry_price:
        candidates.append(('or_low', or_low))
    if direction == 'long' and not np.isnan(or_high) and or_high > entry_price:
        candidates.append(('or_high', or_high))

    # Prior day levels
    if direction == 'short' and not np.isnan(pdl) and pdl < entry_price:
        candidates.append(('prev_day_low', pdl))
    if direction == 'long' and not np.isnan(pdh) and pdh > entry_price:
        candidates.append(('prev_day_high', pdh))

    # Running 50%
    mid = running_50pct_at(day_candles, at_ts)
    if direction == 'short' and not np.isnan(mid) and mid < entry_price:
        candidates.append(('running_50pct', mid))
    if direction == 'long' and not np.isnan(mid) and mid > entry_price:
        candidates.append(('running_50pct', mid))

    if not candidates:
        return None

    # Nearest in trade direction
    if direction == 'short':
        return max(candidates, key=lambda x: x[1])  # closest below = highest of the below
    return min(candidates, key=lambda x: x[1])      # closest above = lowest of the above


# ----- FVG inventory across all TFs (with 5m added) -----

def build_full_fvg_inventory(day_candles: pd.DataFrame, min_size: float) -> list[MultiTFGap]:
    """Build FVG inventory for the day across 30s/1m/2m/3m/5m.

    Mirrors build_fvg_inventory but adds 5m and uses ALL day candles (not capped
    at 11:00 — we need full-day for path-clear post-entry checks).
    """
    gaps = []
    if len(day_candles) < 3:
        return gaps
    for tf in TARGET_TFS:
        bars = day_candles if tf == '30s' else _resample_ohlc(day_candles, _TF_FREQ_EXT[tf])
        if len(bars) < 3:
            continue
        for i in range(2, len(bars)):
            c1 = bars.iloc[i - 2]; c2 = bars.iloc[i - 1]; c3 = bars.iloc[i]
            fvg = detect_fvg(c1, c2, c3, min_size=min_size)
            if fvg is None:
                continue
            gaps.append(MultiTFGap(
                created_at=fvg.created_ts,
                tf=tf,
                direction=fvg.direction,
                top=fvg.top,
                bottom=fvg.bottom,
                size_pts=fvg.size,
            ))
    gaps.sort(key=lambda g: (g.created_at, g.tf))
    return gaps


def mark_inversion_times(gaps: list[MultiTFGap], day_candles: pd.DataFrame) -> None:
    """Walk per-TF bars; mark first close-through time per FVG."""
    by_tf = {}
    for g in gaps:
        by_tf.setdefault(g.tf, []).append(g)

    for tf, tf_gaps in by_tf.items():
        bars = day_candles if tf == '30s' else _resample_ohlc(day_candles, _TF_FREQ_EXT[tf])
        open_gaps = sorted(tf_gaps, key=lambda g: g.created_at)
        for _, c in bars.iterrows():
            if not open_gaps:
                break
            ts = c['timestamp_ny']
            still = []
            rng = c['high'] - c['low']
            body = abs(c['close'] - c['open'])
            body_frac = (body / rng) if rng > 0 else 0
            for g in open_gaps:
                if g.created_at >= ts:
                    still.append(g)
                    continue
                if inverts_fvg(g.direction, g.top, g.bottom, c['close']):
                    g.inverted_at = ts
                    g.inversion_candle_ts = ts
                    g.inversion_close_price = float(c['close'])
                    g.inversion_body_fraction = body_frac
                else:
                    still.append(g)
            open_gaps = still


def is_fvg_filled_at(g: MultiTFGap, ts: pd.Timestamp) -> bool:
    """Has the FVG been inverted/filled BEFORE the given timestamp?"""
    return g.inverted_at is not None and g.inverted_at < ts


# ----- Path-clear check -----

def path_is_clear(
    direction: str,
    entry_price: float,
    target_price: float,
    entry_ts: pd.Timestamp,
    excluded_gap: MultiTFGap,
    all_gaps: list[MultiTFGap],
) -> tuple[bool, list[str]]:
    """Returns (clear, [obstruction descriptions])."""
    obstructions = []
    opposing_dir = 'bullish' if direction == 'short' else 'bearish'

    for g in all_gaps:
        if g is excluded_gap:
            continue
        if g.direction != opposing_dir:
            continue
        if g.created_at >= entry_ts:
            continue  # not yet formed at entry
        if is_fvg_filled_at(g, entry_ts):
            continue  # already mitigated before our entry
        # Body sits between entry and target?
        if direction == 'short':
            # Going down. Obstruction if any part of opposing-bullish FVG
            # body sits BELOW entry but ABOVE target.
            if target_price < g.top < entry_price or target_price < g.bottom < entry_price:
                obstructions.append(f"{g.tf} bullish @ [{g.bottom:.1f}, {g.top:.1f}]")
        else:
            if entry_price < g.top < target_price or entry_price < g.bottom < target_price:
                obstructions.append(f"{g.tf} bearish @ [{g.bottom:.1f}, {g.top:.1f}]")

    return (len(obstructions) == 0, obstructions)


# ----- Trade simulation -----

def simulate_dol_trade(
    direction: str,
    entry_price: float,
    entry_ts: pd.Timestamp,
    stop_price: float,
    target_price: float,
    day_candles: pd.DataFrame,
    gap: MultiTFGap,
) -> dict:
    """100% exit at target (DOL). Hard stop OR target OR soft stop OR EOD."""
    stop_d = abs(stop_price - entry_price)
    target_d = abs(target_price - entry_price)
    r_target = target_d / max(stop_d, 1e-9)
    soft_level = gap.top if direction == 'short' else gap.bottom

    forward = day_candles[
        (day_candles['timestamp_ny'] > entry_ts) &
        (day_candles['timestamp_ny'].dt.time <= EOD)
    ]
    if forward.empty or stop_d <= 0:
        return {'exit_reason': 'no_data', 'r_multiple': 0.0, 'bars_held': 0,
                'exit_price': entry_price, 'r_target_planned': r_target}

    for i, c in enumerate(forward.itertuples(index=False), start=1):
        if direction == 'short':
            if c.high >= stop_price:
                return {'exit_reason': 'hard_stop', 'r_multiple': -1.0, 'bars_held': i,
                        'exit_price': stop_price, 'r_target_planned': r_target}
            if c.low <= target_price:
                return {'exit_reason': 'target', 'r_multiple': r_target, 'bars_held': i,
                        'exit_price': target_price, 'r_target_planned': r_target}
            if c.close > soft_level:
                r = (entry_price - c.close) / stop_d
                return {'exit_reason': 'soft_stop', 'r_multiple': r, 'bars_held': i,
                        'exit_price': c.close, 'r_target_planned': r_target}
        else:
            if c.low <= stop_price:
                return {'exit_reason': 'hard_stop', 'r_multiple': -1.0, 'bars_held': i,
                        'exit_price': stop_price, 'r_target_planned': r_target}
            if c.high >= target_price:
                return {'exit_reason': 'target', 'r_multiple': r_target, 'bars_held': i,
                        'exit_price': target_price, 'r_target_planned': r_target}
            if c.close < soft_level:
                r = (c.close - entry_price) / stop_d
                return {'exit_reason': 'soft_stop', 'r_multiple': r, 'bars_held': i,
                        'exit_price': c.close, 'r_target_planned': r_target}

    # EOD
    last = forward.iloc[-1]
    r = ((entry_price - last['close']) if direction == 'short' else (last['close'] - entry_price)) / stop_d
    return {'exit_reason': 'eod', 'r_multiple': r, 'bars_held': len(forward),
            'exit_price': float(last['close']), 'r_target_planned': r_target}


# ----- Main -----

def main():
    print("=== DOL Continuation MVP ===\n")
    t0 = time.time()

    candles = load_candles(DATA_PATH)
    levels = pd.read_csv(LEVELS_PATH)

    # Filter to cohort
    candles = candles[
        (candles['timestamp_ny'].dt.tz_localize(None) >= COHORT_START) &
        (candles['timestamp_ny'].dt.tz_localize(None) <= COHORT_END + pd.Timedelta(days=1))
    ].copy()
    candles['date_ny'] = candles['timestamp_ny'].dt.date.astype(str)
    print(f"Cohort: {COHORT_START.date()} -> {COHORT_END.date()}")
    print(f"  {len(candles):,} 30s candles across {candles['date_ny'].nunique()} sessions")
    print(f"  loaded in {time.time()-t0:.1f}s\n")

    # Per-day processing
    signals = []
    rejections = Counter()
    for date_str, day_full in candles.groupby('date_ny', sort=True):
        day_full = day_full.reset_index(drop=True)

        # Get DOL anchors
        pdh, pdl = get_pd_levels(levels, date_str)

        # Build full-day FVG inventory across all TFs (for path-clear check)
        gaps_full = build_full_fvg_inventory(day_full, min_size=MIN_FVG_SIZE)
        if not gaps_full:
            continue
        mark_inversion_times(gaps_full, day_full)

        # Iterate FVGs whose inversion fired in killzone
        for g in gaps_full:
            if not g.is_inverted:
                continue
            inv_ts = g.inverted_at
            if inv_ts.time() < KILLZONE_START or inv_ts.time() > KILLZONE_END:
                continue

            direction = 'short' if g.direction == 'bullish' else 'long'
            entry_price = g.inversion_close_price
            if direction == 'short':
                stop_price = g.top + HARD_STOP_BUFFER
            else:
                stop_price = g.bottom - HARD_STOP_BUFFER
            stop_d = abs(stop_price - entry_price)
            if stop_d <= 0:
                rejections['bad_stop'] += 1
                continue

            # Find DOL
            dol = find_nearest_dol(direction, entry_price, inv_ts, day_full, pdh, pdl)
            if dol is None:
                rejections['no_dol_in_direction'] += 1
                continue
            dol_name, dol_price = dol
            target_d = abs(dol_price - entry_price)
            r_distance = target_d / stop_d
            if r_distance < MIN_DOL_DISTANCE_R:
                rejections['dol_too_close'] += 1
                continue

            # Path clear check
            clear, obstructions = path_is_clear(
                direction, entry_price, dol_price, inv_ts, g, gaps_full,
            )
            if not clear:
                rejections['path_obstructed'] += 1
                continue

            # Simulate trade
            outcome = simulate_dol_trade(
                direction, entry_price, inv_ts, stop_price, dol_price, day_full, g,
            )

            signals.append({
                'date': date_str,
                'entry_ts': inv_ts,
                'direction': direction,
                'entry_price': entry_price,
                'stop_price': stop_price,
                'target_price': dol_price,
                'target_source': dol_name,
                'gap_tf': g.tf,
                'gap_size_pts': g.size_pts,
                'inversion_body_fraction': g.inversion_body_fraction,
                'stop_distance_pts': stop_d,
                'target_distance_pts': target_d,
                'r_planned': r_distance,
                **outcome,
                'pnl_pts': outcome['r_multiple'] * stop_d,
            })

    print(f"Signals emitted: {len(signals)}")
    print(f"Rejections: {dict(rejections)}\n")

    if not signals:
        print("No trades emitted.")
        return

    df = pd.DataFrame(signals)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(RESULTS_DIR / 'dol_trades.csv', index=False)
    print(f"Wrote {RESULTS_DIR / 'dol_trades.csv'}\n")

    # Summary stats
    w = (df['r_multiple'] > 0).sum(); l = (df['r_multiple'] < 0).sum()
    wr = w / max(w + l, 1) * 100
    gw = df.loc[df['r_multiple'] > 0, 'pnl_pts'].sum()
    gl = abs(df.loc[df['r_multiple'] < 0, 'pnl_pts'].sum()) or 1e-9
    pf = gw / gl

    print("=== Overall ===")
    print(f"  N: {len(df)}")
    print(f"  WR: {wr:.1f}%")
    print(f"  PF: {pf:.2f}")
    print(f"  Avg R: {df['r_multiple'].mean():+.3f}")
    print(f"  Total R: {df['r_multiple'].sum():+.1f}")
    print(f"  By exit reason: {df['exit_reason'].value_counts().to_dict()}")
    print(f"  By direction: {df['direction'].value_counts().to_dict()}")
    print(f"  By gap TF: {df['gap_tf'].value_counts().to_dict()}")
    print(f"  By DOL target: {df['target_source'].value_counts().to_dict()}")

    print(f"\n=== By gap TF ===")
    for tf, sub in df.groupby('gap_tf'):
        w_tf = (sub['r_multiple']>0).sum(); l_tf = (sub['r_multiple']<0).sum()
        gw_tf = sub.loc[sub['r_multiple']>0, 'pnl_pts'].sum()
        gl_tf = abs(sub.loc[sub['r_multiple']<0, 'pnl_pts'].sum()) or 1e-9
        wr_tf = w_tf/max(w_tf+l_tf,1)*100
        print(f"  {tf:5}  N={len(sub):3}  WR={wr_tf:5.1f}%  PF={gw_tf/gl_tf:.2f}  totR={sub['r_multiple'].sum():+.1f}")

    print(f"\n=== By DOL target ===")
    for tgt, sub in df.groupby('target_source'):
        w_t = (sub['r_multiple']>0).sum(); l_t = (sub['r_multiple']<0).sum()
        gw_t = sub.loc[sub['r_multiple']>0, 'pnl_pts'].sum()
        gl_t = abs(sub.loc[sub['r_multiple']<0, 'pnl_pts'].sum()) or 1e-9
        wr_t = w_t/max(w_t+l_t,1)*100
        print(f"  {tgt:18}  N={len(sub):3}  WR={wr_t:5.1f}%  PF={gw_t/gl_t:.2f}  totR={sub['r_multiple'].sum():+.1f}")

    print(f"\nTotal runtime: {time.time()-t0:.1f}s")


if __name__ == '__main__':
    main()
