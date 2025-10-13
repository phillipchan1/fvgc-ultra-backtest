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
import os
import ast
import numpy as np

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
        "points_tp": [5.0, 10.0, 15.0, 20.0, 25.0],
        "points_sl": [5.0, 10.0, 15.0, 20.0, 25.0],
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


def range_grid() -> Dict[str, List[Any]]:
    """Broader permutation ranges over key variables.

    Note: This is intentionally constrained to keep total combinations reasonable.
    Use --grid with a custom JSON to expand further if needed.
    """
    def seq5(start: float, stop: float) -> List[float]:
        vals: List[float] = []
        x = float(start)
        while x <= float(stop) + 1e-9:
            vals.append(round(x, 4))
            x += 5.0
        return vals

    return {
        # Risk ranges
        "points_tp": seq5(5.0, 25.0),
        "points_sl": seq5(5.0, 25.0),

        # Core scenario toggles
        "entry_touch_type": [None, "tap_only", "close_inside_only"],

        # Keep time-bucket neutral to limit explosion (enable via custom grid if desired)
        "allowed_time_buckets": [None],

        # Taps bands expressed via min/max with validator enforcing allowed pairs
        "min_gap_taps": [None, 0, 2],
        "max_gap_taps": [None, 1, 3],

        # Delivery speed bands (bars to previous break): (None,2) or (3,5)
        "min_bars_to_prev_break": [None, 3],
        "max_bars_to_prev_break": [None, 2, 5],

        # Gap size bands stepped by 5s. We'll validate coherent min/max pairs.
        "gap_size_min_pts": [None] + seq5(0.0, 50.0),
        "gap_size_max_pts": [None] + seq5(10.0, 60.0),

        # Optional scenario switches kept modest
        "penetrated_midline": [None, True],
        "first_five_only": [None],

        # Stable defaults to reduce unrelated variance
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


def _pair_allowed(ov: Dict[str, Any], min_key: str, max_key: str, allowed_pairs: List[Tuple[Any, Any]]) -> bool:
    vmin = ov.get(min_key)
    vmax = ov.get(max_key)
    if vmin is None and vmax is None:
        return True
    return (vmin, vmax) in allowed_pairs


def is_valid_combo(ov: Dict[str, Any]) -> bool:
    """Validate min/max pairings to keep range mode constrained and meaningful."""
    # Taps must be None/None, (0,1), or (2,3)
    if not _pair_allowed(ov, "min_gap_taps", "max_gap_taps", [(0, 1), (2, 3)]):
        return False
    # Delivery bars must be None/None, (None,2) or (3,5)
    if not _pair_allowed(ov, "min_bars_to_prev_break", "max_bars_to_prev_break", [(None, 2), (3, 5)]):
        return False
    # Gap size: allow None/None, or any multiples-of-5 min/max with min < max
    gmin = ov.get("gap_size_min_pts")
    gmax = ov.get("gap_size_max_pts")
    if gmin is None and gmax is None:
        pass
    else:
        try:
            if gmin is None or gmax is None:
                return False
            if gmin >= gmax:
                return False
            def is_mult5(x: float) -> bool:
                return abs((x / 5.0) - round(x / 5.0)) < 1e-9
            if not (is_mult5(float(gmin)) and is_mult5(float(gmax))):
                return False
        except Exception:
            return False

    # Risk: ensure TP/SL multiples of 5 (constructed as such already), keep as sanity check
    for k in ("points_tp", "points_sl"):
        try:
            val = float(ov.get(k))
            if abs((val / 5.0) - round(val / 5.0)) >= 1e-9:
                return False
        except Exception:
            return False
    return True

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
    ap.add_argument("--range-grid", action="store_true", help="Use broader permutation ranges across key variables")
    ap.add_argument("--analyze", action="store_true", help="Run feature correlation/importance analysis against target metric")
    ap.add_argument("--target-metric", type=str, default="profit_factor", help="Target metric to analyze (e.g., profit_factor, net, win_rate)")
    ap.add_argument("--analysis-out", type=str, default="sweep_analysis.csv", help="CSV to save ranked feature analysis (default: sweep_analysis.csv)")
    ap.add_argument("--resume", action="store_true", help="Resume from existing --out CSV and skip completed scenarios (incremental save)")
    args = ap.parse_args()

    # Load data once
    df1s = load_db_1s_csv(BASE_CONFIG["data_path"])
    df30 = resample_to_30s(df1s)

    # Helper: list of scenario keys used for signatures
    scenario_keys = [
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

    def canonicalize_value(v: Any) -> Any:
        if v is None:
            return None
        if isinstance(v, list):
            return [str(x) for x in sorted(v)]
        return v

    def scenario_signature(d: Dict[str, Any]) -> str:
        obj = {k: canonicalize_value(d.get(k)) for k in scenario_keys}
        return json.dumps(obj, sort_keys=True, separators=(",", ":"))

    def parse_cell(v: Any) -> Any:
        if pd.isna(v):
            return None
        if isinstance(v, str):
            s = v.strip()
            # Try to parse list-like strings
            if s.startswith("[") and s.endswith("]"):
                try:
                    val = ast.literal_eval(s)
                    if isinstance(val, list):
                        return [str(x) for x in val]
                except Exception:
                    pass
            # Keep raw string (for categories)
            return s
        return v

    def row_signature(row: pd.Series) -> str:
        d = {}
        for k in scenario_keys:
            if k in row.index:
                d[k] = canonicalize_value(parse_cell(row[k]))
            else:
                d[k] = None
        return json.dumps(d, sort_keys=True, separators=(",", ":"))

    # Build grid or pick named/curated scenarios
    if args.grid is None:
        if args.full_scenarios:
            combos = curated_scenarios()
        elif args.range_grid:
            grid = range_grid()
            all_combos = product(grid)
            combos = [ov for ov in all_combos if is_valid_combo(ov)]
            print(f"Range mode: built {len(all_combos)} combos, filtered to {len(combos)} valid combos")
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

    # Resume support: load existing output and skip done signatures
    df_prev = None
    prev_sigs: set = set()
    header_written = False
    start_run_id = 0
    if args.resume and args.out and os.path.exists(args.out):
        try:
            df_prev = pd.read_csv(args.out)
            if "run_id" in df_prev.columns and not df_prev.empty:
                try:
                    start_run_id = int(pd.to_numeric(df_prev["run_id"], errors="coerce").max()) + 1
                except Exception:
                    start_run_id = 0
            prev_sigs = set(row_signature(r) for _, r in df_prev.iterrows())
            header_written = True
        except Exception:
            df_prev = None
            prev_sigs = set()
            header_written = os.path.exists(args.out)

    if prev_sigs:
        before = len(combos)
        combos = [ov for ov in combos if scenario_signature(ov) not in prev_sigs]
        print(f"Resume: skipping {before - len(combos)} already-completed combos; {len(combos)} remaining")

    # Progress bar sized to remaining work
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
            run_id = start_run_id
            for fut in futures:
                params, total = fut.result()
                row = {"run_id": run_id, **params, **total}
                results.append(row)
                runs.append((params, total))
                run_id += 1
                if progress: progress.update(1)
                # Incremental save for resume
                if args.resume and args.out:
                    try:
                        df_row = pd.DataFrame([row])
                        if df_prev is not None and not df_prev.empty:
                            # Align columns to previous file when possible
                            missing_cols = [c for c in df_prev.columns if c not in df_row.columns]
                            for c in missing_cols:
                                df_row[c] = np.nan
                            df_row = df_row[df_prev.columns]
                        df_row.to_csv(args.out, mode="a", index=False, header=not header_written)
                        header_written = True
                    except Exception:
                        pass
    else:
        run_id = start_run_id
        for ov in combos:
            params, total = run_combo(df30, ov)
            row = {"run_id": run_id, **params, **total}
            results.append(row)
            runs.append((params, total))
            run_id += 1
            if progress: progress.update(1)
            # Incremental save for resume
            if args.resume and args.out:
                try:
                    df_row = pd.DataFrame([row])
                    if df_prev is not None and not df_prev.empty:
                        missing_cols = [c for c in df_prev.columns if c not in df_row.columns]
                        for c in missing_cols:
                            df_row[c] = np.nan
                        df_row = df_row[df_prev.columns]
                    df_row.to_csv(args.out, mode="a", index=False, header=not header_written)
                    header_written = True
                except Exception:
                    pass
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

    # Merge with previous results for display and selection
    if df_prev is not None and not df_prev.empty:
        try:
            res_all = pd.concat([df_prev, res_df], ignore_index=True)
        except Exception:
            res_all = res_df.copy()
    else:
        res_all = res_df.copy()

    # Only write final CSV if not in resume mode (resume increments already written)
    if args.out and not args.resume:
        res_all.to_csv(args.out, index=False)
        print(f"Saved all results to {args.out}")

    # Optional: correlation/importance analysis
    if args.analyze:
        def build_features(df: pd.DataFrame) -> Tuple[pd.DataFrame, List[str]]:
            metric_columns = {
                "run_id", "profit_factor", "net", "win_rate", "trades",
                "gross_profit", "gross_loss", "commissions", "avg_trade", "ending_balance",
                "name",
            }
            # Known time buckets to individually one-hot if present
            known_time_buckets = ["0930-0945", "0945-1000", "1000-1015"]

            feature_cols = [c for c in df.columns if c not in metric_columns]
            X_parts: List[pd.DataFrame] = []

            # Start with numeric and boolean-as-int features
            num_bool_cols: List[str] = []
            for c in feature_cols:
                s = df[c]
                if s.dtype == bool:
                    num_bool_cols.append(c)
                elif pd.api.types.is_numeric_dtype(s):
                    num_bool_cols.append(c)
            if num_bool_cols:
                X_parts.append(df[num_bool_cols].astype(float))

            # Handle allowed_time_buckets specially (lists of strings or None)
            if "allowed_time_buckets" in feature_cols:
                s = df["allowed_time_buckets"].apply(lambda v: v if isinstance(v, list) else ([] if v is None else [str(v)]))
                data = {}
                for bucket in known_time_buckets:
                    data[f"allowed_time_{bucket}"] = s.apply(lambda lst: float(bucket in lst))
                data["allowed_time_none"] = df["allowed_time_buckets"].apply(lambda v: float(v is None or (isinstance(v, list) and len(v) == 0)))
                X_parts.append(pd.DataFrame(data))

            # Categorical/object features (including entry_touch_type, penetrated_midline may be bool)
            cat_cols = []
            for c in feature_cols:
                if c == "allowed_time_buckets":
                    continue
                s = df[c]
                if (not pd.api.types.is_numeric_dtype(s)) and (s.dtype != bool):
                    cat_cols.append(c)
            if cat_cols:
                cat_df = df[cat_cols].copy()
                # Normalize Nones
                for c in cat_cols:
                    cat_df[c] = cat_df[c].apply(lambda v: "<None>" if v is None else str(v))
                X_parts.append(pd.get_dummies(cat_df, prefix=cat_cols, dtype=float))

            X = pd.concat(X_parts, axis=1) if X_parts else pd.DataFrame(index=df.index)
            # Drop any all-NaN or zero-variance columns
            X = X.replace([np.inf, -np.inf], np.nan)
            X = X.fillna(0.0)
            nunique = X.nunique(dropna=False)
            X = X.loc[:, nunique > 1]
            return X, feature_cols

        def run_analysis(df: pd.DataFrame, target_col: str) -> pd.DataFrame:
            if target_col not in df.columns:
                raise ValueError(f"Target metric '{target_col}' not in results")
            # Filter rows with finite target
            y_raw = pd.to_numeric(df[target_col], errors="coerce").replace([np.inf, -np.inf], np.nan)
            mask = y_raw.notna()
            df2 = df.loc[mask].reset_index(drop=True)
            y = y_raw.loc[mask].astype(float).reset_index(drop=True)
            if len(df2) < 3:
                raise ValueError("Not enough rows for analysis after filtering")

            X, _ = build_features(df2)
            if X.empty:
                raise ValueError("No usable features for analysis")

            # Standardize X and y
            Xs = (X - X.mean()) / X.std(ddof=0)
            Xs = Xs.replace([np.inf, -np.inf], 0.0).fillna(0.0)
            ys = (y - y.mean()) / (y.std(ddof=0) if y.std(ddof=0) != 0 else 1.0)

            # Pearson corr
            pearson = X.corrwith(y)
            pearson = pearson.replace([np.inf, -np.inf], np.nan).fillna(0.0)

            # Spearman corr (rank-based)
            rank_X = X.rank(method="average")
            rank_y = y.rank(method="average")
            spearman = rank_X.corrwith(rank_y)
            spearman = spearman.replace([np.inf, -np.inf], np.nan).fillna(0.0)

            # Linear regression via least squares on standardized data
            X_mat = Xs.values
            y_vec = ys.values
            coef = np.linalg.lstsq(X_mat, y_vec, rcond=None)[0]
            preds = X_mat @ coef
            sse = float(np.sum((y_vec - preds) ** 2))
            sst = float(np.sum((y_vec - y_vec.mean()) ** 2)) if len(y_vec) > 1 else 0.0
            baseline_r2 = 1.0 - (sse / sst) if sst > 0 else 0.0

            # Permutation importance: R2 drop per-feature
            perm_importance = []
            rng = np.random.default_rng(0)
            for i, col in enumerate(X.columns):
                X_perm = X_mat.copy()
                shuffled = X_perm[:, i].copy()
                rng.shuffle(shuffled)
                X_perm[:, i] = shuffled
                coef_p = np.linalg.lstsq(X_perm, y_vec, rcond=None)[0]
                preds_p = X_perm @ coef_p
                sse_p = float(np.sum((y_vec - preds_p) ** 2))
                r2_p = 1.0 - (sse_p / sst) if sst > 0 else 0.0
                perm_importance.append(baseline_r2 - r2_p)

            out = pd.DataFrame({
                "feature": X.columns,
                "pearson_r": pearson.values,
                "spearman_rho": spearman.values,
                "lin_coef_std": coef,
                "perm_r2_drop": perm_importance,
            })
            # Aggregate a simple overall score for ranking
            out["rank_score"] = (
                out["pearson_r"].abs().rank(ascending=False)
                + out["spearman_rho"].abs().rank(ascending=False)
                + out["lin_coef_std"].abs().rank(ascending=False)
                + out["perm_r2_drop"].rank(ascending=False)
            )
            out = out.sort_values("rank_score").reset_index(drop=True)
            return out

        try:
            analysis_df = run_analysis(res_df, args.target_metric)
            top_n = min(20, len(analysis_df))
            print(f"\nTop features by combined rank for target='{args.target_metric}':")
            print(analysis_df.head(top_n).to_string(index=False))
            if args.analysis_out:
                analysis_df.to_csv(args.analysis_out, index=False)
                print(f"Saved feature analysis to {args.analysis_out}")
        except Exception as e:
            print(f"Analysis failed: {e}")

    # Re-run best scenario (highest PF, then net) to capture its trades,
    # preferring scenarios that meet the min-trades threshold
    if not res_all.empty:
        cand = res_all
        if "trades" in cand.columns:
            cand2 = cand[cand["trades"] >= int(args.min_trades)]
            if not cand2.empty:
                cand = cand2
        best = cand.iloc[0]
        # Try to map to current session runs by run_id; fallback to reconstruct from row
        best_run_id = int(pd.to_numeric(best.get("run_id", -1), errors="coerce"))
        best_params: Dict[str, Any]
        if 0 <= best_run_id - (start_run_id if len(runs) > 0 else best_run_id) < len(runs):
            # Index into runs if within current session range
            idx = best_run_id - start_run_id
            best_params = runs[idx][0]
        else:
            # Reconstruct params from row
            best_params = {}
            for k in scenario_keys:
                if k in best.index:
                    val = parse_cell(best[k])
                else:
                    val = None
                best_params[k] = val

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


