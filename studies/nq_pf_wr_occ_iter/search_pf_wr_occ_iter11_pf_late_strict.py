#!/usr/bin/env python3
"""Iter11: PF-late strict discovery, k=4 only (bounded).

Goal: push PF upward while preserving decent WR and some occurrence.

- Walk-forward 70/30 by date
- Robustness: only require late_pf >= late_pf_min when finite
- Enumerate AND combos of size k=4 only
- Pool: select top single conditions by test composite (PF-heavy)
- Caps to keep runtime bounded

Run:
  python studies/nq_pf_wr_occ_iter/search_pf_wr_occ_iter11_pf_late_strict.py

Outputs:
  studies/nq_pf_wr_occ_iter/results/iter11_pf_late_strict.json
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

    pf = (gp / gl) if gl > 0 else (float("inf") if gp > 0 else np.nan)

    return {"n": n, "wr": round(wr, 4), "pf": float(pf) if np.isfinite(pf) else pf, "total_pnl": round(float(pnl.sum()), 4)}


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


def composite_score(pf: object, wr: float, n: int) -> float:
    if isinstance(pf, float) and np.isfinite(pf):
        pf_val = pf
    elif pf == float("inf"):
        pf_val = 1e6
    else:
        pf_val = 0.0
    wr_val = float(wr) / 100.0 if pd.notna(wr) else 0.0
    return pf_val * (wr_val ** 1.2) * float(np.log(n + 1.0))


def pf_check_finite_geq(pf: object, thr: float) -> bool:
    # accept inf
    if pf == float('inf'):
        return True
    return isinstance(pf, float) and np.isfinite(pf) and pf >= thr


def main():
    # thresholds
    late_pf_min = 1.15
    test_pf_min = 1.10
    k = 4
    eligible_pool_cap = 18
    max_evals = 80000
    MIN_N_TEST_SINGLE = 16

    df = pd.read_csv(DATA_PATH)
    df = df[df["outcome"].isin(["win", "loss"])].copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    train_df, test_df = time_split(df, 0.7)

    test_dates = sorted(set(test_df["timestamp"].dt.date))
    if len(test_dates) >= 4:
        mid = len(test_dates)//2
        late_dates = set(test_dates[mid:])
    else:
        late_dates = set(test_dates)
    late_df = test_df[test_df["timestamp"].dt.date.astype(object).isin(late_dates)].copy()

    print(f"Trades total={len(df):,} train={len(train_df):,} test={len(test_df):,} late={len(late_df):,}")

    # build conditions (same core pool as earlier)
    conditions: list[Condition] = []

    for ddir in ["long", "short"]:
        if (df["direction"].astype(str) == ddir).any():
            conditions.append(Condition(f"direction={ddir}", mask_eq_str("direction", ddir)))

    variants = sorted(df["variant"].dropna().astype(str).unique().tolist())
    for v in variants:
        conditions.append(Condition(f"variant={v}", mask_eq_str("variant", v)))

    top_groups = df["nearest_magnet_group"].dropna().astype(str).value_counts().head(22).index.tolist()
    for g in top_groups:
        conditions.append(Condition(f"nearest_magnet_group={g}", mask_eq_str("nearest_magnet_group", g)))

    for col in ["path_clear", "magnet_valid", "level_swept_before_entry", "opening_range_swept"]:
        if col in df.columns:
            conditions.append(Condition(f"{col}=True", lambda d, col=col: safe_bool_col(d, col).values))

    for col in ["magnet_within_1R", "magnet_within_2R", "magnet_within_3R"]:
        if col in df.columns:
            conditions.append(Condition(f"{col}=True", lambda d, col=col: safe_bool_col(d, col).values))

    # numeric light gates
    if "opening_range_nearest_R" in df.columns:
        rn = pd.to_numeric(df["opening_range_nearest_R"], errors='coerce').dropna()
        if len(rn) >= 80:
            for q in [0.4, 0.6, 0.8]:
                thr = float(rn.quantile(q))
                conditions.append(Condition(f"opening_range_nearest_R<={thr:.2f}", lambda d, thr=thr: pd.to_numeric(d['opening_range_nearest_R'], errors='coerce').fillna(np.nan).le(thr).fillna(False).values))

    # preselect eligible pool by test_pf
    scored_singles: list[tuple[Condition, dict]] = []
    for c in conditions:
        m_te = c.mask_fn(test_df)
        n_te = int(m_te.sum())
        if n_te < MIN_N_TEST_SINGLE:
            continue
        st_te = compute_stats(test_df.loc[m_te])
        if isinstance(st_te['pf'], float) and np.isfinite(st_te['pf']) and st_te['pf'] < test_pf_min:
            continue
        scored_singles.append((c, st_te))

    if not scored_singles:
        out_path = OUT_DIR / "iter11_pf_late_strict.json"
        out_path.write_text(json.dumps({"results": [], "reason": "no singles"}, indent=2))
        return

    scored_singles.sort(key=lambda t: composite_score(t[1]['pf'], t[1]['wr'], int(t[1]['n'])), reverse=True)
    pool = [c for c, _ in scored_singles[:eligible_pool_cap]]

    print(f"Singles eligible={len(scored_singles)} pool={len(pool)}")

    # combo search
    avail_names = {"path_clear=True", "magnet_valid=True", "level_swept_before_entry=True", "opening_range_swept=True",
                   "magnet_within_1R=True", "magnet_within_2R=True", "magnet_within_3R=True"}

    def has_avail_ctx(names: list[str]) -> bool:
        has_avail = any(n in avail_names or n.startswith('path_clear=') or n.startswith('magnet_valid=') for n in names)
        has_ctx = any(n.startswith('direction=') or n.startswith('variant=') or n.startswith('nearest_magnet_group=') for n in names)
        return has_avail and has_ctx

    results: list[dict] = []
    evals = 0

    MIN_N_TRAIN_COMBO = 240
    MIN_N_TEST_COMBO = 20

    for combo in itertools.combinations(pool, k):
        if evals >= max_evals:
            break
        evals += 1

        names = [c.name for c in combo]
        if not has_avail_ctx(names):
            continue

        m_tr = np.ones(len(train_df), dtype=bool)
        m_te = np.ones(len(test_df), dtype=bool)
        m_lt = np.ones(len(late_df), dtype=bool)
        for c in combo:
            m_tr &= c.mask_fn(train_df)
            m_te &= c.mask_fn(test_df)
            m_lt &= c.mask_fn(late_df)

        n_tr = int(m_tr.sum()); n_te = int(m_te.sum()); n_lt = int(m_lt.sum())
        if n_tr < MIN_N_TRAIN_COMBO or n_te < MIN_N_TEST_COMBO:
            continue

        st_te = compute_stats(test_df.loc[m_te])
        st_lt = compute_stats(late_df.loc[m_lt])

        if not pf_check_finite_geq(st_lt['pf'], late_pf_min):
            continue

        st_tr = compute_stats(train_df.loc[m_tr])

        results.append({
            "condition": " AND ".join(names),
            "k": k,
            "train_n": n_tr,
            "train_wr": st_tr['wr'],
            "train_pf": st_tr['pf'],
            "test_n": n_te,
            "test_wr": st_te['wr'],
            "test_pf": st_te['pf'],
            "late_n": n_lt,
            "late_pf": st_lt['pf'],
            "late_wr": st_lt['wr'],
            "test_total_pnl": st_te['total_pnl'],
            "composite": composite_score(st_te['pf'], st_te['wr'], n_te),
        })

    if not results:
        out_path = OUT_DIR / "iter11_pf_late_strict.json"
        out_path.write_text(json.dumps({"results": [], "evaluated": evals, "reason": "no combos passed late PF gate"}, indent=2))
        return

    res_df = pd.DataFrame(results)
    res_df = res_df.sort_values(["composite", "test_pf", "test_wr"], ascending=[False, False, False])
    top = res_df.head(15).to_dict(orient='records')

    out_path = OUT_DIR / "iter11_pf_late_strict.json"
    out_path.write_text(json.dumps({
        "params": {
            "late_pf_min": late_pf_min,
            "test_pf_min": test_pf_min,
            "k": k,
            "pool": len(pool),
            "eligible_pool_cap": eligible_pool_cap,
            "max_evals": max_evals,
        },
        "evaluated": evals,
        "kept": len(results),
        "top": top,
    }, indent=2))

    print(f"Iter11 done. evaluated={evals:,} kept={len(results):,}")
    print("Top:")
    for r in top[:8]:
        print(f"- {r['condition']} | test n={r['test_n']} WR={r['test_wr']:.2f}% PF={r['test_pf']} latePF={r['late_pf']}")
    print(f"Wrote: {out_path}")


if __name__ == "__main__":
    main()
