# sweep.py
# ---------------------------------------------------------------------------
# Grid search over CONFIG knobs to maximize profit factor / net P&L
# ---------------------------------------------------------------------------

from __future__ import annotations
import argparse
import itertools
import json
from copy import deepcopy
from typing import Dict, Any, List, Tuple

import pandas as pd

from config import CONFIG as BASE_CONFIG
from data_loader import load_db_1s_csv, resample_to_30s
from backtest_engine import run_backtest, calculate_metrics


def product(grid: Dict[str, List[Any]]) -> List[Dict[str, Any]]:
    keys = list(grid.keys())
    vals = [grid[k] for k in keys]
    combos = []
    for tup in itertools.product(*vals):
        combos.append({k: v for k, v in zip(keys, tup)})
    return combos


def run_combo(df30: pd.DataFrame, overrides: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    cfg = deepcopy(BASE_CONFIG)
    cfg.update(overrides)
    # Run backtest with this config (without mutating global CONFIG used elsewhere)
    # We temporarily monkey-patch the imported modules' CONFIG references by passing
    # parameters directly isn't wired; instead, we rely on modules reading CONFIG at call time.
    # The evaluator/backtest_engine read CONFIG dynamically, so we patch the dict in-place.
    from config import CONFIG as LIVE
    # Save and restore
    backup = dict(LIVE)
    try:
        LIVE.clear(); LIVE.update(cfg)
        trades = run_backtest(df30)
        metrics = calculate_metrics(trades)
        total = metrics["TOTAL"]
        return overrides, total
    finally:
        LIVE.clear(); LIVE.update(backup)


def default_grid() -> Dict[str, List[Any]]:
    return {
        # risk/target
        "points_tp": [10.0, 15.0, 20.0, 25.0],
        "points_sl": [15.0, 20.0, 25.0],
        # baseline guards
        "require_pullback_from_outside": [False, True],
        "require_directional_close": [True],
        "require_prev_close_break": [False, True],
        # iFVG knobs
        "ifvg_internal_criterion": ["inside", "overlap"],
        "ifvg_overlap_min_ratio": [0.0, 0.25, 0.5],
        "ifvg_allow_opposite_internal": [True],
        "ifvg_same_bar": [False, True],
        "ifvg_lookback_bars": [6, 10],
        "ifvg_break_metric": ["wick", "close"],
        "ifvg_allow_equal": [True, False],
        # BOS knobs
        "bos_require_close_through": [True],
        "bos_allow_equal": [True, False],
        # conflict behavior
        "skip_conflicting_fvgs": [True],
        "ifvg_ignore_internal_conflict": [True],
    }


def main():
    ap = argparse.ArgumentParser(description="Grid search CONFIG to maximize Profit Factor")
    ap.add_argument("--grid", type=str, help="JSON string or path to JSON file with param grid", default=None)
    ap.add_argument("--top", type=int, default=20, help="Show top N results")
    ap.add_argument("--out", type=str, default=None, help="Optional CSV output of all results")
    ap.add_argument("--workers", type=int, default=0, help="Parallel workers; 0=auto, 1=sync")
    args = ap.parse_args()

    # Load data once
    df1s = load_db_1s_csv(BASE_CONFIG["data_path"])
    df30 = resample_to_30s(df1s)

    # Build grid
    if args.grid is None:
        grid = default_grid()
    else:
        try:
            # Try parse as JSON text first
            grid = json.loads(args.grid)
        except json.JSONDecodeError:
            # Treat as file path
            with open(args.grid, "r") as f:
                grid = json.load(f)

    combos = product(grid)

    # Progress bar (tqdm is optional)
    try:
        from tqdm import tqdm
        progress = tqdm(total=len(combos), desc="Sweeping")
    except Exception:
        progress = None

    results: List[Dict[str, Any]] = []

    # Parallel or sequential execution
    workers = int(args.workers)
    if workers != 1:
        import concurrent.futures as cf
        max_workers = None if workers == 0 else workers
        with cf.ProcessPoolExecutor(max_workers=max_workers) as ex:
            # Pre-load data once per process by passing the df as a global isn't possible across fork
            # so we pass df30 values; but it is picklable, so OK for processes
            futures = [ex.submit(run_combo, df30, ov) for ov in combos]
            for fut in futures:
                params, total = fut.result()
                results.append({**params, **total})
                if progress: progress.update(1)
    else:
        for ov in combos:
            params, total = run_combo(df30, ov)
            results.append({**params, **total})
            if progress: progress.update(1)
    if progress:
        progress.close()

    res_df = pd.DataFrame(results)
    # Sort: highest profit factor, then net
    res_df = res_df.sort_values(["profit_factor", "net"], ascending=[False, False]).reset_index(drop=True)

    # Show top
    cols_show = [
        "profit_factor", "net", "win_rate", "trades",
        "points_tp", "points_sl",
        "require_pullback_from_outside", "require_prev_close_break",
        "ifvg_internal_criterion", "ifvg_overlap_min_ratio", "ifvg_same_bar",
        "ifvg_lookback_bars", "ifvg_break_metric", "ifvg_allow_equal",
        "bos_allow_equal"
    ]
    cols_show = [c for c in cols_show if c in res_df.columns]
    print("Top results (by Profit Factor):")
    print(res_df.head(args.top)[cols_show].to_string(index=False))

    if args.out:
        res_df.to_csv(args.out, index=False)
        print(f"Saved all results to {args.out}")


if __name__ == "__main__":
    main()


