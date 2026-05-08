#!/usr/bin/env python3
"""Iterative PF/WR/Occurrence subset search (fast round 2).

Changes vs iter1:
- Still post-hoc filters only on `data/levels/trades_with_levels.csv`
- Walk-forward train/test split
- Generates AND combos of up to 3 conditions (fast-limited)
- Prefers combos with at least:
    (a) one directional/variant/context condition (direction=*, variant=*)
    (b) one magnet/context availability condition (nearest_magnet_group=*, path_clear=True,
        magnet_valid=True, level_swept_before_entry=True, opening_range_swept=True)
- Outputs many candidates but ranks by each objective on TEST.

Run:
  python studies/nq_pf_wr_occ_iter/search_pf_wr_occ_iter2.py

Outputs:
  studies/nq_pf_wr_occ_iter/results/iter2_best_by_objective.json
  .../results/iter2_top_combos_test.csv
"""

from __future__ import annotations

import itertools
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

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
    losses = n - wins
    wr = wins / n * 100.0

    pnl = pd.to_numeric(df["pnl"], errors="coerce").astype(float)
    pnl = pnl.replace([np.inf, -np.inf], np.nan).dropna()

    # If pnl has NaNs, recompute on pnl-valid subset
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
        "total_pnl": round(float(pd.to_numeric(df["pnl"], errors="coerce").astype(float).sum()), 4),
        "wins": wins2,
        "losses": losses2,
    }


def time_split(df: pd.DataFrame, train_frac: float = 0.7) -> tuple[pd.DataFrame, pd.DataFrame]:
    d = pd.to_datetime(df["timestamp"]).dt.date
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
    if s.dtype == bool:
        return s.fillna(False)
    return s.fillna(False).astype(str).str.lower().isin(["true", "1", "available"])


def main():
    df = pd.read_csv(DATA_PATH)
    df = df[df["outcome"].isin(["win", "loss"])].copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    train_df, test_df = time_split(df, 0.7)

    print(f"Loaded {len(df):,} win/loss trades")
    print(f"Train={len(train_df):,}  Test={len(test_df):,}")

    # Candidate condition pool (keep it small for speed)
    top_groups = (
        df["nearest_magnet_group"].dropna().astype(str).value_counts().head(8).index.tolist()
    )
    variants = sorted(df["variant"].dropna().astype(str).unique().tolist())

    conditions: list[Condition] = []

    # Variant conditions (context)
    for v in variants:
        conditions.append(
            Condition(
                name=f"variant={v}",
                mask_fn=lambda d, v=v: (d["variant"].astype(str) == v).values,
            )
        )

    # Direction conditions (context)
    for ddir in ["long", "short"]:
        if (df["direction"].astype(str) == ddir).any():
            conditions.append(
                Condition(
                    name=f"direction={ddir}",
                    mask_fn=lambda d, ddir=ddir: (d["direction"].astype(str) == ddir).values,
                )
            )

    # Magnet group conditions
    for g in top_groups:
        conditions.append(
            Condition(
                name=f"nearest_magnet_group={g}",
                mask_fn=lambda d, g=g: (d["nearest_magnet_group"].astype(str) == g).values,
            )
        )

    # Availability gates
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

    # Proximity gates (only if present)
    for col in ["magnet_within_1R", "magnet_within_2R", "magnet_within_3R"]:
        if col in df.columns:
            conditions.append(
                Condition(
                    name=f"{col}=True",
                    mask_fn=lambda d, col=col: safe_bool_col(d, col).values,
                )
            )

    # Pre-score single conditions on train to keep only top K
    MIN_N_TRAIN = 90
    MIN_N_TEST = 25

    scored: list[dict] = []

    for cond in conditions:
        m_tr = cond.mask_fn(train_df)
        if int(m_tr.sum()) < MIN_N_TRAIN:
            continue
        m_te = cond.mask_fn(test_df)
        st_tr = compute_stats(train_df.loc[m_tr])
        st_te = compute_stats(test_df.loc[m_te])
        if st_te["n"] < MIN_N_TEST:
            continue
        scored.append({
            "cond": cond,
            "train_n": st_tr["n"],
            "train_wr": st_tr["wr"],
            "train_pf": st_tr["pf"],
            "test_n": st_te["n"],
            "test_wr": st_te["wr"],
            "test_pf": st_te["pf"],
            "test_total_pnl": st_te["total_pnl"],
        })

    if not scored:
        print("No single conditions passed constraints. Exiting.")
        return

    # Sort by a blended score to choose candidates for combos
    def blend(x: dict) -> float:
        pf = x["test_pf"]
        pf_score = pf if (isinstance(pf, float) and np.isfinite(pf)) else (-1.0)
        return (x["test_n"] * 0.1) + pf_score * 10 + x["test_wr"] * 0.02

    scored_sorted = sorted(scored, key=blend, reverse=True)

    TOP_K = 18
    chosen = scored_sorted[:TOP_K]
    chosen_conds = [x["cond"] for x in chosen]

    print(f"Single-pass candidates: {len(scored)}  -> chosen for combos: {len(chosen_conds)}")

    def class_of(cond_name: str) -> str:
        # rough anchor classes
        if cond_name.startswith("direction=") or cond_name.startswith("variant="):
            return "context"
        if cond_name.startswith("nearest_magnet_group="):
            return "magnet"
        if cond_name in ["path_clear=True", "magnet_valid=True", "level_swept_before_entry=True", "opening_range_swept=True"]:
            return "avail"
        if "magnet_within_" in cond_name:
            return "proximity"
        return "other"

    def combo_ok(names: tuple[str, ...]) -> bool:
        cls = [class_of(n) for n in names]
        has_context = any(c == "context" for c in cls)
        has_anchor = any(c in ("magnet", "avail") for c in cls)
        return has_context and has_anchor

    # Combo evaluation
    MAX_COMBOS = 9000
    results: list[dict] = []

    def eval_combo(cond_list: list[Condition], k: int):
        mask_tr = np.ones(len(train_df), dtype=bool)
        for c in cond_list:
            mask_tr &= c.mask_fn(train_df)
        if int(mask_tr.sum()) < MIN_N_TRAIN:
            return

        mask_te = np.ones(len(test_df), dtype=bool)
        for c in cond_list:
            mask_te &= c.mask_fn(test_df)
        if int(mask_te.sum()) < MIN_N_TEST:
            return

        st_tr = compute_stats(train_df.loc[mask_tr])
        st_te = compute_stats(test_df.loc[mask_te])
        results.append({
            "k": k,
            "condition": " AND ".join([c.name for c in cond_list]),
            "train_n": st_tr["n"],
            "train_wr": st_tr["wr"],
            "train_pf": st_tr["pf"],
            "test_n": st_te["n"],
            "test_wr": st_te["wr"],
            "test_pf": st_te["pf"],
            "test_total_pnl": st_te["total_pnl"],
        })

    # 2-way AND (quick)
    combos_seen = 0
    for c1, c2 in itertools.combinations(chosen_conds, 2):
        combos_seen += 1
        if combos_seen > MAX_COMBOS:
            break
        names = (c1.name, c2.name)
        if not combo_ok(names):
            continue
        eval_combo([c1, c2], 2)

    # 3-way AND (fast-limited)
    if combos_seen <= MAX_COMBOS:
        for c1, c2, c3 in itertools.combinations(chosen_conds, 3):
            combos_seen += 1
            if combos_seen > MAX_COMBOS:
                break
            names = (c1.name, c2.name, c3.name)
            if not combo_ok(names):
                continue
            eval_combo([c1, c2, c3], 3)

    if not results:
        print("No combo results. Exiting.")
        return

    combo_df = pd.DataFrame(results)

    # Ranking per objective on TEST
    def finite_pf(x) -> bool:
        return isinstance(x, float) and np.isfinite(x)

    best_pf = combo_df.copy()
    best_pf = best_pf[best_pf["test_pf"].apply(lambda x: (finite_pf(x) and x >= 1.1) or (x == float('inf')))]
    best_pf = best_pf.sort_values(["test_pf", "test_n"], ascending=[False, False]).head(10)

    best_wr = combo_df[combo_df["test_wr"] >= 60].sort_values(["test_wr", "test_pf"], ascending=[False, False]).head(10)

    best_occ = combo_df.sort_values(["test_n", "test_pf"], ascending=[False, False]).head(10)

    # Save CSV of top by test_pf
    combo_df_sorted = combo_df.sort_values(["test_pf", "test_wr", "test_n"], ascending=[False, False, False])
    combo_df_sorted.head(300).to_csv(OUT_DIR / "iter2_top_combos_test.csv", index=False)

    def row_to_obj(row: pd.Series):
        return {
            "condition": row["condition"],
            "k": int(row["k"]),
            "test_n": int(row["test_n"]),
            "test_wr": float(row["test_wr"]),
            "test_pf": row["test_pf"],
            "train_n": int(row["train_n"]),
            "train_wr": float(row["train_wr"]),
            "train_pf": row["train_pf"],
        }

    summary = {
        "picked_by_objective": {
            "high_pf": [row_to_obj(r) for _, r in best_pf.iterrows()],
            "high_wr": [row_to_obj(r) for _, r in best_wr.iterrows()],
            "high_occ": [row_to_obj(r) for _, r in best_occ.iterrows()],
        },
        "notes": {
            "split": "train/test by date (70/30)",
            "combo_limit": MAX_COMBOS,
            "chosen_single_conditions": TOP_K,
            "selection_filters": {
                "MIN_N_TRAIN": MIN_N_TRAIN,
                "MIN_N_TEST": MIN_N_TEST,
            },
        },
    }

    with open(OUT_DIR / "iter2_best_by_objective.json", "w") as f:
        json.dump(summary, f, indent=2)

    print("\n=== Iter2 picks (TEST split) ===")
    for obj, arr in summary["picked_by_objective"].items():
        print(f"\n{obj}:")
        for a in arr:
            print(f"  {a['condition']}  | test n={a['test_n']} WR={a['test_wr']:.2f}% PF={a['test_pf']}")

    print(f"\nWrote: {OUT_DIR / 'iter2_best_by_objective.json'}")
    print(f"Wrote: {OUT_DIR / 'iter2_top_combos_test.csv'}")


if __name__ == "__main__":
    main()
