"""Confluence Framework — evaluation harness (Phase 1).

Every statistical evaluation in this program goes through `evaluate()`, which
auto-appends to results/test_ledger.csv. OOS evaluation is hard-guarded: it
raises unless `allow_oos=True` is passed explicitly (Phase 5 only).

Canonical inputs (frozen in Phase 0/1):
  results/cache/baseline_trades_8yr.csv   (8yr frozen-spec baseline)
  results/cache/session_quality.csv       (>=90% overnight-bar coverage rule)
  results/phase1_split.json               (IS/OOS boundary + 4 IS folds)

Run with python3.13 (pandas 2.x, scipy).
"""
from __future__ import annotations

import json
from datetime import time as dtime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
CACHE = RESULTS / "cache"
LEDGER = RESULTS / "test_ledger.csv"

LEDGER_COLS = ["test_id", "phase", "hypothesis", "cohort", "n", "WR", "PF",
               "p_value", "q_value", "notes"]

_split = json.loads((RESULTS / "phase1_split.json").read_text())
OOS_BOUNDARY = pd.Timestamp(_split["split"]["oos_boundary_date"])
FOLDS = _split["is_folds"]


def load_program_trades() -> pd.DataFrame:
    """Canonical tradeable trades + quality filter + split/fold labels."""
    df = pd.read_csv(CACHE / "baseline_trades_8yr.csv",
                     parse_dates=["timestamp", "fvg_created_at", "exit_time"])
    df = df[df["outcome"].isin(["win", "loss"])].copy()
    df["session_date"] = df["timestamp"].dt.normalize()

    q = pd.read_csv(CACHE / "session_quality.csv", parse_dates=["session_date"])
    ok = set(q.loc[q["pass"], "session_date"])
    df = df[df["session_date"].isin(ok)].copy()

    df["win"] = (df["outcome"] == "win").astype(int)
    df["r"] = np.where(df["sl_dist"] > 0, df["pnl"] / df["sl_dist"], np.nan)
    df["split"] = np.where(df["session_date"] >= OOS_BOUNDARY, "OOS", "IS")

    df["fold"] = ""
    for name, f in FOLDS.items():
        m = ((df["session_date"] >= pd.Timestamp(f["start"]))
             & (df["session_date"] <= pd.Timestamp(f["end"])))
        df.loc[m, "fold"] = name

    df = df.sort_values("timestamp").reset_index(drop=True)
    return df


def benchmark_mask(df: pd.DataFrame) -> pd.Series:
    """Program benchmark: opening-window FVG short, no protected_swing."""
    tod = df["fvg_created_at"].dt.time
    return ((tod >= dtime(9, 29, 30)) & (tod <= dtime(9, 31, 0))
            & (df["direction"] == "short") & (df["variant"] != "protected_swing"))


def _pf(sub: pd.DataFrame) -> float:
    gp = sub.loc[sub["pnl"] > 0, "pnl"].sum()
    gl = -sub.loc[sub["pnl"] < 0, "pnl"].sum()
    return float(gp / gl) if gl > 0 else float("nan")


def _max_consec_losses(sub: pd.DataFrame) -> int:
    worst = run = 0
    for w in sub.sort_values("timestamp")["win"]:
        run = 0 if w else run + 1
        worst = max(worst, run)
    return worst


def _append_ledger(row: dict) -> None:
    out = {c: row.get(c, "") for c in LEDGER_COLS}
    pd.DataFrame([out]).to_csv(LEDGER, mode="a", header=not LEDGER.exists(),
                               index=False)


def evaluate(df: pd.DataFrame, mask: pd.Series, *, test_id: str, phase: int,
             hypothesis: str, cohort: str = "all", split: str = "IS",
             notes: str = "", allow_oos: bool = False, log: bool = True) -> dict:
    """Evaluate a boolean condition. Returns stats dict; appends to ledger.

    split: 'IS' (default), 'OOS' (requires allow_oos=True), or 'ALL'
    (full-sample — only for pre-registered Phase 0/1 benchmark reproduction).
    Baseline WR for the binomial test is computed on the same split of the
    full tradeable pool (not the cohort), so cohort tests are vs their split base rate.
    """
    if split == "OOS" and not allow_oos:
        raise RuntimeError("OOS evaluation is locked until Phase 5 "
                           "(pass allow_oos=True only for frozen candidates).")
    pool = df if split == "ALL" else df[df["split"] == split]
    sub = pool[mask.reindex(pool.index, fill_value=False)]
    base_wr = pool["win"].mean()

    n = len(sub)
    res = dict(test_id=test_id, phase=phase, hypothesis=hypothesis,
               cohort=cohort, split=split, n=n)
    if n == 0:
        res.update(WR=np.nan, PF=np.nan, avg_r=np.nan, p_value=np.nan,
                   max_consec_losses=np.nan, folds={}, folds_same_sign=np.nan,
                   base_wr=round(100 * base_wr, 2), notes=notes or "empty")
        if log:
            _append_ledger({**res, "notes": res["notes"]})
        return res

    wins = int(sub["win"].sum())
    wr = wins / n
    p = stats.binomtest(wins, n, base_wr, alternative="two-sided").pvalue
    effect_sign = np.sign(wr - base_wr)

    folds = {}
    same_sign = 0
    if split in ("IS", "ALL"):
        for name in FOLDS:
            fsub = sub[sub["fold"] == name]
            fpool = pool[pool["fold"] == name]
            if len(fsub) == 0 or len(fpool) == 0:
                folds[name] = dict(n=len(fsub), wr=np.nan)
                continue
            fwr = fsub["win"].mean()
            folds[name] = dict(n=len(fsub), wr=round(100 * fwr, 1))
            if np.sign(fwr - fpool["win"].mean()) == effect_sign:
                same_sign += 1

    res.update(WR=round(100 * wr, 1), PF=round(_pf(sub), 2),
               avg_r=round(float(sub["r"].mean()), 3),
               p_value=p, max_consec_losses=_max_consec_losses(sub),
               folds=folds, folds_same_sign=same_sign,
               base_wr=round(100 * base_wr, 2), notes=notes)
    if log:
        _append_ledger({**res,
                        "notes": (notes + f" | split={split} base={res['base_wr']}% "
                                  f"folds_same_sign={same_sign} avg_r={res['avg_r']}"
                                  ).strip(" |")})
    return res


def bh_fdr_rewrite(q: float = 0.10) -> pd.DataFrame:
    """Recompute BH q-values across the ENTIRE ledger and rewrite it."""
    led = pd.read_csv(LEDGER)
    led["p_value"] = pd.to_numeric(led["p_value"], errors="coerce")
    valid = led["p_value"].notna()
    p = led.loc[valid, "p_value"].values
    m = len(p)
    order = np.argsort(p)
    qv = np.empty(m)
    prev = 1.0
    for rank in range(m - 1, -1, -1):
        i = order[rank]
        prev = min(prev, p[i] * m / (rank + 1))
        qv[i] = prev
    led.loc[valid, "q_value"] = qv
    led.to_csv(LEDGER, index=False)
    return led
