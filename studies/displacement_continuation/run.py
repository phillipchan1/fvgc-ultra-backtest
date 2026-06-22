#!/usr/bin/env python3
"""
Displacement continuation backtest on 30s candles.

Implements:
- Displacement candle detection via body multiple of rolling 20-body average.
- Pullback-to-50% continuation entry with configurable maximum retrace depth.
- Stop beyond opposite body end (+2 pts), with 1R/2R/3R tracking.
- Context permutation grid with BH FDR correction.

Run from repo root:
  python studies/displacement_continuation/run.py
"""

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

DATA_PATH = ROOT / "data" / "consolidated" / "nq-front-month.ohlcv-30s.csv"
TRADING_DAYS_PATH = ROOT / "data" / "trading_days" / "trading_days.csv"
STUDY_DIR = Path(__file__).resolve().parent
RESULTS_DIR = STUDY_DIR / "results"

DISPLACEMENT_THRESHOLDS = [2.0, 2.5, 3.0]
RETRACE_MODES = {
    "50_only": 0.50,
    "allow_61_8": 0.618,
    "allow_75": 0.75,
}
MACRO_SCOPES = ["w1", "w1_w2", "all"]
VIXY_FILTERS = ["all", "low", "medium", "high"]
YN_FILTERS = ["all", "yes", "no"]
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


def displacement_rows(candles: pd.DataFrame, threshold: float) -> pd.DataFrame:
    df = candles.copy()
    df["body"] = (df["close"] - df["open"]).abs()
    # Use prior 20 candles only (shift) to avoid lookahead.
    df["body_avg20"] = df["body"].rolling(20, min_periods=20).mean().shift(1)
    df["is_disp"] = (df["body_avg20"] > 0) & (df["body"] > threshold * df["body_avg20"])

    up = df["close"] > df["open"]
    down = df["close"] < df["open"]
    df["direction"] = np.where(up, "long", np.where(down, "short", ""))

    out = df[df["is_disp"] & (df["direction"] != "")].copy()
    out["disp_idx"] = out.index
    out["date"] = out["timestamp_ny"].dt.date
    return out[
        [
            "disp_idx",
            "timestamp_ny",
            "date",
            "open",
            "high",
            "low",
            "close",
            "direction",
            "body",
            "body_avg20",
        ]
    ]


def retrace_limit_price(body_low: float, body_high: float, direction: str, max_retrace: float) -> float:
    body_range = body_high - body_low
    if direction == "long":
        # Retrace from high back down.
        return body_high - (max_retrace * body_range)
    # Retrace from low back up.
    return body_low + (max_retrace * body_range)


def simulate_displacement_entries(
    candles: pd.DataFrame,
    threshold: float,
    retrace_mode: str,
    touch_tolerance: float = 2.0,
    stop_buffer: float = 2.0,
) -> list[dict]:
    disp = displacement_rows(candles, threshold)
    max_retrace = RETRACE_MODES[retrace_mode]
    trades: list[dict] = []

    for _, row in disp.iterrows():
        i = int(row["disp_idx"])
        direction = row["direction"]
        date = row["date"]

        body_low = min(float(row["open"]), float(row["close"]))
        body_high = max(float(row["open"]), float(row["close"]))
        body_mid = (body_low + body_high) / 2.0
        limit_price = retrace_limit_price(body_low, body_high, direction, max_retrace)

        touch_idx = None
        invalidated = False

        for j in range(i + 1, len(candles)):
            bar = candles.iloc[j]
            if bar["timestamp_ny"].date() != date:
                break

            low_j = float(bar["low"])
            high_j = float(bar["high"])

            if direction == "long":
                if low_j < (limit_price - touch_tolerance):
                    invalidated = True
                    break
                touched = (low_j <= body_mid + touch_tolerance) and (high_j >= body_mid - touch_tolerance)
            else:
                if high_j > (limit_price + touch_tolerance):
                    invalidated = True
                    break
                touched = (high_j >= body_mid - touch_tolerance) and (low_j <= body_mid + touch_tolerance)

            if touched:
                touch_idx = j
                break

        if invalidated or touch_idx is None:
            continue
        if touch_idx + 1 >= len(candles):
            continue
        entry_bar = candles.iloc[touch_idx + 1]
        if entry_bar["timestamp_ny"].date() != date:
            continue

        entry_price = float(entry_bar["close"])
        if direction == "long":
            sl = body_low - stop_buffer
            sl_dist = entry_price - sl
        else:
            sl = body_high + stop_buffer
            sl_dist = sl - entry_price
        if sl_dist <= 0:
            continue

        tp1 = entry_price + sl_dist if direction == "long" else entry_price - sl_dist
        tp2 = entry_price + (2.0 * sl_dist) if direction == "long" else entry_price - (2.0 * sl_dist)
        tp3 = entry_price + (3.0 * sl_dist) if direction == "long" else entry_price - (3.0 * sl_dist)

        outcome = "open"
        exit_price = np.nan
        exit_time = pd.NaT

        max_fav = 0.0
        max_adv = 0.0
        hit_1r = False
        hit_2r = False
        hit_3r = False
        bars_to_1r = np.nan
        bars_to_2r = np.nan
        bars_to_3r = np.nan

        for k in range(touch_idx + 2, len(candles)):
            bar = candles.iloc[k]
            if bar["timestamp_ny"].date() != date:
                if outcome == "open":
                    prev = candles.iloc[k - 1]
                    exit_price = float(prev["close"])
                    exit_time = prev["timestamp_ny"]
                    outcome = "eod"
                break

            bars_held = k - (touch_idx + 1)
            low_k = float(bar["low"])
            high_k = float(bar["high"])

            if direction == "long":
                fav = high_k - entry_price
                adv = entry_price - low_k
                stop_hit = low_k <= sl
                t1_hit = high_k >= tp1
                t2_hit = high_k >= tp2
                t3_hit = high_k >= tp3
            else:
                fav = entry_price - low_k
                adv = high_k - entry_price
                stop_hit = high_k >= sl
                t1_hit = low_k <= tp1
                t2_hit = low_k <= tp2
                t3_hit = low_k <= tp3

            max_fav = max(max_fav, fav)
            max_adv = max(max_adv, adv)

            if t1_hit and not hit_1r:
                hit_1r = True
                bars_to_1r = bars_held
            if t2_hit and not hit_2r:
                hit_2r = True
                bars_to_2r = bars_held
            if t3_hit and not hit_3r:
                hit_3r = True
                bars_to_3r = bars_held

            if outcome == "open":
                if stop_hit and t1_hit:
                    outcome = "ambiguous"
                    exit_price = sl
                    exit_time = bar["timestamp_ny"]
                    break
                if stop_hit:
                    outcome = "loss"
                    exit_price = sl
                    exit_time = bar["timestamp_ny"]
                    break
                if t1_hit:
                    outcome = "win"
                    exit_price = tp1
                    exit_time = bar["timestamp_ny"]
                    # Continue to track MFE through rest of session.

        if outcome == "open":
            last_bar = candles[candles["timestamp_ny"].dt.date == date].iloc[-1]
            outcome = "eod"
            exit_price = float(last_bar["close"])
            exit_time = last_bar["timestamp_ny"]

        pnl_pts = (exit_price - entry_price) if direction == "long" else (entry_price - exit_price)
        pnl_r = pnl_pts / sl_dist if sl_dist > 0 else np.nan

        trades.append(
            {
                "threshold": threshold,
                "retrace_mode": retrace_mode,
                "date": date,
                "displacement_time": row["timestamp_ny"],
                "touch_time": candles.iloc[touch_idx]["timestamp_ny"],
                "entry_time": entry_bar["timestamp_ny"],
                "direction": direction,
                "disp_open": float(row["open"]),
                "disp_close": float(row["close"]),
                "disp_high": float(row["high"]),
                "disp_low": float(row["low"]),
                "disp_body": float(row["body"]),
                "disp_body_avg20": float(row["body_avg20"]),
                "body_mid_50": body_mid,
                "retrace_limit_price": limit_price,
                "entry_price": entry_price,
                "sl": sl,
                "sl_dist": sl_dist,
                "tp_1r": tp1,
                "tp_2r": tp2,
                "tp_3r": tp3,
                "outcome": outcome,
                "exit_time": exit_time,
                "exit_price": exit_price,
                "pnl_pts": pnl_pts,
                "pnl_r": pnl_r,
                "mfe_pts": max_fav,
                "mae_pts": max_adv,
                "mfe_r": (max_fav / sl_dist) if sl_dist > 0 else np.nan,
                "mae_r": (max_adv / sl_dist) if sl_dist > 0 else np.nan,
                "hit_1R": hit_1r,
                "hit_2R": hit_2r,
                "hit_3R": hit_3r,
                "bars_to_1R": bars_to_1r,
                "bars_to_2R": bars_to_2r,
                "bars_to_3R": bars_to_3r,
            }
        )

    return trades


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


def run_combo_permutation(
    combo_mask: np.ndarray,
    win_flags: np.ndarray,
    pnl_vals: np.ndarray,
    n_perms: int,
    rng: np.random.Generator,
) -> tuple[float, float]:
    n_total = len(win_flags)
    if n_total == 0:
        return np.nan, np.nan

    actual_wr = float(win_flags[combo_mask].mean() * 100.0)
    sub_pnl = pnl_vals[combo_mask]
    gp = sub_pnl[sub_pnl > 0].sum()
    gl = abs(sub_pnl[sub_pnl < 0].sum())
    actual_pf = float(gp / gl) if gl > 0 else (np.inf if gp > 0 else np.nan)

    perm_wr = np.empty(n_perms)
    perm_pf = np.empty(n_perms)
    for i in range(n_perms):
        perm = rng.permutation(n_total)
        s_wins = win_flags[perm][combo_mask]
        s_pnl = pnl_vals[perm][combo_mask]
        perm_wr[i] = s_wins.mean() * 100.0
        s_gp = s_pnl[s_pnl > 0].sum()
        s_gl = abs(s_pnl[s_pnl < 0].sum())
        perm_pf[i] = s_gp / s_gl if s_gl > 0 else (np.inf if s_gp > 0 else np.nan)

    perm_wr_mean = np.nanmean(perm_wr)
    p_wr = np.nanmean(perm_wr >= actual_wr) if actual_wr >= perm_wr_mean else np.nanmean(perm_wr <= actual_wr)

    finite_pf = perm_pf[np.isfinite(perm_pf)]
    if len(finite_pf) and np.isfinite(actual_pf):
        pf_mean = np.nanmean(finite_pf)
        p_pf = np.nanmean(finite_pf >= actual_pf) if actual_pf >= pf_mean else np.nanmean(finite_pf <= actual_pf)
    else:
        p_pf = np.nan

    return float(p_wr), float(p_pf)


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
    pf = gp / gl if gl > 0 else (np.inf if gp > 0 else np.nan)
    return {
        "n": n,
        "wins": wins,
        "losses": losses,
        "win_rate": wr,
        "profit_factor": pf,
        "avg_r": float(np.nanmean(pnl_r)),
    }


def add_context_columns(trades: pd.DataFrame) -> pd.DataFrame:
    td = pd.read_csv(TRADING_DAYS_PATH)
    td["date"] = pd.to_datetime(td["date"]).dt.date
    keep = ["date", "vixy_regime", "gap_from_prior_close", "candle_930_direction"]
    trades = trades.merge(td[keep], on="date", how="left")

    trades["entry_time_only"] = trades["entry_time"].dt.time
    trades["macro_window"] = trades["entry_time_only"].apply(get_macro_window)
    trades["vixy_bucket"] = trades["vixy_regime"].apply(map_vixy_regime)

    trades["gap_aligned"] = np.where(
        trades["direction"] == "long",
        trades["gap_from_prior_close"] > 0,
        trades["gap_from_prior_close"] < 0,
    )
    trades["c930_aligned"] = np.where(
        trades["direction"] == "long",
        trades["candle_930_direction"].str.lower() == "bullish",
        trades["candle_930_direction"].str.lower() == "bearish",
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


def yn_mask(series: pd.Series, flag: str) -> pd.Series:
    if flag == "all":
        return pd.Series(True, index=series.index)
    if flag == "yes":
        return series == True
    return series == False


def run_grid(trades: pd.DataFrame, n_perms: int) -> pd.DataFrame:
    base = trades[trades["outcome"].isin(["win", "loss"])].copy()
    rows = []
    rng = np.random.default_rng(RNG_SEED)
    win_flags = (base["outcome"] == "win").to_numpy(dtype=bool)
    pnl_vals = base["pnl_r"].to_numpy(dtype=float)

    for th, rm, ms, vb, ga, c9 in product(
        DISPLACEMENT_THRESHOLDS,
        RETRACE_MODES.keys(),
        MACRO_SCOPES,
        VIXY_FILTERS,
        YN_FILTERS,
        YN_FILTERS,
    ):
        mask = (
            (base["threshold"] == th)
            & (base["retrace_mode"] == rm)
            & macro_scope_mask(base, ms)
            & vixy_mask(base, vb)
            & yn_mask(base["gap_aligned"], ga)
            & yn_mask(base["c930_aligned"], c9)
        )
        stats = summarize_combo(base, mask)
        if stats is None:
            continue

        p_wr, p_pf = run_combo_permutation(mask.to_numpy(dtype=bool), win_flags, pnl_vals, n_perms, rng)
        rows.append(
            {
                "threshold": th,
                "retrace_mode": rm,
                "macro_scope": ms,
                "vixy_filter": vb,
                "gap_aligned_filter": ga,
                "c930_aligned_filter": c9,
                **stats,
                "p_value_wr": p_wr,
                "p_value_pf": p_pf,
            }
        )

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


def print_baseline(trades: pd.DataFrame) -> tuple[float, float, int]:
    t = trades[trades["outcome"].isin(["win", "loss"])].copy()
    n = len(t)
    wins = int((t["outcome"] == "win").sum())
    losses = int((t["outcome"] == "loss").sum())
    wr = wins / (wins + losses) * 100.0 if (wins + losses) else np.nan
    pnl_r = t["pnl_r"].to_numpy(dtype=float)
    gp = pnl_r[pnl_r > 0].sum()
    gl = abs(pnl_r[pnl_r < 0].sum())
    pf = gp / gl if gl > 0 else (np.inf if gp > 0 else np.nan)
    print("\n--- Displacement model baseline (all thresholds + retrace modes) ---")
    print(f"Trades: {n}  Wins: {wins}  Losses: {losses}  WR: {wr:.2f}%  PF: {pf:.3f}")
    return wr, pf, n


def main():
    parser = argparse.ArgumentParser(description="Displacement continuation backtest")
    parser.add_argument("--perms", type=int, default=DEFAULT_PERMS, help="Permutation count per combo")
    args = parser.parse_args()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    print("=" * 60)
    print("Displacement Continuation Backtest")
    print("=" * 60)

    candles = load_candles(DATA_PATH)
    candles = candles.sort_values("timestamp_ny").reset_index(drop=True)
    # Keep analysis in the active model session to bound compute and
    # match the project's standard trade window semantics.
    in_window = (
        (candles["timestamp_ny"].dt.time >= TRADING_WINDOW_START)
        & (candles["timestamp_ny"].dt.time <= TRADING_WINDOW_END)
    )
    candles = candles[in_window].reset_index(drop=True)
    tmin = candles["timestamp_ny"].min()
    tmax = candles["timestamp_ny"].max()
    print(f"Data range (NY): {tmin} -> {tmax}")
    print(f"Bars: {len(candles):,}")

    all_trades = []
    for threshold, retrace_mode in product(DISPLACEMENT_THRESHOLDS, RETRACE_MODES.keys()):
        trades = simulate_displacement_entries(candles, threshold=threshold, retrace_mode=retrace_mode)
        print(f"Generated {len(trades):,} trades | threshold={threshold} retrace={retrace_mode}")
        all_trades.extend(trades)

    trades_df = pd.DataFrame(all_trades)
    if trades_df.empty:
        print("No trades generated.")
        return

    trades_df = add_context_columns(trades_df)
    trades_df = trades_df.sort_values(["entry_time", "threshold", "retrace_mode"]).reset_index(drop=True)

    wr, pf, n = print_baseline(trades_df)
    _ = wr, pf, n

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
