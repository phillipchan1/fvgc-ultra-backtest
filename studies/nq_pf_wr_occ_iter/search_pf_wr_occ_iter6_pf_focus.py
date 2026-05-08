#!/usr/bin/env python3
"""Iter6: PF-focused wide search (bounded) using existing post-hoc filters.

Emphasis: maximize profit factor while keeping WR and occurrence reasonable.

Key changes vs iter5:
- Single-condition prefilter: only keep conditions whose *test* PF >= 1.2 and
  have at least MIN_N_TEST singles.
- Combo search restricted to k=3 (optionally k=4 if runtime allows) and uses a
  smaller eligible pool.
- Robustness: require PF not collapsing across BOTH early_test and late_test
  subsets (PF >= 0.9 for finite values).
- Stronger objective: composite favors PF heavily.

Run:
  python studies/nq_pf_wr_occ_iter/search_pf_wr_occ_iter6_pf_focus.py

Outputs:
  studies/nq_pf_wr_occ_iter/results/iter6_pf_focus.json
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
        return {"n": 0, "wr": np.nan, "pf": np.nan, "total_pnl": 0.0}

    wins = int((df["outcome"] == "win").sum())
    losses = n - wins
    wr = wins / n * 100.0

    pnl = pd.to_numeric(df["pnl"], errors="coerce").astype(float)
    pnl = pnl.replace([np.inf, -np.inf], np.nan).dropna()

    if len(pnl) == 0:
        return {"n": n, "wr": round(wr, 4), "pf": np.nan, "total_pnl": 0.0}

    gross_profit = float(pnl[pnl > 0].sum())
    gross_loss = float(abs(pnl[pnl < 0].sum()))
    if gross_loss > 0:
        pf = gross_profit / gross_loss
    else:
        pf = float("inf") if gross_profit > 0 else float("nan")

    return {"n": n, "wr": round(wr, 4), "pf": float(pf) if np.isfinite(pf) else pf, "total_pnl": round(float(pnl.sum()), 4)}


def safe_bool_col(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series([False] * len(df), index=df.index)
    s = df[col]
    if s.dtype == bool:
        return s.fillna(False)
    return s.fillna(False).astype(str).str.lower().isin(["true", "1", "available"])


def mask_eq_str(col: str, val: str) -> Callable[[pd.DataFrame], np.ndarray]:
    return lambda d: d[col].astype(str).fillna("").values == str(val)


def time_split(df: pd.DataFrame, train_frac: float = 0.7) -> tuple[pd.DataFrame, pd.DataFrame]:
    d = pd.to_datetime(df["timestamp"]).dt.date
    unique_dates = np.array(sorted(set(d)))
    cutoff = int(len(unique_dates) * train_frac)
    train_dates = set(unique_dates[:cutoff])
    test_dates = set(unique_dates[cutoff:])
    train = df[d.isin(train_dates)].copy()
    test = df[d.isin(test_dates)].copy()
    return train, test


def main():
    df = pd.read_csv(DATA_PATH)
    df = df[df["outcome"].isin(["win", "loss"])].copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    train_df, test_df = time_split(df, 0.7)

    test_dates = np.array(sorted(set(test_df["timestamp"].dt.date)))
    if len(test_dates) >= 4:
        mid = len(test_dates) // 2
        early_dates = set(test_dates[:mid])
        late_dates = set(test_dates[mid:])
        early_test_df = test_df[test_df["timestamp"].dt.date.astype(object).isin(early_dates)].copy()
        late_test_df = test_df[test_df["timestamp"].dt.date.astype(object).isin(late_dates)].copy()
    else:
        early_test_df = test_df
        late_test_df = test_df

    print(f"Trades total={len(df):,}  train={len(train_df):,}  test={len(test_df):,}  early={len(early_test_df):,}  late={len(late_test_df):,}")

    # Build pool of discrete anchors and gates
    top_groups = df["nearest_magnet_group"].dropna().astype(str).value_counts().head(18).index.tolist()
    variants = sorted(df["variant"].dropna().astype(str).unique().tolist())

    conditions: list[Condition] = []

    # context anchors
    for g in top_groups:
        conditions.append(Condition(f"nearest_magnet_group={g}", mask_eq_str("nearest_magnet_group", g)))

    for v in variants:
        conditions.append(Condition(f"variant={v}", mask_eq_str("variant", v)))

    for ddir in ["long", "short"]:
        if (df["direction"].astype(str) == ddir).any():
            conditions.append(Condition(f"direction={ddir}", mask_eq_str("direction", ddir)))

    # availability anchors
    for col in ["path_clear", "magnet_valid", "level_swept_before_entry", "opening_range_swept"]:
        if col in df.columns:
            conditions.append(Condition(f"{col}=True", lambda d, col=col: safe_bool_col(d, col).values))

    # proximity constraints
    for col in ["magnet_within_1R", "magnet_within_2R", "magnet_within_3R"]:
        if col in df.columns:
            conditions.append(Condition(f"{col}=True", lambda d, col=col: safe_bool_col(d, col).values))

    # Single-condition prefilter by PF on test (PF-focused)
    MIN_N_TEST_SINGLE = 12
    MIN_PF_TEST_SINGLE = 1.2

    eligible: list[Condition] = []
    for c in conditions:
        m_tr = c.mask_fn(train_df)
        m_te = c.mask_fn(test_df)
        n_te = int(m_te.sum())
        if n_te < MIN_N_TEST_SINGLE:
            continue
        st_te = compute_stats(test_df.loc[m_te])
        pf = st_te["pf"]
        finite_pf = isinstance(pf, float) and np.isfinite(pf)
        if finite_pf and pf >= MIN_PF_TEST_SINGLE:
            eligible.append(c)

    # Cap eligible for runtime
    eligible.sort(key=lambda c: int(c.mask_fn(test_df).sum()), reverse=True)
    eligible = eligible[:28]

    print(f"Eligible after PF-focused single prefilter: {len(eligible)}")

    # Combo constraints
    MIN_N_TRAIN_COMBO = 220
    MIN_N_TEST_COMBO = 20
    k_values = [3]  # keep PF-focused + fast; optionally expand if too few results

    # Require at least one availability and one context in combo
    avail_names = {"path_clear=True", "magnet_valid=True", "level_swept_before_entry=True", "opening_range_swept=True", "magnet_within_1R=True", "magnet_within_2R=True", "magnet_within_3R=True"}
    ctx_prefixes = ("nearest_magnet_group=", "variant=", "direction=")

    def combo_has_context_avail(combo: tuple[Condition, ...]) -> bool:
        names = [c.name for c in combo]
        has_ctx = any(n.startswith(ctx_prefixes) for n in names)
        has_av = any(n in avail_names or n.startswith("path_clear=") or n.startswith("magnet_valid=") or n.startswith("level_swept_before_entry=") for n in names)
        return has_ctx and has_av

    def pf_ok_late_early(pf_val: object) -> bool:
        if pf_val is None:
            return True
        if isinstance(pf_val, float) and np.isfinite(pf_val):
            return pf_val >= 0.9
        return True

    MAX_EVALS = 90000
    evals = 0
    results: list[dict] = []

    for k in k_values:
        print(f"Enumerating combos k={k} ...")
        for combo in itertools.combinations(eligible, k):
            if evals >= MAX_EVALS:
                break
            if not combo_has_context_avail(combo):
                continue

            evals += 1
            m_tr = np.ones(len(train_df), dtype=bool)
            m_te = np.ones(len(test_df), dtype=bool)
            m_ee = np.ones(len(early_test_df), dtype=bool)
            m_le = np.ones(len(late_test_df), dtype=bool)
            for c in combo:
                m_tr &= c.mask_fn(train_df)
                m_te &= c.mask_fn(test_df)
                m_ee &= c.mask_fn(early_test_df)
                m_le &= c.mask_fn(late_test_df)

            n_tr = int(m_tr.sum()); n_te = int(m_te.sum())
            if n_tr < MIN_N_TRAIN_COMBO or n_te < MIN_N_TEST_COMBO:
                continue

            st_tr = compute_stats(train_df.loc[m_tr])
            st_te = compute_stats(test_df.loc[m_te])
            st_e = compute_stats(early_test_df.loc[m_ee])
            st_l = compute_stats(late_test_df.loc[m_le])

            if not pf_ok_late_early(st_e["pf"]):
                continue
            if not pf_ok_late_early(st_l["pf"]):
                continue

            # PF-focused threshold: keep only test PF >= 1.3 when finite
            pf = st_te["pf"]
            if isinstance(pf, float) and np.isfinite(pf) and pf < 1.3:
                continue

            results.append({
                "k": k,
                "condition": " AND ".join([c.name for c in combo]),
                "test_n": int(st_te["n"]),
                "test_wr": float(st_te["wr"]),
                "test_pf": st_te["pf"],
                "early_n": int(st_e["n"]),
                "early_wr": float(st_e["wr"]),
                "early_pf": st_e["pf"],
                "late_n": int(st_l["n"]),
                "late_wr": float(st_l["wr"]),
                "late_pf": st_l["pf"],
                "train_n": int(st_tr["n"]),
                "train_wr": float(st_tr["wr"]),
                "train_pf": st_tr["pf"],
                "test_total_pnl": float(st_te["total_pnl"]),
            })

    if not results:
        print("No combos passed PF-focused thresholds.")
        out = {"results": [], "notes": {"reason": "no pass"}}
        out_path = OUT_DIR / "iter6_pf_focus.json"
        out_path.write_text(json.dumps(out, indent=2))
        return

    res_df = pd.DataFrame(results)

    # Composite score strongly favors PF, then WR, then log(n)
    def composite(row: pd.Series) -> float:
        pf = row["test_pf"]
        pf_val = pf if (isinstance(pf, float) and np.isfinite(pf)) else 0.0
        wr = row["test_wr"] / 100.0
        n = row["test_n"]
        return (pf_val ** 2) * (wr ** 1.2) * float(np.log(n + 1.0))

    res_df["composite"] = res_df.apply(composite, axis=1)

    res_sorted = res_df.sort_values(["composite", "test_pf", "test_wr", "test_n"], ascending=[False, False, False, False])

    # Pick top lists
    top_pf = res_sorted.head(8).to_dict(orient="records")

    # Also top by occurrence among PF>=1.3 in case PF ties
    occ = res_sorted.sort_values(["test_n", "test_pf"], ascending=[False, False]).head(8).to_dict(orient="records")

    out = {
        "split": {
            "train": "first 70% dates",
            "test": "last 30% dates",
            "early_test": "first half of test dates",
            "late_test": "last half of test dates",
        },
        "constraints": {
            "MIN_N_TRAIN_COMBO": MIN_N_TRAIN_COMBO,
            "MIN_N_TEST_COMBO": MIN_N_TEST_COMBO,
            "MIN_PF_TEST_SINGLE": MIN_PF_TEST_SINGLE,
            "MIN_N_TEST_SINGLE": MIN_N_TEST_SINGLE,
            "MAX_EVALS": MAX_EVALS,
            "pf_collapse_threshold": 0.9,
            "min_pf_for_combo": 1.3,
            "k": k_values,
            "eligible_pool_size": len(eligible),
        },
        "top_by_pf": top_pf,
        "top_by_occ": occ,
        "evaluated_limit": {"evals_attempted": evals, "results_kept": len(results)},
    }

    out_path = OUT_DIR / "iter6_pf_focus.json"
    out_path.write_text(json.dumps(out, indent=2))

    print(f"\nIter6 completed. results_kept={len(results)}  evals_attempted={evals}")
    print("\nTop PF combos:")
    for r in top_pf[:5]:
        print(f"- {r['condition']} | n={r['test_n']} WR={r['test_wr']:.2f}% PF={r['test_pf']} earlyPF={r['early_pf']} latePF={r['late_pf']}")

    print(f"\nWrote: {out_path}")


if __name__ == "__main__":
    main()
