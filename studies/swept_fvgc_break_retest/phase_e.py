#!/usr/bin/env python3
"""
Phase E — OOS + robustness for the frozen Phase-D cohorts.

For each frozen cohort:
  - apply its filter to the held-out TEST slice (last 30% of dates),
  - report test PF / E[R] / WR / N / freq,
  - early/late split WITHIN test (both halves must stay PF>=1.0 to be "robust"),
  - label-permutation p-value on test,
  - Bonferroni haircut over the number of cohorts validated,
  - regime-matched baseline (beta vs alpha): excess E[R] vs the same-regime slice.

A cohort PASSES if: test N>=20, test E[R]>0 and PF>1.1, both early & late PF>=1.0,
and perm_p < Bonferroni alpha.

Outputs: results/phase_e_oos.csv
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from studies.swept_fvgc_break_retest.metrics import cohort_metrics, span_years, R_COL  # noqa: E402
from studies.swept_fvgc_break_retest.splits import (  # noqa: E402
    load_tradeable, train_test, early_late,
)
from studies.swept_fvgc_break_retest.phase_d import candidate_filters  # noqa: E402
from studies.swept_fvgc_break_retest.phase_c import perm_pvalue  # noqa: E402

RESULTS_DIR = Path(__file__).resolve().parent / 'results'
N_PERMS = 5000


def mask_for(cohort: list[str], filters: dict) -> np.ndarray:
    m = None
    for c in cohort:
        fm = filters[c][0].to_numpy()
        m = fm if m is None else (m & fm)
    return m


def regime_baseline_mask(cohort: list[str], filters: dict, df: pd.DataFrame) -> np.ndarray:
    """Same-regime baseline: keep only the regime/direction filters of the cohort,
    drop the structural ones — isolates beta so the cohort's excess is alpha."""
    regime_filters = {'short', 'vixy_normal'}
    keep = [c for c in cohort if c in regime_filters]
    if not keep:
        return np.ones(len(df), dtype=bool)
    return mask_for(keep, filters)


def run():
    df = load_tradeable()
    train, test = train_test(df)
    yrs_te = span_years(test)

    frozen = json.loads((RESULTS_DIR / 'phase_d_top_cohorts.json').read_text())
    cohorts = [f['cohort'] for f in frozen]
    n_tests = len(cohorts)
    bonf_alpha = 0.05 / max(n_tests, 1)

    filt_test = candidate_filters(test)
    all_r_test = test[R_COL].to_numpy(dtype=float)
    rng = np.random.default_rng(7)

    e_df, l_df = early_late(test)
    filt_e = candidate_filters(e_df)
    filt_l = candidate_filters(l_df)

    base_te = cohort_metrics(test, span_years=yrs_te)

    rows = []
    for cohort in cohorts:
        m = mask_for(cohort, filt_test)
        sub = test[m]
        mt = cohort_metrics(sub, span_years=yrs_te)

        me = cohort_metrics(e_df[mask_for(cohort, filt_e)], span_years=span_years(e_df) if len(e_df) else 1)
        ml = cohort_metrics(l_df[mask_for(cohort, filt_l)], span_years=span_years(l_df) if len(l_df) else 1)

        p = perm_pvalue(all_r_test, m, N_PERMS, rng) if mt['n'] > 0 else 1.0

        # regime-matched baseline excess
        rb_mask = regime_baseline_mask(cohort, filt_test, test)
        rb = cohort_metrics(test[rb_mask], span_years=yrs_te)
        excess_er = (mt['expectancy_r'] - rb['expectancy_r']) if mt['expectancy_r'] is not None else None

        early_pf = me['pf'] if isinstance(me['pf'], (int, float)) else None
        late_pf = ml['pf'] if isinstance(ml['pf'], (int, float)) else None
        robust = (early_pf is not None and late_pf is not None
                  and early_pf >= 1.0 and late_pf >= 1.0)
        passes = (mt['n'] >= 20 and (mt['expectancy_r'] or -1) > 0
                  and isinstance(mt['pf'], (int, float)) and mt['pf'] > 1.1
                  and robust and p < bonf_alpha)

        rows.append({
            'cohort': ' & '.join(cohort),
            'test_n': mt['n'], 'test_per_year': mt['per_year'], 'test_wr': mt['wr'],
            'test_er': mt['expectancy_r'], 'test_pf': mt['pf'],
            'early_n': me['n'], 'early_pf': early_pf,
            'late_n': ml['n'], 'late_pf': late_pf,
            'perm_p': round(p, 4), 'bonf_alpha': round(bonf_alpha, 5),
            'regime_excess_er': round(excess_er, 4) if excess_er is not None else None,
            'robust': robust, 'PASS': passes,
        })

    out = pd.DataFrame(rows).sort_values('test_er', ascending=False, na_position='last')
    out.to_csv(RESULTS_DIR / 'phase_e_oos.csv', index=False)

    print(f"TEST slice: {len(test)} signals ({test['date'].min()}..{test['date'].max()}, {yrs_te:.1f}yr)")
    print(f"TEST baseline: PF={base_te['pf']} E[R]={base_te['expectancy_r']} n={base_te['n']}")
    print(f"Bonferroni alpha = 0.05/{n_tests} = {bonf_alpha:.5f}\n")
    with pd.option_context('display.width', 200, 'display.max_colwidth', 55):
        print(out.to_string(index=False))
    print(f"\nPASS: {list(out[out['PASS']]['cohort'])}")
    print("Wrote results/phase_e_oos.csv")


if __name__ == '__main__':
    run()
