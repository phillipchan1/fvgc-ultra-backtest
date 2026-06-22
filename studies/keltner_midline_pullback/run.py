#!/usr/bin/env python3
"""
Keltner Channel midline pullback continuation (5m regime, 30s execution).

Compute Keltner on 5m; on band-break, wait for 30s pullback to EMA mid within
tolerance, then enter on first bullish/bearish 30s close. Stop: 30s close
through the opposite band. R = distance from entry to opposite band at entry.

Run from repo root:
  python studies/keltner_midline_pullback/run.py --perms 300
"""

from __future__ import annotations

import argparse
import sys
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from fvgc.data import load_candles
from fvgc.constants import TRADING_WINDOW_START, TRADING_WINDOW_END

DATA_30S = ROOT / "data" / "consolidated" / "nq-front-month.ohlcv-30s.csv"
DATA_5M = ROOT / "data" / "consolidated" / "nq-front-month.ohlcv-5m.csv"
TRADING_DAYS_PATH = ROOT / "data" / "trading_days" / "trading_days.csv"
STUDY_DIR = Path(__file__).resolve().parent
RESULTS_DIR = STUDY_DIR / "results"

EMA_PERIODS = [10, 20, 30]
ATR_MULTS = [1.0, 1.5, 2.0]
PULLBACK_TOLS = [2.0, 3.0, 5.0]

MACRO_SCOPES = ["w1", "w1_w2", "all"]
VIXY_FILTERS = ["all", "low", "medium", "high"]
GAP_FILTERS = ["not_required", "required"]

MIN_N = 30
DEFAULT_PERMS = 300
RNG_SEED = 42


def get_macro_window(entry_time) -> int:
    mins = (entry_time.hour - 9) * 60 + (entry_time.minute - 30) + (entry_time.second / 60.0)
    if mins < 0:
        return -1
    if mins < 15:
        return 1
    if mins < 30:
        return 2
    if mins < 45:
        return 3
    if mins < 60:
        return 4
    return 5


def map_vixy_regime(v: str) -> str:
    if not isinstance(v, str):
        return "unknown"
    vv = v.strip().lower()
    if vv == "low":
        return "low"
    if vv in {"normal", "medium"}:
        return "medium"
    if vv in {"elevated", "high"}:
        return "high"
    return "unknown"


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr


def compute_keltner_5m(candles_5m: pd.DataFrame, period: int, mult: float) -> pd.DataFrame:
    df = candles_5m.sort_values("timestamp_ny").reset_index(drop=True)
    df["tr"] = true_range(df)
    df["atr"] = df["tr"].rolling(period, min_periods=period).mean()
    df["ema"] = df["close"].ewm(span=period, adjust=False).mean()
    df["upper"] = df["ema"] + mult * df["atr"]
    df["lower"] = df["ema"] - mult * df["atr"]
    df["band_width"] = df["upper"] - df["lower"]
    df["bar_end"] = df["timestamp_ny"] + pd.Timedelta(minutes=5)
    return df


def merge_keltner_onto_30s(candles_30s: pd.DataFrame, k5: pd.DataFrame) -> pd.DataFrame:
    left = candles_30s.sort_values("timestamp_ny").reset_index(drop=True)
    right = k5[["bar_end", "ema", "upper", "lower", "band_width"]].sort_values("bar_end")
    out = pd.merge_asof(
        left,
        right,
        left_on="timestamp_ny",
        right_on="bar_end",
        direction="backward",
    )
    out = out.rename(
        columns={
            "ema": "k_ema",
            "upper": "k_upper",
            "lower": "k_lower",
            "band_width": "k_band_width",
        }
    )
    return out


def break_in_session(k5: pd.DataFrame, i: int) -> bool:
    ts = k5.loc[i, "timestamp_ny"]
    be = k5.loc[i, "bar_end"]
    return bool(
        (ts.time() >= TRADING_WINDOW_START)
        and (be.time() <= TRADING_WINDOW_END)
    )


def build_break_events(k5: pd.DataFrame, min_i: int) -> list[tuple[int, str]]:
    events = []
    for i in range(min_i, len(k5)):
        if not break_in_session(k5, i):
            continue
        c = float(k5.loc[i, "close"])
        u = float(k5.loc[i, "upper"])
        l = float(k5.loc[i, "lower"])
        if np.isnan(u) or np.isnan(l):
            continue
        if c > u:
            events.append((i, "long"))
        elif c < l:
            events.append((i, "short"))
    return events


def simulate_keltner_trade(
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
    """Simulate one break -> pullback -> entry path on pre-merged 30s series."""
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
        opp_band = lower_e
    else:
        sl_dist = upper_e - entry_price
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

    max_fav = 0.0
    max_adv = 0.0
    hit_1r = hit_2r = hit_3r = False
    b1 = b2 = b3 = np.nan
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
        bh = k - entry_j

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
            b1 = bh
        if t2h and not hit_2r:
            hit_2r = True
            b2 = bh
        if t3h and not hit_3r:
            hit_3r = True
            b3 = bh

        if outcome != "open":
            continue

        if stop_close and t1h:
            outcome = "ambiguous"
            exit_price = float(closes[k])
            exit_time = candles_30["timestamp_ny"].iat[k]
            full_stop_close = True
            break

        if stop_close:
            outcome = "loss"
            exit_price = float(closes[k])
            exit_time = candles_30["timestamp_ny"].iat[k]
            full_stop_close = True
            break

        if t1h:
            outcome = "win"
            exit_price = tp1
            exit_time = candles_30["timestamp_ny"].iat[k]
            break

    if outcome == "open":
        li = day_last_idx.get(date)
        if li is None:
            return None
        last = candles_30.iloc[li]
        outcome = "eod"
        exit_price = float(last["close"])
        exit_time = last["timestamp_ny"]

    pnl_pts = (exit_price - entry_price) if direction == "long" else (entry_price - exit_price)
    pnl_r = pnl_pts / sl_dist if sl_dist > 0 else np.nan

    return {
        "ema_period": ema_p,
        "atr_mult": atr_m,
        "pullback_tol": tol,
        "date": date,
        "break_time_5m": k5.loc[break_idx, "timestamp_ny"],
        "break_bar_end": break_bar_end,
        "direction": direction,
        "band_width_at_break": float(k5.loc[break_idx, "band_width"]),
        "dist_outside_band_pts": float(break_dist),
        "pullback_depth_to_ema": float(td),
        "midline_touch_time": candles_30.iloc[touch_j]["timestamp_ny"],
        "entry_time": candles_30.iloc[entry_j]["timestamp_ny"],
        "entry_price": entry_price,
        "k_upper_at_entry": upper_e,
        "k_lower_at_entry": lower_e,
        "k_ema_at_entry": float(k_ema[entry_j]),
        "k_band_width_at_entry": bw_e,
        "opposite_band_at_entry": float(opp_band),
        "sl_dist": sl_dist,
        "tp_1r": tp1,
        "tp_2r": tp2,
        "tp_3r": tp3,
        "outcome": outcome,
        "exit_time": exit_time,
        "exit_price": float(exit_price),
        "pnl_pts": float(pnl_pts),
        "pnl_r": float(pnl_r),
        "mfe_pts": float(max_fav),
        "mae_pts": float(max_adv),
        "mfe_r": float(max_fav / sl_dist) if sl_dist > 0 else np.nan,
        "mae_r": float(max_adv / sl_dist) if sl_dist > 0 else np.nan,
        "hit_1R_mfe": hit_1r,
        "hit_2R_mfe": hit_2r,
        "hit_3R_mfe": hit_3r,
        "bars_to_1R": b1,
        "bars_to_2R": b2,
        "bars_to_3R": b3,
        "full_stop_close_through_band": full_stop_close,
    }


def add_context_columns(trades: pd.DataFrame) -> pd.DataFrame:
    td = pd.read_csv(TRADING_DAYS_PATH)
    td["date"] = pd.to_datetime(td["date"]).dt.date
    keep = [
        "date",
        "vixy_regime",
        "gap_from_prior_close",
        "candle_930_direction",
        "overnight_direction",
        "day_of_week_name",
    ]
    trades = trades.merge(td[keep], on="date", how="left")

    et = pd.to_datetime(trades["entry_time"])
    trades["entry_time"] = et
    trades["entry_time_only"] = et.dt.time
    trades["macro_window"] = trades["entry_time"].apply(get_macro_window)
    trades["vixy_bucket"] = trades["vixy_regime"].apply(map_vixy_regime)

    trades["gap_aligned"] = np.where(
        trades["direction"] == "long",
        trades["gap_from_prior_close"] > 0,
        trades["gap_from_prior_close"] < 0,
    )

    od = trades["overnight_direction"].astype(str).str.lower()
    trades["overnight_aligned"] = np.where(
        trades["direction"] == "long",
        od.isin(["up"]),
        np.where(trades["direction"] == "short", od.isin(["down"]), False),
    )
    return trades


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
    """Elementwise PF with inf when gl==0 and gp>0, nan otherwise."""
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


def summarize_combo(df: pd.DataFrame, mask: pd.Series) -> dict | None:
    sub = df[mask]
    n = len(sub)
    if n < MIN_N:
        return None
    wins = int((sub["outcome"] == "win").sum())
    losses = int((sub["outcome"] == "loss").sum())
    if (wins + losses) == 0:
        return None
    wr = wins / (wins + losses) * 100.0
    pnl_r = sub["pnl_r"].to_numpy(dtype=float)
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


def run_grid(trades: pd.DataFrame, n_perms: int) -> pd.DataFrame:
    """Batched permutation tests: one shuffle per iteration for all combos."""
    base = trades[trades["outcome"].isin(["win", "loss"])].copy()
    if base.empty:
        return pd.DataFrame()

    rng = np.random.default_rng(RNG_SEED)
    win_flags = (base["outcome"] == "win").to_numpy(dtype=bool)
    pnl_vals = base["pnl_r"].to_numpy(dtype=float)
    n_total = len(base)

    meta: list[dict] = []
    masks: list[np.ndarray] = []

    for ep, am, ptol, ms, vb, gf in product(
        EMA_PERIODS,
        ATR_MULTS,
        PULLBACK_TOLS,
        MACRO_SCOPES,
        VIXY_FILTERS,
        GAP_FILTERS,
    ):
        mask = (
            (base["ema_period"] == ep)
            & (base["atr_mult"] == am)
            & (base["pullback_tol"] == ptol)
            & macro_scope_mask(base, ms)
            & vixy_mask(base, vb)
            & gap_filter_mask(base, gf)
        ).to_numpy(dtype=bool)
        stats = summarize_combo(base, pd.Series(mask, index=base.index))
        if stats is None:
            continue
        meta.append(
            {
                "ema_period": ep,
                "atr_mult": am,
                "pullback_tol": ptol,
                "macro_scope": ms,
                "vixy_filter": vb,
                "gap_filter": gf,
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


def print_baseline(trades: pd.DataFrame) -> None:
    t = trades[trades["outcome"].isin(["win", "loss"])].copy()
    n = len(t)
    if n == 0:
        print("No win/loss trades for baseline.")
        return
    wins = int((t["outcome"] == "win").sum())
    losses = int((t["outcome"] == "loss").sum())
    wr = wins / (wins + losses) * 100.0 if (wins + losses) else np.nan
    pnl_r = t["pnl_r"].to_numpy(dtype=float)
    gp = pnl_r[pnl_r > 0].sum()
    gl = abs(pnl_r[pnl_r < 0].sum())
    pf = profit_factor_scalar(gp, gl)
    print("\n--- Keltner model baseline (all EMA x mult x tol) ---")
    print(f"Trades: {n}  Wins: {wins}  Losses: {losses}  WR: {wr:.2f}%  PF: {pf:.3f}")


def main():
    parser = argparse.ArgumentParser(description="Keltner midline pullback backtest")
    parser.add_argument("--perms", type=int, default=DEFAULT_PERMS, help="Permutation count per combo")
    args = parser.parse_args()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("Keltner Midline Pullback Continuation")
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

    tmin = candles_30["timestamp_ny"].min()
    tmax = candles_30["timestamp_ny"].max()
    print(f"Data range (NY, session slice): {tmin} -> {tmax}")
    print(f"30s bars: {len(candles_30):,}")

    tny = candles_30["timestamp_ny"]
    day_id = (tny.dt.year * 10000 + tny.dt.month * 100 + tny.dt.day).to_numpy(np.int32)

    ddates = candles_30["timestamp_ny"].dt.date
    day_last_idx: dict = {}
    for i in range(len(candles_30) - 1, -1, -1):
        dd = ddates.iloc[i]
        if dd not in day_last_idx:
            day_last_idx[dd] = i

    all_trades: list[dict] = []

    for ema_p, atr_m in product(EMA_PERIODS, ATR_MULTS):
        n0 = len(all_trades)
        k5 = compute_keltner_5m(candles_5, ema_p, atr_m)
        min_i = ema_p
        brk_events = build_break_events(k5, min_i)

        merged = merge_keltner_onto_30s(candles_30, k5)
        merged["k_ema"] = merged["k_ema"].ffill()
        merged["k_upper"] = merged["k_upper"].ffill()
        merged["k_lower"] = merged["k_lower"].ffill()
        merged["k_band_width"] = merged["k_band_width"].ffill()

        k_ema = merged["k_ema"].to_numpy(float)
        k_upper = merged["k_upper"].to_numpy(float)
        k_lower = merged["k_lower"].to_numpy(float)
        k_bw = merged["k_band_width"].to_numpy(float)

        c30 = merged[
            ["timestamp_ny", "open", "high", "low", "close", "volume"]
        ].copy()

        for tol in PULLBACK_TOLS:
            for break_i, direction in brk_events:
                tr = simulate_keltner_trade(
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
                    all_trades.append(tr)

        print(
            f"  EMA={ema_p} ATRx={atr_m}: breaks={len(brk_events):,}, "
            f"trades_added={len(all_trades) - n0:,} (total {len(all_trades):,})",
            flush=True,
        )

    trades_df = pd.DataFrame(all_trades)
    if trades_df.empty:
        print("No trades generated.")
        return

    trades_df = add_context_columns(trades_df)
    trades_df = trades_df.sort_values(
        ["entry_time", "ema_period", "atr_mult", "pullback_tol"]
    ).reset_index(drop=True)

    print_baseline(trades_df)

    print(f"\nRunning permutation grid ({args.perms} perms) ...", flush=True)
    summary = run_grid(trades_df, n_perms=args.perms)

    out_trades = RESULTS_DIR / "trades.csv"
    out_summary = RESULTS_DIR / "summary_by_combo.csv"
    out_top = RESULTS_DIR / "top_combos.csv"

    trades_df.to_csv(out_trades, index=False)
    print(f"\nWrote {out_trades.relative_to(ROOT)} ({len(trades_df):,} rows)")

    if summary.empty:
        print("No qualifying combos (n >= 30).")
        return

    summary.to_csv(out_summary, index=False)
    top = summary.head(25).copy()
    top.to_csv(out_top, index=False)
    n_fdr = int(summary["survives_fdr_010_wr"].sum())
    print(f"Wrote {out_summary.relative_to(ROOT)} ({len(summary):,} rows)")
    print(f"Wrote {out_top.relative_to(ROOT)} ({len(top):,} rows)")
    print(f"Combos surviving BH FDR q=0.10 (WR): {n_fdr}")
    print("\nDone.")


if __name__ == "__main__":
    main()
