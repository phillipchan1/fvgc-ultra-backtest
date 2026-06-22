#!/usr/bin/env python3
"""Walk-forward validation — test v3.1 PF stability across rolling time windows.

Computes v3.1 PF on every rolling 6-month window in the 5-year cohort using
the best risk config (25/25/50 @ 1/4/8R + BE trail).

Answers: is the OOS PF 3.22 regime-stable, or did we get lucky on the single
OOS window (May 2025 - May 2026)?

Output:
  - Per-window PF, WR, avg_R, N
  - Distribution: how many windows have PF > 1.5, > 2.0, < 1.0
  - Best / worst windows
  - Comparison of factor lit-rate per window (regime indicator)
"""

import sys
import time
from datetime import time as dtime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pandas as pd

from fvgc.data import load_candles

POP_PATH = Path('studies/ifvg_reversal_population/results/population_scored.csv')
DATA_PATH = Path('data/consolidated/nq-front-month.ohlcv-30s.csv')
OUT_CSV = Path('studies/ifvg_reversal_population/results/walk_forward.csv')

_EOD = dtime(16, 0)
HARD_STOP_BUFFER = 2.0

# Best risk config from v3_1_risk_sweep: 25/25/50 @ 1/4/8R + BE
TRIM_TP1 = 0.25; TRIM_TP2 = 0.25; TRIM_TP3 = 0.50
TP1_R = 1.0; TP2_R = 4.0; TP3_R = 8.0
BE_TRAIL = True


def simulate_one(row, day_candles):
    """Simulate scaled exit with BE trail, returns realized R."""
    direction = row['direction']
    entry = row['entry_price']
    gap_top = row['gap_top']; gap_bottom = row['gap_bottom']
    stop_d = row['stop_distance_pts']
    if stop_d <= 0 or day_candles is None or day_candles.empty:
        return 0.0
    entry_ts = pd.to_datetime(row['entry_ts'], utc=True, format='mixed')

    if direction == 'short':
        hard_stop = gap_top + HARD_STOP_BUFFER
        tp1 = entry - TP1_R * stop_d; tp2 = entry - TP2_R * stop_d; tp3 = entry - TP3_R * stop_d
        soft_level = gap_top
    else:
        hard_stop = gap_bottom - HARD_STOP_BUFFER
        tp1 = entry + TP1_R * stop_d; tp2 = entry + TP2_R * stop_d; tp3 = entry + TP3_R * stop_d
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
                acc += pos * ((entry - eff_stop) / stop_d)
                pos = 0; break
            if c.low <= tp1 and not tps[1]:
                tps[1] = True; acc += TRIM_TP1 * TP1_R; pos -= TRIM_TP1
                if BE_TRAIL and not be_active:
                    eff_stop = entry; be_active = True
            if c.low <= tp2 and not tps[2]:
                tps[2] = True; acc += TRIM_TP2 * TP2_R; pos -= TRIM_TP2
            if c.low <= tp3 and not tps[3]:
                tps[3] = True; acc += pos * TP3_R; pos = 0; break
        else:
            if c.low <= eff_stop:
                acc += pos * ((eff_stop - entry) / stop_d)
                pos = 0; break
            if c.high >= tp1 and not tps[1]:
                tps[1] = True; acc += TRIM_TP1 * TP1_R; pos -= TRIM_TP1
                if BE_TRAIL and not be_active:
                    eff_stop = entry; be_active = True
            if c.high >= tp2 and not tps[2]:
                tps[2] = True; acc += TRIM_TP2 * TP2_R; pos -= TRIM_TP2
            if c.high >= tp3 and not tps[3]:
                tps[3] = True; acc += pos * TP3_R; pos = 0; break

        if pos <= 1e-6:
            break

        # Soft stop
        if direction == 'short' and c.close > soft_level:
            acc += pos * ((entry - c.close) / stop_d); pos = 0; break
        if direction == 'long' and c.close < soft_level:
            acc += pos * ((c.close - entry) / stop_d); pos = 0; break

    if pos > 1e-6 and last_close is not None:
        close_r = ((entry - last_close) / stop_d) if direction == 'short' else ((last_close - entry) / stop_d)
        acc += pos * close_r
    return acc


def summarize(rs):
    """Compute PF/WR from a list of R values."""
    import numpy as np
    rs = np.array([r for r in rs if r != 0])
    if len(rs) == 0:
        return None
    w = int((rs > 0).sum()); l = int((rs < 0).sum())
    wr = w / max(w + l, 1) * 100
    gw = rs[rs > 0].sum(); gl = abs(rs[rs < 0].sum()) or 1e-9
    pf = gw / gl
    return {'n': len(rs), 'wr': round(wr, 1), 'pf': round(pf, 2),
            'avg_r': round(rs.mean(), 3), 'total_r': round(rs.sum(), 1)}


def main():
    print("=== v3.1 Walk-Forward Validation ===\n")
    t0 = time.time()

    df = pd.read_csv(POP_PATH)
    df['date'] = pd.to_datetime(df['entry_ts'], utc=True, format='mixed').dt.date.astype(str)
    df['entry_dt'] = pd.to_datetime(df['entry_ts'], utc=True, format='mixed')
    print(f"Population: {len(df)} rows, {df['date'].min()} -> {df['date'].max()}")

    # Apply v3.1 filter (already in df from v3_1_confluence.py)
    setup = df[~df['v3_1_anti_hit'] & (df['v3_1_score'] >= 6)].copy()
    print(f"After anti-filter + score >= 6: {len(setup)} trades")
    print(f"  by direction: {setup['direction'].value_counts().to_dict()}\n")

    # Load candles
    candles = load_candles(DATA_PATH)
    cohort_min = setup['date'].min(); cohort_max = setup['date'].max()
    candles = candles[
        (candles['timestamp_ny'].dt.tz_localize(None) >= pd.Timestamp(cohort_min)) &
        (candles['timestamp_ny'].dt.tz_localize(None) <= pd.Timestamp(cohort_max) + pd.Timedelta(days=1))
    ].copy()
    candles['date_ny'] = candles['timestamp_ny'].dt.date.astype(str)
    candles_by_date = {d: g[['timestamp_ny','open','high','low','close']].reset_index(drop=True)
                       for d, g in candles.groupby('date_ny', sort=False)}
    print(f"Candles loaded in {time.time()-t0:.1f}s\n")

    # Simulate ALL trades once with the best config
    print("Simulating all setup trades with 25/25/50 @ 1/4/8R + BE...")
    rs = []
    for _, row in setup.iterrows():
        r = simulate_one(row, candles_by_date.get(row['date']))
        rs.append(r)
    setup['r_v31'] = rs
    setup['pnl_pts_v31'] = setup['r_v31'] * setup['stop_distance_pts']
    print(f"  done.\n")

    # ============= Walk-forward windows =============
    # Use 6-month rolling windows (180 days), step 3 months (90 days)
    WINDOW_DAYS = 180
    STEP_DAYS = 90

    start_date = pd.Timestamp(cohort_min, tz='UTC')
    end_date = pd.Timestamp(cohort_max, tz='UTC')

    windows = []
    current = start_date
    while current + timedelta(days=WINDOW_DAYS) <= end_date:
        win_start = current
        win_end = current + timedelta(days=WINDOW_DAYS)
        windows.append((win_start, win_end))
        current += timedelta(days=STEP_DAYS)

    print(f"Generated {len(windows)} rolling 6-month windows (step 3mo)\n")

    rows = []
    for win_start, win_end in windows:
        mask = (setup['entry_dt'] >= win_start) & (setup['entry_dt'] < win_end)
        sub = setup[mask]
        s = summarize(sub['r_v31'].tolist())
        if s is None:
            continue
        rows.append({
            'window_start': str(win_start.date()),
            'window_end':   str(win_end.date()),
            'n':            s['n'],
            'wr':           s['wr'],
            'pf':           s['pf'],
            'avg_r':        s['avg_r'],
            'total_r':      s['total_r'],
        })

    out = pd.DataFrame(rows)
    out.to_csv(OUT_CSV, index=False)
    print("Per-window results:")
    print(out.to_string(index=False))

    # Stability analysis
    print("\n=== Stability summary ===")
    pf_series = out['pf']
    n_total = len(out)
    print(f"  N windows: {n_total}")
    print(f"  Median PF: {pf_series.median():.2f}")
    print(f"  Mean PF:   {pf_series.mean():.2f}")
    print(f"  Min PF:    {pf_series.min():.2f}  (worst window: {out.loc[pf_series.idxmin(), 'window_start']})")
    print(f"  Max PF:    {pf_series.max():.2f}  (best window: {out.loc[pf_series.idxmax(), 'window_start']})")
    print()
    for threshold in (1.0, 1.3, 1.5, 2.0, 3.0):
        pct = (pf_series >= threshold).mean() * 100
        print(f"  Windows with PF >= {threshold}: {(pf_series >= threshold).sum()} / {n_total} ({pct:.0f}%)")

    # Annualized R per window
    print(f"\n  Median total_R per 6mo window: {out['total_r'].median():.1f}")
    print(f"  Min/Max total_R: {out['total_r'].min():.1f} / {out['total_r'].max():.1f}")
    print(f"  Negative-R windows: {(out['total_r'] < 0).sum()} / {n_total}")

    print(f"\nWrote {OUT_CSV}")
    print(f"Total runtime: {time.time()-t0:.1f}s")


if __name__ == '__main__':
    main()
