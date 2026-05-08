#!/usr/bin/env python3
"""Iter5: wider PF/WR/occurrence discovery (still bounded runtime).

Compared to iter4:
- More magnet groups in the pool (top 15 instead of top 10)
- Eligible pool cap increased (up to 45)
- Robustness filter relaxed (late_test PF >= 0.85 when finite)
- Adds a composite “best of all” picker that optimizes PF * WR * log(n)

Outputs:
  studies/nq_pf_wr_occ_iter/results/iter5_best_of_all.json
  studies/nq_pf_wr_occ_iter/results/iter5_top_by_objective.json
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
    cls: str


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

    # late-test: last 50% of test dates
    test_dates = np.array(sorted(set(test_df["timestamp"].dt.date)))
    if len(test_dates) >= 4:
        half = len(test_dates) // 2
        late_dates = set(test_dates[half:])
        late_test_df = test_df[test_df["timestamp"].dt.date.astype(object).isin(late_dates)].copy()
    else:
        late_test_df = test_df

    print(f"Trades: total={len(df):,} train={len(train_df):,} test={len(test_df):,} late={len(late_test_df):,}")

    # Build condition pool (wider magnet groups)
    top_groups = (
        df["nearest_magnet_group"].dropna().astype(str).value_counts().head(15).index.tolist()
        if "nearest_magnet_group" in df.columns else []
    )
    variants = sorted(df["variant"].dropna().astype(str).unique().tolist())

    conditions: list[Condition] = []

    # Context anchors
    for g in top_groups:
        conditions.append(Condition(f"nearest_magnet_group={g}", mask_eq_str("nearest_magnet_group", g), "context"))

    for v in variants:
        conditions.append(Condition(f"variant={v}", mask_eq_str("variant", v), "context"))

    # Direction anchors
    for ddir in ["long", "short"]:
        if (df["direction"].astype(str) == ddir).any():
            conditions.append(Condition(f"direction={ddir}", mask_eq_str("direction", ddir), "context"))

    # Availability gates
    avail_cols = ["path_clear", "magnet_valid", "level_swept_before_entry", "opening_range_swept"]
    for col in avail_cols:
        if col in df.columns:
            conditions.append(Condition(f"{col}=True", lambda d, col=col: safe_bool_col(d, col).values, "avail"))

    # Proximity gates
    for col in ["magnet_within_1R", "magnet_within_2R", "magnet_within_3R"]:
        if col in df.columns:
            conditions.append(Condition(f"{col}=True", lambda d, col=col: safe_bool_col(d, col).values, "proximity"))

    # Anchor axes to ensure search meaningful
    anchors_avail = {"path_clear=True", "magnet_valid=True", "level_swept_before_entry=True", "opening_range_swept=True"}
    anchors_context = {
        *(f"nearest_magnet_group={g}" for g in top_groups),
        *(f"variant={v}" for v in variants),
        "direction=long",
        "direction=short",
        "magnet_within_1R=True",
        "magnet_within_2R=True",
        "magnet_within_3R=True",
    }

    def combo_has_anchors(combo: tuple[Condition, ...]) -> bool:
        names = {c.name for c in combo}
        has_avail = any(n in anchors_avail for n in names)
        has_ctx = any(n in anchors_context for n in names)
        return has_avail and has_ctx

    # Build eligible pool by frequency on train and test
    MIN_N_TRAIN = 140
    MIN_N_TEST = 18

    eligible: list[Condition] = []
    for c in conditions:
        n_tr = int(c.mask_fn(train_df).sum())
        n_te = int(c.mask_fn(test_df).sum())
        if n_tr >= MIN_N_TRAIN and n_te >= MIN_N_TEST:
            eligible.append(c)

    # Cap eligible by test frequency (wide)
    eligible.sort(key=lambda c: int(c.mask_fn(test_df).sum()), reverse=True)
    eligible = eligible[:45]

    print(f"Eligible conditions: {len(eligible)}")

    # Evaluate combos of size 3 and 4
    MIN_N_TRAIN_COMBO = 180
    MIN_N_TEST_COMBO = 20

    MAX_EVALS = 120000
    evals = 0
    results: list[dict] = []

    def pf_ok_late(x: object) -> bool:
        if x is None:
            return True
        if isinstance(x, float) and np.isfinite(x):
            return x >= 0.85
        return True  # keep inf/nan as OK

    for k in [3, 4]:
        print(f"Enumerating k={k} combos...")
        for combo in itertools.combinations(eligible, k):
            if evals >= MAX_EVALS:
                break
            evals += 1

            if not combo_has_anchors(combo):
                continue

            # masks
            m_tr = np.ones(len(train_df), dtype=bool)
            m_te = np.ones(len(test_df), dtype=bool)
            m_lt = np.ones(len(late_test_df), dtype=bool)
            for c in combo:
                m_tr &= c.mask_fn(train_df)
                m_te &= c.mask_fn(test_df)
                m_lt &= c.mask_fn(late_test_df)

            n_tr = int(m_tr.sum())
            n_te = int(m_te.sum())
            if n_tr < MIN_N_TRAIN_COMBO or n_te < MIN_N_TEST_COMBO:
                continue

            st_tr = compute_stats(train_df.loc[m_tr])
            st_te = compute_stats(test_df.loc[m_te])
            st_lt = compute_stats(late_test_df.loc[m_lt])

            if not pf_ok_late(st_lt["pf"]):
                continue

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
            })

        if evals >= MAX_EVALS:
            break

    print(f"Evaluated combos: {evals:,}  kept results: {len(results):,}")
    if not results:
        return

    res_df = pd.DataFrame(results)

    def composite_score(row: pd.Series) -> float:
        pf = row["test_pf"]
        if isinstance(pf, float) and np.isfinite(pf):
            pf_val = pf
        else:
            pf_val = 0.0
        wr = float(row["test_wr"]) if pd.notna(row["test_wr"]) else 0.0
        n = int(row["test_n"])
        # maximize: pf * (wr/100) * log(n+1)
        return pf_val * (wr / 100.0) * float(np.log(n + 1.0))

    res_df["composite"] = res_df.apply(composite_score, axis=1)

    # pick top by objectives
    def is_fin_pf(x):
        return isinstance(x, float) and np.isfinite(x) and x >= 0

    pf_df = res_df[res_df["test_pf"].apply(lambda x: is_fin_pf(x) and x >= 1.1)].sort_values(["test_pf", "test_wr", "test_n"], ascending=[False, False, False]).head(12)
    wr_df = res_df[res_df["test_wr"] >= 60].sort_values(["test_wr", "test_pf", "test_n"], ascending=[False, False, False]).head(12)
    occ_df = res_df.sort_values(["test_n", "test_pf", "test_wr"], ascending=[False, False, False]).head(12)
    all_best = res_df.sort_values(["composite", "test_pf", "test_n"], ascending=[False, False, False]).head(12)

    def to_records(d: pd.DataFrame) -> list[dict]:
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
                "test_total_pnl": float(r["test_total_pnl"]),
                "composite": float(r["composite"]),
            })
        return recs

    summary_obj = {
        "split": {
            "train": "first 70% dates",
            "test": "last 30% dates",
            "late_test": "last 50% of test dates",
        },
        "constraints": {
            "MIN_N_TRAIN": MIN_N_TRAIN,
            "MIN_N_TEST": MIN_N_TEST,
            "MIN_N_TRAIN_COMBO": MIN_N_TRAIN_COMBO,
            "MIN_N_TEST_COMBO": MIN_N_TEST_COMBO,
            "MAX_EVALS": MAX_EVALS,
            "late_pf_threshold": 0.85,
            "eligible_pool_cap": 45,
        },
        "picked_by_objective": {
            "high_pf": to_records(pf_df),
            "high_wr": to_records(wr_df),
            "high_occ": to_records(occ_df),
        },
    }

    all_best_obj = {
        "best_of_all": to_records(all_best),
    }

    out1 = OUT_DIR / "iter5_top_by_objective.json"
    out2 = OUT_DIR / "iter5_best_of_all.json"

    out1.write_text(json.dumps(summary_obj, indent=2))
    out2.write_text(json.dumps(all_best_obj, indent=2))

    print(f"Wrote: {out1}")
    print(f"Wrote: {out2}")

    print("\nTop composite candidates:")
    for r in all_best.head(8).to_dict(orient="records"):
        print(f"- {r['condition']} | n={r['test_n']} WR={r['test_wr']:.2f}% PF={r['test_pf']} latePF={r['late_pf']} composite={r['composite']:.3f}")


if __name__ == "__main__":
    main()
