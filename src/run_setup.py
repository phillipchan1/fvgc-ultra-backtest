#!/usr/bin/env python3
"""
Run backtest for a specific setup (scenario) and output all trades.

Sources for setups:
- analysis_out/top_setups.csv (pick by row index or run_id)
- Direct JSON overrides via --overrides

Examples:
  python run_setup.py \
    --top-csv analysis_out/top_setups.csv \
    --index 0 \
    --out trades_selected.csv

  python run_setup.py \
    --top-csv analysis_out/top_setups.csv \
    --run-id 414 \
    --out analysis_out/trades_run414.csv

  python run_setup.py \
    --overrides '{"points_tp":20,"points_sl":20,"entry_touch_type":"close_inside_only","allowed_time_buckets":["1000-1015"]}'
"""

import argparse
import ast
import json
from copy import deepcopy
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from config import CONFIG as BASE_CONFIG
from data_loader import load_db_1s_csv, resample_to_30s
from backtest_engine import run_backtest, calculate_metrics


# Scenario keys we know how to apply to CONFIG (mirrors sweep.py)
SCENARIO_KEYS: List[str] = [
    "points_tp", "points_sl",
    "entry_touch_type", "allowed_time_buckets",
    "min_gap_taps", "max_gap_taps",
    "penetrated_midline", "first_five_only",
    "gap_size_min_pts", "gap_size_max_pts",
    "min_bars_to_prev_break", "max_bars_to_prev_break",
    "require_pullback_from_outside", "require_directional_close", "require_prev_close_break",
    "ifvg_internal_criterion", "ifvg_overlap_min_ratio", "ifvg_allow_opposite_internal",
    "ifvg_same_bar", "ifvg_lookback_bars", "ifvg_break_metric", "ifvg_allow_equal",
    "bos_require_close_through", "bos_allow_equal",
    "skip_conflicting_fvgs", "ifvg_ignore_internal_conflict",
]


def _parse_cell(v: Any) -> Any:
    """Convert CSV cell to appropriate Python type.

    - Empty/NaN -> None
    - List-like strings -> Python list
    - Numeric strings -> float/int where possible (done later)
    """
    if v is None:
        return None
    if isinstance(v, float) and (np.isnan(v) or np.isinf(v)):
        return None
    if isinstance(v, str):
        s = v.strip()
        if s == "" or s.lower() in ("none", "nan", "null"):
            return None
        # Try list/dict literal first
        if (s.startswith("[") and s.endswith("]")) or (s.startswith("{") and s.endswith("}")):
            try:
                return ast.literal_eval(s)
            except Exception:
                pass
        return s
    return v


def _coerce_types(ov: Dict[str, Any]) -> Dict[str, Any]:
    """Coerce overrides to expected types for CONFIG."""
    out: Dict[str, Any] = {}
    bool_keys = {
        "require_pullback_from_outside", "require_directional_close", "require_prev_close_break",
        "ifvg_allow_opposite_internal", "ifvg_same_bar", "ifvg_allow_equal",
        "bos_require_close_through", "bos_allow_equal",
        "skip_conflicting_fvgs", "ifvg_ignore_internal_conflict",
        "penetrated_midline", "first_five_only",
    }
    float_int_keys = {
        "points_tp", "points_sl", "ifvg_overlap_min_ratio", "ifvg_lookback_bars",
        "min_gap_taps", "max_gap_taps",
        "min_bars_to_prev_break", "max_bars_to_prev_break",
        "gap_size_min_pts", "gap_size_max_pts",
    }
    str_keys = {
        "ifvg_internal_criterion", "ifvg_break_metric", "entry_touch_type",
    }
    list_keys = {"allowed_time_buckets"}

    for k, v in ov.items():
        if k in bool_keys:
            if v is None:
                out[k] = None
            elif isinstance(v, bool):
                out[k] = v
            else:
                sv = str(v).strip().lower()
                out[k] = (sv in ("1", "true", "t", "yes", "y"))
        elif k in float_int_keys:
            if v is None:
                out[k] = None
            else:
                try:
                    fv = float(v)
                    # prefer int if integral
                    out[k] = int(fv) if abs(fv - int(fv)) < 1e-9 else fv
                except Exception:
                    out[k] = None
        elif k in str_keys:
            out[k] = None if v is None else str(v)
        elif k in list_keys:
            if v is None:
                out[k] = None
            elif isinstance(v, list):
                out[k] = [str(x) for x in v]
            elif isinstance(v, str):
                # Single bucket like "1000-1015" -> ["1000-1015"]
                out[k] = [v]
            else:
                out[k] = None
        else:
            # passthrough for unknown keys
            out[k] = v
    return out


def _select_overrides_from_csv(path: str, index: Optional[int], run_id: Optional[int]) -> Dict[str, Any]:
    df = pd.read_csv(path)
    if run_id is not None and "run_id" in df.columns:
        try:
            df_match = df[pd.to_numeric(df["run_id"], errors="coerce") == float(run_id)]
            if not df_match.empty:
                row = df_match.iloc[0]
            else:
                raise ValueError(f"run_id {run_id} not found in {path}")
        except Exception:
            raise
    else:
        idx = int(index or 0)
        if idx < 0 or idx >= len(df):
            raise ValueError(f"Row index {idx} out of range (0..{len(df)-1})")
        row = df.iloc[idx]

    ov_raw: Dict[str, Any] = {}
    for k in SCENARIO_KEYS:
        if k in row.index:
            ov_raw[k] = _parse_cell(row[k])
    # Normalize
    ov = _coerce_types(ov_raw)
    return ov


def apply_and_run(overrides: Dict[str, Any], out_csv: str) -> None:
    # Build runtime config
    cfg = deepcopy(BASE_CONFIG)
    for k in SCENARIO_KEYS:
        if k in overrides:
            cfg[k] = overrides[k]

    # Run with temporary CONFIG override
    from config import CONFIG as LIVE
    backup = dict(LIVE)
    try:
        LIVE.clear(); LIVE.update(cfg)
        df1s = load_db_1s_csv(LIVE["data_path"])  # type: ignore[index]
        df30 = resample_to_30s(df1s)
        trades = run_backtest(df30)
        metrics = calculate_metrics(trades)

        # Print summary
        total = metrics["TOTAL"]
        print("\n=== Selected Setup Backtest ===")
        print(
            f"trades={total['trades']:d}  win_rate={total['win_rate']:.2%}  "
            f"gross+=${total['gross_profit']:,.2f}  gross-=${total['gross_loss']:,.2f}  "
            f"net=${total['net']:,.2f}  PF={total['profit_factor']:.2f}"
        )
        for model in ["fvg_ifvg", "fvg_bos", "fvg_no_fvg"]:
            m = metrics[model]
            print(f"{model:12s} trades={m['trades']:4d}  win_rate={m['win_rate']:.2%}  net=${m['net']:,.2f}  PF={m['profit_factor']:.2f}")

        # Save trades
        trades.to_csv(out_csv, index=False)
        print(f"\nSaved trades to: {out_csv}")
    finally:
        LIVE.clear(); LIVE.update(backup)


def main():
    ap = argparse.ArgumentParser(description="Run backtest for a selected setup and output trades")
    ap.add_argument("--top-csv", type=str, default="analysis_out/top_setups.csv", help="Path to top_setups.csv")
    ap.add_argument("--index", type=int, default=None, help="Row index in top_setups.csv to run (0-based)")
    ap.add_argument("--run-id", type=int, default=None, help="Run ID from top_setups.csv to run")
    ap.add_argument("--overrides", type=str, default=None, help="JSON dict of CONFIG overrides to run instead of CSV selection")
    ap.add_argument("--out", type=str, default="trades_selected.csv", help="Output CSV for trades")
    args = ap.parse_args()

    if args.overrides:
        try:
            ov_input = json.loads(args.overrides)
            if not isinstance(ov_input, dict):
                raise ValueError("--overrides must be a JSON object (dict)")
            overrides = _coerce_types(ov_input)
        except json.JSONDecodeError as e:
            raise SystemExit(f"Failed to parse --overrides JSON: {e}")
    else:
        overrides = _select_overrides_from_csv(args.top_csv, args.index, args.run_id)

    print("Selected overrides:")
    print({k: overrides.get(k) for k in SCENARIO_KEYS if k in overrides})

    apply_and_run(overrides, args.out)


if __name__ == "__main__":
    main()



