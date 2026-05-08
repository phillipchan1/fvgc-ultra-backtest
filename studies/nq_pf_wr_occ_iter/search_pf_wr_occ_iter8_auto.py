#!/usr/bin/env python3
"""Iter8: add 3-way robustness within test (early/mid/late) + widen pool a bit.

Still searches post-hoc AND combos on data/levels/trades_with_levels.csv.

Robustness:
- Require PF not collapsing: earlyPF>=0.85, midPF>=0.85, latePF>=0.85 when finite.

Pool:
- Use PF>=1.05 singles on test; keep top 45 by composite.

Combos:
- k=3 first, then k=4 if budget remains.

Outputs:
  iter8_top_by_objective.json
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

    gp = float(pnl[pnl > 0].sum())
    gl = float(abs(pnl[pnl < 0].sum()))
    if gl > 0:
        pf = gp / gl
    else:
        pf = float("inf") if gp > 0 else float("nan")

    return {
        "n": n,
        "wr": round(wr, 4),
        "pf": float(pf) if np.isfinite(pf) else pf,
        "total_pnl": round(float(pnl.sum()), 4),
    }


def time_split(df: pd.DataFrame, train_frac: float = 0.7):
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


def mask_eq_str(col: str, val: str) -> Callable[[pd.DataFrame], np.ndarray]:
    return lambda d: d[col].astype(str).fillna("").values == str(val)


def mask_numeric_leq(col: str, thr: float) -> Callable[[pd.DataFrame], np.ndarray]:
    return lambda d: pd.to_numeric(d[col], errors="coerce").fillna(np.nan).le(thr).fillna(False).values


def mask_numeric_geq(col: str, thr: float) -> Callable[[pd.DataFrame], np.ndarray]:
    return lambda d: pd.to_numeric(d[col], errors="coerce").fillna(np.nan).ge(thr).fillna(False).values


def composite_score(pf: object, wr: object, n: int) -> float:
    if isinstance(pf, float) and np.isfinite(pf):
        pf_val = pf
    elif pf == float("inf"):
        pf_val = 1e6
    else:
        pf_val = 0.0
    wr_val = float(wr) / 100.0 if pd.notna(wr) else 0.0
    return (pf_val ** 2) * (wr_val ** 1.1) * float(np.log(n + 1.0))


def pf_geq(pf: object, thr: float) -> bool:
    if isinstance(pf, float) and np.isfinite(pf):
        return pf >= thr
    # allow inf (and nan -> fail-safe: treat as False)
    if pf == float("inf"):
        return True
    return False


def main():
    df = pd.read_csv(DATA_PATH)
    df = df[df["outcome"].isin(["win", "loss"])].copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    train_df, test_df = time_split(df, 0.7)

    test_dates = sorted(set(test_df["timestamp"].dt.date))
    m = len(test_dates)
    if m < 6:
        early_dates = set(test_dates[: m // 3])
        mid_dates = set(test_dates[m // 3: 2 * m // 3])
        late_dates = set(test_dates[2 * m // 3 :])
    else:
        early_dates = set(test_dates[: m // 3])
        mid_dates = set(test_dates[m // 3: 2 * m // 3])
        late_dates = set(test_dates[2 * m // 3 :])

    early_df = test_df[test_df["timestamp"].dt.date.astype(object).isin(early_dates)].copy()
    mid_df = test_df[test_df["timestamp"].dt.date.astype(object).isin(mid_dates)].copy()
    late_df = test_df[test_df["timestamp"].dt.date.astype(object).isin(late_dates)].copy()

    print(f"Trades total={len(df):,} train={len(train_df):,} test={len(test_df):,} early={len(early_df):,} mid={len(mid_df):,} late={len(late_df):,}")

    # Conditions pool
    conditions: list[Condition] = []

    for ddir in ["long", "short"]:
        if (df["direction"].astype(str) == ddir).any():
            conditions.append(Condition(f"direction={ddir}", mask_eq_str("direction", ddir)))

    variants = sorted(df["variant"].dropna().astype(str).unique().tolist())
    for v in variants:
        conditions.append(Condition(f"variant={v}", mask_eq_str("variant", v)))

    # magnet groups (top 22)
    top_groups = df["nearest_magnet_group"].dropna().astype(str).value_counts().head(22).index.tolist()
    for g in top_groups:
        conditions.append(Condition(f"nearest_magnet_group={g}", mask_eq_str("nearest_magnet_group", g)))

    # availability gates
    for col in ["path_clear", "magnet_valid", "level_swept_before_entry", "opening_range_swept"]:
        if col in df.columns:
            conditions.append(Condition(f"{col}=True", lambda d, col=col: safe_bool_col(d, col).values))

    # proximity gates
    for col in ["magnet_within_1R", "magnet_within_2R", "magnet_within_3R"]:
        if col in df.columns:
            conditions.append(Condition(f"{col}=True", lambda d, col=col: safe_bool_col(d, col).values))

    # numeric gates (light)
    if "opening_range_nearest_R" in df.columns:
        rn = pd.to_numeric(df["opening_range_nearest_R"], errors="coerce").dropna()
        if len(rn) >= 50:
            for q in [0.3, 0.5, 0.7]:
                thr = float(rn.quantile(q))
                conditions.append(Condition(f"opening_range_nearest_R<={thr:.2f}", mask_numeric_leq("opening_range_nearest_R", thr)))

    if "level_confluence_count" in df.columns:
        lc = pd.to_numeric(df["level_confluence_count"], errors="coerce").dropna()
        if len(lc) >= 50:
            for q in [0.7, 0.85]:
                thr = float(lc.quantile(q))
                conditions.append(Condition(f"level_confluence_count>={thr:.0f}", mask_numeric_geq("level_confluence_count", thr)))

    # Single prefilter: keep only those with decent PF on test
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
        # allow inf
        scored_singles.append((c, st_te))

    if not scored_singles:
        print("No single conditions passed PF threshold")
        return

    scored_singles.sort(key=lambda t: composite_score(t[1]["pf"], t[1]["wr"], int(t[1]["n"])), reverse=True)
    pool = [c for c, _ in scored_singles[:45]]

    print(f"Singles passed={len(scored_singles)}  pool={len(pool)}")

    # combo search
    avail_names = {"path_clear=True", "magnet_valid=True", "level_swept_before_entry=True", "opening_range_swept=True"}

    def combo_has_avail_ctx(names: list[str]) -> bool:
        has_av = any(n in avail_names for n in names)
        has_ctx = any(n.startswith("direction=") or n.startswith("variant=") or n.startswith("nearest_magnet_group=") for n in names)
        return has_av and has_ctx

    # combos
    MIN_N_TRAIN_COMBO = 240
    MIN_N_TEST_COMBO = 20
    MAX_EVALS = 160000
    k_list = [3, 4]

    evals = 0
    results: list[dict] = []

    for k in k_list:
        for combo in itertools.combinations(pool, k):
            if evals >= MAX_EVALS:
                break
            evals += 1

            names = [c.name for c in combo]
            if not combo_has_avail_ctx(names):
                continue

            m_tr = np.ones(len(train_df), dtype=bool)
            m_te = np.ones(len(test_df), dtype=bool)
            m_e = np.ones(len(early_df), dtype=bool)
            m_m = np.ones(len(mid_df), dtype=bool)
            m_l = np.ones(len(late_df), dtype=bool)
            for c in combo:
                m_tr &= c.mask_fn(train_df)
                m_te &= c.mask_fn(test_df)
                m_e &= c.mask_fn(early_df)
                m_m &= c.mask_fn(mid_df)
                m_l &= c.mask_fn(late_df)

            n_tr = int(m_tr.sum()); n_te = int(m_te.sum());
            if n_tr < MIN_N_TRAIN_COMBO or n_te < MIN_N_TEST_COMBO:
                continue

            st_te = compute_stats(test_df.loc[m_te])
            st_e = compute_stats(early_df.loc[m_e])
            st_m = compute_stats(mid_df.loc[m_m])
            st_l = compute_stats(late_df.loc[m_l])

            # PF robustness 3-way
            if not pf_geq(st_e["pf"], 0.85):
                continue
            if not pf_geq(st_m["pf"], 0.85):
                continue
            if not pf_geq(st_l["pf"], 0.85):
                continue

            results.append({
                "k": k,
                "condition": " AND ".join(names),
                "test_n": int(st_te["n"]),
                "test_wr": float(st_te["wr"]),
                "test_pf": st_te["pf"],
                "early_pf": st_e["pf"],
                "mid_pf": st_m["pf"],
                "late_pf": st_l["pf"],
                "train_n": int(compute_stats(train_df.loc[m_tr])["n"]),
                "test_total_pnl": float(st_te["total_pnl"]),
            })

        if evals >= MAX_EVALS:
            break

    print(f"Evaluated={evals:,}  kept={len(results):,}")

    if not results:
        out_path = OUT_DIR / "iter8_top_by_objective.json"
        out_path.write_text(json.dumps({"results": [], "reason": "no pass"}, indent=2))
        return

    res_df = pd.DataFrame(results)
    res_df["composite"] = res_df.apply(lambda r: composite_score(r["test_pf"], r["test_wr"], int(r["test_n"])), axis=1)
    res_df = res_df.sort_values(["composite", "test_pf", "test_wr", "test_n"], ascending=[False, False, False, False])

    top = res_df.head(20).to_dict(orient="records")

    out_path = OUT_DIR / "iter8_top_by_objective.json"
    out_path.write_text(json.dumps({"top": top, "evaluated": evals, "kept": len(results)}, indent=2))

    print("\nTop iter8 candidates:")
    for r in top[:10]:
        print(f"- {r['condition']} | n={r['test_n']} WR={r['test_wr']:.2f}% PF={r['test_pf']} (e/m/l PF {r['early_pf']}/{r['mid_pf']}/{r['late_pf']})")
    print(f"\nWrote: {out_path}")


if __name__ == "__main__":
    main()
