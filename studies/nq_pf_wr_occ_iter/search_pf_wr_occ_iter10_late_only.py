#!/usr/bin/env python3
"""Iter10: late-only robustness (keep results flowing), wider pool.

Goal: continue self-discovery without hitting empty-result dead ends.
- Walk-forward 70/30 by date
- Late robustness only: require late_pf >= 0.85 when finite
- Enumerate combos of k=3 and k=4
- Condition pool built from top singles by test composite (PF-weighted)

Outputs:
  iter10_top_by_objective.json
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
    return lambda d: pd.to_numeric(d[col], errors='coerce').fillna(np.nan).le(thr).fillna(False).values


def composite_score(pf: object, wr: object, n: int) -> float:
    if isinstance(pf, float) and np.isfinite(pf):
        pf_val = pf
    elif pf == float('inf'):
        pf_val = 1e6
    else:
        pf_val = 0.0
    wr_val = float(wr) / 100.0 if pd.notna(wr) else 0.0
    return pf_val * (wr_val ** 1.1) * float(np.log(n + 1.0))


def main():
    df = pd.read_csv(DATA_PATH)
    df = df[df["outcome"].isin(["win", "loss"])].copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    train_df, test_df = time_split(df, 0.7)

    # late half of test by date order
    test_dates = sorted(set(test_df['timestamp'].dt.date))
    if len(test_dates) >= 4:
        mid = len(test_dates)//2
        late_dates = set(test_dates[mid:])
    else:
        late_dates = set(test_dates)
    late_df = test_df[test_df['timestamp'].dt.date.astype(object).isin(late_dates)].copy()

    print(f"Trades: total={len(df):,} train={len(train_df):,} test={len(test_df):,} late={len(late_df):,}")

    conditions: list[Condition] = []

    # Context anchors
    for ddir in ['long','short']:
        if (df['direction'].astype(str)==ddir).any():
            conditions.append(Condition(f"direction={ddir}", mask_eq_str('direction', ddir)))

    variants = sorted(df['variant'].dropna().astype(str).unique().tolist())
    for v in variants:
        conditions.append(Condition(f"variant={v}", mask_eq_str('variant', v)))

    top_groups = df['nearest_magnet_group'].dropna().astype(str).value_counts().head(25).index.tolist()
    for g in top_groups:
        conditions.append(Condition(f"nearest_magnet_group={g}", mask_eq_str('nearest_magnet_group', g)))

    # Availability
    for col in ['path_clear','magnet_valid','level_swept_before_entry','opening_range_swept']:
        if col in df.columns:
            conditions.append(Condition(f"{col}=True", lambda d, col=col: safe_bool_col(d, col).values))

    # Proximity
    for col in ['magnet_within_1R','magnet_within_2R','magnet_within_3R']:
        if col in df.columns:
            conditions.append(Condition(f"{col}=True", lambda d, col=col: safe_bool_col(d, col).values))

    # Numeric light gates if columns exist
    if 'opening_range_nearest_R' in df.columns:
        rn = pd.to_numeric(df['opening_range_nearest_R'], errors='coerce').dropna()
        if len(rn) >= 100:
            for thr in [float(rn.quantile(q)) for q in [0.3,0.5,0.7]]:
                conditions.append(Condition(f"opening_range_nearest_R<={thr:.2f}", mask_numeric_leq('opening_range_nearest_R', thr)))

    if 'level_confluence_count' in df.columns:
        lc = pd.to_numeric(df['level_confluence_count'], errors='coerce').dropna()
        if len(lc) >= 100:
            for thr in [float(lc.quantile(q)) for q in [0.7,0.85]]:
                conditions.append(Condition(f"level_confluence_count>={thr:.0f}", lambda d, thr=thr: pd.to_numeric(d['level_confluence_count'], errors='coerce').fillna(np.nan).ge(thr).fillna(False).values))

    # Single scoring on test
    MIN_N_TEST_SINGLE = 18
    MIN_PF_TEST_SINGLE = 1.0
    singles_scored = []
    for c in conditions:
        m_te = c.mask_fn(test_df)
        n_te = int(m_te.sum())
        if n_te < MIN_N_TEST_SINGLE:
            continue
        st_te = compute_stats(test_df.loc[m_te])
        pf = st_te['pf']
        if isinstance(pf, float) and np.isfinite(pf) and pf < MIN_PF_TEST_SINGLE:
            continue
        singles_scored.append((c, st_te))

    if not singles_scored:
        print('No single candidates')
        return

    singles_scored.sort(key=lambda t: composite_score(t[1]['pf'], t[1]['wr'], int(t[1]['n'])), reverse=True)
    pool = [c for c, _ in singles_scored[:55]]

    print(f"Singles scored={len(singles_scored):,}  pool={len(pool):,}")

    # Combo eval
    MIN_N_TRAIN_COMBO = 240
    MIN_N_TEST_COMBO = 20
    MAX_EVALS = 200000

    results: list[dict] = []
    evals = 0

    avail_names = {"path_clear=True","magnet_valid=True","level_swept_before_entry=True","opening_range_swept=True",
                   "magnet_within_1R=True","magnet_within_2R=True","magnet_within_3R=True"}

    def has_avail_ctx(names: list[str]) -> bool:
        has_av = any(n in avail_names for n in names)
        has_ctx = any(n.startswith('direction=') or n.startswith('variant=') or n.startswith('nearest_magnet_group=') for n in names)
        return has_av and has_ctx

    def pf_late_ok(pf_val: object) -> bool:
        if isinstance(pf_val, float) and np.isfinite(pf_val):
            return pf_val >= 0.85
        if pf_val == float('inf'):
            return True
        return False

    for k in [3,4]:
        for combo in itertools.combinations(pool, k):
            if evals >= MAX_EVALS:
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
            st_lt = compute_stats(late_df.loc[m_lt]) if n_lt>0 else compute_stats(late_df.iloc[0:0])

            if not pf_late_ok(st_lt['pf']):
                continue

            st_tr = compute_stats(train_df.loc[m_tr])

            results.append({
                'k': k,
                'condition': ' AND '.join(names),
                'train_n': st_tr['n'],
                'train_wr': st_tr['wr'],
                'train_pf': st_tr['pf'],
                'test_n': st_te['n'],
                'test_wr': st_te['wr'],
                'test_pf': st_te['pf'],
                'late_n': st_lt['n'],
                'late_pf': st_lt['pf'],
            })

        if evals >= MAX_EVALS:
            break

    print(f"Evaluated={evals:,}  results_kept={len(results):,}")

    if not results:
        out_path = OUT_DIR / 'iter10_no_results.json'
        out_path.write_text(json.dumps({'results': [], 'evaluated': evals}, indent=2))
        return

    res_df = pd.DataFrame(results)
    res_df['composite'] = res_df.apply(lambda r: composite_score(r['test_pf'], r['test_wr'], int(r['test_n'])), axis=1)
    res_df = res_df.sort_values(['composite','test_pf','test_wr','test_n'], ascending=[False,False,False,False])

    def pick_top(df_in: pd.DataFrame, topn: int):
        return df_in.head(topn).to_dict(orient='records')

    out = {
        'top_by_pf': pick_top(res_df.sort_values(['test_pf','test_n'], ascending=[False,False]), 10),
        'top_by_wr': pick_top(res_df.sort_values(['test_wr','test_pf','test_n'], ascending=[False,False,False]), 10),
        'top_by_occ': pick_top(res_df.sort_values(['test_n','test_pf','test_wr'], ascending=[False,False,False]), 10),
        'top_by_composite': pick_top(res_df, 10),
        'meta': {'evaluated': evals, 'kept': len(results), 'pool': len(pool)}
    }

    out_path = OUT_DIR / 'iter10_top_by_objective.json'
    out_path.write_text(json.dumps(out, indent=2))

    print('\nTop composite:')
    for r in out['top_by_composite'][:5]:
        print(f"- {r['condition']} | n={r['test_n']} WR={r['test_wr']:.2f}% PF={r['test_pf']} latePF={r['late_pf']}")


if __name__ == '__main__':
    main()
