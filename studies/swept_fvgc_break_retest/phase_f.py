#!/usr/bin/env python3
"""
Phase F — regime & time-of-day breakdown.

No cohort passed Phase E, so this characterizes the best OOS candidate
(`short & below_vwap & level_touch_3_5`) and the runner family vs baseline:
year-by-year stability and time-of-day concentration over the FULL sample. The
point is to show WHERE any weak signal lives and confirm the negative verdict.

Outputs: results/phase_f_breakdown.csv + best-candidate trade list.
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from studies.swept_fvgc_break_retest.metrics import cohort_metrics, span_years  # noqa: E402
from studies.swept_fvgc_break_retest.splits import load_tradeable  # noqa: E402
from studies.swept_fvgc_break_retest.phase_d import candidate_filters  # noqa: E402

RESULTS_DIR = Path(__file__).resolve().parent / 'results'

CANDIDATE = ['short', 'below_vwap', 'level_touch_3_5']


def tod_bucket(t):
    if t < dt.time(9, 45):
        return '0930-0945'
    if t < dt.time(10, 0):
        return '0945-1000'
    return '1000-1015'


def run():
    df = load_tradeable()
    filt = candidate_filters(df)
    mask = np.ones(len(df), dtype=bool)
    for c in CANDIDATE:
        mask &= filt[c][0].to_numpy()
    cand = df[mask].copy()

    print(f"Candidate cohort: {' & '.join(CANDIDATE)}  (full-sample n={len(cand)})\n")

    # year-by-year (candidate vs baseline)
    df['year'] = df['ts'].dt.year
    cand['year'] = cand['ts'].dt.year
    rows = []
    for y in sorted(df['year'].unique()):
        b = cohort_metrics(df[df['year'] == y])
        c = cohort_metrics(cand[cand['year'] == y])
        rows.append({'year': y, 'base_n': b['n'], 'base_er': b['expectancy_r'], 'base_pf': b['pf'],
                     'cand_n': c['n'], 'cand_er': c['expectancy_r'], 'cand_pf': c['pf']})
    yb = pd.DataFrame(rows)
    print("Year-by-year (baseline vs candidate):")
    print(yb.to_string(index=False))

    # time-of-day (full sample)
    df['todb'] = df['tod'].map(tod_bucket)
    cand['todb'] = cand['tod'].map(tod_bucket)
    rows2 = []
    for tb in ['0930-0945', '0945-1000', '1000-1015']:
        b = cohort_metrics(df[df['todb'] == tb])
        c = cohort_metrics(cand[cand['todb'] == tb])
        rows2.append({'tod': tb, 'base_n': b['n'], 'base_er': b['expectancy_r'], 'base_pf': b['pf'],
                      'cand_n': c['n'], 'cand_er': c['expectancy_r'], 'cand_pf': c['pf']})
    tb_df = pd.DataFrame(rows2)
    print("\nTime-of-day (full sample):")
    print(tb_df.to_string(index=False))

    yb.to_csv(RESULTS_DIR / 'phase_f_year_breakdown.csv', index=False)
    tb_df.to_csv(RESULTS_DIR / 'phase_f_tod_breakdown.csv', index=False)
    cand.drop(columns=['todb', 'year'], errors='ignore').to_csv(
        RESULTS_DIR / 'trades_best_candidate.csv', index=False)
    print("\nWrote phase_f_year_breakdown.csv, phase_f_tod_breakdown.csv, trades_best_candidate.csv")


if __name__ == '__main__':
    run()
