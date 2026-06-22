#!/usr/bin/env python3
"""Gate-confluence model — progressive binary gates instead of additive score.

Designed to be:
  (a) Easier to execute live (binary checks, no in-head arithmetic)
  (b) Less overfit (fewer effective parameters than v3.1's 25+)
  (c) Timing-aware (gates activate as data fills in — preserves 9:30-9:45 trades)

GATES (must ALL pass):

PRE-MARKET (available 9:25):
  P1. prior_day_range_atr_ratio >= 0.7
  P2. Direction bias matches sweep:
      - SHORTS: prior_day_type in {reversal_down, trend_down} OR prior_day_close_position <= 0.40
      - LONGS:  prior_day_type in {reversal_up,   trend_up}   OR prior_day_close_position >= 0.60

AT SWEEP TIME:
  S1. sweep_level in valid set (PDH/PDL/ON/Asia/London/Running50)
  S2. gap_size_pts in [10, 20]
  S3. inversion_body_fraction in [0.5, 0.9]
  S4. pd_position correct side (>=0.5 for short, <=0.5 for long)
  S5. killzone_minute < 45 (no entries after 10:15)
  S6. NOT remaining_same_dir_unswept >= 1 (no magnets against)

PROGRESSIVE (activate as data fills in):
  T1. After 9:45 (killzone_minute >= 15): require or_15min_range >= 90
  T2. After 10:15 (killzone_minute >= 45) - already excluded by S5
  T3. After 10:30 (killzone_minute >= 60) - already excluded by S5
       But for the chop_day check: only fires if killzone_minute >= 60

Run + compare to v3.1.
"""

import sys
from datetime import time as dtime, timedelta
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


# =====================================================================
# Gate definitions
# =====================================================================

VALID_SHORT_LEVELS = {'prev_day_high', 'asia_high', 'london_high', 'overnight_high', 'daily_50pct_high'}
VALID_LONG_LEVELS  = {'prev_day_low',  'asia_low',  'london_low',  'overnight_low',  'daily_50pct_low'}


def gate_p1_premarket_quality(r):
    return (r.get('prior_day_range_atr_ratio') or 0) >= 0.7


def gate_p2_direction_bias(r):
    """Direction bias must MATCH the trade direction."""
    direction = r['direction']
    pd_type = r.get('prior_day_type') or ''
    close_pos = r.get('prior_day_close_position') or 0.5
    if direction == 'short':
        return pd_type in ('reversal_down', 'trend_down') or close_pos <= 0.40
    if direction == 'long':
        return pd_type in ('reversal_up', 'trend_up') or close_pos >= 0.60
    return False


def gate_s1_sweep_level(r):
    direction = r['direction']
    if direction == 'short':
        return r['sweep_level'] in VALID_SHORT_LEVELS
    if direction == 'long':
        return r['sweep_level'] in VALID_LONG_LEVELS
    return False


def gate_s2_gap_size(r):
    return 10 <= r['gap_size_pts'] <= 20


def gate_s3_body_fraction(r):
    return 0.5 <= r['inversion_body_fraction'] <= 0.9


def gate_s4_pd_position(r):
    direction = r['direction']
    pd = r['pd_position']
    if direction == 'short':
        return pd >= 0.5
    if direction == 'long':
        return pd <= 0.5
    return False


def gate_s5_killzone_safety(r):
    return (r.get('killzone_minute') or 99) < 45


def gate_s6_no_magnets_against(r):
    return (r.get('remaining_same_dir_unswept') or 0) < 1


def gate_t1_or15_progressive(r):
    """Only required if killzone_minute >= 15 (after 9:45). Before that, pass."""
    km = r.get('killzone_minute') or 0
    if km < 15:
        return True  # OR-15 not available yet, gate is inactive
    return (r.get('or_15min_range') or 0) >= 90


def gate_t2_chop_progressive(r):
    """Only required if killzone_minute >= 60 (after 10:30). Before that, pass."""
    km = r.get('killzone_minute') or 0
    if km < 60:
        return True  # is_chop_day not determinable yet
    return not bool(r.get('is_chop_day', False))


ALL_GATES = [
    ('P1_premarket_atr',    gate_p1_premarket_quality),
    ('P2_direction_bias',   gate_p2_direction_bias),
    ('S1_sweep_level',      gate_s1_sweep_level),
    ('S2_gap_size',         gate_s2_gap_size),
    ('S3_body_fraction',    gate_s3_body_fraction),
    ('S4_pd_position',      gate_s4_pd_position),
    ('S5_killzone_safety',  gate_s5_killzone_safety),
    ('S6_no_magnets',       gate_s6_no_magnets_against),
    ('T1_or15_progressive', gate_t1_or15_progressive),
    ('T2_chop_progressive', gate_t2_chop_progressive),
]


def apply_gates(df):
    """Return new columns: per-gate pass + overall pass."""
    out = df.copy()
    for name, fn in ALL_GATES:
        out[f'gate_{name}'] = out.apply(fn, axis=1)
    gate_cols = [f'gate_{name}' for name, _ in ALL_GATES]
    out['all_gates_pass'] = out[gate_cols].all(axis=1)
    out['gates_passed_count'] = out[gate_cols].sum(axis=1)
    return out


# =====================================================================
# Scaled-exit simulator (same as best v3.1 risk config)
# =====================================================================

def simulate_one(row, day_candles, trim_tp1=0.25, trim_tp2=0.25, trim_tp3=0.50,
                 tp1_r=1.0, tp2_r=4.0, tp3_r=8.0, be_trail=True):
    direction = row['direction']
    entry = row['entry_price']
    gap_top = row['gap_top']; gap_bottom = row['gap_bottom']
    stop_d = row['stop_distance_pts']
    if stop_d <= 0 or day_candles is None or day_candles.empty:
        return 0.0
    entry_ts = pd.to_datetime(row['entry_ts'], utc=True, format='mixed')

    if direction == 'short':
        hard_stop = gap_top + HARD_STOP_BUFFER
        tp1 = entry - tp1_r * stop_d
        tp2 = entry - tp2_r * stop_d
        tp3 = entry - tp3_r * stop_d
        soft_level = gap_top
    else:
        hard_stop = gap_bottom - HARD_STOP_BUFFER
        tp1 = entry + tp1_r * stop_d
        tp2 = entry + tp2_r * stop_d
        tp3 = entry + tp3_r * stop_d
        soft_level = gap_bottom

    forward = day_candles[
        (day_candles['timestamp_ny'] > entry_ts) &
        (day_candles['timestamp_ny'].dt.time <= _EOD)
    ]
    if forward.empty:
        return -1.0

    pos = 1.0; acc = 0.0
    tps = {1: False, 2: False, 3: False}
    last_close = None
    eff_stop = hard_stop; be_active = False

    for c in forward.itertuples(index=False):
        last_close = c.close
        if direction == 'short':
            if c.high >= eff_stop:
                acc += pos * ((entry - eff_stop) / stop_d); pos = 0; break
            if c.low <= tp1 and not tps[1]:
                tps[1] = True; acc += trim_tp1 * tp1_r; pos -= trim_tp1
                if be_trail and not be_active:
                    eff_stop = entry; be_active = True
            if c.low <= tp2 and not tps[2]:
                tps[2] = True; acc += trim_tp2 * tp2_r; pos -= trim_tp2
            if c.low <= tp3 and not tps[3]:
                tps[3] = True; acc += pos * tp3_r; pos = 0; break
        else:
            if c.low <= eff_stop:
                acc += pos * ((eff_stop - entry) / stop_d); pos = 0; break
            if c.high >= tp1 and not tps[1]:
                tps[1] = True; acc += trim_tp1 * tp1_r; pos -= trim_tp1
                if be_trail and not be_active:
                    eff_stop = entry; be_active = True
            if c.high >= tp2 and not tps[2]:
                tps[2] = True; acc += trim_tp2 * tp2_r; pos -= trim_tp2
            if c.high >= tp3 and not tps[3]:
                tps[3] = True; acc += pos * tp3_r; pos = 0; break
        if pos <= 1e-6:
            break
        if direction == 'short' and c.close > soft_level:
            acc += pos * ((entry - c.close) / stop_d); pos = 0; break
        if direction == 'long' and c.close < soft_level:
            acc += pos * ((c.close - entry) / stop_d); pos = 0; break

    if pos > 1e-6 and last_close is not None:
        close_r = ((entry - last_close) / stop_d) if direction == 'short' else ((last_close - entry) / stop_d)
        acc += pos * close_r
    return acc


def summarize(rs):
    rs = np.array([r for r in rs if r != 0])
    if len(rs) == 0:
        return {'n': 0}
    w = int((rs > 0).sum()); l = int((rs < 0).sum())
    gw = rs[rs > 0].sum(); gl = abs(rs[rs < 0].sum()) or 1e-9
    return {'n': len(rs),
            'wr': round(w / max(w+l, 1) * 100, 1),
            'pf': round(gw / gl, 2),
            'avg_r': round(rs.mean(), 3),
            'total_r': round(rs.sum(), 1)}


# =====================================================================
# Main
# =====================================================================

def main():
    df = pd.read_csv(POP_PATH)
    df['date'] = pd.to_datetime(df['entry_ts'], utc=True, format='mixed').dt.date.astype(str)
    df['entry_dt'] = pd.to_datetime(df['entry_ts'], utc=True, format='mixed')
    df['cohort'] = df['date'].apply(lambda d: 'OOS' if d >= OOS_START else 'IS')
    print(f"Population: {len(df)} rows, IS={len(df[df['cohort']=='IS'])}, OOS={len(df[df['cohort']=='OOS'])}\n")

    df = apply_gates(df)

    # Per-gate firing rates (how often each gate KILLS a trade)
    print("=== Per-gate fail rate (how often each gate excludes) ===")
    for name, _ in ALL_GATES:
        col = f'gate_{name}'
        fail_rate = (~df[col]).mean() * 100
        print(f"  {name:25} fails {fail_rate:5.1f}% of trades")
    print()
    print(f"All gates pass: {df['all_gates_pass'].sum()} / {len(df)} ({df['all_gates_pass'].mean()*100:.1f}%)")
    print()

    # Distribution of gates_passed_count
    print("Gates-passed-count distribution:")
    print(df['gates_passed_count'].value_counts().sort_index().to_string())
    print()

    # ============= Load candles for scaled simulation =============
    candles = load_candles(DATA_PATH)
    cohort_min = df['date'].min(); cohort_max = df['date'].max()
    candles = candles[
        (candles['timestamp_ny'].dt.tz_localize(None) >= pd.Timestamp(cohort_min)) &
        (candles['timestamp_ny'].dt.tz_localize(None) <= pd.Timestamp(cohort_max) + pd.Timedelta(days=1))
    ].copy()
    candles['date_ny'] = candles['timestamp_ny'].dt.date.astype(str)
    candles_by_date = {d: g[['timestamp_ny','open','high','low','close']].reset_index(drop=True)
                       for d, g in candles.groupby('date_ny', sort=False)}

    # ============= Run scaled simulation on qualifying trades =============
    qualifying = df[df['all_gates_pass']].copy()
    print(f"\nSimulating {len(qualifying)} qualifying trades with 25/25/50@1/4/8R+BE...")
    rs = []
    for _, row in qualifying.iterrows():
        rs.append(simulate_one(row, candles_by_date.get(row['date'])))
    qualifying['r_gate'] = rs
    qualifying['pnl_pts_gate'] = qualifying['r_gate'] * qualifying['stop_distance_pts']

    # ============= Per-cohort + per-direction summary =============
    print("\n=== GATE MODEL RESULTS ===")
    for cohort_name in ('IS', 'OOS'):
        for direction in ('short', 'long', 'both'):
            if direction == 'both':
                sub = qualifying[qualifying['cohort'] == cohort_name]
            else:
                sub = qualifying[(qualifying['cohort'] == cohort_name) & (qualifying['direction'] == direction)]
            if len(sub) < 5:
                continue
            s = summarize(sub['r_gate'].tolist())
            print(f"  {cohort_name:3} {direction:5}  N={s['n']:4}  WR={s['wr']:5.1f}%  PF={s['pf']:.2f}  "
                  f"avg_R={s['avg_r']:+.3f}  total_R={s['total_r']:+.1f}")

    # ============= Walk-forward stability =============
    print("\n=== Walk-forward (gate model, 6mo windows step 3mo) ===")
    WINDOW_DAYS = 180; STEP_DAYS = 90
    start_date = pd.Timestamp(cohort_min, tz='UTC')
    end_date = pd.Timestamp(cohort_max, tz='UTC')

    windows = []
    current = start_date
    while current + timedelta(days=WINDOW_DAYS) <= end_date:
        windows.append((current, current + timedelta(days=WINDOW_DAYS)))
        current += timedelta(days=STEP_DAYS)

    rows = []
    for win_start, win_end in windows:
        mask = (qualifying['entry_dt'] >= win_start) & (qualifying['entry_dt'] < win_end)
        sub = qualifying[mask]
        s = summarize(sub['r_gate'].tolist())
        if s.get('n', 0) == 0:
            continue
        rows.append({
            'window_start': str(win_start.date()),
            'n': s['n'], 'wr': s['wr'], 'pf': s['pf'],
            'avg_r': s['avg_r'], 'total_r': s['total_r'],
        })

    out_wf = pd.DataFrame(rows)
    print(out_wf.to_string(index=False))

    pf_series = out_wf['pf']
    print(f"\n  N windows:  {len(out_wf)}")
    print(f"  Median PF:  {pf_series.median():.2f}")
    print(f"  Mean PF:    {pf_series.mean():.2f}")
    print(f"  Min/Max PF: {pf_series.min():.2f} / {pf_series.max():.2f}")
    print(f"  Std PF:     {pf_series.std():.2f}")
    for thresh in (1.0, 1.3, 1.5, 2.0):
        pct = (pf_series >= thresh).mean() * 100
        print(f"  Windows PF >= {thresh}: {(pf_series >= thresh).sum()}/{len(out_wf)} ({pct:.0f}%)")

    # ============= Comparison vs v3.1 walk-forward =============
    print("\n=== GATE MODEL vs v3.1 (walk-forward summary) ===")
    print("                       Gate model    v3.1 (score>=6 + 25/25/50 + BE)")
    print(f"  N windows:           {len(out_wf):<12}  19")
    print(f"  Median PF:           {pf_series.median():<12.2f}  1.52")
    print(f"  Mean PF:             {pf_series.mean():<12.2f}  2.67")
    print(f"  Min PF:              {pf_series.min():<12.2f}  0.11")
    print(f"  Max PF:              {pf_series.max():<12.2f}  11.25")
    print(f"  Std PF:              {pf_series.std():<12.2f}  (wide)")
    print(f"  % windows PF >= 1.0: {(pf_series >= 1.0).mean()*100:<12.0f}  68%")
    print(f"  % windows PF >= 1.5: {(pf_series >= 1.5).mean()*100:<12.0f}  53%")

    # Save
    qualifying.to_csv(POP_PATH.with_name('population_gate.csv'), index=False)
    out_wf.to_csv(POP_PATH.with_name('gate_walk_forward.csv'), index=False)
    print(f"\nWrote population_gate.csv and gate_walk_forward.csv")


if __name__ == '__main__':
    main()
