#!/usr/bin/env python3
"""
Study: Small-Gap Fade — Standalone 9:30 Entry Model (v2, extended)

Standalone 9:30 entry model that fades NQ gaps inside prior-day RTH range
toward prior-day close (PDC). Phase 1 (time_stop=10:15, static exits) did not
meet Notion's WR>=65 / PF>=2.0 thresholds; the "small" bucket time-stopped
68% of trades. v2 adds five extensions:

  1. Time-stop sweep:         {10:15, 10:45, 11:00, 11:30}
  2. Scale-out exit:          2 units: TP1 at 50% gap, runner to PDC with BE stop
  3. 9:30-candle alignment:   only take trades when 9:30 bar closes in fade dir
  4. Red-folder news exclude: drop trades on red-folder days
  5. FVGC co-tag:             require a FVGC signal in fade direction before entry window

Run from repo root:
  python studies/small_gap_fade/run.py
"""

import sys
from pathlib import Path
from datetime import time as dtime
from itertools import product
from math import comb

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import numpy as np

from fvgc.data import load_candles
from fvgc.model import generate_signals as fvgc_generate

STUDY_DIR = Path(__file__).resolve().parent
RESULTS_DIR = STUDY_DIR / 'results'

TIMEFRAMES = {
    '15s': ROOT / 'data' / 'consolidated' / 'nq-front-month.ohlcv-15s.csv',
    '30s': ROOT / 'data' / 'consolidated' / 'nq-front-month.ohlcv-30s.csv',
    '1m':  ROOT / 'data' / 'consolidated' / 'nq-front-month.ohlcv-1m.csv',
}

TRADING_DAYS_PATH = ROOT / 'data' / 'trading_days' / 'trading_days.csv'

RTH_OPEN = dtime(9, 30)
RTH_CLOSE = dtime(16, 0)
FVGC_CONFIRM_WINDOW_END = dtime(9, 45)  # FVGC must fire by this time to count as pre-entry confirmation

MIN_GAP_PTS = 2.0
ATR_LOOKBACK = 14

TIME_STOPS = [dtime(10, 15), dtime(10, 45), dtime(11, 0), dtime(11, 30)]
TARGET_FRACS = [0.5, 0.75, 1.0]
STOP_MULTS = [1.0, 1.2, 1.5]

GAP_BUCKETS = [
    ('tiny',       0.0, 0.3),
    ('small',      0.3, 0.6),
    ('tiny_small', 0.0, 0.6),
]
DIRECTIONS = ['long', 'short', 'both']
DOW_GROUPS = {'Tuesday': [1], 'Wed+Thu': [2, 3], 'any': [0, 1, 2, 3, 4]}
VIXY_OPTIONS = ['any', 'low']
CANDLE930_OPTIONS = ['any', 'aligned']
NEWS_OPTIONS = ['any', 'no_news']
FVGC_OPTIONS = ['any', 'aligned']

MIN_CELL_N = 30
FDR_Q = 0.10


# ===================================================================
# Daily levels (prior_day_*, ATR_14d)
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
    daily['prior_day_range'] = daily['rth_range'].shift(1)
    daily['atr_14d'] = (
        daily['prior_day_range'].rolling(ATR_LOOKBACK, min_periods=ATR_LOOKBACK).mean()
    )
    return daily


def find_930_entries(candles: pd.DataFrame) -> pd.DataFrame:
    c = candles.copy()
    c['date'] = c['timestamp_ny'].dt.date
    c['_time'] = c['timestamp_ny'].dt.time
    rth = c[c['_time'] >= RTH_OPEN]
    first_rth = rth.groupby('date', as_index=False).head(1)
    rows = []
    for idx, r in first_rth.iterrows():
        if r['_time'] != RTH_OPEN:
            continue
        rows.append({
            'date': r['date'],
            'entry_idx': idx,
            'entry_time': r['timestamp_ny'],
            'entry_open': r['open'],
        })
    return pd.DataFrame(rows)


# ===================================================================
# Signal construction
# ===================================================================

def build_signals(
    daily: pd.DataFrame,
    entries: pd.DataFrame,
    target_frac: float,
    stop_mult: float,
) -> list:
    merged = entries.merge(daily, on='date', how='left')
    signals = []
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
        signals.append({
            'timestamp': r['entry_time'],
            'entry_idx': int(r['entry_idx']),
            'direction': direction,
            'entry_price': float(open_px),
            'sl': float(sl),
            'tp': float(tp),
            'sl_dist': float(stop_mult * gap_abs),
            'target_frac': target_frac,
            'stop_mult': stop_mult,
            'date': r['date'],
            'gap_pts': float(gap),
            'gap_abs': float(gap_abs),
            'gap_atr_ratio': float(gap_abs / atr),
            'atr_14d': float(atr),
            'prior_day_close': float(pdc),
            'prior_day_high': float(pdh),
            'prior_day_low': float(pdl),
        })
    return signals


# ===================================================================
# Trace walker (single pass, records everything we need)
# ===================================================================

def build_candle_arrays(candles: pd.DataFrame) -> dict:
    """Pack columns into numpy arrays keyed by position for fast walking."""
    ts = candles['timestamp_ny']
    return {
        'time': ts.dt.time.to_numpy(),
        'date': ts.dt.date.to_numpy(),
        'high': candles['high'].to_numpy(dtype=float),
        'low':  candles['low'].to_numpy(dtype=float),
        'close': candles['close'].to_numpy(dtype=float),
        'n': len(candles),
    }


def walk_static(sig: dict, arr: dict, end_time: dtime) -> dict:
    """Walk forward from entry_idx through RTH; record first-touch of TP and SL,
    MFE/MAE, and a time→close map for all bars in [9:30, end_time]."""
    entry_idx = sig['entry_idx']
    entry_price = sig['entry_price']
    direction = sig['direction']
    sl, tp = sig['sl'], sig['tp']
    entry_date = arr['date'][entry_idx]

    tp_bar, sl_bar = -1, -1
    tp_time, sl_time = None, None
    max_fav, max_adv = 0.0, 0.0
    closes_by_time = {}

    j = entry_idx + 1
    n = arr['n']
    times = arr['time']; dates = arr['date']
    highs = arr['high']; lows = arr['low']; closes = arr['close']
    while j < n and dates[j] == entry_date:
        t = times[j]
        if t > end_time:
            break
        closes_by_time[t] = closes[j]
        hi, lo = highs[j], lows[j]

        if direction == 'long':
            fav = hi - entry_price
            adv = entry_price - lo
            if sl_bar < 0 and lo <= sl:
                sl_bar = j; sl_time = t
            if tp_bar < 0 and hi >= tp:
                tp_bar = j; tp_time = t
        else:
            fav = entry_price - lo
            adv = hi - entry_price
            if sl_bar < 0 and hi >= sl:
                sl_bar = j; sl_time = t
            if tp_bar < 0 and lo <= tp:
                tp_bar = j; tp_time = t

        if fav > max_fav: max_fav = fav
        if adv > max_adv: max_adv = adv
        j += 1

    return {
        'tp_bar': tp_bar, 'tp_time': tp_time,
        'sl_bar': sl_bar, 'sl_time': sl_time,
        'max_fav': max_fav, 'max_adv': max_adv,
        'closes_by_time': closes_by_time,  # ordered by bar time
    }


def derive_static(trace: dict, sig: dict, time_stop: dtime) -> dict:
    """Given a trace and a time_stop, derive the static-exit outcome + pnl."""
    tp_bar = trace['tp_bar']; sl_bar = trace['sl_bar']
    tp_ok = tp_bar >= 0 and trace['tp_time'] <= time_stop
    sl_ok = sl_bar >= 0 and trace['sl_time'] <= time_stop
    direction = sig['direction']
    entry = sig['entry_price']; tp = sig['tp']; sl = sig['sl']; sl_dist = sig['sl_dist']

    def tp_pnl():
        return (tp - entry) if direction == 'long' else (entry - tp)

    if tp_ok and sl_ok:
        if tp_bar < sl_bar:
            return {'outcome': 'win', 'exit_reason': 'tp', 'pnl': tp_pnl()}
        if sl_bar < tp_bar:
            return {'outcome': 'loss', 'exit_reason': 'sl', 'pnl': -sl_dist}
        # same bar: conservative = loss
        return {'outcome': 'ambiguous', 'exit_reason': 'ambiguous', 'pnl': -sl_dist}
    if tp_ok:
        return {'outcome': 'win', 'exit_reason': 'tp', 'pnl': tp_pnl()}
    if sl_ok:
        return {'outcome': 'loss', 'exit_reason': 'sl', 'pnl': -sl_dist}

    # Time-stop: close at last bar on or before time_stop
    closes = trace['closes_by_time']
    if not closes:
        return {'outcome': 'skip', 'exit_reason': 'no_bars', 'pnl': 0.0}
    # pick latest bar time <= time_stop
    eligible = [t for t in closes if t <= time_stop]
    if not eligible:
        return {'outcome': 'skip', 'exit_reason': 'no_bars', 'pnl': 0.0}
    last_t = max(eligible)
    cp = closes[last_t]
    pnl = (cp - entry) if direction == 'long' else (entry - cp)
    return {'outcome': 'time_stop', 'exit_reason': 'time_stop', 'pnl': float(pnl)}


def walk_scaleout(sig: dict, arr: dict, time_stop: dtime) -> dict:
    """Walk a scale-out trade: 2 units at entry.
      Leg 1: closes at TP1 = 50% of gap (toward PDC).
      After Leg 1: stop on remaining unit moves to entry (break-even).
      Leg 2: closes at TP2 = PDC (full gap).
      If time_stop reached first, close remaining units at time_stop's close.

    `pnl` is *per initial unit* (total divided by 2), so scale-out and static
    pnls are comparable on a single-unit-risk basis.
    """
    entry_idx = sig['entry_idx']
    direction = sig['direction']
    entry = sig['entry_price']
    gap_abs = sig['gap_abs']
    stop_mult = sig['stop_mult']
    entry_date = arr['date'][entry_idx]

    if direction == 'long':
        tp1 = entry + 0.5 * gap_abs
        tp2 = entry + gap_abs
        sl = entry - stop_mult * gap_abs
    else:
        tp1 = entry - 0.5 * gap_abs
        tp2 = entry - gap_abs
        sl = entry + stop_mult * gap_abs

    n = arr['n']
    times = arr['time']; dates = arr['date']
    highs = arr['high']; lows = arr['low']; closes = arr['close']

    leg1_done = False
    leg2_reason = None
    last_close = None
    max_fav = 0.0; max_adv = 0.0

    j = entry_idx + 1
    while j < n and dates[j] == entry_date:
        t = times[j]
        if t > time_stop:
            break
        last_close = closes[j]
        hi, lo = highs[j], lows[j]

        if direction == 'long':
            fav = hi - entry; adv = entry - lo
        else:
            fav = entry - lo; adv = hi - entry
        if fav > max_fav: max_fav = fav
        if adv > max_adv: max_adv = adv

        if not leg1_done:
            if direction == 'long':
                sl_hit = lo <= sl; tp1_hit = hi >= tp1
            else:
                sl_hit = hi >= sl; tp1_hit = lo <= tp1
            if sl_hit and not tp1_hit:
                # Full loss before TP1
                return {
                    'outcome': 'loss', 'exit_reason': 'sl_pre_tp1',
                    'pnl': -stop_mult * gap_abs,
                    'leg1_hit': False, 'leg2_reason': 'sl',
                    'max_fav': max_fav, 'max_adv': max_adv,
                }
            if tp1_hit and not sl_hit:
                leg1_done = True  # first unit closed at tp1; runner stop = entry (BE)
            if tp1_hit and sl_hit:
                # same bar; conservative = SL first, full loss
                return {
                    'outcome': 'loss', 'exit_reason': 'sl_ambiguous_pre_tp1',
                    'pnl': -stop_mult * gap_abs,
                    'leg1_hit': False, 'leg2_reason': 'sl',
                    'max_fav': max_fav, 'max_adv': max_adv,
                }
        else:
            # Leg 2 phase: stop at entry (BE), target at TP2
            if direction == 'long':
                be_hit = lo <= entry; tp2_hit = hi >= tp2
            else:
                be_hit = hi >= entry; tp2_hit = lo <= tp2
            if tp2_hit and not be_hit:
                leg2_reason = 'tp2'
                total_pnl = 0.5 * gap_abs + gap_abs  # leg1=+0.5*gap, leg2=+gap
                return {
                    'outcome': 'win', 'exit_reason': 'tp1+tp2',
                    'pnl': total_pnl / 2.0,
                    'leg1_hit': True, 'leg2_reason': 'tp2',
                    'max_fav': max_fav, 'max_adv': max_adv,
                }
            if be_hit and not tp2_hit:
                leg2_reason = 'be'
                total_pnl = 0.5 * gap_abs + 0.0
                return {
                    'outcome': 'win', 'exit_reason': 'tp1+be',
                    'pnl': total_pnl / 2.0,
                    'leg1_hit': True, 'leg2_reason': 'be',
                    'max_fav': max_fav, 'max_adv': max_adv,
                }
            if be_hit and tp2_hit:
                # conservative: BE first
                leg2_reason = 'be_ambiguous'
                total_pnl = 0.5 * gap_abs
                return {
                    'outcome': 'win', 'exit_reason': 'tp1+be_ambiguous',
                    'pnl': total_pnl / 2.0,
                    'leg1_hit': True, 'leg2_reason': 'be',
                    'max_fav': max_fav, 'max_adv': max_adv,
                }
        j += 1

    # Fell off end of window
    if not leg1_done:
        if last_close is None:
            return {'outcome': 'skip', 'exit_reason': 'no_bars', 'pnl': 0.0,
                    'leg1_hit': False, 'leg2_reason': 'no_bars',
                    'max_fav': max_fav, 'max_adv': max_adv}
        pnl = (last_close - entry) if direction == 'long' else (entry - last_close)
        outcome = 'win' if pnl > 0 else ('loss' if pnl < 0 else 'flat')
        return {
            'outcome': outcome, 'exit_reason': 'time_stop_no_tp1',
            'pnl': float(pnl),
            'leg1_hit': False, 'leg2_reason': 'time_stop',
            'max_fav': max_fav, 'max_adv': max_adv,
        }
    # TP1 done but TP2/BE not hit by time_stop
    leg2_pnl = 0.0 if last_close is None else (
        (last_close - entry) if direction == 'long' else (entry - last_close)
    )
    total_pnl = 0.5 * gap_abs + leg2_pnl
    per_unit = total_pnl / 2.0
    outcome = 'win' if per_unit > 0 else ('loss' if per_unit < 0 else 'flat')
    return {
        'outcome': outcome, 'exit_reason': 'tp1+time_stop',
        'pnl': float(per_unit),
        'leg1_hit': True, 'leg2_reason': 'time_stop',
        'max_fav': max_fav, 'max_adv': max_adv,
    }


# ===================================================================
# FVGC co-tag
# ===================================================================

def build_fvgc_map(candles: pd.DataFrame) -> dict:
    """Return {date: set_of_directions} for FVGC signals that fired in the
    pre-entry confirmation window (9:30:00 <= ts < FVGC_CONFIRM_WINDOW_END).

    The FVGC model only forms FVGs and fires signals within [9:30, 10:15]
    (self-contained, no warmup), so we restrict the candle set to that RTH
    window for a big speedup on 15s data.
    """
    print("  Running FVGC signal detection (9:30-10:15 only) ...")
    t = candles['timestamp_ny'].dt.time
    window = candles[(t >= RTH_OPEN) & (t <= dtime(10, 15))].reset_index(drop=True)
    print(f"    {len(window):,} bars in FVGC window")
    sigs, _ = fvgc_generate(window)
    m: dict = {}
    for s in sigs:
        ts = s['timestamp']
        if ts.time() >= FVGC_CONFIRM_WINDOW_END:
            continue
        d = ts.date()
        m.setdefault(d, set()).add(s['direction'])
    print(f"  FVGC confirmation signals on {len(m)} days")
    return m


# ===================================================================
# Enrichment
# ===================================================================

def enrich_trades(trades: pd.DataFrame, td: pd.DataFrame, fvgc_map: dict) -> pd.DataFrame:
    """Join per-day context + derive alignment flags."""
    td_small = td[['date', 'day_of_week', 'vixy_regime',
                   'has_red_folder_news', 'candle_930_direction']].copy()
    td_small['date'] = pd.to_datetime(td_small['date']).dt.date
    out = trades.merge(td_small, on='date', how='left')

    # candle_930_aligned: 9:30 candle agrees with fade direction
    def _aligned(row):
        cd = row.get('candle_930_direction')
        if pd.isna(cd) or cd == 'doji':
            return False
        if row['direction'] == 'long' and cd == 'bullish':
            return True
        if row['direction'] == 'short' and cd == 'bearish':
            return True
        return False
    out['candle_930_aligned'] = out.apply(_aligned, axis=1)

    # fvgc_aligned: same-day FVGC signal in fade direction within 9:30-9:45 window
    def _fvgc(row):
        dirs = fvgc_map.get(row['date'], set())
        return row['direction'] in dirs
    out['fvgc_aligned'] = out.apply(_fvgc, axis=1)
    return out


# ===================================================================
# Stats + BH-FDR
# ===================================================================

def cell_stats(sub: pd.DataFrame) -> dict:
    n = len(sub)
    if n == 0:
        return {'n': 0, 'wins': 0, 'losses': 0, 'flats': 0, 'time_stops': 0,
                'wr': None, 'pf': None, 'pnl': 0.0, 'mean_pnl': 0.0,
                'mean_mfe_r': None}
    wins = int((sub['outcome'] == 'win').sum())
    losses = int((sub['outcome'] == 'loss').sum())
    flats = int((sub['outcome'] == 'flat').sum())
    ts = int(sub['exit_reason'].astype(str).str.contains('time_stop').sum())
    pnl = pd.to_numeric(sub['pnl'], errors='coerce').fillna(0)
    total = float(pnl.sum()); mean_pnl = float(pnl.mean())
    gp = float(pnl[pnl > 0].sum()); gl = float(abs(pnl[pnl < 0].sum()))
    pf = (gp / gl) if gl > 0 else (float('inf') if gp > 0 else None)
    decided = wins + losses
    wr = (wins / decided * 100) if decided > 0 else None
    mfe_r = None
    if 'sl_dist' in sub and sub['sl_dist'].gt(0).any():
        mfe = pd.to_numeric(sub.get('max_fav', pd.Series(dtype=float)), errors='coerce')
        sld = pd.to_numeric(sub['sl_dist'], errors='coerce')
        r = (mfe / sld).replace([np.inf, -np.inf], np.nan)
        mfe_r = float(r.mean()) if r.notna().any() else None
    return {'n': n, 'wins': wins, 'losses': losses, 'flats': flats, 'time_stops': ts,
            'wr': wr, 'pf': pf, 'pnl': total, 'mean_pnl': mean_pnl,
            'mean_mfe_r': mfe_r}


def binomial_two_sided_p(k: int, n: int, p0: float = 0.5) -> float:
    if n <= 0:
        return 1.0
    obs = k / n
    if obs >= p0:
        tail = sum(comb(n, i) * (p0 ** i) * ((1 - p0) ** (n - i))
                   for i in range(k, n + 1))
    else:
        tail = sum(comb(n, i) * (p0 ** i) * ((1 - p0) ** (n - i))
                   for i in range(0, k + 1))
    return min(1.0, 2 * tail)


def bh_fdr(pvals: list, q: float) -> list:
    n = len(pvals)
    if n == 0:
        return []
    order = sorted(range(n), key=lambda i: (pvals[i] if pvals[i] is not None else 1.0))
    q_vals = [1.0] * n
    running_min = 1.0
    for rank in range(n, 0, -1):
        idx = order[rank - 1]
        p = pvals[idx]
        adj = 1.0 if p is None else min(1.0, p * n / rank)
        running_min = min(running_min, adj)
        q_vals[idx] = running_min
    return [(qv, qv <= q) for qv in q_vals]


# ===================================================================
# Filter masks
# ===================================================================

def _mask_bucket(df, bucket):
    _, lo, hi = bucket
    return (df['gap_atr_ratio'] >= lo) & (df['gap_atr_ratio'] < hi)


def build_grid(trades: pd.DataFrame, exit_scheme: str) -> pd.DataFrame:
    """Compute one row per cell filter combination.  Supports 'static' or 'scaleout'."""
    # Pre-convert dtypes for speed
    t = trades.copy()
    rows = []
    if exit_scheme == 'static':
        target_opts = TARGET_FRACS
    else:
        target_opts = [None]  # scale-out does not vary target_frac

    for bucket, direction, dow_name, vixy, candle, news, fvgc, target, stop, ts_val in product(
        GAP_BUCKETS, DIRECTIONS, DOW_GROUPS.keys(), VIXY_OPTIONS, CANDLE930_OPTIONS,
        NEWS_OPTIONS, FVGC_OPTIONS, target_opts, STOP_MULTS, TIME_STOPS,
    ):
        m = _mask_bucket(t, bucket)
        if direction != 'both':
            m &= (t['direction'] == direction)
        m &= t['day_of_week'].isin(DOW_GROUPS[dow_name])
        if vixy != 'any':
            m &= (t['vixy_regime'] == vixy)
        if candle == 'aligned':
            m &= (t['candle_930_aligned'] == True)
        if news == 'no_news':
            m &= (t['has_red_folder_news'] == False)
        if fvgc == 'aligned':
            m &= (t['fvgc_aligned'] == True)
        if target is not None:
            m &= (t['target_frac'] == target)
        m &= (t['stop_mult'] == stop)
        m &= (t['time_stop'] == str(ts_val))
        sub = t[m]
        if len(sub) < MIN_CELL_N:
            continue
        st = cell_stats(sub)
        decided = st['wins'] + st['losses']
        p_val = binomial_two_sided_p(st['wins'], decided) if decided > 0 else None
        rows.append({
            'exit_scheme': exit_scheme,
            'gap_bucket': bucket[0],
            'direction': direction,
            'dow': dow_name, 'vixy': vixy,
            'candle_930': candle, 'news': news, 'fvgc': fvgc,
            'target_frac': target if target is not None else '',
            'stop_mult': stop,
            'time_stop': str(ts_val),
            'n': st['n'], 'wins': st['wins'], 'losses': st['losses'],
            'flats': st['flats'], 'time_stops': st['time_stops'],
            'wr': st['wr'], 'pf': st['pf'], 'pnl': st['pnl'],
            'mean_pnl': st['mean_pnl'], 'mean_mfe_r': st['mean_mfe_r'],
            'p_value': p_val,
        })
    df = pd.DataFrame(rows)
    if df.empty:
        df['q_value'] = []
        df['significant'] = []
        return df
    pairs = bh_fdr(df['p_value'].tolist(), FDR_Q)
    df['q_value'] = [q for q, _ in pairs]
    df['significant'] = [s for _, s in pairs]
    return df


# ===================================================================
# Per-timeframe pipeline
# ===================================================================

def run_timeframe(tf_label: str, data_path: Path, td: pd.DataFrame) -> dict:
    print(f"\n{'#' * 72}")
    print(f"  TIMEFRAME: {tf_label}")
    print(f"{'#' * 72}")

    candles = load_candles(data_path)
    print(f"  Data range: {candles['timestamp_ny'].min()} -> {candles['timestamp_ny'].max()}")
    print(f"  Bars: {len(candles):,}")

    daily = compute_daily_levels(candles)
    entries = find_930_entries(candles)
    print(f"  {len(daily)} trading days, {len(entries)} with 9:30 bar")

    fvgc_map = build_fvgc_map(candles)
    arr = build_candle_arrays(candles)

    end_time = max(TIME_STOPS)

    # ---- Static trades: (target, stop) × time_stop ----
    print("  Walking static trades ...")
    static_rows = []
    for target_frac in TARGET_FRACS:
        for stop_mult in STOP_MULTS:
            sigs = build_signals(daily, entries, target_frac, stop_mult)
            for sig in sigs:
                trace = walk_static(sig, arr, end_time)
                for ts_val in TIME_STOPS:
                    res = derive_static(trace, sig, ts_val)
                    row = dict(sig)
                    row.update(res)
                    row['time_stop'] = str(ts_val)
                    row['max_fav'] = trace['max_fav']
                    row['max_adv'] = trace['max_adv']
                    static_rows.append(row)
    trades_static = pd.DataFrame(static_rows)
    print(f"  Static trade rows: {len(trades_static):,} "
          f"({len(trades_static)//len(TIME_STOPS)} unique entries * "
          f"{len(TIME_STOPS)} time_stops)")

    # ---- Scale-out trades: only varies (stop, time_stop) ----
    print("  Walking scale-out trades ...")
    scale_rows = []
    for stop_mult in STOP_MULTS:
        # Use target_frac=1.0 as a placeholder to build signals (target_frac doesn't affect scale-out)
        sigs = build_signals(daily, entries, 1.0, stop_mult)
        for sig in sigs:
            for ts_val in TIME_STOPS:
                res = walk_scaleout(sig, arr, ts_val)
                row = dict(sig)
                row.update(res)
                row['time_stop'] = str(ts_val)
                # scale-out doesn't parameterize target_frac; store '' for grid consistency
                row['target_frac'] = None
                scale_rows.append(row)
    trades_scale = pd.DataFrame(scale_rows)
    print(f"  Scale-out trade rows: {len(trades_scale):,}")

    # ---- Enrich ----
    trades_static = enrich_trades(trades_static, td, fvgc_map)
    trades_scale = enrich_trades(trades_scale, td, fvgc_map)

    # ---- Baseline quick looks (time_stop sensitivity at core primary cohort) ----
    print(f"\n  {'=' * 68}")
    print("  BASELINE: gap_atr<0.6 (tiny_small), target=1.0, stop=1.2, both dirs")
    print(f"  {'=' * 68}")
    print(f"  {'Exit':<10}  {'time_stop':<10}  {'N':>4}  {'WR':>6}  {'PF':>6}  {'PnL':>8}  {'MFE':>6}")
    for ts_val in TIME_STOPS:
        sub = trades_static[
            (trades_static['gap_atr_ratio'] < 0.6)
            & (trades_static['target_frac'] == 1.0)
            & (trades_static['stop_mult'] == 1.2)
            & (trades_static['time_stop'] == str(ts_val))
        ]
        st = cell_stats(sub)
        _print_row('static', str(ts_val), st)
    for ts_val in TIME_STOPS:
        sub = trades_scale[
            (trades_scale['gap_atr_ratio'] < 0.6)
            & (trades_scale['stop_mult'] == 1.2)
            & (trades_scale['time_stop'] == str(ts_val))
        ]
        st = cell_stats(sub)
        _print_row('scaleout', str(ts_val), st)

    # ---- Grid ----
    print("\n  Building static grid ...")
    grid_s = build_grid(trades_static, 'static')
    print(f"  Static grid: {len(grid_s)} cells  (significant at q={FDR_Q}: "
          f"{int(grid_s['significant'].sum()) if len(grid_s) else 0})")

    print("  Building scale-out grid ...")
    grid_o = build_grid(trades_scale, 'scaleout')
    print(f"  Scale-out grid: {len(grid_o)} cells  (significant at q={FDR_Q}: "
          f"{int(grid_o['significant'].sum()) if len(grid_o) else 0})")

    grid_all = pd.concat([grid_s, grid_o], ignore_index=True)

    # Show top 20 cells passing both business thresholds (WR>=65 AND PF>=2.0)
    winners = grid_all[
        (grid_all['significant'])
        & (grid_all['wr'] >= 65)
        & (grid_all['pf'].apply(lambda x: x is not None and x != float('inf') and x >= 2.0))
    ].copy()
    winners = winners.sort_values(['pf', 'wr'], ascending=[False, False])
    print(f"\n  Cells passing WR>=65% AND PF>=2.0 AND q<={FDR_Q}: {len(winners)}")
    if not winners.empty:
        top = winners.head(25)
        print("   " + "-" * 140)
        print(f"   {'scheme':<8} {'bucket':<11} {'dir':<6} {'dow':<8} {'vixy':<5} "
              f"{'c930':<8} {'news':<8} {'fvgc':<8} {'tgt':<5} {'stp':<4} {'ts':<9} "
              f"{'n':>4} {'wr':>6} {'pf':>6} {'pnl':>7} {'q':>7}")
        print("   " + "-" * 140)
        for _, r in top.iterrows():
            _print_grid_row(r)

    # ---- Also show top 15 by PF across all significant cells ----
    sig = grid_all[grid_all['significant']].copy()
    sig = sig[sig['pf'].apply(lambda x: x is not None and x != float('inf'))]
    sig = sig.sort_values('pf', ascending=False)
    print(f"\n  Top 15 significant cells overall (by PF):")
    print("   " + "-" * 140)
    print(f"   {'scheme':<8} {'bucket':<11} {'dir':<6} {'dow':<8} {'vixy':<5} "
          f"{'c930':<8} {'news':<8} {'fvgc':<8} {'tgt':<5} {'stp':<4} {'ts':<9} "
          f"{'n':>4} {'wr':>6} {'pf':>6} {'pnl':>7} {'q':>7}")
    print("   " + "-" * 140)
    for _, r in sig.head(15).iterrows():
        _print_grid_row(r)

    # ---- Write artifacts ----
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    grid_all.to_csv(RESULTS_DIR / f'grid_v2_{tf_label}.csv', index=False)
    # Primary-cohort trade list (time_stop=10:15, target=1.0, stop=1.2) for parity with v1
    primary = trades_static[
        (trades_static['gap_atr_ratio'] < 0.6)
        & (trades_static['target_frac'] == 1.0)
        & (trades_static['stop_mult'] == 1.2)
        & (trades_static['time_stop'] == str(TIME_STOPS[0]))
    ].copy()
    primary.to_csv(RESULTS_DIR / f'trades_primary_{tf_label}.csv', index=False)
    print(f"\n  Wrote {RESULTS_DIR / f'grid_v2_{tf_label}.csv'} ({len(grid_all)} rows)")
    print(f"  Wrote {RESULTS_DIR / f'trades_primary_{tf_label}.csv'} ({len(primary)} rows)")

    return {'tf': tf_label, 'grid': grid_all}


def _print_row(scheme: str, ts_label: str, st: dict):
    if st['n'] == 0:
        print(f"  {scheme:<10}  {ts_label:<10}  n=  0")
        return
    wr = f"{st['wr']:.1f}%" if st['wr'] is not None else '—'
    pf = (f"{st['pf']:.2f}x" if st['pf'] not in (None, float('inf'))
          else ('inf' if st['pf'] == float('inf') else '—'))
    mfe = f"{st['mean_mfe_r']:.2f}R" if st['mean_mfe_r'] is not None else '—'
    print(f"  {scheme:<10}  {ts_label:<10}  {st['n']:>4}  {wr:>6}  {pf:>6}  "
          f"{st['pnl']:>8.1f}  {mfe:>6}")


def _print_grid_row(r):
    wr = f"{r['wr']:.1f}%" if r['wr'] is not None else '—'
    pf = f"{r['pf']:.2f}" if r['pf'] not in (None, float('inf')) else ('inf' if r['pf'] == float('inf') else '—')
    tgt = '' if r['target_frac'] in ('', None) or pd.isna(r['target_frac']) else f"{r['target_frac']:.2f}"
    print(f"   {r['exit_scheme']:<8} {r['gap_bucket']:<11} {r['direction']:<6} "
          f"{r['dow']:<8} {r['vixy']:<5} {r['candle_930']:<8} {r['news']:<8} "
          f"{r['fvgc']:<8} {tgt:<5} {r['stop_mult']:<4.1f} {r['time_stop']:<9} "
          f"{int(r['n']):>4} {wr:>6} {pf:>6} {r['pnl']:>7.1f} {r['q_value']:>7.3f}")


def main():
    print("=" * 72)
    print("Small-Gap Fade v2 — extended (time-stop sweep + scale-out + 3 filters)")
    print("=" * 72)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    td = pd.read_csv(TRADING_DAYS_PATH)
    results = []
    for tf_label, data_path in TIMEFRAMES.items():
        if not data_path.exists():
            print(f"\n  Skipping {tf_label}: {data_path} not found")
            continue
        results.append(run_timeframe(tf_label, data_path, td))
    print("\nDone.")


if __name__ == '__main__':
    main()
