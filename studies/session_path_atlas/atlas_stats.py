"""Shared statistics helpers for the Session Path Atlas (Track B).

Ledger: results/test_ledger.csv — separate file from Track A's ledger.
Columns: test_id, part, statistic, conditioner, cell, as_of, n, p_hat,
ci_lo, ci_hi, marginal_p, delta_pp, p_value, q_value, verdict, notes.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
LEDGER = RESULTS / "test_ledger.csv"
LEDGER_COLS = ["test_id", "part", "statistic", "conditioner", "cell", "as_of",
               "n", "p_hat", "ci_lo", "ci_hi", "marginal_p", "delta_pp",
               "p_value", "q_value", "verdict", "notes"]

YEARS = list(range(2018, 2026))  # stationarity vote years (2026 partial = extra)


def wilson(k: int, n: int, z: float = 1.959964) -> tuple[float, float]:
    """95% Wilson score interval for k successes in n trials."""
    if n == 0:
        return (np.nan, np.nan)
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, centre - half), min(1.0, centre + half))


def ledger_append(row: dict) -> None:
    out = {c: row.get(c, "") for c in LEDGER_COLS}
    pd.DataFrame([out]).to_csv(LEDGER, mode="a", header=not LEDGER.exists(),
                               index=False)


def stationarity(success: pd.Series, valid: pd.Series, years: pd.Series
                 ) -> dict:
    """STABLE if yearly p within pooled 95% Wilson CI in >=6 of 8 years
    (2018-2025). Returns verdict + yearly table + recent-3yr value."""
    v = valid.fillna(False).astype(bool)
    s = success.fillna(False).astype(bool) & v
    n, k = int(v.sum()), int(s.sum())
    lo, hi = wilson(k, n)
    yearly = {}
    in_ci = 0
    voted = 0
    for y in YEARS:
        m = (years == y) & v
        ny = int(m.sum())
        if ny == 0:
            yearly[y] = (np.nan, 0)
            continue
        py = float((s & m).sum()) / ny
        yearly[y] = (py, ny)
        voted += 1
        if lo <= py <= hi:
            in_ci += 1
    m26 = (years == 2026) & v
    yearly[2026] = ((float((s & m26).sum()) / m26.sum(), int(m26.sum()))
                    if m26.sum() else (np.nan, 0))
    recent = (years >= 2023) & (years <= 2025) & v
    p_recent = (float((s & recent).sum()) / recent.sum()
                if recent.sum() else np.nan)
    verdict = "STABLE" if (voted >= 6 and in_ci >= 6) else "DRIFTING"
    # chi-square heterogeneity across years (companion test: the pre-registered
    # pooled-CI rule over-flags DRIFTING at large pooled n — see analysis.md)
    tbl = np.array([[ (s & (years == y) & v).sum(),
                      ((~s) & (years == y) & v).sum()] for y in YEARS
                    if ((years == y) & v).sum() >= 20])
    het_p = np.nan
    if len(tbl) >= 4 and tbl.sum(axis=0).min() > 0:
        try:
            het_p = float(stats.chi2_contingency(tbl)[1])
        except ValueError:
            pass
    return dict(verdict=verdict, in_ci=in_ci, voted=voted, yearly=yearly,
                p_recent=p_recent, p_pooled=k / n if n else np.nan,
                n=n, k=k, ci=(lo, hi), het_p=het_p)


def null_verdict(p_actual: float, null_mean: float,
                 null_band: tuple[float, float] | None) -> str:
    """DEFINITIONS §8: structural / weak / mechanical vs the shuffle null."""
    if np.isnan(null_mean):
        return "NO_NULL"
    dev = abs(p_actual - null_mean)
    outside = (null_band is not None
               and not (null_band[0] <= p_actual <= null_band[1]))
    if outside and dev >= 0.05:
        return "STRUCTURAL"
    if outside and dev >= 0.02:
        return "WEAK_STRUCTURE"
    return "MECHANICAL"


def classify(p_actual, n, ci, null_v, stat_v) -> str:
    """Final atlas grade: GEM / MECHANICAL / WEAK / LOW-N per DEFINITIONS §8."""
    if n < 30:
        return "SUPPRESSED"
    if n < 100:
        return "LOW-N"
    half = (ci[1] - ci[0]) / 2
    if null_v == "STRUCTURAL" and stat_v == "STABLE" and half <= 0.05:
        return "GEM"
    if null_v in ("STRUCTURAL", "WEAK_STRUCTURE"):
        return "STRUCTURAL-DRIFTING" if stat_v == "DRIFTING" else "WEAK-STRUCTURE"
    return "MECHANICAL"


def binom_vs_marginal(k: int, n: int, p0: float) -> float:
    if n == 0 or np.isnan(p0) or not (0 < p0 < 1):
        return np.nan
    return float(stats.binomtest(k, n, p0, alternative="two-sided").pvalue)


def bh_fdr(pvals: np.ndarray) -> np.ndarray:
    """BH q-values; NaNs passed through."""
    q = np.full(len(pvals), np.nan)
    valid = ~np.isnan(pvals)
    p = pvals[valid]
    m = len(p)
    if m == 0:
        return q
    order = np.argsort(p)
    qv = np.empty(m)
    prev = 1.0
    for rank in range(m - 1, -1, -1):
        i = order[rank]
        prev = min(prev, p[i] * m / (rank + 1))
        qv[i] = prev
    q[valid] = qv
    return q
