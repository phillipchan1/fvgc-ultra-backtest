#!/usr/bin/env python3
"""
FVGC v2.0.5 Signal Detector

v2.0.5: §3.7 opposing FVG touch + inverse = IFVG (valid); touch without inverse = dead.
v2.0.4: §1.2 swing sweep kill only runs after first tap, not from creation.
v2.0.3: §1.2 self-reference exclusion on swing sweep kill check.
v2.0.2: §1.2 swing sweep without BOS permanently kills FVG (third kill condition).
v2.0.1: §3.5 self-reference expanded — skip any candle that IS the swing point.
v2.0: Minimum FVG size 3 NQ points (§1.1).
v1.9.2–v1.9.4: Prior swing / tap / opposing-FVG rules (see Notion).

Entry variants: NoFVG, IFVG, BOS, Protected Swing
"""

import pandas as pd
import pytz
from datetime import time as dtime, timedelta
from pathlib import Path
import argparse
from typing import List, Dict, Optional, Tuple
import sys

# ---------------------------------------------------------------------------
# Constants  (Notion §6)
# ---------------------------------------------------------------------------
NY_TZ = pytz.timezone('America/New_York')
TRADING_WINDOW_START = dtime(9, 30)
TRADING_WINDOW_END = dtime(10, 15)
SWING_LOOKBACK = 2
FVG_START_TIME = dtime(9, 30)
SL_INCREMENT = 5
SL_MIN = 15
SL_MAX = 60
RR_RATIO = 1.0
MIN_FVG_SIZE = 3.0  # NQ points; §1.1 v2.0

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
DATA_DIR = Path('data')
RAW_DATA_PATH = DATA_DIR / 'consolidated' / 'nq-front-month.ohlcv-30s.csv'
LOGS_DIR = Path('logs')
FVGS_LOG_PATH = LOGS_DIR / 'fvgs.csv'
TRADES_LOG_PATH = LOGS_DIR / 'trades_generated.csv'
TARGET_DATES = ['2026-03-24', '2026-03-25']


# ===================================================================
# Data loading
# ===================================================================

def load_candles(path: Path = RAW_DATA_PATH, interval: str = '30s') -> pd.DataFrame:
    """Load candles — handles both pre-aggregated and raw 1s Databento CSVs."""
    print(f"Loading data from {path} ...")
    df = pd.read_csv(path)

    if 'timestamp_utc' in df.columns:
        df['timestamp_utc'] = pd.to_datetime(df['timestamp_utc'], utc=True)
        df['timestamp_ny'] = df['timestamp_utc'].dt.tz_convert(NY_TZ)
        df = df.sort_values('timestamp_utc').reset_index(drop=True)
        print(f"  {len(df):,} pre-aggregated candles loaded")
        return df

    df['ts_event'] = pd.to_datetime(df['ts_event'], utc=True)
    print(f"  {len(df):,} raw 1s rows — aggregating to {interval} ...")

    df = df[(df['open'] >= 10_000) & (df['close'] >= 10_000) &
            (df['low'] >= 10_000) & (df['high'] >= 10_000)]

    # Drop spreads if present
    if 'symbol' in df.columns:
        df = df[~df['symbol'].str.contains('-', na=False)]

    df = df.sort_values('ts_event').reset_index(drop=True)
    ts_col = df['ts_event'].dt.floor(interval)

    df['_mid'] = (df['open'] + df['close']) / 2
    group_median = df.groupby(ts_col)['_mid'].transform('median')
    outlier_mask = (df['_mid'] - group_median).abs() > 100
    n_outliers = outlier_mask.sum()
    if n_outliers:
        print(f"  Dropped {n_outliers} outlier rows")
    df = df[~outlier_mask]

    candles = (
        df.groupby(ts_col)
        .agg(open=('open', 'first'), high=('high', 'max'),
             low=('low', 'min'), close=('close', 'last'),
             volume=('volume', 'sum'))
        .reset_index()
        .rename(columns={'ts_event': 'timestamp_utc'})
    )
    candles['timestamp_ny'] = candles['timestamp_utc'].dt.tz_convert(NY_TZ)
    candles = candles.sort_values('timestamp_utc').reset_index(drop=True)
    print(f"  {len(candles):,} {interval} candles")
    return candles


def in_trading_window(ts_ny: pd.Timestamp) -> bool:
    t = ts_ny.time()
    return TRADING_WINDOW_START <= t <= TRADING_WINDOW_END


# ===================================================================
# FVG detection  (§1.1 + §1.5)
# ===================================================================

def detect_fvg(candles: pd.DataFrame, idx: int) -> Optional[Dict]:
    if idx < 2:
        return None
    c1 = candles.iloc[idx - 2]
    c2 = candles.iloc[idx - 1]
    c3 = candles.iloc[idx]

    if c2['timestamp_ny'].time() < FVG_START_TIME or c3['timestamp_ny'].time() < FVG_START_TIME:
        return None

    if c1['high'] < c3['low']:
        gap_size = c3['low'] - c1['high']
        if gap_size < MIN_FVG_SIZE:
            return None
        return {
            'created_idx': idx,
            'created_ts': candles.iloc[idx]['timestamp_ny'],
            'direction': 'bullish',
            'top': c3['low'],
            'bottom': c1['high'],
            'mid': (c3['low'] + c1['high']) / 2,
            'active': True,
            'tap_bar_idx_1': None,
            'tap_bar_idx_2': None,
            'needs_retap': False,
        }

    if c1['low'] > c3['high']:
        gap_size = c1['low'] - c3['high']
        if gap_size < MIN_FVG_SIZE:
            return None
        return {
            'created_idx': idx,
            'created_ts': candles.iloc[idx]['timestamp_ny'],
            'direction': 'bearish',
            'top': c1['low'],
            'bottom': c3['high'],
            'mid': (c1['low'] + c3['high']) / 2,
            'active': True,
            'tap_bar_idx_1': None,
            'tap_bar_idx_2': None,
            'needs_retap': False,
        }
    return None


# ===================================================================
# FVG inversion  (§1.2)
# ===================================================================

def check_inversion(fvg: Dict, candle: pd.Series) -> bool:
    if fvg['direction'] == 'bullish':
        return candle['close'] < fvg['bottom']
    return candle['close'] > fvg['top']


# ===================================================================
# Tap detection  (§2.1 Phase 1)
# ===================================================================

def _candle_enters_fvg(fvg: Dict, candle: pd.Series) -> bool:
    if fvg['direction'] == 'bullish':
        return candle['low'] <= fvg['top']
    return candle['high'] >= fvg['bottom']


def check_midpoint_hold(fvg: Dict, candle: pd.Series) -> bool:
    """v1.5: permanent health check — close past midpoint kills FVG forever."""
    if fvg['direction'] == 'bullish':
        return candle['close'] >= fvg['mid']
    return candle['close'] <= fvg['mid']


# ===================================================================
# Swing-point detection  (§1.3)
# ===================================================================

def compute_swing_points(candles: pd.DataFrame, n: int = SWING_LOOKBACK) -> pd.DataFrame:
    swings = []
    for i in range(n, len(candles) - n):
        h = candles.iloc[i]['high']
        l = candles.iloc[i]['low']
        is_high = all(
            h > candles.iloc[i - j]['high'] and h > candles.iloc[i + j]['high']
            for j in range(1, n + 1))
        is_low = all(
            l < candles.iloc[i - j]['low'] and l < candles.iloc[i + j]['low']
            for j in range(1, n + 1))
        if is_high:
            swings.append({'idx': i, 'type': 'high', 'price': h, 'confirmed_at_idx': i + n - 1})
        if is_low:
            swings.append({'idx': i, 'type': 'low', 'price': l, 'confirmed_at_idx': i + n - 1})
    if swings:
        return pd.DataFrame(swings)
    return pd.DataFrame(columns=['idx', 'type', 'price', 'confirmed_at_idx'])


def current_swing_at(swings_df: pd.DataFrame, bar_idx: int, swing_type: str) -> Optional[Dict]:
    mask = (swings_df['type'] == swing_type) & (swings_df['confirmed_at_idx'] <= bar_idx)
    valid = swings_df[mask]
    if valid.empty:
        return None
    row = valid.iloc[-1]
    return {'idx': int(row['idx']), 'price': row['price']}


# ===================================================================
# SL / TP  (§4)
# ===================================================================

def _compute_sl_tp(entry_price: float, direction: str, variant: str,
                   fvg: Dict, candle: pd.Series) -> Optional[Dict]:
    if variant == 'protected_swing':
        sl_ref = candle['high'] if direction == 'short' else candle['low']
    else:
        sl_ref = fvg['top'] if direction == 'short' else fvg['bottom']

    raw_sl = abs(entry_price - sl_ref)
    rounded_sl = round(raw_sl / SL_INCREMENT) * SL_INCREMENT
    if rounded_sl < SL_MIN or rounded_sl > SL_MAX:
        return None
    tp_dist = rounded_sl * RR_RATIO
    if direction == 'short':
        return {'sl': entry_price + rounded_sl, 'tp': entry_price - tp_dist, 'sl_dist': rounded_sl}
    return {'sl': entry_price - rounded_sl, 'tp': entry_price + tp_dist, 'sl_dist': rounded_sl}


# ===================================================================
# Variant classification  (§3)
# ===================================================================

def _classify_variant(
    tap_idx: int, candle: pd.Series, idx: int,
    candles: pd.DataFrame, swings_df: pd.DataFrame,
    all_fvgs: List[Dict], direction: str,
) -> Optional[str]:
    """v1.9.4 §3.6: Swing check validates BOTH directions of swing interaction."""
    swing_high = current_swing_at(swings_df, idx, 'high')
    swing_low = current_swing_at(swings_df, idx, 'low')

    if direction == 'long':
        opp_touched = _window_touched_swing(tap_idx, idx, candles, swings_df, 'low')
        same_touched = _window_touched_swing(tap_idx, idx, candles, swings_df, 'high')
        entry_closes_through = swing_high is not None and candle['close'] > swing_high['price']
        same_swing = swing_high
    else:
        opp_touched = _window_touched_swing(tap_idx, idx, candles, swings_df, 'high')
        same_touched = _window_touched_swing(tap_idx, idx, candles, swings_df, 'low')
        entry_closes_through = swing_low is not None and candle['close'] < swing_low['price']
        same_swing = swing_low

    if same_touched and not entry_closes_through:
        return None

    if entry_closes_through and _is_first_break(tap_idx, idx, candles, same_swing, direction):
        return 'bos'

    if opp_touched:
        return None

    if tap_idx == idx:
        return 'protected_swing'

    opposing_dir = 'bearish' if direction == 'long' else 'bullish'
    inversed = _inversed_opposing_in_window(tap_idx, idx, all_fvgs, opposing_dir)
    return 'ifvg' if inversed else 'no_fvg'


def _is_first_break(
    tap_idx: int, entry_idx: int, candles: pd.DataFrame,
    swing: Dict, direction: str,
) -> bool:
    """v1.9.1: Entry candle must be the FIRST to close through the swing level.
    Also checks no prior candle SWEPT (wick) the swing — a sweep without close-through
    means structure was already compromised."""
    level = swing['price']
    for i in range(tap_idx, entry_idx):
        c = candles.iloc[i]
        if direction == 'short':
            if c['close'] < level or c['low'] < level:
                return False
        if direction == 'long':
            if c['close'] > level or c['high'] > level:
                return False
    return True


def _window_touched_swing(
    start_idx: int, end_idx: int, candles: pd.DataFrame,
    swings_df: pd.DataFrame, swing_type: str,
) -> bool:
    """§3.5 v2.0.1: Skip any candle in the window that IS the swing point."""
    swing = current_swing_at(swings_df, end_idx, swing_type)
    if swing is None:
        return False

    swing_bar_idx = swing['idx']

    for j in range(start_idx, end_idx + 1):
        if j == swing_bar_idx:
            continue
        c = candles.iloc[j]
        if swing_type == 'high' and c['high'] >= swing['price']:
            return True
        if swing_type == 'low' and c['low'] <= swing['price']:
            return True
    return False


def _inversed_opposing_in_window(
    start_idx: int, end_idx: int, all_fvgs: List[Dict], opposing_dir: str,
) -> bool:
    for dead in all_fvgs:
        if dead['direction'] != opposing_dir:
            continue
        inv = dead.get('inversed_at_idx')
        if inv is not None and start_idx <= inv <= end_idx:
            return True
    return False


def _check_opposing_fvg_interaction(
    candle: pd.Series, direction: str, active_fvgs: List[Dict],
    all_fvgs: List[Dict], bar_idx: int,
) -> str:
    """v2.0.5 §3.7: Entry candle opposing FVG interaction.

    Checks both active FVGs and FVGs killed on the current bar (same-bar kills
    should still block entries).
    Returns 'no_contact', 'ifvg' (touched + inversed), or 'dead' (touched, not inversed).
    """
    candidates = [f for f in active_fvgs if f['active']]
    candidates += [f for f in all_fvgs
                   if f.get('killed_at_idx') == bar_idx
                   or f.get('inversed_at_idx') == bar_idx]

    for opp in candidates:
        if direction == 'long' and opp['direction'] == 'bearish':
            if candle['high'] >= opp['bottom']:
                if candle['close'] > opp['top']:
                    return 'ifvg'
                return 'dead'
        if direction == 'short' and opp['direction'] == 'bullish':
            if candle['low'] <= opp['top']:
                if candle['close'] < opp['bottom']:
                    return 'ifvg'
                return 'dead'
    return 'no_contact'


# ===================================================================
# Signal generation  (§2 — cascading tap, v1.9.1)
# ===================================================================

def generate_signals(candles: pd.DataFrame) -> Tuple[List[Dict], List[Dict]]:
    signals: List[Dict] = []
    active_fvgs: List[Dict] = []
    all_fvgs: List[Dict] = []
    fvg_seq = 0
    swings_df = compute_swing_points(candles)

    prev_date = None
    for i in range(len(candles)):
        candle = candles.iloc[i]
        ts_ny = candle['timestamp_ny']
        cur_date = ts_ny.date()

        if cur_date != prev_date:
            all_fvgs.extend(active_fvgs)
            active_fvgs = []
            prev_date = cur_date

        new_fvg = detect_fvg(candles, i)
        if new_fvg is not None:
            fvg_seq += 1
            new_fvg['id'] = fvg_seq
            active_fvgs.append(new_fvg)

        # --- Phase 1: midpoint + inversion kills (pre-entry) ---
        still_active = []
        for fvg in active_fvgs:
            if not fvg['active']:
                still_active.append(fvg)
                continue

            if not check_midpoint_hold(fvg, candle):
                fvg['active'] = False
                fvg['killed_reason'] = 'midpoint_violated'
                fvg['killed_at_idx'] = i
                all_fvgs.append(fvg)
                continue

            if check_inversion(fvg, candle):
                fvg['active'] = False
                fvg['inversed_at_idx'] = i
                fvg['inversed_at_ts'] = ts_ny
                all_fvgs.append(fvg)
                continue

            if _candle_enters_fvg(fvg, candle):
                if fvg.get('needs_retap'):
                    fvg['needs_retap'] = False
                    fvg['tap_bar_idx_1'] = i
                    fvg['tap_bar_idx_2'] = None
                else:
                    if fvg['tap_bar_idx_1'] is None and i >= fvg['created_idx'] + 1:
                        fvg['tap_bar_idx_1'] = i
                    if fvg['tap_bar_idx_2'] is None and i >= fvg['created_idx'] + 2:
                        fvg['tap_bar_idx_2'] = i

            still_active.append(fvg)
        active_fvgs = still_active

        # --- Phase 2: entry checks (before swing-sweep kill) ---
        if i >= 1 and in_trading_window(ts_ny):
            prev = candles.iloc[i - 1]
            entry = _try_entry_cascading(active_fvgs, candle, prev, i, candles,
                                         swings_df, all_fvgs, ts_ny)
            if entry is not None:
                signals.append(entry)

        # --- Phase 3: swing sweep kill (v2.0.4 §1.2 — only after tap) ---
        still_active2 = []
        for fvg in active_fvgs:
            if not fvg['active']:
                still_active2.append(fvg)
                continue
            if fvg['tap_bar_idx_1'] is None:
                still_active2.append(fvg)
                continue
            swing_type = 'low' if fvg['direction'] == 'bearish' else 'high'
            swing = current_swing_at(swings_df, i, swing_type)
            if swing is not None and swing['idx'] != i:
                swept = False
                if fvg['direction'] == 'bearish' and candle['low'] <= swing['price'] and candle['close'] > swing['price']:
                    swept = True
                elif fvg['direction'] == 'bullish' and candle['high'] >= swing['price'] and candle['close'] < swing['price']:
                    swept = True
                if swept:
                    fvg['active'] = False
                    fvg['killed_reason'] = 'swing_swept_no_bos'
                    fvg['killed_at_idx'] = i
                    all_fvgs.append(fvg)
                    continue
            still_active2.append(fvg)
        active_fvgs = still_active2

    all_fvgs.extend(active_fvgs)
    return signals, all_fvgs


def _try_entry_cascading(
    active_fvgs: List[Dict], candle: pd.Series, prev: pd.Series,
    idx: int, candles: pd.DataFrame, swings_df: pd.DataFrame,
    all_fvgs: List[Dict], ts_ny: pd.Timestamp,
) -> Optional[Dict]:
    """v2.0.5: Cascading tap + re-tap rule + refined opposing FVG check."""
    for fvg in active_fvgs:
        if not fvg['active']:
            continue
        if fvg.get('needs_retap'):
            continue

        direction = 'long' if fvg['direction'] == 'bullish' else 'short'

        if direction == 'long':
            if candle['close'] <= prev['high']:
                continue
        else:
            if candle['close'] >= prev['low']:
                continue

        opp_result = _check_opposing_fvg_interaction(candle, direction, active_fvgs,
                                                       all_fvgs, idx)
        if opp_result == 'dead':
            continue

        tap_candidates = []
        if _candle_enters_fvg(fvg, candle) and idx >= fvg['created_idx'] + 1:
            tap_candidates.append(idx)
        if fvg['tap_bar_idx_1'] is not None and fvg['tap_bar_idx_1'] not in tap_candidates:
            tap_candidates.append(fvg['tap_bar_idx_1'])
        if fvg['tap_bar_idx_2'] is not None and fvg['tap_bar_idx_2'] not in tap_candidates:
            tap_candidates.append(fvg['tap_bar_idx_2'])

        if not tap_candidates:
            continue

        for tap_idx in tap_candidates:
            if tap_idx > idx:
                continue

            if opp_result == 'ifvg':
                variant = 'ifvg'
            else:
                variant = _classify_variant(tap_idx, candle, idx, candles,
                                            swings_df, all_fvgs, direction)
            if variant is None:
                continue

            sl_tp = _compute_sl_tp(candle['close'], direction, variant, fvg, candle)

            fvg['tap_bar_idx_1'] = None
            fvg['tap_bar_idx_2'] = None
            fvg['needs_retap'] = True

            return {
                'timestamp': ts_ny,
                'direction': direction,
                'entry_price': candle['close'],
                'variant': variant,
                'fvg_id': fvg['id'],
                'fvg_direction': fvg['direction'],
                'fvg_top': fvg['top'],
                'fvg_bottom': fvg['bottom'],
                'fvg_mid': fvg['mid'],
                'fvg_created_ts': fvg['created_ts'],
                'sl': sl_tp['sl'] if sl_tp else '',
                'tp': sl_tp['tp'] if sl_tp else '',
                'sl_dist': sl_tp['sl_dist'] if sl_tp else '',
                'entry_idx': idx,
                'tap_bar_idx': tap_idx,
            }
    return None


# ===================================================================
# Logging
# ===================================================================

def log_fvgs(fvgs: List[Dict]):
    rows = []
    for f in fvgs:
        rows.append({
            'fvg_id': f['id'], 'direction': f['direction'],
            'top': f['top'], 'bottom': f['bottom'], 'mid': f['mid'],
            'created_at': f['created_ts'].strftime('%Y-%m-%d %H:%M:%S'),
            'inversed_at': (f['inversed_at_ts'].strftime('%Y-%m-%d %H:%M:%S')
                            if 'inversed_at_ts' in f else ''),
        })
    pd.DataFrame(rows).to_csv(FVGS_LOG_PATH, index=False)
    print(f"Logged {len(rows)} FVGs -> {FVGS_LOG_PATH}")


def log_signals(signals: List[Dict], path: Path = TRADES_LOG_PATH):
    rows = []
    for s in signals:
        rows.append({
            'timestamp': s['timestamp'].strftime('%Y-%m-%d %H:%M:%S'),
            'direction': s['direction'], 'entry_price': s['entry_price'],
            'variant': s['variant'],
            'sl': s.get('sl', ''), 'tp': s.get('tp', ''),
            'sl_dist': s.get('sl_dist', ''),
            'fvg_id': s['fvg_id'], 'fvg_direction': s['fvg_direction'],
            'fvg_top': s['fvg_top'], 'fvg_bottom': s['fvg_bottom'],
            'fvg_mid': s['fvg_mid'],
            'fvg_created_at': s['fvg_created_ts'].strftime('%Y-%m-%d %H:%M:%S'),
            'entry_idx': s.get('entry_idx', ''),
        })
    pd.DataFrame(rows).to_csv(path, index=False)
    print(f"Logged {len(rows)} signals -> {path}")


# ===================================================================
# Main
# ===================================================================

def main():
    parser = argparse.ArgumentParser(description='FVGC v2.0.5 signal detector')
    parser.add_argument(
        '--last-days', type=int, metavar='N',
        help='Print signals from the last N calendar days (from newest bar date in data)',
    )
    parser.add_argument(
        '--data', type=Path, default=RAW_DATA_PATH, metavar='PATH',
        help=f'Path to OHLCV-1s CSV (default: {RAW_DATA_PATH})',
    )
    args = parser.parse_args()

    print("=" * 60)
    print("FVGC v2.0.5 Signal Detector")
    print("=" * 60)
    LOGS_DIR.mkdir(exist_ok=True)

    candles = load_candles(args.data)
    print("\nDetecting FVGs and scanning for entries ...")
    signals, fvgs = generate_signals(candles)

    print(f"\nTotal FVGs across all days: {len(fvgs)}")
    print(f"Total signals across all days: {len(signals)}")

    if args.last_days is not None:
        end_d = candles['timestamp_ny'].max().date()
        start_d = end_d - timedelta(days=args.last_days - 1)
        filtered = [s for s in signals if start_d <= s['timestamp'].date() <= end_d]
        print(f"\n--- Last {args.last_days} calendar days ({start_d} → {end_d}): "
              f"{len(filtered)} signals ---")
        for s in filtered:
            sl = s.get('sl', '')
            tp = s.get('tp', '')
            sl_s = f'{sl:.2f}' if sl != '' else 'skip'
            tp_s = f'{tp:.2f}' if tp != '' else 'skip'
            print(f"  {s['timestamp'].strftime('%Y-%m-%d %H:%M:%S')} {s['direction']:5s} "
                  f"@ {s['entry_price']:.2f}  [{s['variant']:15s}]  "
                  f"FVG#{s['fvg_id']} ({s['fvg_direction']})  SL={sl_s} TP={tp_s}")
        out = LOGS_DIR / f'trades_last_{args.last_days}d.csv'
        log_signals(filtered, path=out)
    else:
        for td in TARGET_DATES:
            target = [s for s in signals if s['timestamp'].strftime('%Y-%m-%d') == td]
            print(f"\n--- {td}: {len(target)} signals ---")
            for s in target:
                print(f"  {s['timestamp'].strftime('%H:%M:%S')} {s['direction']:5s} "
                      f"@ {s['entry_price']:.2f}  [{s['variant']}]  "
                      f"FVG#{s['fvg_id']} ({s['fvg_direction']})")

    log_fvgs(fvgs)
    log_signals(signals)


if __name__ == '__main__':
    main()
