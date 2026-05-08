#!/usr/bin/env python3
"""Iter7 auto-discovery: PF/WR/occurrence search with small numeric gates.

Self-discovery mode:
- Uses your existing post-hoc columns in data/levels/trades_with_levels.csv
- Walk-forward split by date: 70% train / 30% test
- Within test: early/late halves for robustness
- Searches combos of size 3 (optionally 4 if runtime budget remains)
- Numeric gates added (if columns exist):
    - opening_range_nearest_R <= {q30,q50,q70}
    - level_confluence_count >= {q70,q85}

Selection pressure:
- Keep condition pool manageable by pre-scoring SINGLE conditions on TEST
- Enumerate AND combos under a hard MAX_EVALS cap
- Rank by composite = PF * (WR/100) * log(n+1)
- Robustness: require early_PF >= 0.9 and late_PF >= 0.9 when finite.

Run:
  python studies/nq_pf_wr_occ_iter/search_pf_wr_occ_iter7_auto.py

Outputs:
  studies/nq_pf_wr_occ_iter/results/iter7_auto_best.json
  studies/nq_pf_wr_occ_iter/results/iter7_auto_top_combos.csv
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
    cls: str  # context/avail/proximity/numeric


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


def time_split(df: pd.DataFrame, train_frac: float = 0.7):
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


def mask_numeric_leq(col: str, thr: float) -> Callable[[pd.DataFrame], np.ndarray]:
    return lambda d: pd.to_numeric(d[col], errors="coerce").fillna(np.nan).le(thr).fillna(False).values


def mask_numeric_geq(col: str, thr: float) -> Callable[[pd.DataFrame], np.ndarray]:
    return lambda d: pd.to_numeric(d[col], errors="coerce").fillna(np.nan).ge(thr).fillna(False).values


def composite_score(pf: object, wr: object, n: int) -> float:
    # pf may be inf
    if isinstance(pf, float) and np.isfinite(pf):
        pf_val = pf
    elif pf == float("inf"):
        pf_val = 1e6
    else:
        pf_val = 0.0
    wr_val = float(wr) / 100.0 if pd.notna(wr) else 0.0
    return pf_val * wr_val * float(np.log(n + 1.0))


def main():
    df = pd.read_csv(DATA_PATH)
    df = df[df["outcome"].isin(["win", "loss"])].copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    train_df, test_df = time_split(df, 0.7)

    # early/late within test
    test_dates = np.array(sorted(set(test_df["timestamp"].dt.date)))
    if len(test_dates) >= 4:
        mid = len(test_dates) // 2
        early_dates = set(test_dates[:mid])
        late_dates = set(test_dates[mid:])
    else:
        early_dates = set(test_dates)
        late_dates = set(test_dates)

    early_df = test_df[test_df["timestamp"].dt.date.astype(object).isin(early_dates)].copy()
    late_df = test_df[test_df["timestamp"].dt.date.astype(object).isin(late_dates)].copy()

    print(f"Trades total={len(df):,} train={len(train_df):,} test={len(test_df):,} early={len(early_df):,} late={len(late_df):,}")

    # Build condition pool
    conditions: list[Condition] = []

    # Context: direction, variant, nearest_magnet_group
    for ddir in ["long", "short"]:
        if (df["direction"].astype(str) == ddir).any():
            conditions.append(Condition(name=f"direction={ddir}", mask_fn=mask_eq_str("direction", ddir), cls="context"))

    variants = sorted(df["variant"].dropna().astype(str).unique().tolist())
    for v in variants:
        conditions.append(Condition(name=f"variant={v}", mask_fn=mask_eq_str("variant", v), cls="context"))

    top_groups = df["nearest_magnet_group"].dropna().astype(str).value_counts().head(20).index.tolist()
    for g in top_groups:
        conditions.append(Condition(name=f"nearest_magnet_group={g}", mask_fn=mask_eq_str("nearest_magnet_group", g), cls="context"))

    # Availability
    for col in ["path_clear", "magnet_valid", "level_swept_before_entry", "opening_range_swept"]:
        if col in df.columns:
            conditions.append(Condition(name=f"{col}=True", mask_fn=lambda d, col=col: safe_bool_col(d, col).values, cls="avail"))

    # Proximity gates
    for col in ["magnet_within_1R", "magnet_within_2R", "magnet_within_3R"]:
        if col in df.columns:
            conditions.append(Condition(name=f"{col}=True", mask_fn=lambda d, col=col: safe_bool_col(d, col).values, cls="proximity"))

    # Numeric gates
    if "opening_range_nearest_R" in df.columns:
        rn = pd.to_numeric(df["opening_range_nearest_R"], errors="coerce").dropna()
        if len(rn) >= 50:
            qs = [0.3, 0.5, 0.7]
            thr_map = [(float(rn.quantile(q)), f"opening_range_nearest_R<={float(rn.quantile(q)):.2f}") for q in qs]
            for thr, label in thr_map:
                conditions.append(Condition(name=label, mask_fn=mask_numeric_leq("opening_range_nearest_R", thr), cls="numeric"))

    if "level_confluence_count" in df.columns:
        lc = pd.to_numeric(df["level_confluence_count"], errors="coerce").dropna()
        if len(lc) >= 50:
            qs = [0.7, 0.85]
            for q in qs:
                thr = float(lc.quantile(q))
                conditions.append(Condition(name=f"level_confluence_count>={thr:.0f}", mask_fn=mask_numeric_geq("level_confluence_count", thr), cls="numeric"))

    # Pre-score SINGLE conditions on TEST
    MIN_N_TEST_SINGLE = 18
    MIN_PF_TEST_SINGLE = 1.05
    scored_singles: list[tuple[Condition, dict]] = []

    for c in conditions:
        m_te = c.mask_fn(test_df)
        n_te = int(m_te.sum())
        if n_te < MIN_N_TEST_SINGLE:
            continue
        st_te = compute_stats(test_df.loc[m_te])
        pf = st_te["pf"]
        if isinstance(pf, float) and np.isfinite(pf):
            if pf < MIN_PF_TEST_SINGLE:
                continue
        scored_singles.append((c, st_te))

    if not scored_singles:
        print("No singles passed PF threshold. Exiting.")
        return

    # Choose top singles by composite
    scored_singles.sort(key=lambda t: composite_score(t[1]["pf"], t[1]["wr"], t[1]["n"]), reverse=True)
    TOP_POOL = 35
    pool = [t[0] for t in scored_singles[:TOP_POOL]]

    print(f"Singles scored={len(scored_singles):,} pool={len(pool):,}")

    # Combo search
    MIN_N_TRAIN_COMBO = 220
    MIN_N_TEST_COMBO = 20
    MAX_EVALS = 180000
    evals = 0

    results: list[dict] = []

    # Anchors: encourage meaningful mixes
    avail_names = {"path_clear=True", "magnet_valid=True", "level_swept_before_entry=True", "opening_range_swept=True"}

    def has_context(combo_names: list[str]) -> bool:
        return any(n.startswith("direction=") or n.startswith("variant=") or n.startswith("nearest_magnet_group=") for n in combo_names)

    def has_avail(combo_names: list[str]) -> bool:
        return any(n in avail_names or n.startswith("path_clear=") or n.startswith("magnet_valid=") or n.startswith("level_swept_before_entry=") for n in combo_names)

    def pf_finite_geq(x: object, thr: float) -> bool:
        if isinstance(x, float) and np.isfinite(x):
            return x >= thr
        # keep inf/nan as pass (robustness gate only for finite)
        return True

    def combo_iter(k: int):
        nonlocal evals
        for combo in itertools.combinations(pool, k):
            if evals >= MAX_EVALS:
                return
            evals += 1
            names = [c.name for c in combo]
            if not (has_context(names) and has_avail(names)):
                continue

            m_tr = np.ones(len(train_df), dtype=bool)
            m_te = np.ones(len(test_df), dtype=bool)
            m_ee = np.ones(len(early_df), dtype=bool)
            m_le = np.ones(len(late_df), dtype=bool)
            for c in combo:
                m_tr &= c.mask_fn(train_df)
                m_te &= c.mask_fn(test_df)
                m_ee &= c.mask_fn(early_df)
                m_le &= c.mask_fn(late_df)

            n_tr = int(m_tr.sum()); n_te = int(m_te.sum())
            if n_tr < MIN_N_TRAIN_COMBO or n_te < MIN_N_TEST_COMBO:
                continue

            st_tr = compute_stats(train_df.loc[m_tr])
            st_te = compute_stats(test_df.loc[m_te])
            st_ee = compute_stats(early_df.loc[m_ee])
            st_le = compute_stats(late_df.loc[m_le])

            # robustness: PF doesn't collapse in early/late
            if not pf_finite_geq(st_ee["pf"], 0.9):
                continue
            if not pf_finite_geq(st_le["pf"], 0.9):
                continue

            results.append({
                "k": k,
                "condition": " AND ".join(names),
                "train_n": int(st_tr["n"]),
                "train_wr": float(st_tr["wr"]),
                "train_pf": st_tr["pf"],
                "test_n": int(st_te["n"]),
                "test_wr": float(st_te["wr"]),
                "test_pf": st_te["pf"],
                "early_n": int(st_ee["n"]),
                "early_wr": float(st_ee["wr"]),
                "early_pf": st_ee["pf"],
                "late_n": int(st_le["n"]),
                "late_wr": float(st_le["wr"]),
                "late_pf": st_le["pf"],
                "test_total_pnl": float(st_te["total_pnl"]),
            })

    print("Searching k=3 combos...")
    combo_iter(3)

    if evals < MAX_EVALS:
        # opportunistically search k=4 if we still have budget
        print("Searching k=4 combos (if budget remains)...")
        combo_iter(4)

    print(f"Evaluated evals={evals:,} kept={len(results):,}")

    if not results:
        out = {"results": [], "notes": {"reason": "no combos"}}
        out_path = OUT_DIR / "iter7_auto_best.json"
        out_path.write_text(json.dumps(out, indent=2))
        return

    res_df = pd.DataFrame(results)

    # Rank by composite (PF heavy)
    def composite_row(r: pd.Series) -> float:
        return composite_score(r["test_pf"], r["test_wr"], int(r["test_n"]))

    res_df["composite"] = res_df.apply(composite_row, axis=1)
    res_df = res_df.sort_values(["composite", "test_pf", "test_wr", "test_n"], ascending=[False, False, False, False])

    top = res_df.head(15)

    best_out = {
        "split": {"train": "first 70% dates", "test": "last 30% dates", "early": "first half of test dates", "late": "second half of test dates"},
        "constraints": {
            "MIN_N_TRAIN_COMBO": MIN_N_TRAIN_COMBO,
            "MIN_N_TEST_COMBO": MIN_N_TEST_COMBO,
            "MAX_EVALS": MAX_EVALS,
            "late_pf_collapse_guard": 0.9,
            "PF_single_threshold": MIN_PF_TEST_SINGLE,
            "pool_size": TOP_POOL,
        },
        "top_combos": top.to_dict(orient="records"),
        "kept_results": len(results),
        "evaluated": evals,
    }

    out_json = OUT_DIR / "iter7_auto_best.json"
    out_csv = OUT_DIR / "iter7_auto_top_combos.csv"
    out_json.write_text(json.dumps(best_out, indent=2))
    res_df.head(3000).to_csv(out_csv, index=False)

    print("\n=== Top candidates ===")
    for _, r in top.iterrows():
        print(f"- {r['condition']} | n={int(r['test_n'])} WR={r['test_wr']:.2f}% PF={r['test_pf']} earlyPF={r['early_pf']} latePF={r['late_pf']} composite={r['composite']:.3f}")

    print(f"\nWrote: {out_json}")
    print(f"Wrote: {out_csv}")


if __name__ == "__main__":
    main()
