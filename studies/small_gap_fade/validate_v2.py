#!/usr/bin/env python3
"""
Validate v2 headline cell with two fixes:

  1. Shift entry from 9:30:00 open -> 9:31:00 open (after 9:30 1m candle closes,
     so candle_930_aligned is legitimately known at entry time).
  2. In-sample / out-of-sample split at 2025-06-01 (~10 months OOS).

Headline cell being validated (from analysis.md):
  gap-down, open inside prior-day RTH range, gap_atr < 0.6,
  9:30 candle closes bullish (aligned with long fade),
  scale-out (TP1 = 50% of gap, runner = PDC with BE stop),
  stop_mult in {1.0, 1.2, 1.5}, time_stop = 10:45.

Also reports static target=0.5 variant (single-unit fade to 50% fill).
"""

import sys
from pathlib import Path
from datetime import time as dtime, date as ddate

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import numpy as np

from fvgc.data import load_candles
from run import (
    compute_daily_levels, build_candle_arrays, walk_scaleout,
    walk_static, derive_static, cell_stats, binomial_two_sided_p,
    RTH_OPEN, MIN_GAP_PTS,
)

STUDY_DIR = Path(__file__).resolve().parent
RESULTS_DIR = STUDY_DIR / 'results'

TIMEFRAMES = {
    '15s': ROOT / 'data' / 'consolidated' / 'nq-front-month.ohlcv-15s.csv',
    '30s': ROOT / 'data' / 'consolidated' / 'nq-front-month.ohlcv-30s.csv',
    '1m':  ROOT / 'data' / 'consolidated' / 'nq-front-month.ohlcv-1m.csv',
}
TRADING_DAYS_PATH = ROOT / 'data' / 'trading_days' / 'trading_days.csv'

ENTRY_TIME = dtime(9, 31)    # after 9:30 1m candle closes
TIME_STOP = dtime(10, 45)
STOP_MULTS = [1.0, 1.2, 1.5]
OOS_SPLIT = ddate(2025, 6, 1)


def find_931_entries(candles: pd.DataFrame) -> pd.DataFrame:
    """Find the first bar on/after 9:31:00 per day.  Must exist at 9:31:00 exactly."""
    c = candles.copy()
    c['date'] = c['timestamp_ny'].dt.date
    c['_time'] = c['timestamp_ny'].dt.time
    at_931 = c[c['_time'] == ENTRY_TIME]
    # For 15s/30s timeframes 9:31:00 is still a bar; for 1m also 9:31:00 bar exists.
    first = at_931.groupby('date', as_index=False).head(1)
    rows = []
    for idx, r in first.iterrows():
        rows.append({'date': r['date'], 'entry_idx': idx,
                     'entry_time': r['timestamp_ny'], 'entry_open': r['open']})
    return pd.DataFrame(rows)


def build_signals_931(daily: pd.DataFrame, entries: pd.DataFrame,
                      target_frac: float, stop_mult: float) -> list:
    """Signals with 9:31 entry.  gap = 9:31_open - PDC."""
    merged = entries.merge(daily, on='date', how='left')
    sigs = []
    for _, r in merged.iterrows():
        pdc = r['prior_day_close']; pdh = r['prior_day_high']; pdl = r['prior_day_low']
        atr = r['atr_14d']
        if any(pd.isna(x) for x in (pdc, pdh, pdl, atr)) or atr <= 0:
            continue
        open_px = r['entry_open']
        gap = open_px - pdc
        if abs(gap) < MIN_GAP_PTS:
            continue
        if not (pdl < open_px < pdh):
            continue
        gap_abs = abs(gap)
        if gap > 0:
            direction = 'short'
            tp = open_px - target_frac * gap_abs
            sl = open_px + stop_mult * gap_abs
        else:
            direction = 'long'
            tp = open_px + target_frac * gap_abs
            sl = open_px - stop_mult * gap_abs
        sigs.append({
            'timestamp': r['entry_time'], 'entry_idx': int(r['entry_idx']),
            'direction': direction, 'entry_price': float(open_px),
            'sl': float(sl), 'tp': float(tp),
            'sl_dist': float(stop_mult * gap_abs),
            'target_frac': target_frac, 'stop_mult': stop_mult,
            'date': r['date'], 'gap_pts': float(gap), 'gap_abs': float(gap_abs),
            'gap_atr_ratio': float(gap_abs / atr), 'atr_14d': float(atr),
            'prior_day_close': float(pdc),
        })
    return sigs


def run_timeframe(tf_label: str, data_path: Path, td: pd.DataFrame) -> pd.DataFrame:
    print(f"\n{'='*72}")
    print(f"  TIMEFRAME: {tf_label}   (entry=9:31, time_stop=10:45)")
    print(f"{'='*72}")

    candles = load_candles(data_path)
    daily = compute_daily_levels(candles)
    entries = find_931_entries(candles)
    print(f"  {len(daily)} days; {len(entries)} with 9:31 bar")

    arr = build_candle_arrays(candles)

    # Join candle_930_aligned from trading_days
    td_small = td[['date', 'candle_930_direction', 'has_red_folder_news']].copy()
    td_small['date'] = pd.to_datetime(td_small['date']).dt.date
    td_map = td_small.set_index('date').to_dict(orient='index')

    def candle_aligned(d, direction):
        r = td_map.get(d)
        if not r: return False
        cd = r.get('candle_930_direction')
        if pd.isna(cd) or cd == 'doji': return False
        return (direction == 'long' and cd == 'bullish') or (direction == 'short' and cd == 'bearish')

    def has_news(d):
        r = td_map.get(d)
        return False if not r else bool(r.get('has_red_folder_news', False))

    rows = []
    for stop_mult in STOP_MULTS:
        # --- scale-out ---
        sigs = build_signals_931(daily, entries, target_frac=1.0, stop_mult=stop_mult)
        for sig in sigs:
            if sig['gap_atr_ratio'] >= 0.6: continue
            if sig['direction'] != 'long': continue
            if not candle_aligned(sig['date'], sig['direction']): continue
            res = walk_scaleout(sig, arr, TIME_STOP)
            rows.append({
                'scheme': 'scaleout', 'stop_mult': stop_mult,
                'target_frac': None, 'date': sig['date'],
                'gap_atr_ratio': sig['gap_atr_ratio'],
                'has_red_folder_news': has_news(sig['date']),
                'outcome': res['outcome'], 'exit_reason': res['exit_reason'],
                'pnl': res['pnl'], 'sl_dist': sig['sl_dist'],
                'max_fav': res['max_fav'], 'max_adv': res['max_adv'],
            })
        # --- static target=0.5 ---
        sigs = build_signals_931(daily, entries, target_frac=0.5, stop_mult=stop_mult)
        for sig in sigs:
            if sig['gap_atr_ratio'] >= 0.6: continue
            if sig['direction'] != 'long': continue
            if not candle_aligned(sig['date'], sig['direction']): continue
            trace = walk_static(sig, arr, TIME_STOP)
            res = derive_static(trace, sig, TIME_STOP)
            rows.append({
                'scheme': 'static_50', 'stop_mult': stop_mult,
                'target_frac': 0.5, 'date': sig['date'],
                'gap_atr_ratio': sig['gap_atr_ratio'],
                'has_red_folder_news': has_news(sig['date']),
                'outcome': res['outcome'], 'exit_reason': res['exit_reason'],
                'pnl': res['pnl'], 'sl_dist': sig['sl_dist'],
                'max_fav': trace['max_fav'], 'max_adv': trace['max_adv'],
            })

    df = pd.DataFrame(rows)
    df['timeframe'] = tf_label
    df['period'] = df['date'].apply(lambda d: 'IS' if d < OOS_SPLIT else 'OOS')
    return df


def report(df: pd.DataFrame, label: str):
    print(f"\n  {'-'*68}")
    print(f"  {label}")
    print(f"  {'-'*68}")
    print(f"  {'scheme':<10} {'stop':<5} {'period':<4} {'n':>4}  {'wr':>6}  {'pf':>7}  {'pnl':>8}  {'p':>6}")
    for (scheme, stop), grp in df.groupby(['scheme', 'stop_mult']):
        for period in ['ALL', 'IS', 'OOS']:
            sub = grp if period == 'ALL' else grp[grp['period'] == period]
            st = cell_stats(sub)
            if st['n'] == 0:
                print(f"  {scheme:<10} {stop:<5.1f} {period:<4}   0")
                continue
            wr = f"{st['wr']:.1f}%" if st['wr'] is not None else '—'
            pf = (f"{st['pf']:.2f}x" if st['pf'] not in (None, float('inf'))
                  else ('inf' if st['pf'] == float('inf') else '—'))
            decided = st['wins'] + st['losses']
            pval = binomial_two_sided_p(st['wins'], decided) if decided > 0 else None
            pv = f"{pval:.3f}" if pval is not None else '—'
            print(f"  {scheme:<10} {stop:<5.1f} {period:<4} {st['n']:>4}  {wr:>6}  "
                  f"{pf:>7}  {st['pnl']:>8.1f}  {pv:>6}")


def main():
    print("=" * 72)
    print("Small-Gap Fade v2 — VALIDATION: 9:31 entry + IS/OOS split")
    print("=" * 72)
    print(f"  OOS split: {OOS_SPLIT}  (IS < {OOS_SPLIT} <= OOS)")
    print(f"  Filter: candle_930 aligned, gap_atr<0.6, long only, stop in {STOP_MULTS}")

    td = pd.read_csv(TRADING_DAYS_PATH)
    all_results = []
    for tf_label, data_path in TIMEFRAMES.items():
        if not data_path.exists():
            continue
        df = run_timeframe(tf_label, data_path, td)
        all_results.append(df)
        report(df, f"TF={tf_label} — headline cell (candle_930 aligned, long, gap_atr<0.6)")

    if all_results:
        combined = pd.concat(all_results, ignore_index=True)
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        combined.to_csv(RESULTS_DIR / 'validation_v2.csv', index=False)
        print(f"\n  Wrote {RESULTS_DIR / 'validation_v2.csv'} ({len(combined)} rows)")

    print("\nDone.")


if __name__ == '__main__':
    main()
