# sweep.py
# ---------------------------------------------------------------------------
# Grid search over CONFIG knobs to maximize profit factor / net P&L
# ---------------------------------------------------------------------------

from __future__ import annotations
import argparse
import itertools
import json
from copy import deepcopy
import sys
import time
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
    """Curated scenario permutations (not random), with clear semantics.

    Notes on scenario fields:
    - entry_touch_type: "tap_only" means bar touched gap and closed outside ("strong delivery").
      "close_inside_only" means bar closed inside the gap ("weak delivery").
    - min/max_gap_taps: number of prior touches into the gap before entry.
    - penetrated_midline: whether the pullback went beyond 50% of the gap.
    - allowed_time_buckets: pick from ["0930-0945","0945-1000","1000-1015"].
    - first_five_only: restrict to 09:30-09:35 ET.
    - gap_size_min/max_pts: restrict gap size in points (e.g., 2 to 40).
    - min/max_bars_to_prev_break: delivery speed; 1-2-3 stronger if small.
    """
    # QUICK GRID: drastically reduced permutations for fast local runs.
    # Varies only entry_touch_type and time bucket; all other scenario knobs disabled.
    return {
        # Keep risk params modest and fixed here unless explicitly varied
        "points_tp": [20.0],
        "points_sl": [20.0],
        # Core scenario toggles (reduced)
        "entry_touch_type": [None, "tap_only", "close_inside_only"],  # 3
        "allowed_time_buckets": [None, ["0930-0945"], ["0945-1000"], ["1000-1015"]],  # 4
        # Disabled scenario dimensions for speed (set to None only)
        "min_gap_taps": [None],
        "max_gap_taps": [None],
        "penetrated_midline": [None],
        "first_five_only": [None],
        "gap_size_min_pts": [None],
        "gap_size_max_pts": [None],
        "min_bars_to_prev_break": [None],
        "max_bars_to_prev_break": [None],
        # Reduce unrelated knobs to stable defaults
        "require_pullback_from_outside": [False],
        "require_directional_close": [True],
        "require_prev_close_break": [False],
        "ifvg_internal_criterion": ["inside"],
        "ifvg_overlap_min_ratio": [0.0],
        "ifvg_allow_opposite_internal": [True],
        "ifvg_same_bar": [False],
        "ifvg_lookback_bars": [10],
        "ifvg_break_metric": ["wick"],
        "ifvg_allow_equal": [True],
        "bos_require_close_through": [True],
        "bos_allow_equal": [True],
        "skip_conflicting_fvgs": [True],
        "ifvg_ignore_internal_conflict": [True],
    }


def named_scenarios() -> List[Dict[str, Any]]:
    """Hand-picked scenarios with clear names and comments.

    You can pass one of these via --grid JSON to run only that scenario, e.g.:
    --grid '{"entry_touch_type":"tap_only","first_five_only":true}'
    """
    base = {
        "points_tp": 20.0,
        "points_sl": 20.0,
        # lock unrelated knobs
        "require_pullback_from_outside": False,
        "require_directional_close": True,
        "require_prev_close_break": False,
        "ifvg_internal_criterion": "inside",
        "ifvg_overlap_min_ratio": 0.0,
        "ifvg_allow_opposite_internal": True,
        "ifvg_same_bar": False,
        "ifvg_lookback_bars": 10,
        "ifvg_break_metric": "wick",
        "ifvg_allow_equal": True,
        "bos_require_close_through": True,
        "bos_allow_equal": True,
        "skip_conflicting_fvgs": True,
        "ifvg_ignore_internal_conflict": True,
    }
    return [
        {
            "name": "Tap Strong Delivery (all times)",
            **base,
            "entry_touch_type": "tap_only",
        },
        {
            "name": "Close-Inside Weak Delivery (all times)",
            **base,
            "entry_touch_type": "close_inside_only",
        },
        {
            "name": "Tap with Midline Penetration",
            **base,
            "entry_touch_type": "tap_only",
            "penetrated_midline": True,
        },
        {
            "name": "0-1 taps before entry (fresh)",
            **base,
            "min_gap_taps": 0,
            "max_gap_taps": 1,
        },
        {
            "name": "2-3 taps (weaker delivery)",
            **base,
            "min_gap_taps": 2,
            "max_gap_taps": 3,
        },
        {
            "name": "930-945 bucket",
            **base,
            "allowed_time_buckets": ["0930-0945"],
        },
        {
            "name": "945-1000 bucket",
            **base,
            "allowed_time_buckets": ["0945-1000"],
        },
        {
            "name": "1000-1015 bucket",
            **base,
            "allowed_time_buckets": ["1000-1015"],
        },
        {
            "name": "First 5 minutes only",
            **base,
            "first_five_only": True,
        },
        {
            "name": "Gap size 2-40 pts",
            **base,
            "gap_size_min_pts": 2.0,
            "gap_size_max_pts": 40.0,
        },
        {
            "name": "Fast 1-2-3 delivery (<=2 bars)",
            **base,
            "max_bars_to_prev_break": 2,
        },
        {
            "name": "Slower delivery (3-5 bars)",
            **base,
            "min_bars_to_prev_break": 3,
            "max_bars_to_prev_break": 5,
        },
    ]


def curated_scenarios() -> List[Dict[str, Any]]:
    """Generate a curated, moderate-sized set of scenarios (~432 combos)."""
    base = {
        "points_tp": 20.0,
        "points_sl": 20.0,
        # lock unrelated knobs
        "require_pullback_from_outside": False,
        "require_directional_close": True,
        "require_prev_close_break": False,
        "ifvg_internal_criterion": "inside",
        "ifvg_overlap_min_ratio": 0.0,
        "ifvg_allow_opposite_internal": True,
        "ifvg_same_bar": False,
        "ifvg_lookback_bars": 10,
        "ifvg_break_metric": "wick",
        "ifvg_allow_equal": True,
        "bos_require_close_through": True,
        "bos_allow_equal": True,
        "skip_conflicting_fvgs": True,
        "ifvg_ignore_internal_conflict": True,
    }
    touch_types = [None, "tap_only", "close_inside_only"]
    buckets = [None, ["0930-0945"], ["0945-1000"], ["1000-1015"]]
    midline_opts = [None, True]
    taps_bands = [None, (0, 1), (2, 3)]
    delivery_bands = [None, (None, 2), (3, 5)]
    gap_bands = [None, (2.0, 40.0)]

    scenarios: List[Dict[str, Any]] = []
    for t in touch_types:
        for b in buckets:
            for pen in midline_opts:
                for taps in taps_bands:
                    for dv in delivery_bands:
                        for g in gap_bands:
                            ov = dict(base)
                            if t:
                                ov["entry_touch_type"] = t
                            else:
                                ov["entry_touch_type"] = None
                            ov["allowed_time_buckets"] = b
                            ov["penetrated_midline"] = pen
                            if taps is None:
                                ov["min_gap_taps"] = None
                                ov["max_gap_taps"] = None
                            else:
                                ov["min_gap_taps"], ov["max_gap_taps"] = taps
                            if dv is None:
                                ov["min_bars_to_prev_break"] = None
                                ov["max_bars_to_prev_break"] = None
                            else:
                                ov["min_bars_to_prev_break"], ov["max_bars_to_prev_break"] = dv
                            if g is None:
                                ov["gap_size_min_pts"] = None
                                ov["gap_size_max_pts"] = None
                            else:
                                ov["gap_size_min_pts"], ov["gap_size_max_pts"] = g
                            scenarios.append(ov)
    return scenarios


def main():
    ap = argparse.ArgumentParser(description="Grid search CONFIG to maximize Profit Factor")
    ap.add_argument("--grid", type=str, help="JSON string or path to JSON file with param grid", default=None)
    ap.add_argument("--top", type=int, default=20, help="Show top N results")
    ap.add_argument("--out", type=str, default="sweep_results.csv", help="CSV output of all results (default: sweep_results.csv)")
    ap.add_argument("--workers", type=int, default=1, help="Parallel workers; 1=sequential (quiet fan), 0=auto, N=fixed")
    ap.add_argument("--best-trades-out", type=str, default="trades_best.csv", help="CSV to save trades for best Profit Factor scenario (default: trades_best.csv)")
    ap.add_argument("--min-trades", type=int, default=10, help="Minimum trades required to consider a scenario as top candidate")
    ap.add_argument("--full-scenarios", action="store_true", help="Use a curated set of full scenarios (~432) instead of the quick grid")
    args = ap.parse_args()

    # Load data once
    df1s = load_db_1s_csv(BASE_CONFIG["data_path"])
    df30 = resample_to_30s(df1s)

    # Build grid or pick named/curated scenarios
    if args.grid is None:
        if args.full_scenarios:
            combos = curated_scenarios()
        else:
            grid = default_grid()
            combos = product(grid)
    else:
        try:
            # Try parse as JSON text first
            maybe = json.loads(args.grid)
            # If it looks like a dict (single scenario), wrap into list
            if isinstance(maybe, dict):
                combos = [maybe]
            elif isinstance(maybe, list):
                combos = maybe
            else:
                grid = maybe
                combos = product(grid)
        except json.JSONDecodeError:
            # Treat as file path (could be JSON array or dict)
            with open(args.grid, "r") as f:
                maybe = json.load(f)
                if isinstance(maybe, dict):
                    combos = [maybe]
                elif isinstance(maybe, list):
                    combos = maybe
                else:
                    grid = maybe
                    combos = product(grid)

    # Progress bar (tqdm optional). Provide a simple fallback if missing.
    class SimpleProgress:
        def __init__(self, total: int, desc: str = ""):
            self.total = int(total)
            self.current = 0
            self.desc = desc
            self.start = time.perf_counter()
            self._render()
        def update(self, n: int = 1):
            self.current += int(n)
            if self.current > self.total:
                self.current = self.total
            self._render()
        def _render(self):
            width = 30
            done = width if self.total == 0 else int(width * (self.current / max(1, self.total)))
            if done > width:
                done = width
            bar = "=" * done + "-" * (width - done)
            elapsed = time.perf_counter() - self.start
            rate = (self.current / elapsed) if elapsed > 0 else None
            remain = ((self.total - self.current) / rate) if rate and rate > 0 else None
            def fmt(secs: float) -> str:
                secs = int(max(0, secs))
                h = secs // 3600
                m = (secs % 3600) // 60
                s = secs % 60
                return f"{h:02d}:{m:02d}:{s:02d}"
            eta_str = fmt(remain) if remain is not None else "--:--:--"
            el_str = fmt(elapsed)
            sys.stdout.write(f"\r{self.desc} [{bar}] {self.current}/{self.total}  elapsed {el_str}  eta {eta_str}")
            sys.stdout.flush()
        def close(self):
            sys.stdout.write("\n")
            sys.stdout.flush()

    try:
        from tqdm import tqdm
        progress = tqdm(total=len(combos), desc="Sweeping", unit="combo", dynamic_ncols=True)
    except Exception:
        progress = SimpleProgress(total=len(combos), desc="Sweeping")

    results: List[Dict[str, Any]] = []
    runs: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []  # keep (params,total) in order

    # Parallel or sequential execution
    workers = int(args.workers)
    if workers != 1:
        import concurrent.futures as cf
        max_workers = None if workers == 0 else workers
        with cf.ProcessPoolExecutor(max_workers=max_workers) as ex:
            # Pre-load data once per process by passing the df as a global isn't possible across fork
            # so we pass df30 values; but it is picklable, so OK for processes
            futures = [ex.submit(run_combo, df30, ov) for ov in combos]
            run_id = 0
            for fut in futures:
                params, total = fut.result()
                results.append({"run_id": run_id, **params, **total})
                runs.append((params, total))
                run_id += 1
                if progress: progress.update(1)
    else:
        run_id = 0
        for ov in combos:
            params, total = run_combo(df30, ov)
            results.append({"run_id": run_id, **params, **total})
            runs.append((params, total))
            run_id += 1
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
        # scenario columns
        "entry_touch_type", "min_gap_taps", "max_gap_taps",
        "penetrated_midline", "allowed_time_buckets", "first_five_only",
        "gap_size_min_pts", "gap_size_max_pts",
        "min_bars_to_prev_break", "max_bars_to_prev_break",
    ]
    cols_show = [c for c in cols_show if c in res_df.columns]
    print("Top results (by Profit Factor):")
    print(res_df.head(args.top)[cols_show].to_string(index=False))

    # Also show top with min-trades filter if applicable
    if "trades" in res_df.columns:
        filtered = res_df[res_df["trades"] >= int(args.min_trades)]
        if not filtered.empty:
            print(f"\nTop results with trades >= {args.min_trades}:")
            print(filtered.head(args.top)[cols_show].to_string(index=False))
        else:
            print(f"\nNo scenarios met trades >= {args.min_trades}; showing unfiltered above.")

    # If the user passed a list of named scenarios, show name if present
    if "name" in res_df.columns:
        print("\nNamed Scenarios run:")
        print(res_df[["name", "profit_factor", "win_rate", "trades", "net"]].head(args.top).to_string(index=False))

    if args.out:
        res_df.to_csv(args.out, index=False)
        print(f"Saved all results to {args.out}")

    # Re-run best scenario (highest PF, then net) to capture its trades,
    # preferring scenarios that meet the min-trades threshold
    if not res_df.empty:
        cand = res_df
        if "trades" in cand.columns:
            cand2 = cand[cand["trades"] >= int(args.min_trades)]
            if not cand2.empty:
                cand = cand2
        best = cand.iloc[0]
        best_run_id = int(best.get("run_id", 0))
        if 0 <= best_run_id < len(runs):
            best_params = runs[best_run_id][0]

            # Re-run to get trades under best params
            def run_trades_for_combo(df30_local: pd.DataFrame, overrides_local: Dict[str, Any]) -> pd.DataFrame:
                cfg = deepcopy(BASE_CONFIG)
                cfg.update(overrides_local)
                from config import CONFIG as LIVE
                backup = dict(LIVE)
                try:
                    LIVE.clear(); LIVE.update(cfg)
                    trades_local = run_backtest(df30_local)
                    return trades_local
                finally:
                    LIVE.clear(); LIVE.update(backup)

            trades_best = run_trades_for_combo(df30, best_params)
            print("\nBest scenario parameters:")
            print({k: v for k, v in best_params.items()})
            print(f"Trades taken by best scenario: {len(trades_best)}")

            # Print trades to console (cap to 200 rows for readability)
            if len(trades_best) <= 200:
                print(trades_best.to_string(index=False))
            else:
                print(trades_best.head(50).to_string(index=False))
                print("... (truncated) ...")

            # Save if requested
            if args.best_trades_out:
                trades_best.to_csv(args.best_trades_out, index=False)
                print(f"Saved best scenario trades to {args.best_trades_out}")


if __name__ == "__main__":
    main()


