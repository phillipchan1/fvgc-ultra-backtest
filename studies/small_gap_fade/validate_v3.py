#!/usr/bin/env python3
"""
Small-Gap Fade v3 — exit-scheme shootout.

Same entry filter as v2 validation (9:31 entry, long only, candle_930 aligned,
gap_atr<0.6, stop_mult=1.5, time-stop 10:45), but we now test SIX different
exit / risk-management schemes on the SAME 64 trades and compare them
head-to-head.  Per-variant stats + full per-trade PnL ledger so the user can
replicate any of them.

Variants
--------
V1 static_50     Baseline.  Full 1 unit.  TP=+0.5 gap.  SL=-1.5 gap.
V2 static_pdc    Full 1 unit.  TP=+1.0 gap (full gap fill).  SL=-1.5 gap.
V3 scaleout_be   0.5 unit at +0.5 gap (TP1), runner 0.5 unit to +1.0 gap (PDC)
                 with stop moved to entry (BE) after TP1.  SL=-1.5 gap initially.
V4 full_trail    Full 1 unit.  Initial SL=-1.5 gap.  Once MFE >= 1.0R, stop
                 jumps to BE and then trails at 50% of running max_fav.
V5 scale_trail   0.5 unit at +0.5 gap (TP1); runner 0.5 unit trails at 50% of
                 max_fav once MFE>=1.0R (no static PDC target).  BE after TP1.
V6 three_way     1/3 at +0.5 gap, 1/3 at +1.0 gap (PDC), 1/3 trailed at 50%
                 max_fav once MFE>=1.0R.  All three start at initial SL; TP1
                 moves the remaining 2/3 to BE.

All schemes reported per unit of initial risk (1R = 1.5*gap points), so PnL
numbers are directly comparable.
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
    compute_daily_levels, build_candle_arrays,
    RTH_OPEN, MIN_GAP_PTS,
)
from validate_v2 import find_931_entries, build_signals_931

STUDY_DIR = Path(__file__).resolve().parent
RESULTS_DIR = STUDY_DIR / 'results'

DATA_PATH = ROOT / 'data' / 'consolidated' / 'nq-front-month.ohlcv-30s.csv'
TRADING_DAYS_PATH = ROOT / 'data' / 'trading_days' / 'trading_days.csv'

ENTRY_TIME = dtime(9, 31)
TIME_STOP = dtime(10, 45)
STOP_MULT = 1.5
TRAIL_ACTIVATE_R = 1.0     # only start trailing once MFE >= 1R
TRAIL_FRAC = 0.5           # after activation, stop = entry + trail_frac * running_max_fav
OOS_SPLIT = ddate(2025, 6, 1)


# ---------------------------------------------------------------------------
# Walk functions — one per variant.  Each returns dict with pnl (per unit of
# initial risk) + diagnostic fields.
# ---------------------------------------------------------------------------

def _iter_bars(sig, arr, end_time):
    """Yield (j, time, hi, lo, close) for bars after entry on entry_date until end_time."""
    entry_idx = sig['entry_idx']
    entry_date = arr['date'][entry_idx]
    n = arr['n']
    times = arr['time']; dates = arr['date']
    highs = arr['high']; lows = arr['low']; closes = arr['close']
    j = entry_idx + 1
    while j < n and dates[j] == entry_date:
        t = times[j]
        if t > end_time:
            return
        yield j, t, highs[j], lows[j], closes[j]
        j += 1


def walk_static_target(sig, arr, end_time, target_frac):
    """Full 1-unit walk: TP at +target_frac * gap, SL at +/- stop_mult * gap."""
    entry = sig['entry_price']; gap = sig['gap_abs']; sl_dist = sig['sl_dist']
    tp = entry + target_frac * gap          # long
    sl = entry - sl_dist                    # long
    max_fav = 0.0; max_adv = 0.0; last_close = None
    for j, t, hi, lo, cp in _iter_bars(sig, arr, end_time):
        last_close = cp
        fav = hi - entry; adv = entry - lo
        if fav > max_fav: max_fav = fav
        if adv > max_adv: max_adv = adv
        sl_hit = lo <= sl; tp_hit = hi >= tp
        if sl_hit and tp_hit:
            return {'pnl': -sl_dist, 'exit': 'sl_ambig', 'max_fav': max_fav, 'max_adv': max_adv}
        if tp_hit:
            return {'pnl': tp - entry, 'exit': 'tp', 'max_fav': max_fav, 'max_adv': max_adv}
        if sl_hit:
            return {'pnl': -sl_dist, 'exit': 'sl', 'max_fav': max_fav, 'max_adv': max_adv}
    # time stop
    if last_close is None:
        return {'pnl': 0.0, 'exit': 'no_bars', 'max_fav': max_fav, 'max_adv': max_adv}
    return {'pnl': float(last_close - entry), 'exit': 'time_stop',
            'max_fav': max_fav, 'max_adv': max_adv}


def walk_scaleout_be(sig, arr, end_time):
    """0.5 unit at +0.5 gap; runner 0.5 unit to +1.0 gap with BE stop after TP1."""
    entry = sig['entry_price']; gap = sig['gap_abs']; sl_dist = sig['sl_dist']
    tp1 = entry + 0.5 * gap
    tp2 = entry + 1.0 * gap
    sl_initial = entry - sl_dist
    leg1_hit = False
    max_fav = 0.0; max_adv = 0.0; last_close = None
    total_pnl = 0.0
    exit_reason = None

    for j, t, hi, lo, cp in _iter_bars(sig, arr, end_time):
        last_close = cp
        fav = hi - entry; adv = entry - lo
        if fav > max_fav: max_fav = fav
        if adv > max_adv: max_adv = adv

        if not leg1_hit:
            sl_hit = lo <= sl_initial
            tp1_hit = hi >= tp1
            if sl_hit and not tp1_hit:
                return {'pnl': -sl_dist, 'exit': 'sl_pre_tp1',
                        'max_fav': max_fav, 'max_adv': max_adv}
            if tp1_hit and sl_hit:
                return {'pnl': -sl_dist, 'exit': 'sl_ambig_pre_tp1',
                        'max_fav': max_fav, 'max_adv': max_adv}
            if tp1_hit:
                leg1_hit = True
                total_pnl += 0.5 * (tp1 - entry)  # half unit @ TP1
        else:
            # runner phase: BE stop at entry, target at tp2
            be_hit = lo <= entry
            tp2_hit = hi >= tp2
            if be_hit and tp2_hit:
                # conservative: BE first
                total_pnl += 0.5 * 0.0
                return {'pnl': total_pnl, 'exit': 'tp1+be_ambig',
                        'max_fav': max_fav, 'max_adv': max_adv}
            if tp2_hit:
                total_pnl += 0.5 * (tp2 - entry)
                return {'pnl': total_pnl, 'exit': 'tp1+tp2',
                        'max_fav': max_fav, 'max_adv': max_adv}
            if be_hit:
                total_pnl += 0.5 * 0.0
                return {'pnl': total_pnl, 'exit': 'tp1+be',
                        'max_fav': max_fav, 'max_adv': max_adv}

    # end of window
    if not leg1_hit:
        if last_close is None:
            return {'pnl': 0.0, 'exit': 'no_bars', 'max_fav': max_fav, 'max_adv': max_adv}
        return {'pnl': float(last_close - entry), 'exit': 'time_stop_pre_tp1',
                'max_fav': max_fav, 'max_adv': max_adv}
    # runner still open at time-stop
    leg2_pnl = 0.0 if last_close is None else (last_close - entry)
    total_pnl += 0.5 * leg2_pnl
    return {'pnl': float(total_pnl), 'exit': 'tp1+time_stop',
            'max_fav': max_fav, 'max_adv': max_adv}


def walk_full_trail(sig, arr, end_time):
    """Full 1 unit.  Initial SL = entry - sl_dist.
       Once running_max_fav >= TRAIL_ACTIVATE_R * sl_dist, stop steps up to
       max(BE, entry + TRAIL_FRAC * running_max_fav_END_OF_PREVIOUS_BAR).
       We use prev-bar max_fav to set the stop used during the current bar.
    """
    entry = sig['entry_price']; sl_dist = sig['sl_dist']
    sl_initial = entry - sl_dist
    activate = TRAIL_ACTIVATE_R * sl_dist

    max_fav_prev = 0.0  # running max_fav as of END of the previous bar
    max_fav = 0.0; max_adv = 0.0; last_close = None

    for j, t, hi, lo, cp in _iter_bars(sig, arr, end_time):
        # compute current bar's stop using PREVIOUS bar's running max_fav
        if max_fav_prev >= activate:
            current_stop = max(sl_initial, entry + TRAIL_FRAC * max_fav_prev)
        else:
            current_stop = sl_initial

        last_close = cp
        # check stop hit this bar
        if lo <= current_stop:
            # also update MFE tracking before returning (using this bar's high)
            fav_now = hi - entry
            if fav_now > max_fav: max_fav = fav_now
            adv_now = entry - lo
            if adv_now > max_adv: max_adv = adv_now
            pnl = current_stop - entry
            exit_reason = 'trail' if current_stop > sl_initial else 'sl'
            return {'pnl': float(pnl), 'exit': exit_reason,
                    'max_fav': max_fav, 'max_adv': max_adv,
                    'stop_at_exit': float(current_stop)}

        # update running MFE with this bar's high
        fav = hi - entry; adv = entry - lo
        if fav > max_fav: max_fav = fav
        if adv > max_adv: max_adv = adv
        max_fav_prev = max_fav

    if last_close is None:
        return {'pnl': 0.0, 'exit': 'no_bars', 'max_fav': max_fav, 'max_adv': max_adv}
    return {'pnl': float(last_close - entry), 'exit': 'time_stop',
            'max_fav': max_fav, 'max_adv': max_adv}


def walk_scale_trail(sig, arr, end_time):
    """0.5 unit at TP1 (+0.5 gap); runner 0.5 unit with trail at 50% of MFE
       activated once MFE>=1R.  No static PDC target on the runner.
       Runner's initial stop remains at -sl_dist until TP1 hits, then jumps to
       BE; then trails once MFE crosses activate threshold.
    """
    entry = sig['entry_price']; gap = sig['gap_abs']; sl_dist = sig['sl_dist']
    tp1 = entry + 0.5 * gap
    sl_initial = entry - sl_dist
    activate = TRAIL_ACTIVATE_R * sl_dist
    leg1_hit = False
    max_fav_prev = 0.0
    max_fav = 0.0; max_adv = 0.0; last_close = None
    total_pnl = 0.0

    for j, t, hi, lo, cp in _iter_bars(sig, arr, end_time):
        # runner stop for THIS bar
        if leg1_hit:
            if max_fav_prev >= activate:
                runner_stop = max(entry, entry + TRAIL_FRAC * max_fav_prev)
            else:
                runner_stop = entry  # BE stop after TP1
        else:
            runner_stop = sl_initial  # shared with first half-unit pre-TP1

        last_close = cp

        if not leg1_hit:
            sl_hit = lo <= sl_initial
            tp1_hit = hi >= tp1
            if sl_hit and tp1_hit:
                # conservative: SL first
                return {'pnl': -sl_dist, 'exit': 'sl_ambig_pre_tp1',
                        'max_fav': max(max_fav, hi-entry), 'max_adv': max(max_adv, entry-lo)}
            if sl_hit:
                return {'pnl': -sl_dist, 'exit': 'sl_pre_tp1',
                        'max_fav': max(max_fav, hi-entry), 'max_adv': max(max_adv, entry-lo)}
            if tp1_hit:
                leg1_hit = True
                total_pnl += 0.5 * (tp1 - entry)
                # fall through: treat rest of this bar as runner phase using same bar's low
                # for stop check.  But runner stop is BE (entry) at this point.
                if lo <= entry:
                    # pulled back through entry same bar as TP1: BE hit, runner closes flat
                    fav = hi - entry; adv = entry - lo
                    if fav > max_fav: max_fav = fav
                    if adv > max_adv: max_adv = adv
                    return {'pnl': total_pnl + 0.5 * 0.0, 'exit': 'tp1+be_samebar',
                            'max_fav': max_fav, 'max_adv': max_adv}
                # else runner survives this bar; continue to next bar
                fav = hi - entry; adv = entry - lo
                if fav > max_fav: max_fav = fav
                if adv > max_adv: max_adv = adv
                max_fav_prev = max_fav
                continue
        else:
            # runner phase with trail
            if lo <= runner_stop:
                fav_now = hi - entry
                if fav_now > max_fav: max_fav = fav_now
                adv_now = entry - lo
                if adv_now > max_adv: max_adv = adv_now
                pnl_runner = runner_stop - entry
                total_pnl += 0.5 * pnl_runner
                reason = ('tp1+trail' if runner_stop > entry else 'tp1+be')
                return {'pnl': float(total_pnl), 'exit': reason,
                        'max_fav': max_fav, 'max_adv': max_adv,
                        'runner_stop_at_exit': float(runner_stop)}

        fav = hi - entry; adv = entry - lo
        if fav > max_fav: max_fav = fav
        if adv > max_adv: max_adv = adv
        max_fav_prev = max_fav

    # end of window
    if not leg1_hit:
        if last_close is None:
            return {'pnl': 0.0, 'exit': 'no_bars', 'max_fav': max_fav, 'max_adv': max_adv}
        return {'pnl': float(last_close - entry), 'exit': 'time_stop_pre_tp1',
                'max_fav': max_fav, 'max_adv': max_adv}
    leg2_pnl = 0.0 if last_close is None else (last_close - entry)
    total_pnl += 0.5 * leg2_pnl
    return {'pnl': float(total_pnl), 'exit': 'tp1+time_stop',
            'max_fav': max_fav, 'max_adv': max_adv}


def walk_three_way(sig, arr, end_time):
    """1/3 at +0.5 gap, 1/3 at +1.0 gap (PDC), 1/3 trailed at 50% MFE (activate 1R).
       Third and second units: initial SL until TP1 hits, then BE; runner
       starts trailing once max_fav hits 1R.
    """
    entry = sig['entry_price']; gap = sig['gap_abs']; sl_dist = sig['sl_dist']
    tp1 = entry + 0.5 * gap
    tp2 = entry + 1.0 * gap
    sl_initial = entry - sl_dist
    activate = TRAIL_ACTIVATE_R * sl_dist

    leg1_hit = False    # unit A closed at TP1?
    leg2_hit = False    # unit B closed at TP2?
    max_fav_prev = 0.0
    max_fav = 0.0; max_adv = 0.0; last_close = None
    total_pnl = 0.0
    # unit weights: each is 1/3 of the 1-unit position
    w = 1.0 / 3.0

    for j, t, hi, lo, cp in _iter_bars(sig, arr, end_time):
        # active stops for remaining units this bar
        if leg1_hit:
            # B and C stops are at least BE
            if leg2_hit:
                # only C remains, trailing stop applies
                if max_fav_prev >= activate:
                    c_stop = max(entry, entry + TRAIL_FRAC * max_fav_prev)
                else:
                    c_stop = entry
                b_stop = None
                bc_stop = c_stop
            else:
                bc_stop = entry  # B and C both at BE; C doesn't trail independently until B hits
                c_stop = None; b_stop = None
        else:
            bc_stop = sl_initial
            c_stop = None; b_stop = None

        last_close = cp

        if not leg1_hit:
            sl_hit = lo <= sl_initial
            tp1_hit = hi >= tp1
            if sl_hit and tp1_hit:
                # conservative: SL first, whole position out at initial SL
                return {'pnl': -sl_dist, 'exit': 'sl_ambig_pre_tp1',
                        'max_fav': max(max_fav, hi-entry), 'max_adv': max(max_adv, entry-lo)}
            if sl_hit:
                return {'pnl': -sl_dist, 'exit': 'sl_pre_tp1',
                        'max_fav': max(max_fav, hi-entry), 'max_adv': max(max_adv, entry-lo)}
            if tp1_hit:
                leg1_hit = True
                total_pnl += w * (tp1 - entry)
                # now units B and C move to BE.  Check remainder of this bar for TP2 / BE.
                if hi >= tp2:
                    # TP2 hit same bar as TP1; B exits at +gap
                    leg2_hit = True
                    total_pnl += w * (tp2 - entry)
                    # C continues; check if low of this bar hit BE (C stops at BE)
                    if lo <= entry:
                        fav = hi - entry; adv = entry - lo
                        if fav > max_fav: max_fav = fav
                        if adv > max_adv: max_adv = adv
                        return {'pnl': total_pnl + w * 0.0, 'exit': 'tp1+tp2+be_samebar',
                                'max_fav': max_fav, 'max_adv': max_adv}
                elif lo <= entry:
                    # BE hit same bar as TP1 for B and C both (neither reached TP2)
                    fav = hi - entry; adv = entry - lo
                    if fav > max_fav: max_fav = fav
                    if adv > max_adv: max_adv = adv
                    return {'pnl': total_pnl + 2 * w * 0.0, 'exit': 'tp1+be_samebar',
                            'max_fav': max_fav, 'max_adv': max_adv}
                fav = hi - entry; adv = entry - lo
                if fav > max_fav: max_fav = fav
                if adv > max_adv: max_adv = adv
                max_fav_prev = max_fav
                continue
        else:
            # runner phase
            if not leg2_hit:
                # Units B and C both have BE stop; B also has TP2 target
                tp2_hit = hi >= tp2
                be_hit = lo <= entry
                if be_hit and tp2_hit:
                    # conservative: BE first — both B and C stopped at BE
                    fav = hi - entry; adv = entry - lo
                    if fav > max_fav: max_fav = fav
                    if adv > max_adv: max_adv = adv
                    return {'pnl': total_pnl + 2*w*0.0, 'exit': 'tp1+be_ambig',
                            'max_fav': max_fav, 'max_adv': max_adv}
                if tp2_hit:
                    leg2_hit = True
                    total_pnl += w * (tp2 - entry)
                    # after TP2, unit C continues; its trailing stop may already be set
                    # Check this bar's low against the NEW c_stop (post-TP2 activation)
                    if max_fav_prev >= activate:
                        c_stop_now = max(entry, entry + TRAIL_FRAC * max_fav_prev)
                    else:
                        c_stop_now = entry
                    if lo <= c_stop_now:
                        fav = hi - entry; adv = entry - lo
                        if fav > max_fav: max_fav = fav
                        if adv > max_adv: max_adv = adv
                        total_pnl += w * (c_stop_now - entry)
                        return {'pnl': total_pnl, 'exit': 'tp1+tp2+trail_samebar',
                                'max_fav': max_fav, 'max_adv': max_adv,
                                'runner_stop_at_exit': float(c_stop_now)}
                    fav = hi - entry; adv = entry - lo
                    if fav > max_fav: max_fav = fav
                    if adv > max_adv: max_adv = adv
                    max_fav_prev = max_fav
                    continue
                if be_hit:
                    # B and C both stopped at BE
                    fav = hi - entry; adv = entry - lo
                    if fav > max_fav: max_fav = fav
                    if adv > max_adv: max_adv = adv
                    return {'pnl': total_pnl + 2*w*0.0, 'exit': 'tp1+be',
                            'max_fav': max_fav, 'max_adv': max_adv}
            else:
                # only C remains; trail stop
                if lo <= bc_stop:
                    fav = hi - entry; adv = entry - lo
                    if fav > max_fav: max_fav = fav
                    if adv > max_adv: max_adv = adv
                    total_pnl += w * (bc_stop - entry)
                    reason = ('tp1+tp2+trail' if bc_stop > entry else 'tp1+tp2+be')
                    return {'pnl': total_pnl, 'exit': reason,
                            'max_fav': max_fav, 'max_adv': max_adv,
                            'runner_stop_at_exit': float(bc_stop)}

        fav = hi - entry; adv = entry - lo
        if fav > max_fav: max_fav = fav
        if adv > max_adv: max_adv = adv
        max_fav_prev = max_fav

    # end of window
    if not leg1_hit:
        if last_close is None:
            return {'pnl': 0.0, 'exit': 'no_bars', 'max_fav': max_fav, 'max_adv': max_adv}
        return {'pnl': float(last_close - entry), 'exit': 'time_stop_pre_tp1',
                'max_fav': max_fav, 'max_adv': max_adv}
    # leg1 closed; maybe leg2 too
    leg_close = 0.0 if last_close is None else (last_close - entry)
    if not leg2_hit:
        # B and C both close at last_close
        total_pnl += 2 * w * leg_close
        return {'pnl': float(total_pnl), 'exit': 'tp1+time_stop',
                'max_fav': max_fav, 'max_adv': max_adv}
    # only C remains
    total_pnl += w * leg_close
    return {'pnl': float(total_pnl), 'exit': 'tp1+tp2+time_stop',
            'max_fav': max_fav, 'max_adv': max_adv}


VARIANTS = {
    'V1_static_50':   lambda sig, arr: walk_static_target(sig, arr, TIME_STOP, 0.5),
    'V2_static_pdc':  lambda sig, arr: walk_static_target(sig, arr, TIME_STOP, 1.0),
    'V3_scaleout_be': lambda sig, arr: walk_scaleout_be(sig, arr, TIME_STOP),
    'V4_full_trail':  lambda sig, arr: walk_full_trail(sig, arr, TIME_STOP),
    'V5_scale_trail': lambda sig, arr: walk_scale_trail(sig, arr, TIME_STOP),
    'V6_three_way':   lambda sig, arr: walk_three_way(sig, arr, TIME_STOP),
}


# ---------------------------------------------------------------------------
# Entry filter — same as validate_v2
# ---------------------------------------------------------------------------

def build_filtered_trades():
    print("Loading 30s data...")
    candles = load_candles(DATA_PATH)
    daily = compute_daily_levels(candles)
    entries = find_931_entries(candles)
    arr = build_candle_arrays(candles)

    td = pd.read_csv(TRADING_DAYS_PATH)
    td_small = td[['date', 'candle_930_direction', 'has_red_folder_news']].copy()
    td_small['date'] = pd.to_datetime(td_small['date']).dt.date
    td_map = td_small.set_index('date').to_dict(orient='index')

    def candle_aligned_long(d):
        r = td_map.get(d)
        if not r: return False
        cd = r.get('candle_930_direction')
        if pd.isna(cd): return False
        return cd == 'bullish'

    def has_news(d):
        r = td_map.get(d)
        return False if not r else bool(r.get('has_red_folder_news', False))

    # Use target_frac=1.0 as placeholder; walkers compute their own TPs.
    sigs = build_signals_931(daily, entries, target_frac=1.0, stop_mult=STOP_MULT)
    filtered = []
    for sig in sigs:
        if sig['gap_atr_ratio'] >= 0.6: continue
        if sig['direction'] != 'long': continue
        if not candle_aligned_long(sig['date']): continue
        sig['has_red_folder_news'] = has_news(sig['date'])
        filtered.append(sig)
    print(f"  {len(filtered)} trades pass filter (should be 64)")
    return filtered, arr


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def summarize(df, variant):
    sub = df[df['variant'] == variant]
    n = len(sub)
    wins = (sub['pnl_r'] > 0).sum()
    losses = (sub['pnl_r'] < 0).sum()
    flats = (sub['pnl_r'] == 0).sum()
    decided = wins + losses
    wr = (wins / decided * 100) if decided > 0 else None
    gp = sub.loc[sub['pnl_r'] > 0, 'pnl_r'].sum()
    gl = abs(sub.loc[sub['pnl_r'] < 0, 'pnl_r'].sum())
    pf = (gp / gl) if gl > 0 else float('inf')
    total_r = sub['pnl_r'].sum()
    total_pts = sub['pnl_pts'].sum()
    mean_r = sub['pnl_r'].mean()
    median_r = sub['pnl_r'].median()
    # max drawdown in R, equity-curve sense (cumulative sum of R)
    curve = sub.sort_values('date')['pnl_r'].cumsum().to_numpy()
    peak = np.maximum.accumulate(curve) if len(curve) > 0 else np.array([0.0])
    dd = (curve - peak) if len(curve) > 0 else np.array([0.0])
    max_dd_r = float(dd.min()) if len(dd) > 0 else 0.0
    return {
        'variant': variant, 'n': n, 'wins': wins, 'losses': losses, 'flats': flats,
        'wr': wr, 'pf': pf, 'total_r': total_r, 'total_pts': total_pts,
        'mean_r': mean_r, 'median_r': median_r, 'max_dd_r': max_dd_r,
    }


def print_summary(summaries, title):
    print()
    print(f"  {title}")
    print("  " + "-" * 92)
    print(f"  {'variant':<16} {'n':>3} {'W':>3} {'L':>3} {'WR':>6} {'PF':>6} "
          f"{'mean R':>7} {'med R':>6} {'total R':>8} {'pts':>8} {'maxDD':>7}")
    print("  " + "-" * 92)
    for s in summaries:
        wr = f"{s['wr']:.1f}%" if s['wr'] is not None else '—'
        pf = f"{s['pf']:.2f}x" if s['pf'] != float('inf') else 'inf'
        print(f"  {s['variant']:<16} {s['n']:>3} {s['wins']:>3} {s['losses']:>3} "
              f"{wr:>6} {pf:>6} "
              f"{s['mean_r']:>7.3f} {s['median_r']:>6.3f} "
              f"{s['total_r']:>8.2f} {s['total_pts']:>8.1f} {s['max_dd_r']:>7.2f}")


def main():
    print("=" * 92)
    print("Small-Gap Fade v3 — exit scheme shootout on 30s, 64 trades")
    print("  entry=9:31, long-only, candle_930 aligned, gap_atr<0.6, stop=1.5*gap, ts=10:45")
    print("=" * 92)

    filtered, arr = build_filtered_trades()

    rows = []
    for sig in filtered:
        sl_dist = sig['sl_dist']
        for vname, walker in VARIANTS.items():
            res = walker(sig, arr)
            rows.append({
                'variant': vname, 'date': sig['date'],
                'period': 'IS' if sig['date'] < OOS_SPLIT else 'OOS',
                'entry_time': sig['timestamp'],
                'entry_price': sig['entry_price'],
                'gap_pts': sig['gap_pts'],
                'gap_abs': sig['gap_abs'],
                'gap_atr_ratio': sig['gap_atr_ratio'],
                'sl_dist_pts': sl_dist,
                'has_red_folder_news': sig['has_red_folder_news'],
                'pnl_pts': res['pnl'],
                'pnl_r': res['pnl'] / sl_dist if sl_dist > 0 else 0.0,
                'mfe_r': res['max_fav'] / sl_dist if sl_dist > 0 else None,
                'mae_r': res['max_adv'] / sl_dist if sl_dist > 0 else None,
                'exit_reason': res['exit'],
                'stop_at_exit': res.get('stop_at_exit') or res.get('runner_stop_at_exit'),
            })

    df = pd.DataFrame(rows)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ledger_path = RESULTS_DIR / 'v3_trade_ledger.csv'
    df.to_csv(ledger_path, index=False)
    print(f"\n  Full ledger written: {ledger_path}  ({len(df)} rows = 6 variants x 64 trades)")

    all_summaries = [summarize(df, v) for v in VARIANTS.keys()]
    print_summary(all_summaries, "ALL (full period, n=64)")

    is_df = df[df['period'] == 'IS']
    oos_df = df[df['period'] == 'OOS']
    is_sums = [summarize(is_df, v) for v in VARIANTS.keys()]
    oos_sums = [summarize(oos_df, v) for v in VARIANTS.keys()]
    print_summary(is_sums, f"IN-SAMPLE (pre {OOS_SPLIT}, n=47)")
    print_summary(oos_sums, f"OUT-OF-SAMPLE ({OOS_SPLIT}+, n=17)")

    # Summary CSV
    summary_rows = []
    for period, sums in [('ALL', all_summaries), ('IS', is_sums), ('OOS', oos_sums)]:
        for s in sums:
            summary_rows.append({'period': period, **s})
    pd.DataFrame(summary_rows).to_csv(RESULTS_DIR / 'v3_summary.csv', index=False)
    print(f"\n  Summary written: {RESULTS_DIR / 'v3_summary.csv'}")

    print("\nDone.")


if __name__ == '__main__':
    main()
