#!/usr/bin/env python3
"""
Keltner PF optimization: compare close-through-band stop vs fixed 1R intrabar stop
vs scale-out (half at 1R, half to 2R with breakeven), with extended context grid.

Entry logic matches studies/keltner_midline_pullback/run.py.

Run from repo root:
  python studies/keltner_pf_optimization/run.py --perms 300
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from fvgc.data import load_candles
from fvgc.constants import TRADING_WINDOW_START, TRADING_WINDOW_END

# Load sibling study module (not a package)
_KSPEC = importlib.util.spec_from_file_location(
    "keltner_midline_pullback_run",
    ROOT / "studies" / "keltner_midline_pullback" / "run.py",
)
if _KSPEC is None or _KSPEC.loader is None:
    raise RuntimeError("Cannot load keltner_midline_pullback/run.py")
_kmb = importlib.util.module_from_spec(_KSPEC)
_KSPEC.loader.exec_module(_kmb)

compute_keltner_5m = _kmb.compute_keltner_5m
merge_keltner_onto_30s = _kmb.merge_keltner_onto_30s
build_break_events = _kmb.build_break_events
add_context_columns = _kmb.add_context_columns
get_macro_window = _kmb.get_macro_window

DATA_30S = ROOT / "data" / "consolidated" / "nq-front-month.ohlcv-30s.csv"
DATA_5M = ROOT / "data" / "consolidated" / "nq-front-month.ohlcv-5m.csv"
STUDY_DIR = Path(__file__).resolve().parent
RESULTS_DIR = STUDY_DIR / "results"

EMA_PERIODS = [10, 20, 30]
ATR_MULTS = [1.0, 1.5, 2.0]
PULLBACK_TOLS = [2.0, 3.0, 5.0]

MACRO_SCOPES = ["w1", "w1_w2", "all"]
VIXY_FILTERS = ["all", "low", "medium", "high"]
GAP_FILTERS = ["not_required", "required"]
DOW_FILTERS = [
    "all",
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "not_monday",
]

MIN_N = 30
DEFAULT_PERMS = 300
RNG_SEED = 42


def macro_scope_mask(df: pd.DataFrame, scope: str) -> pd.Series:
    if scope == "w1":
        return df["macro_window"] == 1
    if scope == "w1_w2":
        return df["macro_window"].isin([1, 2])
    return pd.Series(True, index=df.index)


def vixy_mask(df: pd.DataFrame, bucket: str) -> pd.Series:
    if bucket == "all":
        return pd.Series(True, index=df.index)
    return df["vixy_bucket"] == bucket


def gap_filter_mask(df: pd.DataFrame, mode: str) -> pd.Series:
    if mode == "not_required":
        return pd.Series(True, index=df.index)
    return df["gap_aligned"]


def dow_mask(df: pd.DataFrame, dow: str) -> pd.Series:
    if dow == "all":
        return pd.Series(True, index=df.index)
    if dow == "not_monday":
        return df["day_of_week_name"] != "Monday"
    return df["day_of_week_name"] == dow


def find_keltner_entry(
    candles_30: pd.DataFrame,
    k_ema: np.ndarray,
    k_upper: np.ndarray,
    k_lower: np.ndarray,
    k_band_width: np.ndarray,
    k5: pd.DataFrame,
    break_idx: int,
    direction: str,
    tol: float,
    day_id: np.ndarray,
) -> dict | None:
    """Return entry state through entry bar; None if no valid entry."""
    date = k5.loc[break_idx, "bar_end"].date()
    break_bar_end = k5.loc[break_idx, "bar_end"]
    target_day_id = date.year * 10000 + date.month * 100 + date.day

    close_b = float(k5.loc[break_idx, "close"])
    upper_b = float(k5.loc[break_idx, "upper"])
    lower_b = float(k5.loc[break_idx, "lower"])

    if direction == "long":
        break_dist = close_b - upper_b
    else:
        break_dist = lower_b - close_b

    ts = candles_30["timestamp_ny"]
    start = int(ts.searchsorted(break_bar_end, side="right"))
    if start >= len(candles_30) or int(day_id[start]) != target_day_id:
        return None

    highs = candles_30["high"].to_numpy(float)
    lows = candles_30["low"].to_numpy(float)
    closes = candles_30["close"].to_numpy(float)
    opens = candles_30["open"].to_numpy(float)

    touch_j = None
    for j in range(start, len(candles_30)):
        if int(day_id[j]) != target_day_id:
            break
        if np.isnan(k_lower[j]) or np.isnan(k_ema[j]):
            continue
        ema_j = float(k_ema[j])
        lo_j = float(k_lower[j])
        hi_j = float(k_upper[j])
        if direction == "long":
            if closes[j] < lo_j:
                return None
            touched = (lows[j] <= ema_j + tol) and (highs[j] >= ema_j - tol)
        else:
            if closes[j] > hi_j:
                return None
            touched = (highs[j] >= ema_j - tol) and (lows[j] <= ema_j + tol)

        if touched:
            touch_j = j
            break

    if touch_j is None:
        return None

    entry_j = None
    for j in range(touch_j + 1, len(candles_30)):
        if int(day_id[j]) != target_day_id:
            break
        if np.isnan(k_lower[j]) or np.isnan(k_upper[j]):
            continue
        lo_j = float(k_lower[j])
        hi_j = float(k_upper[j])
        if direction == "long":
            if closes[j] < lo_j:
                return None
            if closes[j] > opens[j]:
                entry_j = j
                break
        else:
            if closes[j] > hi_j:
                return None
            if closes[j] < opens[j]:
                entry_j = j
                break

    if entry_j is None:
        return None

    entry_price = float(closes[entry_j])
    lower_e = float(k_lower[entry_j])
    upper_e = float(k_upper[entry_j])
    bw_e = float(k_band_width[entry_j])

    if direction == "long":
        sl_dist = entry_price - lower_e
        sl_price = lower_e
        opp_band = lower_e
    else:
        sl_dist = upper_e - entry_price
        sl_price = upper_e
        opp_band = upper_e

    if sl_dist <= 0:
        return None

    tp1 = entry_price + sl_dist if direction == "long" else entry_price - sl_dist
    tp2 = entry_price + 2 * sl_dist if direction == "long" else entry_price - 2 * sl_dist
    tp3 = entry_price + 3 * sl_dist if direction == "long" else entry_price - 3 * sl_dist

    ema_t = float(k_ema[touch_j])
    td = min(
        abs(highs[touch_j] - ema_t),
        abs(lows[touch_j] - ema_t),
        abs(closes[touch_j] - ema_t),
    )

    return {
        "date": date,
        "target_day_id": target_day_id,
        "break_bar_end": break_bar_end,
        "touch_j": touch_j,
        "entry_j": entry_j,
        "entry_price": entry_price,
        "sl_price": sl_price,
        "sl_dist": sl_dist,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "direction": direction,
        "break_dist": float(break_dist),
        "td": float(td),
        "lower_e": lower_e,
        "upper_e": upper_e,
        "bw_e": bw_e,
        "opp_band": float(opp_band),
    }


def _exit_close_band(
    candles_30: pd.DataFrame,
    k_lower: np.ndarray,
    k_upper: np.ndarray,
    direction: str,
    entry_j: int,
    entry_price: float,
    sl_dist: float,
    tp1: float,
    tp2: float,
    tp3: float,
    day_id: np.ndarray,
    target_day_id: int,
    day_last_idx: dict,
    date,
) -> dict:
    """Original: stop on 30s close through opposite band; 1R target intrabar."""
    highs = candles_30["high"].to_numpy(float)
    lows = candles_30["low"].to_numpy(float)
    closes = candles_30["close"].to_numpy(float)
    ts_iat = candles_30["timestamp_ny"]

    max_fav = max_adv = 0.0
    hit_1r = hit_2r = hit_3r = False
    outcome = "open"
    exit_price = np.nan
    exit_time = pd.NaT
    full_stop_close = False

    for k in range(entry_j + 1, len(candles_30)):
        if int(day_id[k]) != target_day_id:
            prev = candles_30.iloc[k - 1]
            if outcome == "open":
                outcome = "eod"
                exit_price = float(prev["close"])
                exit_time = prev["timestamp_ny"]
            break

        if np.isnan(k_lower[k]) or np.isnan(k_upper[k]):
            continue

        lo_k = float(k_lower[k])
        hi_k = float(k_upper[k])

        if direction == "long":
            fav = highs[k] - entry_price
            adv = entry_price - lows[k]
            stop_close = closes[k] < lo_k
            t1h = highs[k] >= tp1
            t2h = highs[k] >= tp2
            t3h = highs[k] >= tp3
        else:
            fav = entry_price - lows[k]
            adv = highs[k] - entry_price
            stop_close = closes[k] > hi_k
            t1h = lows[k] <= tp1
            t2h = lows[k] <= tp2
            t3h = lows[k] <= tp3

        max_fav = max(max_fav, fav)
        max_adv = max(max_adv, adv)

        if t1h and not hit_1r:
            hit_1r = True
        if t2h and not hit_2r:
            hit_2r = True
        if t3h and not hit_3r:
            hit_3r = True

        if stop_close and t1h:
            outcome = "ambiguous"
            exit_price = float(closes[k])
            exit_time = ts_iat.iat[k]
            full_stop_close = True
            break

        if stop_close:
            outcome = "loss"
            exit_price = float(closes[k])
            exit_time = ts_iat.iat[k]
            full_stop_close = True
            break

        if t1h:
            outcome = "win"
            exit_price = tp1
            exit_time = ts_iat.iat[k]
            break

    if outcome == "open":
        li = day_last_idx.get(date)
        if li is None:
            return {}
        last = candles_30.iloc[li]
        outcome = "eod"
        exit_price = float(last["close"])
        exit_time = last["timestamp_ny"]

    pnl_pts = (exit_price - entry_price) if direction == "long" else (entry_price - exit_price)
    pnl_r = float(pnl_pts / sl_dist) if sl_dist > 0 else np.nan

    return {
        "outcome_cb": outcome,
        "exit_price_cb": float(exit_price),
        "exit_time_cb": exit_time,
        "pnl_pts_cb": float(pnl_pts),
        "pnl_r_cb": pnl_r,
        "mfe_pts_cb": float(max_fav),
        "mae_pts_cb": float(max_adv),
        "mfe_r_cb": float(max_fav / sl_dist) if sl_dist > 0 else np.nan,
        "mae_r_cb": float(max_adv / sl_dist) if sl_dist > 0 else np.nan,
        "hit_1R_mfe_cb": hit_1r,
        "hit_2R_mfe_cb": hit_2r,
        "hit_3R_mfe_cb": hit_3r,
        "full_stop_close_cb": full_stop_close,
    }


def _exit_fixed_1r(
    candles_30: pd.DataFrame,
    direction: str,
    entry_j: int,
    entry_price: float,
    sl_price: float,
    sl_dist: float,
    tp1: float,
    tp2: float,
    tp3: float,
    day_id: np.ndarray,
    target_day_id: int,
    day_last_idx: dict,
    date,
) -> dict:
    """Intrabar SL at sl_price; 1R TP at tp1 (fvgc.engine-style)."""
    highs = candles_30["high"].to_numpy(float)
    lows = candles_30["low"].to_numpy(float)
    ts_iat = candles_30["timestamp_ny"]

    max_fav = max_adv = 0.0
    hit_1r = hit_2r = hit_3r = False
    outcome = "open"
    exit_price = np.nan
    exit_time = pd.NaT

    for k in range(entry_j + 1, len(candles_30)):
        if int(day_id[k]) != target_day_id:
            prev = candles_30.iloc[k - 1]
            if outcome == "open":
                outcome = "eod"
                exit_price = float(prev["close"])
                exit_time = prev["timestamp_ny"]
            break

        if direction == "long":
            fav = highs[k] - entry_price
            adv = entry_price - lows[k]
            sl_hit = lows[k] <= sl_price
            t1h = highs[k] >= tp1
            t2h = highs[k] >= tp2
            t3h = highs[k] >= tp3
        else:
            fav = entry_price - lows[k]
            adv = highs[k] - entry_price
            sl_hit = highs[k] >= sl_price
            t1h = lows[k] <= tp1
            t2h = lows[k] <= tp2
            t3h = lows[k] <= tp3

        max_fav = max(max_fav, fav)
        max_adv = max(max_adv, adv)

        if t1h and not hit_1r:
            hit_1r = True
        if t2h and not hit_2r:
            hit_2r = True
        if t3h and not hit_3r:
            hit_3r = True

        if sl_hit and t1h:
            outcome = "ambiguous"
            exit_price = sl_price
            exit_time = ts_iat.iat[k]
            break
        if sl_hit:
            outcome = "loss"
            exit_price = sl_price
            exit_time = ts_iat.iat[k]
            break
        if t1h:
            outcome = "win"
            exit_price = tp1
            exit_time = ts_iat.iat[k]
            break

    if outcome == "open":
        li = day_last_idx.get(date)
        if li is None:
            return {}
        last = candles_30.iloc[li]
        outcome = "eod"
        exit_price = float(last["close"])
        exit_time = last["timestamp_ny"]

    pnl_pts = (exit_price - entry_price) if direction == "long" else (entry_price - exit_price)
    pnl_r = float(pnl_pts / sl_dist) if sl_dist > 0 else np.nan

    return {
        "outcome_f1": outcome,
        "exit_price_f1": float(exit_price),
        "exit_time_f1": exit_time,
        "pnl_pts_f1": float(pnl_pts),
        "pnl_r_f1": pnl_r,
        "mfe_pts_f1": float(max_fav),
        "mae_pts_f1": float(max_adv),
        "mfe_r_f1": float(max_fav / sl_dist) if sl_dist > 0 else np.nan,
        "mae_r_f1": float(max_adv / sl_dist) if sl_dist > 0 else np.nan,
        "hit_1R_mfe_f1": hit_1r,
        "hit_2R_mfe_f1": hit_2r,
        "hit_3R_mfe_f1": hit_3r,
    }


def _exit_scaleout_fixed(
    candles_30: pd.DataFrame,
    direction: str,
    entry_j: int,
    entry_price: float,
    sl_price: float,
    sl_dist: float,
    tp1: float,
    tp2: float,
    day_id: np.ndarray,
    target_day_id: int,
    day_last_idx: dict,
    date,
) -> dict:
    """Half size exits at 1R; runner moves to BE, targets 2R. Same intrabar SL before scale."""
    highs = candles_30["high"].to_numpy(float)
    lows = candles_30["low"].to_numpy(float)
    ts_iat = candles_30["timestamp_ny"]

    half = 0.5
    scaled = False
    pnl_pts = 0.0
    max_fav = max_adv = 0.0
    outcome = "open"
    exit_time = pd.NaT

    for k in range(entry_j + 1, len(candles_30)):
        if int(day_id[k]) != target_day_id:
            prev = candles_30.iloc[k - 1]
            last_px = float(prev["close"])
            if not scaled:
                pnl_pts = (last_px - entry_price) if direction == "long" else (entry_price - last_px)
                outcome = "eod"
            else:
                pnl_pts += half * (
                    (last_px - entry_price) if direction == "long" else (entry_price - last_px)
                )
                outcome = "eod"
            exit_time = prev["timestamp_ny"]
            break

        if direction == "long":
            fav = highs[k] - entry_price
            adv = entry_price - lows[k]
        else:
            fav = entry_price - lows[k]
            adv = highs[k] - entry_price
        max_fav = max(max_fav, fav)
        max_adv = max(max_adv, adv)

        if not scaled:
            sl_hit = lows[k] <= sl_price if direction == "long" else highs[k] >= sl_price
            tp1_hit = highs[k] >= tp1 if direction == "long" else lows[k] <= tp1
            if sl_hit and tp1_hit:
                outcome = "ambiguous"
                pnl_pts = -(sl_dist)  # full -1R
                exit_time = ts_iat.iat[k]
                break
            if sl_hit:
                outcome = "loss"
                pnl_pts = -sl_dist
                exit_time = ts_iat.iat[k]
                break
            if tp1_hit:
                scaled = True
                pnl_pts += half * ((tp1 - entry_price) if direction == "long" else (entry_price - tp1))
                # Same bar: runner may hit 2R or BE before next bar
                tp2_hit = highs[k] >= tp2 if direction == "long" else lows[k] <= tp2
                be_hit = lows[k] <= entry_price if direction == "long" else highs[k] >= entry_price
                if tp2_hit:
                    outcome = "win"
                    pnl_pts += half * (
                        (tp2 - entry_price) if direction == "long" else (entry_price - tp2)
                    )
                    exit_time = ts_iat.iat[k]
                    break
                if be_hit:
                    outcome = "partial_win"
                    exit_time = ts_iat.iat[k]
                    break
        else:
            tp2_hit = highs[k] >= tp2 if direction == "long" else lows[k] <= tp2
            be_hit = lows[k] <= entry_price if direction == "long" else highs[k] >= entry_price
            if tp2_hit:
                outcome = "win"
                pnl_pts += half * ((tp2 - entry_price) if direction == "long" else (entry_price - tp2))
                exit_time = ts_iat.iat[k]
                break
            if be_hit:
                outcome = "partial_win"
                exit_time = ts_iat.iat[k]
                break

    if outcome == "open":
        li = day_last_idx.get(date)
        if li is None:
            return {}
        last = candles_30.iloc[li]
        last_px = float(last["close"])
        if not scaled:
            pnl_pts = (last_px - entry_price) if direction == "long" else (entry_price - last_px)
        else:
            pnl_pts += half * (
                (last_px - entry_price) if direction == "long" else (entry_price - last_px)
            )
        outcome = "eod"
        exit_time = last["timestamp_ny"]

    pnl_r = float(pnl_pts / sl_dist) if sl_dist > 0 else np.nan

    return {
        "outcome_so": outcome,
        "exit_time_so": exit_time,
        "pnl_pts_so": float(pnl_pts),
        "pnl_r_so": pnl_r,
        "mfe_pts_so": float(max_fav),
        "mae_pts_so": float(max_adv),
        "mfe_r_so": float(max_fav / sl_dist) if sl_dist > 0 else np.nan,
        "mae_r_so": float(max_adv / sl_dist) if sl_dist > 0 else np.nan,
        "scaled_1r_so": scaled,
    }


def simulate_three_exits(
    candles_30: pd.DataFrame,
    k_ema: np.ndarray,
    k_upper: np.ndarray,
    k_lower: np.ndarray,
    k_band_width: np.ndarray,
    ema_p: int,
    atr_m: float,
    tol: float,
    k5: pd.DataFrame,
    break_idx: int,
    direction: str,
    day_last_idx: dict,
    day_id: np.ndarray,
) -> dict | None:
    ent = find_keltner_entry(
        candles_30,
        k_ema,
        k_upper,
        k_lower,
        k_band_width,
        k5,
        break_idx,
        direction,
        tol,
        day_id,
    )
    if ent is None:
        return None

    date = ent["date"]
    target_day_id = ent["target_day_id"]
    entry_j = ent["entry_j"]
    entry_price = ent["entry_price"]
    sl_dist = ent["sl_dist"]
    sl_price = ent["sl_price"]
    tp1, tp2, tp3 = ent["tp1"], ent["tp2"], ent["tp3"]

    dcb = _exit_close_band(
        candles_30,
        k_lower,
        k_upper,
        direction,
        entry_j,
        entry_price,
        sl_dist,
        tp1,
        tp2,
        tp3,
        day_id,
        target_day_id,
        day_last_idx,
        date,
    )
    if not dcb:
        return None

    df1 = _exit_fixed_1r(
        candles_30,
        direction,
        entry_j,
        entry_price,
        sl_price,
        sl_dist,
        tp1,
        tp2,
        tp3,
        day_id,
        target_day_id,
        day_last_idx,
        date,
    )
    if not df1:
        return None

    dso = _exit_scaleout_fixed(
        candles_30,
        direction,
        entry_j,
        entry_price,
        sl_price,
        sl_dist,
        tp1,
        tp2,
        day_id,
        target_day_id,
        day_last_idx,
        date,
    )
    if not dso:
        return None

    row = {
        "ema_period": ema_p,
        "atr_mult": atr_m,
        "pullback_tol": tol,
        "date": date,
        "break_time_5m": k5.loc[break_idx, "timestamp_ny"],
        "break_bar_end": ent["break_bar_end"],
        "direction": direction,
        "band_width_at_break": float(k5.loc[break_idx, "band_width"]),
        "dist_outside_band_pts": ent["break_dist"],
        "pullback_depth_to_ema": ent["td"],
        "midline_touch_time": candles_30.iloc[ent["touch_j"]]["timestamp_ny"],
        "entry_time": candles_30.iloc[entry_j]["timestamp_ny"],
        "entry_price": entry_price,
        "k_upper_at_entry": ent["upper_e"],
        "k_lower_at_entry": ent["lower_e"],
        "k_ema_at_entry": float(k_ema[entry_j]),
        "k_band_width_at_entry": ent["bw_e"],
        "opposite_band_at_entry": ent["opp_band"],
        "sl_dist": sl_dist,
        "tp_1r": tp1,
        "tp_2r": tp2,
        "tp_3r": tp3,
    }
    row.update(dcb)
    row.update(df1)
    row.update(dso)
    return row


def apply_corrections(df: pd.DataFrame, p_col: str) -> pd.DataFrame:
    valid = df[p_col].notna()
    n_tests = int(valid.sum())
    bonf_col = f"{p_col}_bonferroni"
    bh_col = f"{p_col}_bh"
    df[bonf_col] = np.nan
    df[bh_col] = np.nan
    if n_tests == 0:
        return df

    df.loc[valid, bonf_col] = np.minimum(df.loc[valid, p_col] * n_tests, 1.0)

    valid_idx = df.index[valid]
    p_vals = df.loc[valid_idx, p_col].to_numpy(dtype=float)
    order = np.argsort(p_vals)
    p_sorted = p_vals[order]
    ranks = np.arange(1, len(p_sorted) + 1, dtype=float)

    q_sorted = p_sorted * n_tests / ranks
    for i in range(len(q_sorted) - 2, -1, -1):
        q_sorted[i] = min(q_sorted[i], q_sorted[i + 1])
    q_sorted = np.minimum(q_sorted, 1.0)

    q_vals = np.empty_like(q_sorted)
    q_vals[order] = q_sorted
    df.loc[valid_idx, bh_col] = q_vals
    return df


def profit_factor_scalar(gp: float, gl: float) -> float:
    if gl > 0:
        return float(gp / gl)
    if gp > 0:
        return float(np.inf)
    return float(np.nan)


def profit_factor_arrays(gp: np.ndarray, gl: np.ndarray) -> np.ndarray:
    r = np.empty_like(gp, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        m = gl > 0
        r[m] = gp[m] / gl[m]
        r[~m] = np.where(gp[~m] > 0, np.inf, np.nan)
    return r


def _p_value_two_sided(actual: float, perm_samples: np.ndarray) -> float:
    perm_mean = np.nanmean(perm_samples)
    if np.isnan(actual) or np.isnan(perm_mean):
        return np.nan
    if actual >= perm_mean:
        return float(np.nanmean(perm_samples >= actual))
    return float(np.nanmean(perm_samples <= actual))


def summarize_combo_mask(
    base: pd.DataFrame,
    mask: np.ndarray,
    outcome_col: str,
    pnl_col: str,
) -> dict | None:
    sub = base[mask]
    n = len(sub)
    if n < MIN_N:
        return None
    wins = int((sub[outcome_col] == "win").sum())
    losses = int((sub[outcome_col] == "loss").sum())
    if wins + losses == 0:
        return None
    wr = wins / (wins + losses) * 100.0
    pnl_r = sub[pnl_col].to_numpy(dtype=float)
    gp = pnl_r[pnl_r > 0].sum()
    gl = abs(pnl_r[pnl_r < 0].sum())
    pf = profit_factor_scalar(gp, gl)
    return {
        "n": n,
        "wins": wins,
        "losses": losses,
        "win_rate": wr,
        "profit_factor": pf,
        "avg_r": float(np.nanmean(pnl_r)),
    }


def _normalize_scaleout_outcome(df: pd.DataFrame) -> pd.DataFrame:
    """Map partial_win to win for WR/PF stats (profitable resolution)."""
    out = df["outcome_so"].copy()
    out = np.where(out == "partial_win", "win", out)
    df = df.copy()
    df["outcome_so_wl"] = out
    return df


def run_grid_for_variant(
    base_full: pd.DataFrame,
    outcome_col: str,
    pnl_col: str,
    exit_variant: str,
    n_perms: int,
) -> pd.DataFrame:
    base = base_full[base_full[outcome_col].isin(["win", "loss"])].copy()
    if base.empty:
        return pd.DataFrame()

    rng = np.random.default_rng(RNG_SEED)
    win_flags = (base[outcome_col] == "win").to_numpy(dtype=bool)
    pnl_vals = base[pnl_col].to_numpy(dtype=float)
    n_total = len(base)

    meta: list[dict] = []
    masks: list[np.ndarray] = []

    for ep, am, ptol, ms, vb, gf, dow in product(
        EMA_PERIODS,
        ATR_MULTS,
        PULLBACK_TOLS,
        MACRO_SCOPES,
        VIXY_FILTERS,
        GAP_FILTERS,
        DOW_FILTERS,
    ):
        mask = (
            (base["ema_period"] == ep)
            & (base["atr_mult"] == am)
            & (base["pullback_tol"] == ptol)
            & macro_scope_mask(base, ms)
            & vixy_mask(base, vb)
            & gap_filter_mask(base, gf)
            & dow_mask(base, dow)
        ).to_numpy(dtype=bool)
        stats = summarize_combo_mask(base, mask, outcome_col, pnl_col)
        if stats is None:
            continue
        meta.append(
            {
                "exit_variant": exit_variant,
                "ema_period": ep,
                "atr_mult": am,
                "pullback_tol": ptol,
                "macro_scope": ms,
                "vixy_filter": vb,
                "gap_filter": gf,
                "dow_filter": dow,
                **stats,
            }
        )
        masks.append(mask)

    if not masks:
        return pd.DataFrame()

    n_combo = len(masks)
    mask_mat = np.stack(masks, axis=0)
    counts = mask_mat.sum(axis=1).astype(float)
    mm = mask_mat.astype(float)

    w_float = win_flags.astype(float)
    win_sums0 = mm @ w_float
    with np.errstate(divide="ignore", invalid="ignore"):
        actual_wr = np.where(counts > 0, win_sums0 / counts * 100.0, np.nan)

    pn_pos = np.maximum(pnl_vals, 0.0)
    pn_neg = np.minimum(pnl_vals, 0.0)
    gp0 = mm @ pn_pos
    gl0 = np.abs(mm @ pn_neg)
    actual_pf = profit_factor_arrays(gp0, gl0)

    perm_wr = np.full((n_perms, n_combo), np.nan)
    perm_pf = np.full((n_perms, n_combo), np.nan)

    for p in range(n_perms):
        perm = rng.permutation(n_total)
        sw = win_flags[perm].astype(float)
        sp = pnl_vals[perm]
        win_sums = mm @ sw
        with np.errstate(divide="ignore", invalid="ignore"):
            perm_wr[p, :] = np.where(counts > 0, win_sums / counts * 100.0, np.nan)

        sp_pos = np.maximum(sp, 0.0)
        sp_neg = np.minimum(sp, 0.0)
        gp = mm @ sp_pos
        gl = np.abs(mm @ sp_neg)
        perm_pf[p, :] = profit_factor_arrays(gp, gl)

    rows = []
    for c in range(n_combo):
        row = dict(meta[c])
        row["p_value_wr"] = _p_value_two_sided(actual_wr[c], perm_wr[:, c])
        row["p_value_pf"] = _p_value_two_sided(actual_pf[c], perm_pf[:, c])
        rows.append(row)

    summary = pd.DataFrame(rows)
    if summary.empty:
        return summary
    summary = apply_corrections(summary, "p_value_wr")
    summary = apply_corrections(summary, "p_value_pf")
    summary["survives_fdr_010_wr"] = summary["p_value_wr_bh"] < 0.10
    summary["survives_fdr_010_pf"] = summary["p_value_pf_bh"] < 0.10
    summary = summary.sort_values(
        ["survives_fdr_010_wr", "win_rate", "profit_factor", "n"],
        ascending=[False, False, False, False],
    ).reset_index(drop=True)
    return summary


def print_baselines(trades: pd.DataFrame) -> None:
    for label, oc, pc in [
        ("close_band (v2)", "outcome_cb", "pnl_r_cb"),
        ("fixed_1R (v1)", "outcome_f1", "pnl_r_f1"),
        ("scaleout (v3)", "outcome_so_wl", "pnl_r_so"),
    ]:
        t = trades[trades[oc].isin(["win", "loss"])].copy()
        if t.empty:
            print(f"\n--- {label}: no tradeable ---")
            continue
        wins = int((t[oc] == "win").sum())
        losses = int((t[oc] == "loss").sum())
        wr = wins / (wins + losses) * 100.0 if (wins + losses) else np.nan
        pnl = t[pc].to_numpy(float)
        gp = pnl[pnl > 0].sum()
        gl = abs(pnl[pnl < 0].sum())
        pf = profit_factor_scalar(gp, gl)
        print(f"\n--- {label} ---")
        print(f"  Trades: {len(t)}  W: {wins}  L: {losses}  WR: {wr:.2f}%  PF: {pf:.3f}  avgR: {pnl.mean():.3f}")


def main():
    parser = argparse.ArgumentParser(description="Keltner PF optimization study")
    parser.add_argument("--perms", type=int, default=DEFAULT_PERMS, help="Permutations per combo per variant")
    args = parser.parse_args()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("Keltner PF Optimization (stop variants + DOW grid)")
    print("=" * 60)

    candles_30 = load_candles(DATA_30S)
    candles_30 = candles_30.sort_values("timestamp_ny").reset_index(drop=True)
    in_window = (
        (candles_30["timestamp_ny"].dt.time >= TRADING_WINDOW_START)
        & (candles_30["timestamp_ny"].dt.time <= TRADING_WINDOW_END)
    )
    candles_30 = candles_30[in_window].reset_index(drop=True)

    candles_5 = load_candles(DATA_5M)
    candles_5 = candles_5.sort_values("timestamp_ny").reset_index(drop=True)

    print(f"30s bars: {len(candles_30):,}")

    tny = candles_30["timestamp_ny"]
    day_id = (tny.dt.year * 10000 + tny.dt.month * 100 + tny.dt.day).to_numpy(np.int32)

    ddates = candles_30["timestamp_ny"].dt.date
    day_last_idx: dict = {}
    for i in range(len(candles_30) - 1, -1, -1):
        dd = ddates.iloc[i]
        if dd not in day_last_idx:
            day_last_idx[dd] = i

    all_rows: list[dict] = []

    for ema_p, atr_m in product(EMA_PERIODS, ATR_MULTS):
        n0 = len(all_rows)
        k5 = compute_keltner_5m(candles_5, ema_p, atr_m)
        brk_events = build_break_events(k5, ema_p)

        merged = merge_keltner_onto_30s(candles_30, k5)
        merged[["k_ema", "k_upper", "k_lower", "k_band_width"]] = merged[
            ["k_ema", "k_upper", "k_lower", "k_band_width"]
        ].ffill()

        k_ema = merged["k_ema"].to_numpy(float)
        k_upper = merged["k_upper"].to_numpy(float)
        k_lower = merged["k_lower"].to_numpy(float)
        k_bw = merged["k_band_width"].to_numpy(float)

        c30 = merged[["timestamp_ny", "open", "high", "low", "close", "volume"]].copy()

        for tol in PULLBACK_TOLS:
            for break_i, direction in brk_events:
                tr = simulate_three_exits(
                    c30,
                    k_ema,
                    k_upper,
                    k_lower,
                    k_bw,
                    ema_p,
                    atr_m,
                    tol,
                    k5,
                    break_i,
                    direction,
                    day_last_idx,
                    day_id,
                )
                if tr:
                    all_rows.append(tr)

        print(
            f"  EMA={ema_p} ATRx={atr_m}: breaks={len(brk_events):,}, "
            f"rows+={len(all_rows) - n0:,} (total {len(all_rows):,})",
            flush=True,
        )

    trades_df = pd.DataFrame(all_rows)
    if trades_df.empty:
        print("No trades.")
        return

    trades_df = add_context_columns(trades_df)
    trades_df = _normalize_scaleout_outcome(trades_df)
    trades_df = trades_df.sort_values(
        ["entry_time", "ema_period", "atr_mult", "pullback_tol"]
    ).reset_index(drop=True)

    print_baselines(trades_df)

    print(f"\nRunning grids ({args.perms} perms each variant) ...", flush=True)
    sum_cb = run_grid_for_variant(trades_df, "outcome_cb", "pnl_r_cb", "close_band", args.perms)
    sum_f1 = run_grid_for_variant(trades_df, "outcome_f1", "pnl_r_f1", "fixed_1r", args.perms)
    sum_so = run_grid_for_variant(trades_df, "outcome_so_wl", "pnl_r_so", "scaleout", args.perms)

    combined = pd.concat([sum_cb, sum_f1, sum_so], ignore_index=True)

    trades_df.to_csv(RESULTS_DIR / "trades.csv", index=False)
    combined.to_csv(RESULTS_DIR / "summary_by_combo_all_variants.csv", index=False)

    if not sum_cb.empty:
        sum_cb.head(25).to_csv(RESULTS_DIR / "top_combos_close_band.csv", index=False)
    if not sum_f1.empty:
        sum_f1.head(25).to_csv(RESULTS_DIR / "top_combos_fixed_1r.csv", index=False)
    if not sum_so.empty:
        sum_so.head(25).to_csv(RESULTS_DIR / "top_combos_scaleout.csv", index=False)

    # Side-by-side: same combo keys, merge PF/WR for three variants
    key_cols = [
        "ema_period",
        "atr_mult",
        "pullback_tol",
        "macro_scope",
        "vixy_filter",
        "gap_filter",
        "dow_filter",
    ]
    if not sum_cb.empty and not sum_f1.empty:
        cb = sum_cb[key_cols + ["n", "win_rate", "profit_factor", "avg_r"]].rename(
            columns={
                "n": "n_cb",
                "win_rate": "wr_cb",
                "profit_factor": "pf_cb",
                "avg_r": "avg_r_cb",
            }
        )
        f1 = sum_f1[key_cols + ["n", "win_rate", "profit_factor", "avg_r"]].rename(
            columns={
                "n": "n_f1",
                "win_rate": "wr_f1",
                "profit_factor": "pf_f1",
                "avg_r": "avg_r_f1",
            }
        )
        so = sum_so[key_cols + ["n", "win_rate", "profit_factor", "avg_r"]].rename(
            columns={
                "n": "n_so",
                "win_rate": "wr_so",
                "profit_factor": "pf_so",
                "avg_r": "avg_r_so",
            }
        )
        merged = cb.merge(f1, on=key_cols, how="outer").merge(so, on=key_cols, how="outer")
        merged["pf_lift_f1_vs_cb"] = merged["pf_f1"] - merged["pf_cb"]
        merged["wr_delta_f1_vs_cb"] = merged["wr_f1"] - merged["wr_cb"]
        merged = merged.sort_values("pf_f1", ascending=False, na_position="last")
        merged.to_csv(RESULTS_DIR / "comparison_side_by_side.csv", index=False)

    print(f"\nWrote {RESULTS_DIR / 'trades.csv'} ({len(trades_df):,} rows)")
    print(f"Wrote {RESULTS_DIR / 'summary_by_combo_all_variants.csv'} ({len(combined):,} rows)")
    if (RESULTS_DIR / "comparison_side_by_side.csv").exists():
        print(f"Wrote {RESULTS_DIR / 'comparison_side_by_side.csv'}")
    print("\nDone.")


if __name__ == "__main__":
    main()
