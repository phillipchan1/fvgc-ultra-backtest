#!/usr/bin/env python3
"""Iterative PF/WR/Occurrence discovery round (iter4, bounded runtime).

Design goals:
- Stay fast (intended 1–2 hours runtime budget)
- Improve intelligently by *refining around* the repeating axes found in iter1–3
- Post-hoc filters only on `data/levels/trades_with_levels.csv`

Approach:
1) Build a candidate condition pool from a limited set of discrete gates.
2) Enumerate AND-combos of size 3 and 4 under hard runtime caps.
3) Score combos on a walk-forward split (70/30 by date) and also report
   a quick secondary holdout within the test window (last 50% of test dates).

Outputs:
  studies/nq_pf_wr_occ_iter/results/iter4_top_by_objective.json
  studies/nq_pf_wr_occ_iter/results/iter4_top_combos_summary.csv

Run:
  python studies/nq_pf_wr_occ_iter/search_pf_wr_occ_iter4.py
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
    cls: str  # context/avail/magnet/proximity


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


def mask_eq_str(col: str, val: str) -> Callable[[pd.DataFrame], np.ndarray]:
    return lambda d: d[col].astype(str).fillna("").values == str(val)


def main():
    df = pd.read_csv(DATA_PATH)
    df = df[df["outcome"].isin(["win", "loss"])].copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    train_df, test_df = time_split(df, 0.7)

    # secondary holdout: last 50% of test dates
    test_dates = np.array(sorted(set(test_df["timestamp"].dt.date)))
    if len(test_dates) >= 4:
        half = len(test_dates) // 2
        late_dates = set(test_dates[half:])
        late_test_df = test_df[test_df["timestamp"].dt.date.astype(object).isin(late_dates)].copy()
    else:
        late_test_df = test_df

    print(f"Trades: total={len(df):,} train={len(train_df):,} test={len(test_df):,} late_test={len(late_test_df):,}")

    # Candidate pool: focus on repeating axes
    top_groups = (
        df["nearest_magnet_group"].dropna().astype(str).value_counts().head(10).index.tolist()
    )
    variants = sorted(df["variant"].dropna().astype(str).unique().tolist())

    # Anchor gates (always included via combo constraints, not necessarily in pool)
    avail_cols = [
        "path_clear",
        "magnet_valid",
        "level_swept_before_entry",
        "opening_range_swept",
    ]

    prox_cols = ["magnet_within_1R", "magnet_within_2R", "magnet_within_3R"]

    conditions: list[Condition] = []

    # Context: direction + variants + top magnet groups
    for ddir in ["long", "short"]:
        if (df["direction"].astype(str) == ddir).any():
            conditions.append(Condition(
                name=f"direction={ddir}",
                mask_fn=mask_eq_str("direction", ddir),
                cls="context",
            ))

    for v in variants:
        conditions.append(Condition(
            name=f"variant={v}",
            mask_fn=mask_eq_str("variant", v),
            cls="context",
        ))

    for g in top_groups:
        conditions.append(Condition(
            name=f"nearest_magnet_group={g}",
            mask_fn=mask_eq_str("nearest_magnet_group", g),
            cls="context",
        ))

    # Availability gates
    for col in avail_cols:
        if col in df.columns:
            conditions.append(Condition(
                name=f"{col}=True",
                mask_fn=lambda d, col=col: safe_bool_col(d, col).values,
                cls="avail",
            ))

    # Proximity gates
    for col in prox_cols:
        if col in df.columns:
            conditions.append(Condition(
                name=f"{col}=True",
                mask_fn=lambda d, col=col: safe_bool_col(d, col).values,
                cls="proximity",
            ))

    # Hard constraints to keep search realistic
    anchors_avail = {"path_clear=True", "magnet_valid=True", "level_swept_before_entry=True"}
    anchors_context = {
        "nearest_magnet_group=overnight",
        "nearest_magnet_group=htf_fvg_15m",
        "variant=bos",
        "direction=long",
        "direction=short",
        "magnet_within_1R=True",
        "magnet_within_3R=True",
    }

    def cond_name(c: Condition) -> str:
        return c.name

    def combo_has_anchors(combo: tuple[Condition, ...]) -> bool:
        names = {c.name for c in combo}
        has_avail = any(n in anchors_avail for n in names)
        has_context = any(n in anchors_context for n in names)
        return has_avail and has_context

    MIN_N_TRAIN = 180
    MIN_N_TEST = 20

    MAX_EVALS = 45000

    evals = 0
    results: list[dict] = []

    # choose sizes 3 and 4, but enumerate combos in a bounded way
    for k in [3, 4]:
        # To reduce combinatorics, prefilter: only keep conditions that occur often enough in train
        eligible: list[Condition] = []
        for c in conditions:
            m_tr = c.mask_fn(train_df)
            if int(m_tr.sum()) >= MIN_N_TRAIN:
                eligible.append(c)
        # Still too many? cap eligible.
        # Keep top eligible by test PF on a quick scan (cheap):
        # Instead of recomputing PF for all, we just sort by test n descending.
        eligible.sort(key=lambda c: int(c.mask_fn(test_df).sum()), reverse=True)
        eligible = eligible[:28]

        print(f"Eligible pool for k={k}: {len(eligible)}")

        for combo in itertools.combinations(eligible, k):
            if evals >= MAX_EVALS:
                break
            evals += 1

            if not combo_has_anchors(combo):
                continue

            # masks
            m_tr = np.ones(len(train_df), dtype=bool)
            m_te = np.ones(len(test_df), dtype=bool)
            m_late = np.ones(len(late_test_df), dtype=bool)
            for c in combo:
                m_tr &= c.mask_fn(train_df)
                m_te &= c.mask_fn(test_df)
                m_late &= c.mask_fn(late_test_df)

            n_tr = int(m_tr.sum())
            n_te = int(m_te.sum())
            if n_tr < MIN_N_TRAIN or n_te < MIN_N_TEST:
                continue

            st_tr = compute_stats(train_df.loc[m_tr])
            st_te = compute_stats(test_df.loc[m_te])
            st_lt = compute_stats(late_test_df.loc[m_late])

            results.append({
                "k": k,
                "condition": " AND ".join([c.name for c in combo]),
                "train_n": st_tr["n"],
                "train_wr": st_tr["wr"],
                "train_pf": st_tr["pf"],
                "test_n": st_te["n"],
                "test_wr": st_te["wr"],
                "test_pf": st_te["pf"],
                "late_n": st_lt["n"],
                "late_wr": st_lt["wr"],
                "late_pf": st_lt["pf"],
                "test_total_pnl": st_te["total_pnl"],
                "late_total_pnl": st_lt["total_pnl"],
            })

        if evals >= MAX_EVALS:
            break

    if not results:
        print("No results under constraints.")
        return

    res_df = pd.DataFrame(results)

    def is_pf_ok(x) -> bool:
        return (isinstance(x, float) and np.isfinite(x) and x >= 1.1) or (x == float('inf'))

    # Objective rankings prefer PF, then WR, then n
    pf_df = res_df[res_df["test_pf"].apply(is_pf_ok)].sort_values(
        ["test_pf", "test_wr", "test_n"], ascending=[False, False, False]
    ).head(10)

    wr_df = res_df[res_df["test_wr"] >= 60].sort_values(
        ["test_wr", "test_pf", "test_n"], ascending=[False, False, False]
    ).head(10)

    occ_df = res_df.sort_values(["test_n", "test_pf", "test_wr"], ascending=[False, False, False]).head(10)

    # Robustness filter: require late_test PF not collapsing
    def late_ok(row: pd.Series) -> bool:
        lp = row["late_pf"]
        if isinstance(lp, float) and np.isfinite(lp):
            return lp >= 0.95
        return True

    pf_df2 = pf_df[pf_df.apply(late_ok, axis=1)].head(8)
    wr_df2 = wr_df[wr_df.apply(late_ok, axis=1)].head(8)
    occ_df2 = occ_df[occ_df.apply(late_ok, axis=1)].head(8)

    def to_rec(d: pd.DataFrame) -> list[dict]:
        recs = []
        for _, r in d.iterrows():
            recs.append({
                "condition": r["condition"],
                "k": int(r["k"]),
                "test_n": int(r["test_n"]),
                "test_wr": float(r["test_wr"]),
                "test_pf": r["test_pf"],
                "late_n": int(r["late_n"]),
                "late_wr": float(r["late_wr"]),
                "late_pf": r["late_pf"],
            })
        return recs

    summary = {
        "split": {
            "train": "first 70% dates",
            "test": "last 30% dates",
            "late_test": "last 50% of test dates",
        },
        "constraints": {
            "MIN_N_TRAIN": MIN_N_TRAIN,
            "MIN_N_TEST": MIN_N_TEST,
            "MAX_EVALS": MAX_EVALS,
            "allowed_combo_anchor_axes": {
                "avail": sorted(list(anchors_avail)),
                "context": sorted(list(anchors_context)),
            },
        },
        "picked_by_objective": {
            "high_pf": to_rec(pf_df2),
            "high_wr": to_rec(wr_df2),
            "high_occ": to_rec(occ_df2),
        },
        "notes": {
            "selection": "ranked on test split; filtered with late_test PF>=0.95 when finite",
        },
    }

    out_json = OUT_DIR / "iter4_top_by_objective.json"
    out_csv = OUT_DIR / "iter4_top_combos_summary.csv"
    summary_path = str(out_json)

    out_json.write_text(json.dumps(summary, indent=2))

    # save top combos overall by combined rank
    res_df.sort_values(["test_pf", "test_wr", "test_n"], ascending=[False, False, False]).head(2000).to_csv(out_csv, index=False)

    print("\n=== Iter4 picks (with late_test robustness filter) ===")
    for obj, recs in summary["picked_by_objective"].items():
        print(f"\n{obj}:")
        for r in recs:
            print(f"  {r['condition']} | k={r['k']} test_n={r['test_n']} WR={r['test_wr']:.2f}% PF={r['test_pf']} | late_n={r['late_n']} late_WR={r['late_wr']:.2f}% late_PF={r['late_pf']}")

    print(f"\nWrote: {out_json}")
    print(f"Wrote: {out_csv}")


if __name__ == "__main__":
    main()
