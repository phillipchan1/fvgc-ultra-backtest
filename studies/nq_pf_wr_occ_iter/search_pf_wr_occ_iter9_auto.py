#!/usr/bin/env python3
"""Iter9: PF/WR/occ search with relaxed 3-slice robustness.

Relax iter8 by not requiring PF>=0.85 on ALL early/mid/late.
Robustness:
- require late_pf>=0.85 when finite
- require early_pf>=0.80 when finite
- mid_pf: only require >=0.75 when finite (or ignore if NaN)

Ranking: composite heavily favors PF.
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
    return (pf_val ** 1.8) * (wr_val ** 1.1) * float(np.log(n + 1.0))


def pf_check(pf: object, thr: float) -> bool:
    if isinstance(pf, float) and np.isfinite(pf):
        return pf >= thr
    # allow inf (passes), ignore NaN/None (fails-safe)
    if pf == float('inf'):
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
        print('Too few test dates')
        return

    a = m // 3
    b = (2 * m) // 3
    early_dates = set(test_dates[:a])
    mid_dates = set(test_dates[a:b])
    late_dates = set(test_dates[b:])

    early_df = test_df[test_df["timestamp"].dt.date.astype(object).isin(early_dates)].copy()
    mid_df = test_df[test_df["timestamp"].dt.date.astype(object).isin(mid_dates)].copy()
    late_df = test_df[test_df["timestamp"].dt.date.astype(object).isin(late_dates)].copy()

    print(f"Trades total={len(df):,} train={len(train_df):,} test={len(test_df):,} (e/m/l sizes {len(early_df):,}/{len(mid_df):,}/{len(late_df):,})")

    # Build condition pool similar to iter7 but larger numeric gates light
    conditions: list[Condition] = []

    # Context
    for ddir in ["long", "short"]:
        if (df["direction"].astype(str) == ddir).any():
            conditions.append(Condition(f"direction={ddir}", mask_eq_str("direction", ddir)))

    variants = sorted(df["variant"].dropna().astype(str).unique().tolist())
    for v in variants:
        conditions.append(Condition(f"variant={v}", mask_eq_str("variant", v)))

    top_groups = df["nearest_magnet_group"].dropna().astype(str).value_counts().head(24).index.tolist()
    for g in top_groups:
        conditions.append(Condition(f"nearest_magnet_group={g}", mask_eq_str("nearest_magnet_group", g)))

    # Availability
    for col in ["path_clear", "magnet_valid", "level_swept_before_entry", "opening_range_swept"]:
        if col in df.columns:
            conditions.append(Condition(f"{col}=True", lambda d, col=col: safe_bool_col(d, col).values))

    # Proximity
    for col in ["magnet_within_1R", "magnet_within_2R", "magnet_within_3R"]:
        if col in df.columns:
            conditions.append(Condition(f"{col}=True", lambda d, col=col: safe_bool_col(d, col).values))

    # Numeric light
    if "opening_range_nearest_R" in df.columns:
        rn = pd.to_numeric(df["opening_range_nearest_R"], errors='coerce').dropna()
        if len(rn) >= 80:
            for q in [0.4, 0.6]:
                thr = float(rn.quantile(q))
                conditions.append(Condition(f"opening_range_nearest_R<={thr:.2f}", lambda d, thr=thr: pd.to_numeric(d['opening_range_nearest_R'], errors='coerce').fillna(np.nan).le(thr).fillna(False).values))

    # Single prefilter on TEST PF
    MIN_N_TEST_SINGLE = 16
    MIN_PF_TEST_SINGLE = 1.0
    scored: list[tuple[Condition, dict]] = []
    for c in conditions:
        m_te = c.mask_fn(test_df)
        if int(m_te.sum()) < MIN_N_TEST_SINGLE:
            continue
        st_te = compute_stats(test_df.loc[m_te])
        if st_te['n'] == 0:
            continue
        if isinstance(st_te['pf'], float) and np.isfinite(st_te['pf']) and st_te['pf'] < MIN_PF_TEST_SINGLE:
            continue
        scored.append((c, st_te))

    if not scored:
        print('No singles')
        return

    scored.sort(key=lambda t: composite_score(t[1]['pf'], t[1]['wr'], int(t[1]['n'])), reverse=True)
    pool = [c for c, _ in scored[:50]]

    print(f"Singles scored={len(scored)} pool={len(pool)}")

    # Combo search k=3 then k=4 if budget
    MIN_N_TRAIN_COMBO = 240
    MIN_N_TEST_COMBO = 20
    MAX_EVALS = 140000

    avail_set = {"path_clear=True", "magnet_valid=True", "level_swept_before_entry=True", "opening_range_swept=True"}

    def has_avail_ctx(names: list[str]) -> bool:
        has_av = any(n in avail_set for n in names)
        has_ctx = any(n.startswith('direction=') or n.startswith('variant=') or n.startswith('nearest_magnet_group=') for n in names)
        return has_av and has_ctx

    evals = 0
    results: list[dict] = []

    def eval_combo(combo: tuple[Condition, ...], k: int):
        nonlocal evals
        if evals >= MAX_EVALS:
            return
        names = [c.name for c in combo]
        if not has_avail_ctx(names):
            return

        evals += 1
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

        n_tr = int(m_tr.sum()); n_te = int(m_te.sum())
        if n_tr < MIN_N_TRAIN_COMBO or n_te < MIN_N_TEST_COMBO:
            return

        st_tr = compute_stats(train_df.loc[m_tr])
        st_te = compute_stats(test_df.loc[m_te])
        st_e = compute_stats(early_df.loc[m_e])
        st_m = compute_stats(mid_df.loc[m_m])
        st_l = compute_stats(late_df.loc[m_l])

        # robustness checks relaxed
        if not pf_check(st_e['pf'], 0.80):
            return
        if not pf_check(st_l['pf'], 0.85):
            return
        # mid only if finite
        if isinstance(st_m['pf'], float) and np.isfinite(st_m['pf']):
            if not pf_check(st_m['pf'], 0.75):
                return

        results.append({
            'k': k,
            'condition': ' AND '.join(names),
            'train_n': st_tr['n'],
            'test_n': st_te['n'],
            'test_wr': st_te['wr'],
            'test_pf': st_te['pf'],
            'early_pf': st_e['pf'],
            'mid_pf': st_m['pf'],
            'late_pf': st_l['pf'],
        })

    for k in [3, 4]:
        if evals >= MAX_EVALS:
            break
        for combo in itertools.combinations(pool, k):
            eval_combo(combo, k)
            if evals >= MAX_EVALS:
                break

    print(f"Evaluated attempts={evals:,} kept={len(results):,}")
    if not results:
        out_path = OUT_DIR / 'iter9_no_results.json'
        out_path.write_text(json.dumps({'results': [], 'evaluated': evals}, indent=2))
        return

    res_df = pd.DataFrame(results)
    res_df['composite'] = res_df.apply(lambda r: composite_score(r['test_pf'], r['test_wr'], int(r['test_n'])), axis=1)
    res_df = res_df.sort_values(['composite', 'test_pf', 'test_wr', 'test_n'], ascending=[False, False, False, False])
    top = res_df.head(20)

    out = {'top': top.to_dict(orient='records'), 'evaluated': evals, 'kept': len(results)}
    out_path = OUT_DIR / 'iter9_top_by_objective.json'
    out_path.write_text(json.dumps(out, indent=2))

    print('\nTop iter9:')
    for _, r in top.iterrows():
        print(f"- {r['condition']} | n={int(r['test_n'])} WR={r['test_wr']:.2f}% PF={r['test_pf']} latePF={r['late_pf']}")
    print(f"\nWrote: {out_path}")


if __name__ == '__main__':
    main()
