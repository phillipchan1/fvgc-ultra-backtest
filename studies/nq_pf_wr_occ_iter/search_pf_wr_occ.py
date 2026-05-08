#!/usr/bin/env python3
"""Iterative PF/WR/Occurrence subset search for NQ (FVGC baseline outcomes).

Goal: find simple trade-filter subsets that simultaneously target:
  1) high profit factor (PF)
  2) high win rate (WR)
  3) high occurrence (# trades)

This does *not* change the FVGC entry model; it searches over post-hoc filters
on the existing `data/levels/trades_with_levels.csv` which already contains
SL/TP outcomes (win/loss) and level-proximity features.

Run:
  python studies/nq_pf_wr_occ_iter/search_pf_wr_occ.py

Outputs:
  studies/nq_pf_wr_occ_iter/results/top_candidates.csv
  studies/nq_pf_wr_occ_iter/results/top_candidates_detail.csv
  studies/nq_pf_wr_occ_iter/results/best_by_objective.json
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA_PATH = ROOT / "data" / "levels" / "trades_with_levels.csv"
OUT_DIR = Path(__file__).resolve().parent / "results"
OUT_DIR.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class Condition:
    name: str
    mask_fn: Callable[[pd.DataFrame], np.ndarray]


def compute_stats(df: pd.DataFrame) -> dict:
    n = int(len(df))
    if n == 0:
        return {
            "n": 0,
            "wr": np.nan,
            "pf": np.nan,
            "total_pnl": 0.0,
            "wins": 0,
            "losses": 0,
        }

    wins = int((df["outcome"] == "win").sum())
    losses = int((df["outcome"] == "loss").sum())
    wr = wins / n * 100.0

    pnl = pd.to_numeric(df["pnl"], errors="coerce").astype(float)
    pnl = pnl.replace([np.inf, -np.inf], np.nan).dropna()

    # If pnl has NaNs, recompute n on pnl-valid rows
    if len(pnl) != n:
        n2 = int(len(pnl))
        if n2 == 0:
            return {
                "n": n,
                "wr": wr,
                "pf": np.nan,
                "total_pnl": 0.0,
                "wins": wins,
                "losses": losses,
            }
        wins2 = int((df.loc[pnl.index, "outcome"] == "win").sum())
        losses2 = int(n2 - wins2)
    else:
        wins2, losses2 = wins, losses

    gross_profit = float(pnl[pnl > 0].sum())
    gross_loss = float(abs(pnl[pnl < 0].sum()))
    if gross_loss > 0:
        pf = gross_profit / gross_loss
    else:
        pf = float("inf") if gross_profit > 0 else float("nan")

    return {
        "n": n,
        "wr": round(wr, 4),
        "pf": float(pf) if np.isfinite(pf) else pf,
        "total_pnl": round(float(pnl.sum()), 4),
        "wins": wins2,
        "losses": losses2,
    }


def time_split(df: pd.DataFrame, train_frac: float = 0.7) -> tuple[pd.DataFrame, pd.DataFrame]:
    d = pd.to_datetime(df["timestamp"]).dt.date
    # sorted unique dates
    unique_dates = np.array(sorted(set(d)))
    if len(unique_dates) < 10:
        return df, df.iloc[0:0]
    cutoff = int(len(unique_dates) * train_frac)
    train_dates = set(unique_dates[:cutoff])
    test_dates = set(unique_dates[cutoff:])
    train = df[d.isin(train_dates)].copy()
    test = df[d.isin(test_dates)].copy()
    return train, test


def safe_bool_col(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series([False] * len(df), index=df.index)
    s = df[col]
    # Handle already-bool or string
    if s.dtype == bool:
        return s.fillna(False)
    return s.fillna(False).astype(str).str.lower().isin(["true", "1", "available"])


def main():
    df = pd.read_csv(DATA_PATH)
    df = df[df["outcome"].isin(["win", "loss"])].copy()

    # Ensure types
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    print(f"Loaded {len(df):,} win/loss trades from {DATA_PATH}")

    # Robustness split
    train_df, test_df = time_split(df, 0.7)
    print(f"Train trades={len(train_df):,}  Test trades={len(test_df):,}")

    # Candidate value sets
    top_groups = (
        df["nearest_magnet_group"]
        .dropna()
        .astype(str)
        .value_counts()
        .head(8)
        .index
        .tolist()
    )

    variants = sorted(df["variant"].dropna().unique().astype(str).tolist())

    conditions: list[Condition] = []

    # Variant filters
    for v in variants:
        conditions.append(
            Condition(
                name=f"variant={v}",
                mask_fn=lambda d, v=v: (d["variant"].astype(str) == v).values,
            )
        )

    # Direction filters
    for ddir in ["long", "short"]:
        if (df["direction"].astype(str) == ddir).any():
            conditions.append(
                Condition(
                    name=f"direction={ddir}",
                    mask_fn=lambda d, ddir=ddir: (d["direction"].astype(str) == ddir).values,
                )
            )

    # Magnet group filters
    for g in top_groups:
        conditions.append(
            Condition(
                name=f"nearest_magnet_group={g}",
                mask_fn=lambda d, g=g: (d["nearest_magnet_group"].astype(str) == g).values,
            )
        )

    # Common boolean / availability gates
    for col in [
        "magnet_valid",
        "path_clear",
        "level_swept_before_entry",
        "opening_range_swept",
    ]:
        conditions.append(
            Condition(
                name=f"{col}=True",
                mask_fn=lambda d, col=col: safe_bool_col(d, col).values,
            )
        )

    # Magnet proximity gates
    for col in ["magnet_within_2R", "magnet_within_3R", "magnet_within_1R"]:
        if col in df.columns:
            conditions.append(
                Condition(
                    name=f"{col}=True",
                    mask_fn=lambda d, col=col: safe_bool_col(d, col).values,
                )
            )

    # Level confluence count thresholds
    if "level_confluence_count" in df.columns:
        # Use quantiles to create a few buckets
        qc = pd.to_numeric(df["level_confluence_count"], errors="coerce").dropna()
        if len(qc) > 0:
            q70 = float(qc.quantile(0.7))
            q85 = float(qc.quantile(0.85))
            for thr, lab in [(q70, "ge70"), (q85, "ge85")]:
                conditions.append(
                    Condition(
                        name=f"level_confluence_count={lab} (>= {thr:.2f})",
                        mask_fn=lambda d, thr=thr: (pd.to_numeric(d["level_confluence_count"], errors="coerce") >= thr).fillna(False).values,
                    )
                )

    # Opening-range proximity gate (numeric)
    if "opening_range_nearest_R" in df.columns:
        rn = pd.to_numeric(df["opening_range_nearest_R"], errors="coerce").dropna()
        if len(rn) > 20:
            for thr in [0.5, 1.0, 2.0]:
                conditions.append(
                    Condition(
                        name=f"opening_range_nearest_R<={thr}",
                        mask_fn=lambda d, thr=thr: (pd.to_numeric(d["opening_range_nearest_R"], errors="coerce") <= thr).fillna(False).values,
                    )
                )

    # Define scoring for objective 1/2/3
    def score_obj_pf(stats: dict) -> float:
        pf = stats["pf"]
        if not (pf is None) and (isinstance(pf, float) and np.isfinite(pf)):
            return pf
        # inf or nan
        if pf == float("inf"):
            return 1e9
        return -1.0

    def score_obj_wr(stats: dict) -> float:
        return stats["wr"]

    def score_obj_occ(stats: dict) -> float:
        # Encourage large n but not purely by n; tie-break on pf
        pf = stats["pf"]
        pf_part = 0.0
        if isinstance(pf, float) and np.isfinite(pf):
            pf_part = pf
        return stats["n"] * 0.01 + pf_part

    # Evaluate single-condition candidates
    MIN_N_TRAIN = 80
    MIN_N_TEST = 30

    evaluated = []

    def eval_condition(cond: Condition, df_in: pd.DataFrame, split_name: str):
        mask = cond.mask_fn(df_in)
        sub = df_in.loc[mask]
        s = compute_stats(sub)
        return {f"{split_name}_{k}": v for k, v in s.items()}

    singles = []
    for cond in conditions:
        tr = eval_condition(cond, train_df, "train")
        te = eval_condition(cond, test_df, "test")
        if tr["train_n"] < MIN_N_TRAIN:
            continue
        # soft constraint on test
        if te["test_n"] < MIN_N_TEST:
            continue

        combined = {
            "condition": cond.name,
            **tr,
            **te,
        }
        evaluated.append(combined)
        singles.append(combined)

    singles_df = pd.DataFrame(evaluated)
    print(f"Single-condition candidates evaluated: {len(singles_df):,}")

    # If no candidates, stop
    if singles_df.empty:
        print("No single-condition candidates met MIN_N constraints.")
        return

    # Select top-k per objective (train-based)
    k = 12
    top_pf = singles_df.sort_values("train_pf", ascending=False).head(k).copy()
    top_wr = singles_df.sort_values("train_wr", ascending=False).head(k).copy()
    top_occ = singles_df.sort_values(["train_n"], ascending=False).head(k).copy()

    seed_names = set(top_pf["condition"].tolist() + top_wr["condition"].tolist() + top_occ["condition"].tolist())
    seed_conds = [c for c in conditions if c.name in seed_names]

    # Build combos: AND of two conditions (avoid identical names)
    # Evaluate combos quickly by precomputing masks on full df
    # But to keep RAM manageable, we compute masks on the split DF.

    combo_results = []
    cond_by_name = {c.name: c for c in conditions}

    # Use candidates as second factors: all conditions minus the first
    second_pool = [c for c in conditions]

    def mask_for(cond: Condition, d: pd.DataFrame):
        return cond.mask_fn(d)

    # Combo loops
    for c1 in seed_conds:
        m1_tr = mask_for(c1, train_df)
        if int(m1_tr.sum()) < MIN_N_TRAIN:
            continue
        for c2 in second_pool:
            if c2.name == c1.name:
                continue
            # AND
            m = m1_tr & mask_for(c2, train_df)
            sub_tr = train_df.loc[m]
            if len(sub_tr) < MIN_N_TRAIN:
                continue

            m_test = mask_for(c1, test_df) & mask_for(c2, test_df)
            sub_te = test_df.loc[m_test]
            if len(sub_te) < MIN_N_TEST:
                continue

            tr_stats = compute_stats(sub_tr)
            te_stats = compute_stats(sub_te)

            combo_results.append(
                {
                    "condition": f"({c1.name}) AND ({c2.name})",
                    "train_n": tr_stats["n"],
                    "train_wr": tr_stats["wr"],
                    "train_pf": tr_stats["pf"],
                    "train_total_pnl": tr_stats["total_pnl"],
                    "test_n": te_stats["n"],
                    "test_wr": te_stats["wr"],
                    "test_pf": te_stats["pf"],
                    "test_total_pnl": te_stats["total_pnl"],
                }
            )

    combo_df = pd.DataFrame(combo_results)
    print(f"Combo candidates evaluated: {len(combo_df):,}")

    # Save detail
    singles_df.to_csv(OUT_DIR / "top_single_candidates.csv", index=False)
    if not combo_df.empty:
        combo_df.to_csv(OUT_DIR / "top_combo_candidates.csv", index=False)

    # Objective pickers (use test robustness)
    # Choose top PF/WR by test_pf/test_wr with minimum constraints.
    def pick_top(df_in: pd.DataFrame, by: str, min_pf: float | None = None) -> pd.DataFrame:
        out = df_in.copy()
        if min_pf is not None:
            # Keep only finite PF>=min_pf
            def finite_pf(x):
                return (isinstance(x, float) and np.isfinite(x) and x >= min_pf)

            out = out[out[by.replace("test_", "test_")].apply(finite_pf)]
        return out.sort_values(by, ascending=False).head(8)

    candidates_df = combo_df if not combo_df.empty else singles_df

    # Normalize columns for picker
    candidates_df = candidates_df.copy()

    # PF objective
    best_pf = candidates_df.copy()
    best_pf = best_pf[(best_pf["test_n"] >= MIN_N_TEST) & (best_pf["test_pf"].apply(lambda x: (isinstance(x, float) and np.isfinite(x) and x >= 1.1) or x == float('inf')))]
    best_pf = best_pf.sort_values("test_pf", ascending=False).head(3)

    # WR objective
    best_wr = candidates_df.copy()
    best_wr = best_wr[(best_wr["test_n"] >= MIN_N_TEST) & (best_wr["test_wr"] >= 58)].sort_values("test_wr", ascending=False).head(3)

    # Occurrence objective
    best_occ = candidates_df.copy()
    best_occ = best_occ[(best_occ["test_n"] >= MIN_N_TEST) & (best_occ["test_pf"].apply(lambda x: (isinstance(x, float) and np.isfinite(x) and x >= 1.05) or x == float('inf')))].sort_values(["test_n","test_pf"], ascending=[False, False]).head(3)

    # Save JSON summary
    def row_to_obj(row: pd.Series):
        return {
            "condition": row["condition"],
            "test_n": int(row["test_n"]),
            "test_wr": float(row["test_wr"]),
            "test_pf": float(row["test_pf"]) if (isinstance(row["test_pf"], float) and np.isfinite(row["test_pf"])) else str(row["test_pf"]),
            "train_n": int(row["train_n"]),
            "train_wr": float(row["train_wr"]),
            "train_pf": float(row["train_pf"]) if (isinstance(row["train_pf"], float) and np.isfinite(row["train_pf"])) else str(row["train_pf"]),
        }

    summary = {
        "best_by_objective": {
            "high_pf": [row_to_obj(r) for _, r in best_pf.iterrows()],
            "high_wr": [row_to_obj(r) for _, r in best_wr.iterrows()],
            "high_occ": [row_to_obj(r) for _, r in best_occ.iterrows()],
        },
        "notes": {
            "objective_selection": "ranked on test split for robustness",
            "combos": "2-condition AND only",
            "data": str(DATA_PATH),
        },
    }

    with open(OUT_DIR / "best_by_objective.json", "w") as f:
        json.dump(summary, f, indent=2)

    # Also save combined detail frame
    combined_detail_path = OUT_DIR / "top_candidates_detail.csv"
    if not combo_df.empty:
        # keep top by test_pf
        candidates_df.sort_values("test_pf", ascending=False).head(200).to_csv(combined_detail_path, index=False)
    else:
        singles_df.sort_values("test_pf", ascending=False).head(200).to_csv(combined_detail_path, index=False)

    print("\n=== TOP PICKS (test split) ===")
    for k, arr in summary["best_by_objective"].items():
        print(f"\n{k}: ")
        for x in arr:
            print(f"  {x['condition']}")
            print(f"    train n={x['train_n']} WR={x['train_wr']:.1f} PF={x['train_pf']}  |  test n={x['test_n']} WR={x['test_wr']:.1f} PF={x['test_pf']}")


if __name__ == "__main__":
    main()
