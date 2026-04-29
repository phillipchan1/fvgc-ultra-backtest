#!/usr/bin/env python3
"""
15m FVG Breakout CONTINUATION study (canonical n=40 cohort).

Same machinery as reversal_fvg_continuation/run.py, with one critical change:
trade direction matches the BREAK direction (continuation), not the opposite
(reversal). This produces the canonical n=40 cohort referenced in the
'15m FVG Breakout Continuation' Notion play.

Diff from reversal version (line 344):
  - Old:  entry_dir = 'short' if sweep['sweep_direction'] == 'up' else 'long'
  - New:  entry_dir = 'long'  if sweep['sweep_direction'] == 'up' else 'short'

Event sequence: sweep (close-through, non-reclaiming) -> opposing FVG
inversion -> first FVGC signal in BREAK direction.
"""

import sys
import time as _time
from datetime import time as dtime
from pathlib import Path

import numpy as np
import pandas as pd
import pytz

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from fvgc.data import load_candles
from fvgc.model import generate_signals
from fvgc.engine import simulate_trades, summarize_results, print_summary

# ===================================================================
# Constants
# ===================================================================

NY_TZ = pytz.timezone('America/New_York')
ENTRY_START = dtime(9, 30)
ENTRY_END = dtime(10, 15)

STUDY_DIR = Path(__file__).resolve().parent
RESULTS_DIR = STUDY_DIR / 'results'

TIMEFRAME_CONFIGS = {
    '30s': {
        'path': ROOT / 'data' / 'consolidated' / 'nq-front-month.ohlcv-30s.csv',
        # Canonical Notion config: rw=10, ew=40, reclaims=False, locality='any'
        'reversal_windows': [10],
        'entry_windows': [40],
        'baseline_trades': None,
        'baseline_fvgs': None,
    },
}

LIQUIDITY_PATH = ROOT / 'data' / 'levels' / 'liquidity_levels.csv'

RUN_ORDER = ['30s']


# ===================================================================
# Level loading + filtering
# ===================================================================

def load_liquidity_levels() -> dict:
    """Load and filter levels, return dict of date -> list of (price, side, name)."""
    from data.levels.enrich_trades_with_levels import filter_trade_date_levels

    liqu = pd.read_csv(LIQUIDITY_PATH)
    liqu['date'] = pd.to_datetime(liqu['date']).dt.date

    levels_by_date = {}
    for d, grp in liqu.groupby('date'):
        filtered = filter_trade_date_levels(grp)
        if filtered is None or filtered.empty:
            continue
        rows = []
        for _, r in filtered.iterrows():
            price = r['price']
            if pd.isna(price):
                continue
            tf = r.get('timeframe')
            if pd.notna(tf) and str(tf).strip().lower() not in ('', 'nan', 'none'):
                d_str = str(r.get('fvg_direction', '')).lower()
                side = 'support' if d_str == 'bullish' else ('resistance' if d_str == 'bearish' else 'both')
            else:
                side = str(r.get('side', 'both'))
            rows.append((float(price), side, str(r.get('level_name', ''))))
        if rows:
            levels_by_date[d] = rows
    return levels_by_date


# ===================================================================
# Cached baseline loading
# ===================================================================

def load_cached_data(config, candles):
    """Load trades + FVGs from cached CSV files, mapping timestamps to indices."""
    trades_path = config['baseline_trades']
    fvgs_path = config['baseline_fvgs']

    if trades_path is None or not trades_path.exists():
        return None, None
    if fvgs_path is None or not fvgs_path.exists():
        return None, None

    print(f"  Loading cached trades from {trades_path.name}")
    print(f"  Loading cached FVGs from {fvgs_path.name}")

    # Build timestamp -> index map
    ts_to_idx = {}
    for i in range(len(candles)):
        ts_ny = candles.iloc[i]['timestamp_ny']
        ts_str = ts_ny.strftime('%Y-%m-%d %H:%M:%S')
        ts_to_idx[ts_str] = i

    # Load trades
    trades_df = pd.read_csv(trades_path)
    results = []
    for _, row in trades_df.iterrows():
        ts_str = str(row['timestamp'])
        ts_ny = pd.Timestamp(ts_str).tz_localize(NY_TZ) if pd.Timestamp(ts_str).tzinfo is None else pd.Timestamp(ts_str)
        sl_val = row.get('sl', '')
        tp_val = row.get('tp', '')
        sl_dist_val = row.get('sl_dist', '')

        r = {
            'timestamp': ts_ny,
            'direction': row['direction'],
            'entry_price': float(row['entry_price']),
            'variant': row['variant'],
            'fvg_id': int(row['fvg_id']),
            'fvg_direction': row['fvg_direction'],
            'fvg_top': float(row['fvg_top']),
            'fvg_bottom': float(row['fvg_bottom']),
            'fvg_mid': float(row['fvg_mid']),
            'fvg_created_ts': pd.Timestamp(row['fvg_created_at']).tz_localize(NY_TZ),
            'entry_idx': int(row['entry_idx']),
            'outcome': row['outcome'],
            'exit_price': row.get('exit_price', ''),
            'pnl': row.get('pnl', ''),
            'sl': float(sl_val) if sl_val != '' and pd.notna(sl_val) else '',
            'tp': float(tp_val) if tp_val != '' and pd.notna(tp_val) else '',
            'sl_dist': float(sl_dist_val) if sl_dist_val != '' and pd.notna(sl_dist_val) else '',
            'mfe_pts': row.get('mfe_pts', 0.0) if 'mfe_pts' in trades_df.columns else 0.0,
            'mae_pts': row.get('mae_pts', 0.0) if 'mae_pts' in trades_df.columns else 0.0,
            'mfe_r': row.get('mfe_r', 0.0) if 'mfe_r' in trades_df.columns else 0.0,
            'mae_r': row.get('mae_r', 0.0) if 'mae_r' in trades_df.columns else 0.0,
        }
        et = row.get('exit_time', '')
        if et and str(et) not in ('', 'nan'):
            r['exit_time'] = pd.Timestamp(et).tz_localize(NY_TZ)
        else:
            r['exit_time'] = ''
        results.append(r)

    # Load FVGs
    fvgs_df = pd.read_csv(fvgs_path)
    all_fvgs = []
    for _, row in fvgs_df.iterrows():
        created_str = str(row['created_at'])
        created_idx = ts_to_idx.get(created_str)
        if created_idx is None:
            continue
        all_fvgs.append({
            'id': int(row['fvg_id']),
            'direction': row['direction'],
            'top': float(row['top']),
            'bottom': float(row['bottom']),
            'mid': float(row['mid']),
            'created_idx': created_idx,
            'created_ts': pd.Timestamp(created_str).tz_localize(NY_TZ),
        })

    print(f"  Loaded {len(results)} cached trades, {len(all_fvgs)} cached FVGs")
    return results, all_fvgs


# ===================================================================
# FVG inversion detection
#
# generate_signals() never records inversed_at_idx because midpoint
# kill fires first (close past mid implies close past bottom for
# bullish, top for bearish). We scan candles ourselves.
# ===================================================================

def detect_inversions(all_fvgs, candles):
    """For each FVG, find the first bar where close crosses the far boundary.

    Bullish: inversion = close < bottom
    Bearish: inversion = close > top
    """
    closes = candles['close'].values
    dates = candles['timestamp_ny'].dt.date.values
    n = len(closes)

    # Group FVGs by creation date for day-scoped scanning
    for fvg in all_fvgs:
        created_idx = fvg['created_idx']
        created_date = dates[created_idx]

        if fvg['direction'] == 'bullish':
            boundary = fvg['bottom']
            for i in range(created_idx + 1, n):
                if dates[i] != created_date:
                    break
                if closes[i] < boundary:
                    fvg['inversed_at_idx'] = i
                    break
        else:  # bearish
            boundary = fvg['top']
            for i in range(created_idx + 1, n):
                if dates[i] != created_date:
                    break
                if closes[i] > boundary:
                    fvg['inversed_at_idx'] = i
                    break

    inverted = sum(1 for f in all_fvgs if f.get('inversed_at_idx') is not None)
    print(f"  Inversions detected: {inverted}/{len(all_fvgs)} FVGs")


# ===================================================================
# Sweep detection (vectorized per day)
# ===================================================================

def find_sweeps(candles: pd.DataFrame, levels_by_date: dict) -> list:
    """Find all bars that sweep a liquidity level."""
    sweeps = []
    candles_arr = candles[['high', 'low', 'close']].values
    dates = candles['timestamp_ny'].dt.date.values
    ts_arr = candles['timestamp_ny'].values

    # Group bar indices by date
    date_ranges = {}
    prev_date = None
    start_i = 0
    for i in range(len(candles)):
        d = dates[i]
        if d != prev_date:
            if prev_date is not None:
                date_ranges[prev_date] = (start_i, i)
            start_i = i
            prev_date = d
    if prev_date is not None:
        date_ranges[prev_date] = (start_i, len(candles))

    for d, (lo_i, hi_i) in date_ranges.items():
        day_levels = levels_by_date.get(d)
        if not day_levels:
            continue

        highs = candles_arr[lo_i:hi_i, 0]
        lows = candles_arr[lo_i:hi_i, 1]
        closes = candles_arr[lo_i:hi_i, 2]

        for price, side, name in day_levels:
            if side in ('resistance', 'both'):
                mask = highs >= price
                idxs = np.where(mask)[0]
                for j in idxs:
                    abs_idx = lo_i + j
                    sweeps.append({
                        'sweep_bar_idx': abs_idx,
                        'sweep_bar_ts': ts_arr[abs_idx],
                        'sweep_direction': 'up',
                        'sweep_level_price': price,
                        'sweep_level_name': name,
                        'sweep_reclaims': bool(closes[j] < price),
                        'sweep_close': float(closes[j]),
                        'sweep_date': d,
                    })

            if side in ('support', 'both'):
                mask = lows <= price
                idxs = np.where(mask)[0]
                for j in idxs:
                    abs_idx = lo_i + j
                    sweeps.append({
                        'sweep_bar_idx': abs_idx,
                        'sweep_bar_ts': ts_arr[abs_idx],
                        'sweep_direction': 'down',
                        'sweep_level_price': price,
                        'sweep_level_name': name,
                        'sweep_reclaims': bool(closes[j] > price),
                        'sweep_close': float(closes[j]),
                        'sweep_date': d,
                    })

    sweeps.sort(key=lambda s: s['sweep_bar_idx'])
    return sweeps


# ===================================================================
# Reversal confirmation + entry matching
# ===================================================================

def build_fvg_inversion_index(all_fvgs):
    """Build inversed_at_idx -> [fvgs] lookup dicts, partitioned by direction."""
    bullish_by_inv = {}
    bearish_by_inv = {}
    for fvg in all_fvgs:
        inv = fvg.get('inversed_at_idx')
        if inv is None:
            continue
        target = bullish_by_inv if fvg['direction'] == 'bullish' else bearish_by_inv
        if inv not in target:
            target[inv] = []
        target[inv].append(fvg)
    return bullish_by_inv, bearish_by_inv


def match_reversal_events(sweeps, all_fvgs, results, reversal_window,
                          entry_window, fvg_locality,
                          bullish_inv_idx, bearish_inv_idx):
    """Match sweep -> inversion -> entry for a single grid cell.

    Uses pre-built inversion index for O(rw) lookup per sweep instead of O(fvgs).
    """
    signals_by_idx = {}
    for sig in results:
        idx = sig['entry_idx']
        if idx not in signals_by_idx:
            signals_by_idx[idx] = []
        signals_by_idx[idx].append(sig)

    claimed_signal_indices = set()
    events = []

    for sweep in sweeps:
        sweep_idx = sweep['sweep_bar_idx']
        opposing_dir = 'bullish' if sweep['sweep_direction'] == 'up' else 'bearish'
        # CONTINUATION: trade direction = SAME as break direction.
        entry_dir = 'long' if sweep['sweep_direction'] == 'up' else 'short'
        inv_index = bullish_inv_idx if opposing_dir == 'bullish' else bearish_inv_idx

        best_fvg = None
        best_dist = float('inf')

        # Check only bars within the reversal window
        for check_bar in range(sweep_idx, sweep_idx + reversal_window + 1):
            fvgs_at_bar = inv_index.get(check_bar)
            if not fvgs_at_bar:
                continue
            for fvg in fvgs_at_bar:
                if fvg['created_idx'] >= sweep_idx:
                    continue

                fvg_mid = fvg['mid']

                if fvg_locality == 'between_price_and_level':
                    lo = min(sweep['sweep_close'], sweep['sweep_level_price'])
                    hi = max(sweep['sweep_close'], sweep['sweep_level_price'])
                    if not (lo <= fvg_mid <= hi):
                        continue

                dist = abs(fvg_mid - sweep['sweep_close'])
                if dist < best_dist:
                    best_dist = dist
                    best_fvg = fvg

        if best_fvg is None:
            continue

        inversion_idx = best_fvg['inversed_at_idx']

        # Find first signal in entry_dir within entry_window after inversion
        found_signal = None
        for check_idx in range(inversion_idx, inversion_idx + entry_window + 1):
            if check_idx in claimed_signal_indices:
                continue
            if check_idx not in signals_by_idx:
                continue
            for sig in signals_by_idx[check_idx]:
                if sig['direction'] != entry_dir:
                    continue
                ts = sig['timestamp']
                t = ts.time() if hasattr(ts, 'time') else pd.Timestamp(ts).time()
                if not (ENTRY_START <= t <= ENTRY_END):
                    continue
                found_signal = sig
                break
            if found_signal is not None:
                break

        if found_signal is None:
            continue

        claimed_signal_indices.add(found_signal['entry_idx'])

        events.append({
            **found_signal,
            'sweep_level_name': sweep['sweep_level_name'],
            'sweep_bar_idx': sweep['sweep_bar_idx'],
            'sweep_bar_ts': sweep['sweep_bar_ts'],
            'sweep_direction': sweep['sweep_direction'],
            'sweep_reclaims': sweep['sweep_reclaims'],
            'inversion_fvg_id': best_fvg['id'],
            'inversion_bar_idx': inversion_idx,
            'inversion_bar_ts': None,
            'reversal_window': reversal_window,
            'entry_window': entry_window,
            'fvg_locality': fvg_locality,
        })

    return events


# ===================================================================
# Grid computation
# ===================================================================

def compute_grid_cell_stats(events):
    tradeable = [e for e in events if e.get('outcome') in ('win', 'loss')]
    n_events = len(events)
    n_trades = len(tradeable)

    if n_trades == 0:
        return {
            'n_events': n_events,
            'n_trades': 0,
            'win_rate': None,
            'expectancy_r': None,
            'avg_mfe_r': None,
            'avg_mae_r': None,
        }

    wins = sum(1 for e in tradeable if e['outcome'] == 'win')
    win_rate = wins / n_trades
    expectancy_r = (wins * 1.0 + (n_trades - wins) * -1.0) / n_trades

    mfe_vals = [float(e['mfe_r']) for e in tradeable
                if e.get('mfe_r', '') != '' and float(e.get('mfe_r', 0)) != 0]
    mae_vals = [float(e['mae_r']) for e in tradeable
                if e.get('mae_r', '') != '' and float(e.get('mae_r', 0)) != 0]

    return {
        'n_events': n_events,
        'n_trades': n_trades,
        'win_rate': round(win_rate, 4),
        'expectancy_r': round(expectancy_r, 4),
        'avg_mfe_r': round(np.mean(mfe_vals), 4) if mfe_vals else None,
        'avg_mae_r': round(np.mean(mae_vals), 4) if mae_vals else None,
    }


def compute_baseline(results):
    baseline = []
    for r in results:
        ts = r['timestamp']
        t = ts.time() if hasattr(ts, 'time') else pd.Timestamp(ts).time()
        if ENTRY_START <= t <= ENTRY_END:
            baseline.append(r)
    return baseline


def run_timeframe(tf, config, levels_by_date):
    print(f"\n{'='*60}")
    print(f"  Timeframe: {tf}")
    print(f"{'='*60}")

    t0 = _time.time()
    candles = load_candles(config['path'], interval=tf)
    print(f"  Candle load: {_time.time() - t0:.1f}s")

    t0 = _time.time()
    results, all_fvgs = load_cached_data(config, candles)
    if results is None:
        print("  No cache — running generate_signals + simulate_trades...")
        t1 = _time.time()
        signals, all_fvgs = generate_signals(candles)
        print(f"  generate_signals: {_time.time() - t1:.1f}s")
        t1 = _time.time()
        results = simulate_trades(signals, candles)
        print(f"  simulate_trades: {_time.time() - t1:.1f}s")
    print(f"  Data ready: {_time.time() - t0:.1f}s — {len(results)} trades, {len(all_fvgs)} FVGs")

    # Detect inversions (not tracked by model due to midpoint-first kill order)
    t0 = _time.time()
    detect_inversions(all_fvgs, candles)
    print(f"  Inversion scan: {_time.time() - t0:.1f}s")

    # Find sweeps
    t0 = _time.time()
    sweeps = find_sweeps(candles, levels_by_date)
    print(f"  Sweeps: {len(sweeps)} found in {_time.time() - t0:.1f}s")

    # Baseline
    baseline_trades = compute_baseline(results)
    baseline_stats = compute_grid_cell_stats(baseline_trades)
    print(f"  Baseline (09:30-10:15): {baseline_stats['n_trades']} trades, "
          f"WR={baseline_stats['win_rate']}")

    grid_rows = []
    all_trade_rows = []

    grid_rows.append({
        'timeframe': tf,
        'reversal_window': 'NA',
        'entry_window': 'NA',
        'sweep_reclaims': 'NA',
        'fvg_locality': 'NA',
        **baseline_stats,
    })

    sweeps_true = [s for s in sweeps if s['sweep_reclaims']]
    sweeps_false = [s for s in sweeps if not s['sweep_reclaims']]

    # Build FVG inversion index once
    bullish_inv_idx, bearish_inv_idx = build_fvg_inversion_index(all_fvgs)
    print(f"  FVG inversion index: {sum(len(v) for v in bullish_inv_idx.values())} bullish, "
          f"{sum(len(v) for v in bearish_inv_idx.values())} bearish")

    t0 = _time.time()
    for rw in config['reversal_windows']:
        for ew in config['entry_windows']:
            for reclaims_val in [True, False]:
                filtered_sweeps = sweeps_true if reclaims_val else sweeps_false
                for locality in ['between_price_and_level', 'any']:
                    events = match_reversal_events(
                        filtered_sweeps, all_fvgs, results,
                        rw, ew, locality,
                        bullish_inv_idx, bearish_inv_idx,
                    )
                    stats = compute_grid_cell_stats(events)
                    grid_rows.append({
                        'timeframe': tf,
                        'reversal_window': rw,
                        'entry_window': ew,
                        'sweep_reclaims': reclaims_val,
                        'fvg_locality': locality,
                        **stats,
                    })
                    for e in events:
                        all_trade_rows.append({**e, 'timeframe': tf})

    print(f"  Grid sweep: {_time.time() - t0:.1f}s")

    cells_with_trades = [r for r in grid_rows if r.get('n_trades', 0) > 0
                         and r['reversal_window'] != 'NA']
    if cells_with_trades:
        best = max(cells_with_trades, key=lambda x: x['n_trades'])
        print(f"  Largest cohort: rw={best['reversal_window']} ew={best['entry_window']} "
              f"reclaims={best['sweep_reclaims']} loc={best['fvg_locality']} -> "
              f"{best['n_trades']} trades, WR={best['win_rate']}")

    return grid_rows, all_trade_rows


# ===================================================================
# Output formatting
# ===================================================================

def format_trade_row(t):
    row = {}
    for k in ['timeframe', 'reversal_window', 'entry_window', 'sweep_reclaims', 'fvg_locality']:
        row[k] = t.get(k, '')
    for k in ['sweep_level_name', 'sweep_bar_idx', 'sweep_bar_ts', 'sweep_direction',
              'inversion_fvg_id', 'inversion_bar_idx', 'inversion_bar_ts']:
        row[k] = t.get(k, '')

    ts = t.get('timestamp', '')
    row['timestamp'] = ts.strftime('%Y-%m-%d %H:%M:%S') if hasattr(ts, 'strftime') else str(ts)
    row['direction'] = t.get('direction', '')
    row['entry_price'] = t.get('entry_price', '')
    row['variant'] = t.get('variant', '')
    row['fvg_id'] = t.get('fvg_id', '')
    row['fvg_direction'] = t.get('fvg_direction', '')
    row['fvg_top'] = t.get('fvg_top', '')
    row['fvg_bottom'] = t.get('fvg_bottom', '')
    row['fvg_mid'] = t.get('fvg_mid', '')
    fvg_ts = t.get('fvg_created_ts', '')
    row['fvg_created_ts'] = fvg_ts.strftime('%Y-%m-%d %H:%M:%S') if hasattr(fvg_ts, 'strftime') else str(fvg_ts)
    row['sl'] = t.get('sl', '')
    row['tp'] = t.get('tp', '')
    row['sl_dist'] = t.get('sl_dist', '')
    row['entry_idx'] = t.get('entry_idx', '')
    row['tap_bar_idx'] = t.get('tap_bar_idx', '')
    row['outcome'] = t.get('outcome', '')
    row['exit_price'] = t.get('exit_price', '')
    exit_t = t.get('exit_time', '')
    row['exit_time'] = exit_t.strftime('%Y-%m-%d %H:%M:%S') if hasattr(exit_t, 'strftime') else str(exit_t)
    row['pnl'] = t.get('pnl', '')
    row['mfe_pts'] = t.get('mfe_pts', '')
    row['mae_pts'] = t.get('mae_pts', '')
    row['mfe_r'] = t.get('mfe_r', '')
    row['mae_r'] = t.get('mae_r', '')
    return row


# ===================================================================
# Main
# ===================================================================

def main():
    print("Loading liquidity levels...")
    levels_by_date = load_liquidity_levels()
    print(f"  {len(levels_by_date)} trading days with levels")

    all_grid_rows = []
    all_trade_rows = []

    for tf in RUN_ORDER:
        config = TIMEFRAME_CONFIGS[tf]
        grid_rows, trade_rows = run_timeframe(tf, config, levels_by_date)
        all_grid_rows.extend(grid_rows)
        all_trade_rows.extend(trade_rows)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    grid_df = pd.DataFrame(all_grid_rows)
    grid_cols = ['timeframe', 'reversal_window', 'entry_window', 'sweep_reclaims',
                 'fvg_locality', 'n_events', 'n_trades', 'win_rate', 'expectancy_r',
                 'avg_mfe_r', 'avg_mae_r']
    grid_df = grid_df[grid_cols]
    grid_df.to_csv(RESULTS_DIR / 'grid_summary.csv', index=False)
    print(f"\nWrote {len(grid_df)} grid rows to results/grid_summary.csv")

    trade_formatted = [format_trade_row(t) for t in all_trade_rows]
    if trade_formatted:
        trades_df = pd.DataFrame(trade_formatted)
        trades_df.to_csv(RESULTS_DIR / 'trades_continuation.csv', index=False)
        print(f"Wrote {len(trades_df)} trade rows to results/trades_continuation.csv")
        # Also filter to canonical 15m FVG sweep cohort and write that separately
        is_15m = trades_df['sweep_level_name'].astype(str).str.contains('15m', case=False, na=False)
        canonical = trades_df[is_15m].copy()
        canonical.to_csv(RESULTS_DIR / 'trades_continuation_15m_only.csv', index=False)
        print(f"Wrote {len(canonical)} 15m-FVG-sweep trades to results/trades_continuation_15m_only.csv")
    else:
        print("No reversal trades found across any grid cell.")

    # Summary
    print("\n" + "=" * 60)
    print("  GRID SUMMARY")
    print("=" * 60)
    for tf in RUN_ORDER:
        tf_rows = [r for r in all_grid_rows if r['timeframe'] == tf]
        baseline = [r for r in tf_rows if r['reversal_window'] == 'NA']
        study_rows = [r for r in tf_rows if r['reversal_window'] != 'NA' and r['n_trades'] > 0]

        if baseline:
            b = baseline[0]
            print(f"\n  {tf} baseline: {b['n_trades']} trades, WR={b['win_rate']}")

        if study_rows:
            best_wr = max(study_rows, key=lambda x: (x['win_rate'] or 0))
            print(f"  {tf} best WR: rw={best_wr['reversal_window']} ew={best_wr['entry_window']} "
                  f"recl={best_wr['sweep_reclaims']} loc={best_wr['fvg_locality']} -> "
                  f"n={best_wr['n_trades']} WR={best_wr['win_rate']} E[R]={best_wr['expectancy_r']}")
            most_trades = max(study_rows, key=lambda x: x['n_trades'])
            print(f"  {tf} largest: rw={most_trades['reversal_window']} ew={most_trades['entry_window']} "
                  f"recl={most_trades['sweep_reclaims']} loc={most_trades['fvg_locality']} -> "
                  f"n={most_trades['n_trades']} WR={most_trades['win_rate']} E[R]={most_trades['expectancy_r']}")

    # ifvg dominance check
    if all_trade_rows:
        total = len(all_trade_rows)
        ifvg_count = sum(1 for t in all_trade_rows if t.get('variant') == 'ifvg')
        pct = ifvg_count / total * 100
        print(f"\n  IFVG variant: {ifvg_count}/{total} = {pct:.1f}%")
        if pct > 50:
            print("  WARNING: ifvg variants dominate the cohort (>50%)")


if __name__ == '__main__':
    main()
