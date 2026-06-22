#!/usr/bin/env python3
"""Enrich population with Order Block (OB) confirmation factors.

Per Tempo recaps R3, R5, R6, R9: an Order Block is a 2-candle pattern where the
ENTRY-direction candle fully engulfs the prior OPPOSITE-direction candle (by body).

Bullish OB (long entry confirmation): green candle whose body engulfs the prior red candle's body.
Bearish OB (short entry confirmation): red candle whose body engulfs the prior green candle's body.

For each trade in the population, scan back N bars before entry on the gap_tf
timeframe. Flag whether an OB confirmation in the trade's direction is present.

Output: new columns added to population_enriched.csv:
  has_ob_confirm                  bool — found OB in trade direction within N bars
  ob_confirm_bar_offset           int — bars before entry where OB found (1=immediately prior)
  ob_engulfing_body_pts           float — size of engulfing candle's body
  ob_engulfed_body_pts            float — size of engulfed candle's body
  ob_strength_ratio               float — engulfing/engulfed body ratio
"""

import sys
import time
from datetime import time as dtime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pandas as pd

from fvgc.data import load_candles

DATA_PATH = Path('data/consolidated/nq-front-month.ohlcv-30s.csv')
POP_PATH = Path('studies/ifvg_reversal_population/results/population_enriched.csv')
OUT_PATH = Path('studies/ifvg_reversal_population/results/population_enriched.csv')

LOOKBACK_BARS = 5
MIN_OB_STRENGTH = 1.0  # engulfing body must be ≥ engulfed body

# TF resample map (matches multi_tf_fvg.py)
TF_FREQ = {'30s': '30s', '1min': '1min', '2min': '2min', '3min': '3min'}


def detect_ob_long(c1, c2) -> bool:
    """Bullish OB: c1 is red (close < open), c2 is green (close > open),
    c2's body engulfs c1's body."""
    c1_red = c1['close'] < c1['open']
    c2_green = c2['close'] > c2['open']
    if not (c1_red and c2_green):
        return False
    c1_body_top, c1_body_bot = c1['open'], c1['close']
    c2_body_top, c2_body_bot = c2['close'], c2['open']
    return c2_body_bot <= c1_body_bot and c2_body_top >= c1_body_top


def detect_ob_short(c1, c2) -> bool:
    """Bearish OB: c1 green, c2 red, c2's body engulfs c1's body."""
    c1_green = c1['close'] > c1['open']
    c2_red = c2['close'] < c2['open']
    if not (c1_green and c2_red):
        return False
    c1_body_top, c1_body_bot = c1['close'], c1['open']
    c2_body_top, c2_body_bot = c2['open'], c2['close']
    return c2_body_bot <= c1_body_bot and c2_body_top >= c1_body_top


def _resample(day: pd.DataFrame, freq: str) -> pd.DataFrame:
    """Resample 30s candles to a coarser TF."""
    df = day.set_index('timestamp_ny')
    out = df.resample(freq, label='left', closed='left').agg({
        'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last',
    }).dropna(how='any').reset_index()
    return out


def check_trade(row, day_candles):
    """Look back N bars on trade's TF for an OB confirmation."""
    direction = row['direction']
    tf = row['gap_tf'] if pd.notna(row['gap_tf']) else '30s'
    entry_ts = pd.to_datetime(row['entry_ts'], utc=True, format='mixed')

    if day_candles is None or day_candles.empty:
        return False, None, None, None, None

    # Resample to trade's TF
    if tf == '30s':
        bars = day_candles
    else:
        bars = _resample(day_candles, TF_FREQ.get(tf, '30s'))

    # Get bars BEFORE entry
    prior = bars[bars['timestamp_ny'] < entry_ts].tail(LOOKBACK_BARS + 1)
    if len(prior) < 2:
        return False, None, None, None, None

    # Walk from most-recent backward looking for OB pair
    bars_list = prior.iloc[-LOOKBACK_BARS-1:].reset_index(drop=True)
    for i in range(len(bars_list) - 1, 0, -1):
        c1 = bars_list.iloc[i - 1]
        c2 = bars_list.iloc[i]
        if direction == 'long' and detect_ob_long(c1, c2):
            engulfing = abs(c2['close'] - c2['open'])
            engulfed = abs(c1['close'] - c1['open'])
            offset = len(bars_list) - 1 - i
            return True, offset, engulfing, engulfed, engulfing / max(engulfed, 1e-9)
        if direction == 'short' and detect_ob_short(c1, c2):
            engulfing = abs(c2['close'] - c2['open'])
            engulfed = abs(c1['close'] - c1['open'])
            offset = len(bars_list) - 1 - i
            return True, offset, engulfing, engulfed, engulfing / max(engulfed, 1e-9)

    return False, None, None, None, None


def main():
    print("=== Order Block enrichment ===\n")
    t0 = time.time()

    pop = pd.read_csv(POP_PATH)
    print(f"  population: {len(pop)} rows")

    candles = load_candles(DATA_PATH)
    cohort_min = pop['date'].min() if 'date' in pop.columns else \
        pd.to_datetime(pop['entry_ts'], utc=True, format='mixed').dt.date.astype(str).min()
    cohort_max = pop['date'].max() if 'date' in pop.columns else \
        pd.to_datetime(pop['entry_ts'], utc=True, format='mixed').dt.date.astype(str).max()
    if 'date' not in pop.columns:
        pop['date'] = pd.to_datetime(pop['entry_ts'], utc=True, format='mixed').dt.date.astype(str)

    candles = candles[
        (candles['timestamp_ny'].dt.tz_localize(None) >= pd.Timestamp(cohort_min)) &
        (candles['timestamp_ny'].dt.tz_localize(None) <= pd.Timestamp(cohort_max) + pd.Timedelta(days=1))
    ].copy()
    candles['date_ny'] = candles['timestamp_ny'].dt.date.astype(str)
    candles_by_date = {d: g[['timestamp_ny', 'open', 'high', 'low', 'close']].reset_index(drop=True)
                       for d, g in candles.groupby('date_ny', sort=False)}
    print(f"  candles loaded in {time.time()-t0:.1f}s")

    t = time.time()
    flags, offsets, eng_pts, e_pts, strengths = [], [], [], [], []
    for _, row in pop.iterrows():
        f, offset, eng, e, strength = check_trade(row, candles_by_date.get(row['date']))
        flags.append(f); offsets.append(offset); eng_pts.append(eng)
        e_pts.append(e); strengths.append(strength)

    pop['has_ob_confirm'] = flags
    pop['ob_confirm_bar_offset'] = offsets
    pop['ob_engulfing_body_pts'] = eng_pts
    pop['ob_engulfed_body_pts'] = e_pts
    pop['ob_strength_ratio'] = strengths

    pop.to_csv(OUT_PATH, index=False)
    print(f"  enriched in {time.time()-t:.1f}s\n")

    # Sanity preview
    print(f"OB confirmation rate: {pop['has_ob_confirm'].mean()*100:.1f}% of trades")
    if pop['has_ob_confirm'].any():
        print(f"  Strength ratio distribution:")
        print(f"    median: {pop.loc[pop['has_ob_confirm'], 'ob_strength_ratio'].median():.2f}")
        print(f"    p75:    {pop.loc[pop['has_ob_confirm'], 'ob_strength_ratio'].quantile(0.75):.2f}")
        print(f"  By direction:")
        print(pop.groupby('direction')['has_ob_confirm'].mean().to_string())
        print(f"\n  WR comparison:")
        with_ob = pop[pop['has_ob_confirm']]
        without_ob = pop[~pop['has_ob_confirm']]
        for name, sub in (('with OB', with_ob), ('without OB', without_ob)):
            w = (sub['r_multiple'] > 0).sum(); l = (sub['r_multiple'] < 0).sum()
            gw = sub.loc[sub['r_multiple']>0, 'pnl_pts'].sum()
            gl = abs(sub.loc[sub['r_multiple']<0, 'pnl_pts'].sum()) or 1e-9
            wr = w/max(w+l,1)*100
            print(f"    {name:<12} N={len(sub):4} WR={wr:5.1f}%  PF={gw/gl:.2f}")

    print(f"\nWrote {OUT_PATH}")


if __name__ == '__main__':
    main()
