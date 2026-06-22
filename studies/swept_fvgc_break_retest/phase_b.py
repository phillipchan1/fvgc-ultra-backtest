#!/usr/bin/env python3
"""
Phase B — single-factor sweeps (IN-SAMPLE / train only).

For every factor, bucket it and report PF / E[R] / WR / N / freq and lift over
the train baseline. N>=30 floor per bucket (else flagged 'inconclusive').

Output: results/phase_b_factor_sweeps.csv  (+ printed leaders)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from studies.swept_fvgc_break_retest.metrics import cohort_metrics, span_years  # noqa: E402
from studies.swept_fvgc_break_retest.splits import (  # noqa: E402
    load_tradeable, train_test, factor_buckets,
)

RESULTS_DIR = Path(__file__).resolve().parent / 'results'
MIN_N = 30


def run():
    df = load_tradeable()
    train, test = train_test(df)
    yrs = span_years(train)
    base = cohort_metrics(train, span_years=yrs)
    print(f"Train: {len(train)} signals ({train['date'].min()}..{train['date'].max()}, {yrs:.1f}yr)")
    print(f"Train baseline: PF={base['pf']}  E[R]={base['expectancy_r']}  "
          f"WR={base['wr']}  n={base['n']}\n")

    buckets = factor_buckets(train)
    rows = []
    for fname, series in buckets.items():
        for bval, idx in series.groupby(series).groups.items():
            sub = train.loc[idx]
            m = cohort_metrics(sub, span_years=yrs)
            rows.append({
                'factor': fname,
                'bucket': bval,
                'n': m['n'],
                'per_year': m['per_year'],
                'wr': m['wr'],
                'expectancy_r': m['expectancy_r'],
                'pf': m['pf'],
                'lift_er': round(m['expectancy_r'] - base['expectancy_r'], 4) if m['expectancy_r'] is not None else None,
                'lift_pf': round(m['pf'] - base['pf'], 4) if isinstance(m['pf'], (int, float)) else None,
                'inconclusive': m['n'] < MIN_N,
            })

    out = pd.DataFrame(rows).sort_values(['factor', 'expectancy_r'], ascending=[True, False])
    out.to_csv(RESULTS_DIR / 'phase_b_factor_sweeps.csv', index=False)

    # Leaders: buckets with N>=MIN_N, ranked by expectancy lift
    valid = out[~out['inconclusive']].copy()
    valid = valid.sort_values('lift_er', ascending=False)
    print("Top positive-lift buckets (N>=30), ranked by E[R] lift:")
    cols = ['factor', 'bucket', 'n', 'per_year', 'wr', 'expectancy_r', 'pf', 'lift_er']
    with pd.option_context('display.width', 160):
        print(valid.head(25)[cols].to_string(index=False))
        print("\nWorst (anti-signals):")
        print(valid.tail(10)[cols].to_string(index=False))
    print(f"\nWrote results/phase_b_factor_sweeps.csv ({len(out)} factor-buckets)")


if __name__ == '__main__':
    run()
