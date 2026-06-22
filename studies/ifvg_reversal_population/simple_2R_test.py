#!/usr/bin/env python3
"""Test the simplest possible exit: 100% at 2R, no BE, no trims, no runner.

Just: stop OR target OR soft-stop OR EOD.
"""

import sys
from datetime import time as dtime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import numpy as np
import pandas as pd

from fvgc.data import load_candles

POP_PATH = Path('studies/ifvg_reversal_population/results/population_scored.csv')
DATA_PATH = Path('data/consolidated/nq-front-month.ohlcv-30s.csv')

OOS_START = '2025-05-17'
_EOD = dtime(16, 0)
HARD_STOP_BUFFER = 2.0
TARGET_R = 2.0


def simulate(row, day_candles):
    """100% at 2R. No BE, no trims, no runner."""
    direction = row['direction']
    entry = row['entry_price']
    gap_top = row['gap_top']; gap_bottom = row['gap_bottom']
    stop_d = row['stop_distance_pts']
    if stop_d <= 0 or day_candles is None or day_candles.empty:
        return 0.0
    entry_ts = pd.to_datetime(row['entry_ts'], utc=True, format='mixed')

    if direction == 'short':
        hard_stop = gap_top + HARD_STOP_BUFFER
        target = entry - TARGET_R * stop_d
        soft_level = gap_top
    else:
        hard_stop = gap_bottom - HARD_STOP_BUFFER
        target = entry + TARGET_R * stop_d
        soft_level = gap_bottom

    forward = day_candles[
        (day_candles['timestamp_ny'] > entry_ts) &
        (day_candles['timestamp_ny'].dt.time <= _EOD)
    ]
    if forward.empty:
        return -1.0

    last_close = None
    for c in forward.itertuples(index=False):
        last_close = c.close
        if direction == 'short':
            if c.high >= hard_stop:
                return -1.0
            if c.low <= target:
                return TARGET_R
            if c.close > soft_level:
                return (entry - c.close) / stop_d
        else:
            if c.low <= hard_stop:
                return -1.0
            if c.high >= target:
                return TARGET_R
            if c.close < soft_level:
                return (c.close - entry) / stop_d

    if last_close is not None:
        if direction == 'short':
            return (entry - last_close) / stop_d
        return (last_close - entry) / stop_d
    return 0.0


def summarize(rs, label):
    rs = np.array([r for r in rs if r is not None])
    w = int((rs > 0).sum()); l = int((rs < 0).sum()); flat = int((rs == 0).sum())
    wr = w / max(w + l, 1) * 100
    gw = rs[rs > 0].sum(); gl = abs(rs[rs < 0].sum()) or 1e-9
    pf = gw / gl
    return f"  {label:30}  N={len(rs):4} W/L/F={w}/{l}/{flat}  WR={wr:5.1f}%  PF={pf:.2f}  avgR={rs.mean():+.3f}  totR={rs.sum():+.1f}"


def main():
    df = pd.read_csv(POP_PATH)
    df['date'] = pd.to_datetime(df['entry_ts'], utc=True, format='mixed').dt.date.astype(str)
    df['cohort'] = df['date'].apply(lambda d: 'OOS' if d >= OOS_START else 'IS')

    candles = load_candles(DATA_PATH)
    cohort_min = df['date'].min(); cohort_max = df['date'].max()
    candles = candles[
        (candles['timestamp_ny'].dt.tz_localize(None) >= pd.Timestamp(cohort_min)) &
        (candles['timestamp_ny'].dt.tz_localize(None) <= pd.Timestamp(cohort_max) + pd.Timedelta(days=1))
    ].copy()
    candles['date_ny'] = candles['timestamp_ny'].dt.date.astype(str)
    candles_by_date = {d: g[['timestamp_ny','open','high','low','close']].reset_index(drop=True)
                       for d, g in candles.groupby('date_ny', sort=False)}

    print("=== SIMPLE 2R TEST: 100% exit at 2R, no BE, no trims ===\n")

    # Apply v3.1 filter at multiple thresholds
    for filter_name, mask_fn in [
        ('SHORT score≥4', lambda d: (d['direction']=='short') & ~d['v3_1_anti_hit'] & (d['v3_1_score_short']>=4)),
        ('LONG  score≥5', lambda d: (d['direction']=='long')  & ~d['v3_1_anti_hit'] & (d['v3_1_score_long']>=5)),
        ('LONG  score≥6', lambda d: (d['direction']=='long')  & ~d['v3_1_anti_hit'] & (d['v3_1_score_long']>=6)),
        ('LONG  score≥7', lambda d: (d['direction']=='long')  & ~d['v3_1_anti_hit'] & (d['v3_1_score_long']>=7)),
        ('COMBINED ≥5',   lambda d: ~d['v3_1_anti_hit'] & (d['v3_1_score']>=5)),
        ('COMBINED ≥6',   lambda d: ~d['v3_1_anti_hit'] & (d['v3_1_score']>=6)),
    ]:
        sub = df[mask_fn(df)].copy()
        is_sub  = sub[sub['cohort']=='IS']
        oos_sub = sub[sub['cohort']=='OOS']

        print(f"-- {filter_name} --")
        rs_is = [simulate(row, candles_by_date.get(row['date'])) for _, row in is_sub.iterrows()]
        rs_oos = [simulate(row, candles_by_date.get(row['date'])) for _, row in oos_sub.iterrows()]
        print(summarize(rs_is, 'IS'))
        print(summarize(rs_oos, 'OOS'))
        print()


if __name__ == '__main__':
    main()
