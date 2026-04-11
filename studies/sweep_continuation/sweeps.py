"""Sweep detection and outcome labeling.

A "sweep event" is the first 30s bar after a level becomes active whose
wick pierces the level:
  - bullish sweep: bar.high > level.price for a 'high'-side level
  - bearish sweep: bar.low  < level.price for a 'low'-side level

Each sweep is classified as:
  - wick_only   : close did not break through (classic reversal signature)
  - run_through : close extended past the level by >= RUN_THROUGH_EPS_ATR * ATR

Outcomes are measured at multiple horizons. For each horizon H we record:
  mfe_past_level  - max favorable excursion past the level (in points)
  mae_back_thru   - max adverse excursion back through the level
  close_at_H      - close price at bar index (sweep_idx + H)
  label_H         - RUN / REVERSE / CHOP based on ATR-normalized thresholds
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from typing import List, Dict


# -------------------------------------------------------------------
# ATR helper (Wilder-style simple)
# -------------------------------------------------------------------

def compute_atr(candles: pd.DataFrame, length: int = 14) -> np.ndarray:
    h = candles['high'].values
    l = candles['low'].values
    c = candles['close'].values
    prev_c = np.concatenate(([c[0]], c[:-1]))
    tr = np.maximum.reduce([h - l, np.abs(h - prev_c), np.abs(l - prev_c)])
    # simple moving ATR for speed; small bias vs Wilder but fine for labeling
    atr = pd.Series(tr).rolling(length, min_periods=1).mean().values
    return atr


# -------------------------------------------------------------------
# Sweep detection
# -------------------------------------------------------------------

def detect_sweeps(
    candles: pd.DataFrame,
    levels: pd.DataFrame,
    run_through_eps_atr: float = 0.25,
    max_scan_bars: int = 2880,  # 24h at 30s — cap runaway scans
) -> pd.DataFrame:
    """For every level, find the first bar after created_idx that sweeps it.

    Returns a DataFrame with one row per sweep event. Levels that never get
    swept within max_scan_bars are omitted.
    """
    if levels.empty:
        return pd.DataFrame()

    atr = compute_atr(candles, length=14)
    highs = candles['high'].values
    lows = candles['low'].values
    closes = candles['close'].values
    ts_ny = candles['timestamp_ny'].values

    events: List[Dict] = []
    for row in levels.itertuples(index=False):
        start = row.created_idx
        if start is None or start >= len(candles) - 1:
            continue
        end = min(start + max_scan_bars, len(candles))
        price = row.price

        if row.side == 'high':
            # First bar where high > price
            window_hi = highs[start:end]
            hits = np.where(window_hi > price)[0]
            if hits.size == 0:
                continue
            offset = int(hits[0])
        else:
            window_lo = lows[start:end]
            hits = np.where(window_lo < price)[0]
            if hits.size == 0:
                continue
            offset = int(hits[0])

        sweep_idx = start + offset
        bar_close = closes[sweep_idx]
        a = atr[sweep_idx] if atr[sweep_idx] > 0 else 1.0
        eps = run_through_eps_atr * a

        if row.side == 'high':
            run_through = bar_close > (price + eps)
            direction = 'bullish'
        else:
            run_through = bar_close < (price - eps)
            direction = 'bearish'

        events.append({
            'level_id': row.level_id,
            'level_type': row.type,
            'level_side': row.side,
            'level_price': price,
            'level_created_idx': start,
            'level_age_bars': offset,
            'sweep_idx': sweep_idx,
            'sweep_ts': pd.Timestamp(ts_ny[sweep_idx]),
            'sweep_direction': direction,
            'sweep_close': float(bar_close),
            'sweep_atr': float(a),
            'kind': 'run_through' if run_through else 'wick_only',
        })

    return pd.DataFrame(events)


# -------------------------------------------------------------------
# Outcome labeling
# -------------------------------------------------------------------

def label_outcomes(
    sweeps: pd.DataFrame,
    candles: pd.DataFrame,
    horizons_bars: List[int],
    run_threshold_atr: float = 1.0,
    rev_threshold_atr: float = 1.0,
) -> pd.DataFrame:
    """Attach RUN/REVERSE/CHOP labels at each horizon to a sweeps frame."""
    if sweeps.empty:
        return sweeps

    atr = compute_atr(candles, length=14)
    highs = candles['high'].values
    lows = candles['low'].values
    closes = candles['close'].values
    n = len(candles)

    out = sweeps.copy()
    for h in horizons_bars:
        mfe = np.zeros(len(out))
        mae = np.zeros(len(out))
        close_at = np.zeros(len(out))
        label = np.array(['CHOP'] * len(out), dtype=object)

        for k, row in enumerate(out.itertuples(index=False)):
            i0 = row.sweep_idx
            i1 = min(i0 + h, n - 1)
            if i1 <= i0:
                label[k] = 'CHOP'
                continue
            price = row.level_price
            seg_hi = highs[i0:i1 + 1]
            seg_lo = lows[i0:i1 + 1]
            if row.sweep_direction == 'bullish':
                mfe[k] = float(seg_hi.max() - price)
                mae[k] = float(price - seg_lo.min())
            else:
                mfe[k] = float(price - seg_lo.min())
                mae[k] = float(seg_hi.max() - price)
            close_at[k] = float(closes[i1])

            a = atr[i0] if atr[i0] > 0 else 1.0
            if row.sweep_direction == 'bullish':
                delta_close = close_at[k] - price
            else:
                delta_close = price - close_at[k]

            if delta_close >= run_threshold_atr * a:
                label[k] = 'RUN'
            elif delta_close <= -rev_threshold_atr * a:
                label[k] = 'REVERSE'
            else:
                label[k] = 'CHOP'

        out[f'mfe_past_level_h{h}'] = mfe
        out[f'mae_back_through_h{h}'] = mae
        out[f'close_at_h{h}'] = close_at
        out[f'label_h{h}'] = label

    return out
