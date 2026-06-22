#!/usr/bin/env python3
"""Shared metric helpers — used by every phase. Headline metric is R, not WR.

A "tradeable" row has sim_exit_type != 'skip' (the model assigned a structure SL).
win = sim_realized_r > 0, loss = sim_realized_r < 0, push = 0.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

R_COL = 'sim_realized_r'


def tradeable(df: pd.DataFrame) -> pd.DataFrame:
    return df[df['sim_exit_type'] != 'skip'].copy()


def cohort_metrics(df: pd.DataFrame, span_years: float | None = None, r_col: str = R_COL) -> dict:
    """PF / expectancy-in-R / WR / frequency for a cohort (already tradeable-filtered)."""
    n = len(df)
    if n == 0:
        return {'n': 0, 'wr': None, 'expectancy_r': None, 'pf': None,
                'gross_r': None, 'per_year': None, 'fixed_wr': None}
    r = df[r_col].astype(float)
    wins = int((r > 0).sum())
    losses = int((r < 0).sum())
    wr = wins / (wins + losses) if (wins + losses) > 0 else None
    pos = r[r > 0].sum()
    neg = -r[r < 0].sum()
    pf = (pos / neg) if neg > 0 else (float('inf') if pos > 0 else None)
    expectancy = float(r.mean())
    gross_r = float(r.sum())
    per_year = (n / span_years) if span_years else None

    fixed_wr = None
    if 'hit_1_0R' in df.columns:
        h = df['hit_1_0R']
        h = h.map({True: 1, False: 0, 'True': 1, 'False': 0}) if h.dtype == object else h.astype(int)
        fixed_wr = float(h.mean())

    return {
        'n': n,
        'wr': round(wr, 4) if wr is not None else None,
        'expectancy_r': round(expectancy, 4),
        'pf': round(pf, 4) if pf not in (None, float('inf')) else pf,
        'gross_r': round(gross_r, 2),
        'per_year': round(per_year, 1) if per_year else None,
        'fixed_wr': round(fixed_wr, 4) if fixed_wr is not None else None,
    }


def span_years(df: pd.DataFrame) -> float:
    ts = pd.to_datetime(df['timestamp'])
    days = (ts.max() - ts.min()).days
    return max(days / 365.25, 1e-9)
