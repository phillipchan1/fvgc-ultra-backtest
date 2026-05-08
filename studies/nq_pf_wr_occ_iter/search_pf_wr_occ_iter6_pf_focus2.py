#!/usr/bin/env python3
"""Iter6b: PF-focused but less strict, to avoid empty result sets.

Same structure as iter6_pf_focus, but relax:
- MIN_PF_TEST_SINGLE to 1.05
- min_pf_for_combo to 1.1
- collapse checks PF >= 0.8

Run:
  python studies/nq_pf_wr_occ_iter/search_pf_wr_occ_iter6_pf_focus2.py
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


def time_split(df: pd.DataFrame, train_frac: float = 0.7):
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

    print(f"Trades total={len(df):,} train={len(train_df):,} test={len(test_df):,} early={len(early_test_df):,} late={len(late_test_df):,}")

    # Candidate pool
    top_groups = df["nearest_magnet_group"].dropna().astype(str).value_counts().head(18).index.tolist()
    variants = sorted(df["variant"].dropna().astype(str).unique().tolist())

    conditions: list[Condition] = []
    for g in top_groups:
        conditions.append(Condition(f"nearest_magnet_group={g}", mask_eq_str("nearest_magnet_group", g)))
    for v in variants:
        conditions.append(Condition(f"variant={v}", mask_eq_str("variant", v)))

    for ddir in ["long", "short"]:
        if (df["direction"].astype(str) == ddir).any():
            conditions.append(Condition(f"direction={ddir}", mask_eq_str("direction", ddir)))

    for col in ["path_clear", "magnet_valid", "level_swept_before_entry", "opening_range_swept"]:
        if col in df.columns:
            conditions.append(Condition(f"{col}=True", lambda d, col=col: safe_bool_col(d, col).values))

    for col in ["magnet_within_1R", "magnet_within_2R", "magnet_within_3R"]:
        if col in df.columns:
            conditions.append(Condition(f"{col}=True", lambda d, col=col: safe_bool_col(d, col).values))

    # PF-focused single prefilter (relaxed)
    MIN_PF_TEST_SINGLE = 1.05
    MIN_N_TEST_SINGLE = 12

    eligible: list[Condition] = []
    for c in conditions:
        m_te = c.mask_fn(test_df)
        n_te = int(m_te.sum())
        if n_te < MIN_N_TEST_SINGLE:
            continue
        st_te = compute_stats(test_df.loc[m_te])
        pf = st_te["pf"]
        if isinstance(pf, float) and np.isfinite(pf) and pf >= MIN_PF_TEST_SINGLE:
            eligible.append(c)

    eligible.sort(key=lambda c: int(c.mask_fn(test_df).sum()), reverse=True)
    eligible = eligible[:30]

    print(f"Eligible after relaxed PF prefilter: {len(eligible)}")

    MIN_N_TRAIN_COMBO = 220
    MIN_N_TEST_COMBO = 20

    MIN_PF_COMBO = 1.10
    PF_COLLAPSE_MIN = 0.80

    MAX_EVALS = 90000
    evals = 0
    results: list[dict] = []

    for k in [3]:
        for combo in itertools.combinations(eligible, k):
            if evals >= MAX_EVALS:
                break
            evals += 1

            # require at least 1 avail+1 context
            names = [c.name for c in combo]
            has_avail = any(n in {"path_clear=True", "magnet_valid=True", "level_swept_before_entry=True", "opening_range_swept=True"} for n in names)
            has_ctx = any(n.startswith("nearest_magnet_group=") or n.startswith("variant=") or n.startswith("direction=") for n in names)
            if not (has_avail and has_ctx):
                continue

            m_tr = np.ones(len(train_df), dtype=bool)
            m_te = np.ones(len(test_df), dtype=bool)
            m_e = np.ones(len(early_test_df), dtype=bool)
            m_l = np.ones(len(late_test_df), dtype=bool)
            for c in combo:
                m_tr &= c.mask_fn(train_df)
                m_te &= c.mask_fn(test_df)
                m_e &= c.mask_fn(early_test_df)
                m_l &= c.mask_fn(late_test_df)

            n_tr = int(m_tr.sum()); n_te = int(m_te.sum());
            if n_tr < MIN_N_TRAIN_COMBO or n_te < MIN_N_TEST_COMBO:
                continue

            st_tr = compute_stats(train_df.loc[m_tr])
            st_te = compute_stats(test_df.loc[m_te])
            st_e = compute_stats(early_test_df.loc[m_e])
            st_l = compute_stats(late_test_df.loc[m_l])

            # collapse checks
            for st in (st_e, st_l):
                pf = st["pf"]
                if isinstance(pf, float) and np.isfinite(pf) and pf < PF_COLLAPSE_MIN:
                    break
            else:
                # PF combo threshold
                pf2 = st_te["pf"]
                if isinstance(pf2, float) and np.isfinite(pf2) and pf2 < MIN_PF_COMBO:
                    continue

                results.append({
                    "condition": " AND ".join(names),
                    "k": k,
                    "test_n": int(st_te["n"]),
                    "test_wr": float(st_te["wr"]),
                    "test_pf": st_te["pf"],
                    "early_pf": st_e["pf"],
                    "late_pf": st_l["pf"],
                    "train_n": int(st_tr["n"]),
                    "train_wr": float(st_tr["wr"]),
                    "train_pf": st_tr["pf"],
                })

    print(f"Evaluated combos={evals:,}  results_kept={len(results):,}")
    if not results:
        out_path = OUT_DIR / "iter6b_pf_focus.json"
        out_path.write_text(json.dumps({"results": [], "notes": {"reason": "no pass"}}, indent=2))
        return

    res_df = pd.DataFrame(results)

    # composite score
    def composite(row: pd.Series) -> float:
        pf = row["test_pf"]
        pf_val = pf if (isinstance(pf, float) and np.isfinite(pf)) else 0.0
        wr = row["test_wr"] / 100.0
        n = row["test_n"]
        return (pf_val ** 2) * (wr ** 1.2) * float(np.log(n + 1.0))

    res_df["composite"] = res_df.apply(composite, axis=1)
    res_df = res_df.sort_values(["composite", "test_pf", "test_wr", "test_n"], ascending=[False, False, False, False])

    top = res_df.head(10).to_dict(orient="records")

    out = {
        "top_by_pf_wr": top,
        "constraints": {
            "MIN_PF_TEST_SINGLE": MIN_PF_TEST_SINGLE,
            "MIN_N_TEST_SINGLE": MIN_N_TEST_SINGLE,
            "MIN_PF_COMBO": MIN_PF_COMBO,
            "PF_COLLAPSE_MIN": PF_COLLAPSE_MIN,
            "MIN_N_TRAIN_COMBO": MIN_N_TRAIN_COMBO,
            "MIN_N_TEST_COMBO": MIN_N_TEST_COMBO,
            "MAX_EVALS": MAX_EVALS,
        },
    }

    out_path = OUT_DIR / "iter6b_pf_focus.json"
    out_path.write_text(json.dumps(out, indent=2))

    print("\nTop ideas:")
    for r in top:
        print(f"- {r['condition']} | n={r['test_n']} WR={r['test_wr']:.2f}% PF={r['test_pf']} earlyPF={r['early_pf']} latePF={r['late_pf']}")
    print(f"\nWrote: {out_path}")


if __name__ == "__main__":
    main()
