"""Reusable lift-table builder.

Input: a population DataFrame + factor column name + bucket spec.
Output: per-bucket N, wins, losses, WR, PF, avg R, total P&L, bootstrap PF CI.

Bucket spec can be:
  - a callable: df -> Series of labels (custom bucketing)
  - a list of edges: [a, b, c, ...] -> pd.cut bins
  - None: treat factor as categorical (groupby value)

Use directly in studies; no need for one-off scripts.
"""

from typing import Callable, List, Optional, Union
import numpy as np
import pandas as pd


def build_lift_table(
    df: pd.DataFrame,
    factor: str,
    bucketer: Union[Callable, List[float], None] = None,
    bootstrap_iters: int = 1000,
    min_bucket_n: int = 0,
) -> pd.DataFrame:
    """Bucket trades by `factor` and compute WR, PF, avg R, etc. per bucket.

    Returns a DataFrame with columns:
        bucket, n, wins, losses, flat, wr_pct, pf, avg_r, total_pnl_pts,
        pf_ci_low, pf_ci_high  (5th/95th percentile from bootstrap)
    """
    work = df.copy()

    if callable(bucketer):
        work['_bucket'] = bucketer(work)
    elif isinstance(bucketer, list):
        work['_bucket'] = pd.cut(work[factor], bins=bucketer, include_lowest=True)
    else:
        work['_bucket'] = work[factor]

    rows = []
    for label, g in work.groupby('_bucket', observed=True, dropna=False):
        if len(g) < min_bucket_n:
            continue
        rows.append(_summarize(label, g, bootstrap_iters))

    out = pd.DataFrame(rows).sort_values('bucket', key=lambda s: s.astype(str))
    return out.reset_index(drop=True)


def _summarize(label, g: pd.DataFrame, bootstrap_iters: int) -> dict:
    r = g['r_multiple'].values
    pnl = g['pnl_pts'].values
    wins = int((r > 0).sum())
    losses = int((r < 0).sum())
    flat = int((r == 0).sum())
    wr = (wins / (wins + losses) * 100) if (wins + losses) else 0.0
    gw = float(pnl[pnl > 0].sum())
    gl = float(abs(pnl[pnl < 0].sum())) or 1e-9
    pf = gw / gl

    if bootstrap_iters > 0 and len(g) >= 10:
        pfs = _bootstrap_pf(pnl, bootstrap_iters)
        pf_ci_low = float(np.percentile(pfs, 5))
        pf_ci_high = float(np.percentile(pfs, 95))
    else:
        pf_ci_low = pf_ci_high = float('nan')

    return {
        'bucket': str(label),
        'n': len(g),
        'wins': wins,
        'losses': losses,
        'flat': flat,
        'wr_pct': round(wr, 1),
        'pf': round(pf, 2),
        'avg_r': round(float(r.mean()), 3),
        'total_pnl_pts': round(float(pnl.sum()), 1),
        'pf_ci_low': round(pf_ci_low, 2),
        'pf_ci_high': round(pf_ci_high, 2),
    }


def _bootstrap_pf(pnl: np.ndarray, iters: int) -> np.ndarray:
    """Resample pnl with replacement, compute PF each time."""
    n = len(pnl)
    rng = np.random.default_rng(42)
    pfs = np.empty(iters)
    for i in range(iters):
        sample = pnl[rng.integers(0, n, n)]
        gw = sample[sample > 0].sum()
        gl = abs(sample[sample < 0].sum())
        pfs[i] = gw / max(gl, 1e-9)
    return pfs


def print_table(table: pd.DataFrame, title: str = "") -> None:
    if title:
        print(f"\n=== {title} ===")
    cols = ['bucket', 'n', 'wr_pct', 'pf', 'pf_ci_low', 'pf_ci_high',
            'avg_r', 'total_pnl_pts']
    print(table[cols].to_string(index=False))
