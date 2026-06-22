#!/usr/bin/env python3
"""
Phase A — Baseline + regime-matched baselines.

Plain FVGC continuation, NO conditions, under the dynamic-magnet exit. Every
cohort mined later must beat this on PF / expectancy-in-R (not WR).

Regime-matched baselines (direction, macro_trend, direction x macro_trend) let us
separate beta from alpha in Phase E: "longs work" in a bull tape is beta — only
the excess over the same-regime baseline is edge.

Input : results/signals_simulated.csv
Output: results/phase_a_baseline.csv  (+ printed summary)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from studies.swept_fvgc_break_retest.metrics import (  # noqa: E402
    tradeable, cohort_metrics, span_years,
)

STUDY_DIR = Path(__file__).resolve().parent
RESULTS_DIR = STUDY_DIR / 'results'


def run():
    df = pd.read_csv(RESULTS_DIR / 'signals_simulated.csv')
    tr = tradeable(df)
    yrs = span_years(tr)

    rows = []

    def add(label, sub):
        m = cohort_metrics(sub, span_years=yrs)
        rows.append({'cohort': label, **m})

    add('ALL (Phase A baseline)', tr)
    add('long', tr[tr['direction'] == 'long'])
    add('short', tr[tr['direction'] == 'short'])
    for mt in ['up', 'down', 'flat']:
        add(f'macro_{mt}', tr[tr['macro_trend'] == mt])
    # direction x macro_trend (alignment matrix)
    for direction in ['long', 'short']:
        for mt in ['up', 'down', 'flat']:
            sub = tr[(tr['direction'] == direction) & (tr['macro_trend'] == mt)]
            add(f'{direction} x macro_{mt}', sub)
    # aligned vs counter diagonal
    add('aligned (regime_alignment)', tr[tr['regime_alignment'] == 'aligned'])
    add('counter (regime_alignment)', tr[tr['regime_alignment'] == 'counter'])
    add('flat regime', tr[tr['regime_alignment'] == 'flat'])
    # by variant (informational)
    for v in sorted(tr['variant'].dropna().unique()):
        add(f'variant={v}', tr[tr['variant'] == v])

    out = pd.DataFrame(rows)
    out.to_csv(RESULTS_DIR / 'phase_a_baseline.csv', index=False)

    print(f"\nPhase A — {len(tr)} tradeable signals over {yrs:.1f}yr "
          f"({tr['timestamp'].min()} .. {tr['timestamp'].max()})\n")
    cols = ['cohort', 'n', 'per_year', 'wr', 'fixed_wr', 'expectancy_r', 'pf', 'gross_r']
    with pd.option_context('display.max_rows', None, 'display.width', 160):
        print(out[cols].to_string(index=False))
    print(f"\nWrote results/phase_a_baseline.csv")


if __name__ == '__main__':
    run()
