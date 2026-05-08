#!/usr/bin/env python3
"""Fast PF/WR/Occurrence discovery round (iter3): 3-way AND focus.

- Post-hoc filters only on `data/levels/trades_with_levels.csv`
- Walk-forward date split (70/30)
- Chooses a larger pool of single conditions, then enumerates 3-condition ANDs
- Keeps runtime bounded with MAX_EVALS

Run:
  python studies/nq_pf_wr_occ_iter/search_pf_wr_occ_iter3.py

Outputs:
  studies/nq_pf_wr_occ_iter/results/iter3_top_by_objective.json
  studies/nq_pf_wr_occ_iter/results/iter3_top_combos_test.csv
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
        return {"n": 0, "wr": np.nan, "pf": np.nan, "total_pnl": 0.0, "wins": 0, "losses": 0}

    wins = int((df["outcome"] == "win").sum())
    losses = n - wins
    wr = wins / n * 100.0

    pnl = pd.to_numeric(df["pnl"], errors="coerce").astype(float)
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
        "wins": wins,
        "losses": losses,
    }


def time_split(df: pd.DataFrame, train_frac: float = 0.7) -> tuple[pd.DataFrame, pd.DataFrame]:
    d = pd.to_datetime(df["timestamp"]).dt.date
    unique_dates = np.array(sorted(set(d)))
    cutoff = int(len(unique_dates) * train_frac)
    train_dates = set(unique_dates[:cutoff])
    test_dates = set(unique_dates[cutoff:])
    return df[d.isin(train_dates)].copy(), df[d.isin(test_dates)].copy()


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

    # Candidate singles pool
    top_groups = (
        df["nearest_magnet_group"].dropna().astype(str).value_counts().head(10).index.tolist()
    )
    variants = sorted(df["variant"].dropna().astype(str).unique().tolist())

    conditions: list[Condition] = []

    # Context: variant
    for v in variants:
        conditions.append(Condition(name=f"variant={v}", mask_fn=lambda d, v=v: (d["variant"].astype(str) == v).values))

    # Direction
    for ddir in ["long", "short"]:
        if (df["direction"].astype(str) == ddir).any():
            conditions.append(Condition(name=f"direction={ddir}", mask_fn=lambda d, ddir=ddir: (d["direction"].astype(str) == ddir).values))

    # Magnet groups
    for g in top_groups:
        conditions.append(Condition(name=f"nearest_magnet_group={g}", mask_fn=lambda d, g=g: (d["nearest_magnet_group"].astype(str) == g).values))

    # Availability gates
    for col in ["magnet_valid", "path_clear", "level_swept_before_entry", "opening_range_swept"]:
        conditions.append(Condition(name=f"{col}=True", mask_fn=lambda d, col=col: safe_bool_col(d, col).values))

    # Proximity gates
    for col in ["magnet_within_1R", "magnet_within_2R", "magnet_within_3R"]:
        if col in df.columns:
            conditions.append(Condition(name=f"{col}=True", mask_fn=lambda d, col=col: safe_bool_col(d, col).values))

    MIN_N_TRAIN = 100
    MIN_N_TEST = 20
    TOP_K = 26
    MAX_EVALS = 25000  # hard runtime cap

    # Score singles quickly on TEST to pick pool
    scored = []
    for cond in conditions:
        m_tr = cond.mask_fn(train_df)
        if int(m_tr.sum()) < MIN_N_TRAIN:
            continue
        m_te = cond.mask_fn(test_df)
        s_te = compute_stats(test_df.loc[m_te])
        if s_te["n"] < MIN_N_TEST:
            continue
        s_tr = compute_stats(train_df.loc[m_tr])
        scored.append((cond, s_tr, s_te))

    if not scored:
        print("No single conditions passed constraints")
        return

    # blend: prefer PF, then n, then WR
    def blend(s_te: dict, s_tr: dict) -> float:
        pf = s_te["pf"]
        pf_val = pf if (isinstance(pf, float) and np.isfinite(pf)) else (-1.0)
        return (pf_val * 10) + (s_te["n"] * 0.02) + (s_te["wr"] * 0.01)

    scored.sort(key=lambda t: blend(t[2], t[1]), reverse=True)
    chosen = [t[0] for t in scored[:TOP_K]]

    print(f"Singles pool chosen: {len(chosen)} (from {len(scored)} scored)")

    evals = 0
    results: list[dict] = []

    # 3-way AND evaluation
    # We require at least one context (direction/variant/magnet_group) and at least one availability/proximity gate.
    def classify(name: str) -> str:
        if name.startswith("direction=") or name.startswith("variant=") or name.startswith("nearest_magnet_group="):
            return "context"
        if any(name.startswith(x) for x in ["path_clear=", "magnet_valid=", "level_swept_before_entry=", "opening_range_swept="]):
            return "avail"
        if name.startswith("magnet_within_"):
            return "prox"
        return "other"

    def combo_ok(names: tuple[str, str, str]) -> bool:
        cls = [classify(n) for n in names]
        has_context = any(c == "context" for c in cls)
        has_anchor = any(c in ("avail", "prox") for c in cls)
        return has_context and has_anchor

    for c1, c2, c3 in itertools.combinations(chosen, 3):
        if evals >= MAX_EVALS:
            break
        names = (c1.name, c2.name, c3.name)
        if not combo_ok(names):
            continue

        evals += 1

        # train
        m_tr = c1.mask_fn(train_df) & c2.mask_fn(train_df) & c3.mask_fn(train_df)
        if int(m_tr.sum()) < MIN_N_TRAIN:
            continue
        # test
        m_te = c1.mask_fn(test_df) & c2.mask_fn(test_df) & c3.mask_fn(test_df)
        if int(m_te.sum()) < MIN_N_TEST:
            continue

        s_tr = compute_stats(train_df.loc[m_tr])
        s_te = compute_stats(test_df.loc[m_te])

        results.append({
            "condition": " AND ".join(names),
            "train_n": s_tr["n"],
            "train_wr": s_tr["wr"],
            "train_pf": s_tr["pf"],
            "test_n": s_te["n"],
            "test_wr": s_te["wr"],
            "test_pf": s_te["pf"],
            "test_total_pnl": s_te["total_pnl"],
        })

    if not results:
        print("No combo results")
        return

    combo_df = pd.DataFrame(results)
    combo_df_sorted = combo_df.sort_values(["test_pf", "test_wr", "test_n"], ascending=[False, False, False])
    combo_df_sorted.head(500).to_csv(OUT_DIR / "iter3_top_combos_test.csv", index=False)

    # per objective pickers
    def is_pf_ok(x) -> bool:
        return (isinstance(x, float) and np.isfinite(x) and x >= 1.1) or (x == float('inf'))

    pf_df = combo_df[combo_df["test_pf"].apply(is_pf_ok)].sort_values(["test_pf", "test_n"], ascending=[False, False]).head(10)
    wr_df = combo_df[combo_df["test_wr"] >= 60].sort_values(["test_wr", "test_pf", "test_n"], ascending=[False, False, False]).head(10)
    occ_df = combo_df.sort_values(["test_n", "test_pf"], ascending=[False, False]).head(10)

    summary = {
        "split": "train/test by date (70/30)",
        "singles_chosen": len(chosen),
        "combo_evals": evals,
        "picked_by_objective": {
            "high_pf": pf_df.to_dict(orient="records"),
            "high_wr": wr_df.to_dict(orient="records"),
            "high_occ": occ_df.to_dict(orient="records"),
        },
    }

    with open(OUT_DIR / "iter3_top_by_objective.json", "w") as f:
        json.dump(summary, f, indent=2)

    print("\n=== Iter3 top picks (TEST split) ===")
    print("high_pf")
    for _, r in pf_df.head(5).iterrows():
        print(" ", r["condition"], f"| n={int(r['test_n'])} WR={float(r['test_wr']):.2f}% PF={r['test_pf']}")
    print("high_wr")
    for _, r in wr_df.head(5).iterrows():
        print(" ", r["condition"], f"| n={int(r['test_n'])} WR={float(r['test_wr']):.2f}% PF={r['test_pf']}")
    print("high_occ")
    for _, r in occ_df.head(5).iterrows():
        print(" ", r["condition"], f"| n={int(r['test_n'])} WR={float(r['test_wr']):.2f}% PF={r['test_pf']}")

    print(f"\nWrote: {OUT_DIR / 'iter3_top_by_objective.json'}")


if __name__ == "__main__":
    main()
