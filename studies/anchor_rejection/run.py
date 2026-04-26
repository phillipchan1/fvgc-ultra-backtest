#!/usr/bin/env python3
"""
Study: Anchor Rejection — does the fade-the-failure-of-a-fixed-liquidity-event
mechanic that powers the 9:30-gap short generalize to other anchors?

Eight anchors are scored on equal footing using a standardized bracket so the
table is apples-to-apples. The bracket deliberately differs from each play's
natural one — we are comparing mechanisms, not reproducing headlines.

Trigger archetypes:
  * entry_bar         — the fixed-time bar IS the trigger (930-gap)
  * first_touch_reject — walk window, first bar where price tags the level
                         AND closes back through it

Standardized bracket (--bracket atr, default):
    sl_dist = max(MIN_STOP_PTS=15, ATR_FRAC=0.30 * prior_day_atr_14)
    tp_dist = TP_R=1.0 * sl_dist
    time_stop = anchor's window end

Optional --bracket structural:
    sl  = trigger-bar wick + STRUCTURAL_BUFFER_PTS=2pt buffer
    tp_dist = 1.0 * sl_dist  (same TP_R)

Run from repo root:
  python studies/anchor_rejection/run.py
  python studies/anchor_rejection/run.py --bracket structural
"""

import argparse
import sys
from datetime import time as dtime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from fvgc.data import load_candles

STUDY_DIR = Path(__file__).resolve().parent
RESULTS_DIR = STUDY_DIR / 'results'

DATA_30S = ROOT / 'data' / 'consolidated' / 'nq-front-month.ohlcv-30s.csv'
VP_PATH = ROOT / 'data' / 'levels' / 'daily_volume_profile.csv'

RTH_OPEN = dtime(9, 30)
RTH_CLOSE = dtime(16, 0)
OR15_END = dtime(9, 45)

MIN_GAP_PTS = 2.0
MIN_STOP_PTS = 15.0
ATR_FRAC = 0.30
TP_R = 1.0
ATR_LOOKBACK = 14
STRUCTURAL_BUFFER_PTS = 2.0

# Per-anchor configuration:
#   archetype   — 'entry_bar' or 'first_touch_reject'
#   direction   — 'short' or 'long'
#   level_col   — column on the daily levels frame to compare against
#   search_start, search_end — trigger search window (search_end is also time_stop)
ANCHORS = [
    {'name': '930_gap_short', 'archetype': 'entry_bar', 'direction': 'short',
     'search_start': dtime(9, 30), 'search_end': dtime(11, 0)},
    {'name': '930_gap_long',  'archetype': 'entry_bar', 'direction': 'long',
     'search_start': dtime(9, 30), 'search_end': dtime(11, 0)},
    {'name': 'or15_sweep_reject_short', 'archetype': 'first_touch_reject', 'direction': 'short',
     'level_col': 'or15_high', 'search_start': dtime(9, 45), 'search_end': dtime(11, 0)},
    {'name': 'or15_sweep_reject_long',  'archetype': 'first_touch_reject', 'direction': 'long',
     'level_col': 'or15_low',  'search_start': dtime(9, 45), 'search_end': dtime(11, 0)},
    {'name': 'pdh_first_touch_reject', 'archetype': 'first_touch_reject', 'direction': 'short',
     'level_col': 'prior_day_high', 'search_start': dtime(9, 30), 'search_end': dtime(11, 30)},
    {'name': 'pdl_first_touch_reject', 'archetype': 'first_touch_reject', 'direction': 'long',
     'level_col': 'prior_day_low',  'search_start': dtime(9, 30), 'search_end': dtime(11, 30)},
    {'name': 'vah_first_touch_reject', 'archetype': 'first_touch_reject', 'direction': 'short',
     'level_col': 'prior_day_vah', 'search_start': dtime(9, 30), 'search_end': dtime(11, 30)},
    {'name': 'val_first_touch_reject', 'archetype': 'first_touch_reject', 'direction': 'long',
     'level_col': 'prior_day_val', 'search_start': dtime(9, 30), 'search_end': dtime(11, 30)},
]


# ===================================================================
# Daily levels: prior day H/L/C, ATR_14d, OR15 H/L, prior-day VAH/VAL
# ===================================================================

def compute_daily_levels(candles: pd.DataFrame) -> pd.DataFrame:
    c = candles.copy()
    c['date'] = c['timestamp_ny'].dt.date
    c['_time'] = c['timestamp_ny'].dt.time
    rth = c[(c['_time'] >= RTH_OPEN) & (c['_time'] < RTH_CLOSE)]
    g = rth.groupby('date', sort=True)
    daily = pd.DataFrame({
        'rth_open': g['open'].first(),
        'rth_close': g['close'].last(),
        'rth_high': g['high'].max(),
        'rth_low': g['low'].min(),
    }).reset_index()
    daily['rth_range'] = daily['rth_high'] - daily['rth_low']
    daily['prior_day_close'] = daily['rth_close'].shift(1)
    daily['prior_day_high'] = daily['rth_high'].shift(1)
    daily['prior_day_low'] = daily['rth_low'].shift(1)
    daily['atr_14d'] = (
        daily['rth_range'].shift(1)
        .rolling(ATR_LOOKBACK, min_periods=ATR_LOOKBACK).mean()
    )

    # OR15 (9:30-9:44:30) high/low
    or_window = c[(c['_time'] >= RTH_OPEN) & (c['_time'] < OR15_END)]
    or_g = or_window.groupby('date', sort=True)
    or_df = pd.DataFrame({
        'or15_high': or_g['high'].max(),
        'or15_low':  or_g['low'].min(),
    }).reset_index()
    daily = daily.merge(or_df, on='date', how='left')
    return daily


def attach_volume_profile(daily: pd.DataFrame) -> pd.DataFrame:
    if not VP_PATH.exists():
        print(f"  WARN: {VP_PATH} not found — VAH/VAL anchors will be skipped")
        daily['prior_day_vah'] = np.nan
        daily['prior_day_val'] = np.nan
        return daily
    vp = pd.read_csv(VP_PATH)
    vp['date'] = pd.to_datetime(vp['date']).dt.date
    vp = vp[['date', 'vah', 'val']].sort_values('date').reset_index(drop=True)
    daily = daily.merge(vp, on='date', how='left')
    daily['prior_day_vah'] = daily['vah'].shift(1)
    daily['prior_day_val'] = daily['val'].shift(1)
    daily.drop(columns=['vah', 'val'], inplace=True)
    return daily


# ===================================================================
# Candle arrays for fast walking
# ===================================================================

def build_candle_arrays(candles: pd.DataFrame) -> dict:
    ts = candles['timestamp_ny']
    return {
        'ts':    ts.to_numpy(),
        'time':  ts.dt.time.to_numpy(),
        'date':  ts.dt.date.to_numpy(),
        'open':  candles['open'].to_numpy(dtype=float),
        'high':  candles['high'].to_numpy(dtype=float),
        'low':   candles['low'].to_numpy(dtype=float),
        'close': candles['close'].to_numpy(dtype=float),
        'n':     len(candles),
    }


def build_day_index(arr: dict) -> dict:
    """Return {date: (start_idx_inclusive, end_idx_exclusive)}."""
    dates = arr['date']
    n = arr['n']
    idx = {}
    if n == 0:
        return idx
    cur = dates[0]; start = 0
    for i in range(1, n):
        if dates[i] != cur:
            idx[cur] = (start, i)
            cur = dates[i]; start = i
    idx[cur] = (start, n)
    return idx


# ===================================================================
# Bracket logic
# ===================================================================

def atr_bracket(direction: str, entry_price: float, atr_14d: float) -> tuple:
    sl_dist = max(MIN_STOP_PTS, ATR_FRAC * atr_14d)
    tp_dist = TP_R * sl_dist
    if direction == 'short':
        return entry_price + sl_dist, entry_price - tp_dist, sl_dist
    return entry_price - sl_dist, entry_price + tp_dist, sl_dist


def structural_bracket(direction: str, entry_price: float,
                       trigger_high: float, trigger_low: float) -> tuple:
    if direction == 'short':
        sl = trigger_high + STRUCTURAL_BUFFER_PTS
        sl_dist = sl - entry_price
        if sl_dist < MIN_STOP_PTS:
            sl = entry_price + MIN_STOP_PTS
            sl_dist = MIN_STOP_PTS
        return sl, entry_price - TP_R * sl_dist, sl_dist
    sl = trigger_low - STRUCTURAL_BUFFER_PTS
    sl_dist = entry_price - sl
    if sl_dist < MIN_STOP_PTS:
        sl = entry_price - MIN_STOP_PTS
        sl_dist = MIN_STOP_PTS
    return sl, entry_price + TP_R * sl_dist, sl_dist


# ===================================================================
# Trigger detection
# ===================================================================

def find_entry_bar_signals(arr: dict, day_idx: dict, daily: pd.DataFrame, anchor: dict):
    """930_gap_short / 930_gap_long: 9:30 candle is the trigger.
    Entry at next bar's open."""
    direction = anchor['direction']
    times = arr['time']; opens = arr['open']
    highs = arr['high']; lows = arr['low']; closes = arr['close']
    by_date = {row['date']: row for _, row in daily.iterrows()}
    sigs = []
    for d, (s, e) in day_idx.items():
        if d not in by_date:
            continue
        levels = by_date[d]
        if any(pd.isna(levels[k]) for k in ('prior_day_close', 'atr_14d')):
            continue
        # find 9:30 bar
        j = s
        while j < e and times[j] < RTH_OPEN:
            j += 1
        if j >= e or times[j] != RTH_OPEN:
            continue
        bar_open = opens[j]; bar_high = highs[j]
        bar_low = lows[j]; bar_close = closes[j]
        gap = bar_open - levels['prior_day_close']
        if direction == 'short':
            if gap < MIN_GAP_PTS:
                continue
            if not (bar_close < bar_open):  # bearish 9:30 candle
                continue
        else:
            if gap > -MIN_GAP_PTS:
                continue
            if not (bar_close > bar_open):  # bullish 9:30 candle
                continue
        # entry at next bar (9:30:30) open
        if j + 1 >= e:
            continue
        entry_idx = j + 1
        sigs.append({
            'date': d,
            'direction': direction,
            'entry_idx': entry_idx,
            'entry_price': float(opens[entry_idx]),
            'trigger_high': float(bar_high),
            'trigger_low':  float(bar_low),
            'atr_14d': float(levels['atr_14d']),
        })
    return sigs


def find_first_touch_reject_signals(arr: dict, day_idx: dict, daily: pd.DataFrame, anchor: dict):
    """Walk window; first bar where high tags level (short) or low tags level (long)
    AND close is back through the level. Entry at next bar's open.

    For shorts (selling rejection of a level above): require the day's RTH open
    to be on the approach side (below the level). Mirror for longs."""
    direction = anchor['direction']
    level_col = anchor['level_col']
    win_start = anchor['search_start']
    win_end = anchor['search_end']
    times = arr['time']; opens = arr['open']
    highs = arr['high']; lows = arr['low']; closes = arr['close']
    by_date = {row['date']: row for _, row in daily.iterrows()}
    sigs = []
    for d, (s, e) in day_idx.items():
        if d not in by_date:
            continue
        levels = by_date[d]
        L = levels.get(level_col, np.nan)
        atr = levels.get('atr_14d', np.nan)
        if pd.isna(L) or pd.isna(atr):
            continue
        # day's RTH open on approach side
        j = s
        while j < e and times[j] < RTH_OPEN:
            j += 1
        if j >= e or times[j] != RTH_OPEN:
            continue
        rth_open_px = opens[j]
        if direction == 'short' and not (rth_open_px < L):
            continue
        if direction == 'long' and not (rth_open_px > L):
            continue

        # walk window
        k = j
        while k < e and times[k] < win_start:
            k += 1
        trigger_idx = -1
        while k < e and times[k] < win_end:
            hi, lo, cl = highs[k], lows[k], closes[k]
            if direction == 'short':
                if hi > L and cl < L:
                    trigger_idx = k
                    break
            else:
                if lo < L and cl > L:
                    trigger_idx = k
                    break
            k += 1
        if trigger_idx < 0:
            continue
        if trigger_idx + 1 >= e:
            continue
        # entry must still be inside the window (so trade has room to play)
        entry_idx = trigger_idx + 1
        if times[entry_idx] >= win_end:
            continue
        sigs.append({
            'date': d,
            'direction': direction,
            'entry_idx': entry_idx,
            'entry_price': float(opens[entry_idx]),
            'trigger_high': float(highs[trigger_idx]),
            'trigger_low':  float(lows[trigger_idx]),
            'atr_14d': float(atr),
            'level_value': float(L),
        })
    return sigs


# ===================================================================
# Walker
# ===================================================================

def walk_trade(sig: dict, arr: dict, sl: float, tp: float, sl_dist: float,
               time_stop: dtime, end_idx_excl: int) -> dict:
    direction = sig['direction']
    entry = sig['entry_price']
    times = arr['time']; highs = arr['high']; lows = arr['low']; closes = arr['close']
    j = sig['entry_idx']
    n = end_idx_excl
    max_fav = 0.0; max_adv = 0.0
    last_close = entry; last_idx = j
    while j < n and times[j] <= time_stop:
        hi, lo, cl = highs[j], lows[j], closes[j]
        last_close = cl; last_idx = j
        if direction == 'long':
            fav = hi - entry; adv = entry - lo
            sl_hit = lo <= sl; tp_hit = hi >= tp
        else:
            fav = entry - lo; adv = hi - entry
            sl_hit = hi >= sl; tp_hit = lo <= tp
        if fav > max_fav: max_fav = fav
        if adv > max_adv: max_adv = adv
        if sl_hit and tp_hit:
            # same-bar ambiguity → conservative: SL first
            return {'outcome': 'loss', 'exit_reason': 'sl_ambiguous',
                    'pnl_pts': -sl_dist, 'mfe': max_fav, 'mae': max_adv,
                    'exit_idx': j}
        if sl_hit:
            return {'outcome': 'loss', 'exit_reason': 'sl',
                    'pnl_pts': -sl_dist, 'mfe': max_fav, 'mae': max_adv,
                    'exit_idx': j}
        if tp_hit:
            tp_pnl = (tp - entry) if direction == 'long' else (entry - tp)
            return {'outcome': 'win', 'exit_reason': 'tp',
                    'pnl_pts': tp_pnl, 'mfe': max_fav, 'mae': max_adv,
                    'exit_idx': j}
        j += 1
    pnl = (last_close - entry) if direction == 'long' else (entry - last_close)
    return {'outcome': 'time_stop', 'exit_reason': 'time_stop',
            'pnl_pts': float(pnl), 'mfe': max_fav, 'mae': max_adv,
            'exit_idx': last_idx}


# ===================================================================
# Per-anchor pipeline
# ===================================================================

def run_anchor(anchor: dict, arr: dict, day_idx: dict, daily: pd.DataFrame,
               bracket_mode: str) -> pd.DataFrame:
    if anchor['archetype'] == 'entry_bar':
        sigs = find_entry_bar_signals(arr, day_idx, daily, anchor)
    else:
        sigs = find_first_touch_reject_signals(arr, day_idx, daily, anchor)

    rows = []
    for sig in sigs:
        d = sig['date']
        s, e = day_idx[d]
        if bracket_mode == 'atr':
            sl, tp, sl_dist = atr_bracket(sig['direction'], sig['entry_price'], sig['atr_14d'])
        else:
            sl, tp, sl_dist = structural_bracket(
                sig['direction'], sig['entry_price'],
                sig['trigger_high'], sig['trigger_low'],
            )
        res = walk_trade(sig, arr, sl, tp, sl_dist, anchor['search_end'], e)
        ts = arr['ts'][sig['entry_idx']]
        rows.append({
            'date': d,
            'anchor': anchor['name'],
            'direction': sig['direction'],
            'entry_time': pd.Timestamp(ts).isoformat(),
            'entry_price': sig['entry_price'],
            'sl_price': float(sl),
            'tp_price': float(tp),
            'sl_dist_pts': float(sl_dist),
            'atr_14d': sig['atr_14d'],
            'outcome': res['outcome'],
            'pnl_pts': res['pnl_pts'],
            'pnl_r': res['pnl_pts'] / sl_dist if sl_dist > 0 else 0.0,
            'mfe_r': res['mfe'] / sl_dist if sl_dist > 0 else 0.0,
            'mae_r': res['mae'] / sl_dist if sl_dist > 0 else 0.0,
            'exit_reason': res['exit_reason'],
        })
    return pd.DataFrame(rows)


# ===================================================================
# Summary
# ===================================================================

def summarize(trades: pd.DataFrame, anchor_name: str, months_in_data: float) -> dict:
    n = len(trades)
    if n == 0:
        return {'name': anchor_name, 'n': 0, 'wins': 0, 'losses': 0, 'time_stops': 0,
                'wr': None, 'pf': None, 'mean_r': None, 'median_r': None,
                'total_r': 0.0, 'total_pts': 0.0, 'freq_per_month': 0.0,
                'max_dd_r': 0.0}
    wins = int((trades['outcome'] == 'win').sum())
    losses = int((trades['outcome'] == 'loss').sum())
    ts = int((trades['outcome'] == 'time_stop').sum())
    decided = wins + losses
    wr = (wins / decided * 100) if decided > 0 else None
    pnl = pd.to_numeric(trades['pnl_pts'], errors='coerce').fillna(0)
    gp = float(pnl[pnl > 0].sum()); gl = float(abs(pnl[pnl < 0].sum()))
    pf = (gp / gl) if gl > 0 else (float('inf') if gp > 0 else None)
    pnl_r = pd.to_numeric(trades['pnl_r'], errors='coerce').fillna(0)
    sorted_trades = trades.sort_values('entry_time')
    cum_r = pd.to_numeric(sorted_trades['pnl_r'], errors='coerce').fillna(0).cumsum()
    if len(cum_r):
        peak = cum_r.cummax()
        dd = (cum_r - peak)
        max_dd_r = float(dd.min())
    else:
        max_dd_r = 0.0
    return {
        'name': anchor_name, 'n': n, 'wins': wins, 'losses': losses, 'time_stops': ts,
        'wr': wr, 'pf': pf,
        'mean_r': float(pnl_r.mean()), 'median_r': float(pnl_r.median()),
        'total_r': float(pnl_r.sum()), 'total_pts': float(pnl.sum()),
        'freq_per_month': (n / months_in_data) if months_in_data > 0 else 0.0,
        'max_dd_r': max_dd_r,
    }


def fmt(val, spec):
    if val is None or (isinstance(val, float) and (np.isnan(val) or np.isinf(val))):
        if isinstance(val, float) and np.isinf(val):
            return 'inf'
        return '—'
    return format(val, spec)


def print_summary_table(summaries: list, bracket_mode: str):
    print("\n" + "=" * 110)
    print(f"  ANCHOR REJECTION SUMMARY  (bracket={bracket_mode})  "
          f"control = 930_gap_short")
    print("=" * 110)
    hdr = (f"  {'anchor':<28} {'n':>4} {'W':>4} {'L':>4} {'TS':>4} "
           f"{'WR':>7} {'PF':>6} {'meanR':>7} {'totR':>8} {'maxDD':>8} {'/mo':>6}")
    print(hdr)
    print("  " + "-" * 108)
    # control first
    ordered = sorted(summaries, key=lambda x: 0 if x['name'] == '930_gap_short' else 1)
    for s in ordered:
        marker = '*' if s['name'] == '930_gap_short' else ' '
        line = (f" {marker}{s['name']:<28} {s['n']:>4} {s['wins']:>4} {s['losses']:>4} "
                f"{s['time_stops']:>4} "
                f"{fmt(s['wr'], '6.1f') + '%' if s['wr'] is not None else '—':>7} "
                f"{fmt(s['pf'], '5.2f'):>6} "
                f"{fmt(s['mean_r'], '6.2f'):>7} "
                f"{fmt(s['total_r'], '7.1f'):>8} "
                f"{fmt(s['max_dd_r'], '7.1f'):>8} "
                f"{fmt(s['freq_per_month'], '5.1f'):>6}")
        print(line)
    print("=" * 110)


# ===================================================================
# Main
# ===================================================================

def parse_args():
    p = argparse.ArgumentParser(description='Anchor rejection comparison study')
    p.add_argument('--bracket', choices=['atr', 'structural'], default='atr',
                   help='atr (default): max(15, 0.30*ATR14) stop; '
                        'structural: trigger-bar wick + 2pt buffer')
    return p.parse_args()


def detect_lfs_pointer(path: Path):
    """If a data file is still an LFS pointer, fail with a helpful message."""
    if not path.exists():
        raise FileNotFoundError(f"Missing data file: {path}")
    try:
        head = path.open('rb').read(200)
    except Exception:
        return
    if head.startswith(b'version https://git-lfs'):
        raise SystemExit(
            f"\n  ERROR: {path} is a Git-LFS pointer, not real data.\n"
            f"  Run `git lfs pull` from the repo root and re-run.\n"
        )


def main():
    args = parse_args()
    print("=" * 72)
    print("Anchor Rejection — multi-anchor first-touch / rejection comparison")
    print(f"Bracket mode: {args.bracket}")
    print("=" * 72)

    detect_lfs_pointer(DATA_30S)
    if VP_PATH.exists():
        detect_lfs_pointer(VP_PATH)

    candles = load_candles(DATA_30S)
    print(f"  Data range: {candles['timestamp_ny'].min()} -> {candles['timestamp_ny'].max()}")

    daily = compute_daily_levels(candles)
    daily = attach_volume_profile(daily)
    print(f"  {len(daily)} trading days; "
          f"VAH/VAL coverage: {daily['prior_day_vah'].notna().sum()} days")

    arr = build_candle_arrays(candles)
    day_idx = build_day_index(arr)

    # Approximate months for freq normalization
    span_days = (candles['timestamp_ny'].max() - candles['timestamp_ny'].min()).days
    months_in_data = max(span_days / 30.4375, 1.0)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    summaries = []
    for anchor in ANCHORS:
        print(f"\n  -> {anchor['name']:<28} ({anchor['archetype']}, {anchor['direction']})")
        trades = run_anchor(anchor, arr, day_idx, daily, args.bracket)
        suffix = '' if args.bracket == 'atr' else f"_{args.bracket}"
        out = RESULTS_DIR / f"trades_{anchor['name']}{suffix}.csv"
        trades.to_csv(out, index=False)
        s = summarize(trades, anchor['name'], months_in_data)
        summaries.append(s)
        wr_s = fmt(s['wr'], '5.1f')
        pf_s = fmt(s['pf'], '4.2f')
        print(f"     n={s['n']:>3}  WR={wr_s}%  PF={pf_s}  "
              f"meanR={fmt(s['mean_r'], '5.2f')}  totalR={fmt(s['total_r'], '6.1f')}  "
              f"-> {out.relative_to(ROOT)}")

    print_summary_table(summaries, args.bracket)
    summary_df = pd.DataFrame(summaries)
    suffix = '' if args.bracket == 'atr' else f"_{args.bracket}"
    summary_path = RESULTS_DIR / f"summary{suffix}.csv"
    summary_df.to_csv(summary_path, index=False)
    print(f"\n  Wrote {summary_path.relative_to(ROOT)}")
    print("Done.")


if __name__ == '__main__':
    main()
