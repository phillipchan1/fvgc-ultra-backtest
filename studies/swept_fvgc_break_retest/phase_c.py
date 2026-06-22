#!/usr/bin/env python3
"""
Phase C — marginal factor ranking (IN-SAMPLE / train).

For each factor we pick its best ACTIONABLE bucket (N>=30, excluding degenerate
none/na buckets that just re-expose the 134 'unswept' signals), measure the
expectancy-R lift over the train baseline, and test significance with a
label-permutation null (shuffle realized-R across all train signals; how often
does a random same-size subset beat the observed mean?).

A factor 'survives' if: lift_er > 0, permutation p < 0.05, N >= 30, and it has a
one-sentence mechanism. Survivors feed Phase D.

Output: results/phase_c_factor_ranking.csv
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from studies.swept_fvgc_break_retest.metrics import cohort_metrics, span_years, R_COL  # noqa: E402
from studies.swept_fvgc_break_retest.splits import (  # noqa: E402
    load_tradeable, train_test, factor_buckets,
)

RESULTS_DIR = Path(__file__).resolve().parent / 'results'
MIN_N = 30
N_PERMS = 5000
DEGENERATE = {'none', 'na', 'nan', 'unknown', 'None'}

# One-sentence mechanism per factor (mechanism-before-metric gate).
MECHANISM = {
    'provenance': 'FVG forms at a specific swept liquidity pool (trapped stops as fuel).',
    'magnet_group': 'Target type: mean-reversion magnets pull; HTF gaps are resistance/obstruction.',
    'magnet_R': 'Distance to target in R — near magnets cap winners, far magnets are runners.',
    'htf_position': 'Where entry sits inside a nested HTF gap: mid = runway, far = into the far edge (fade).',
    'htf_aligned': 'HTF gap direction vs trade direction (toward far edge = into HTF resistance).',
    'inside_htf_fvg': 'Entry nested inside an unfilled HTF gap.',
    'r0_ge_10pt': 'Entry >=10 pts from VWAP — room before the mean-reversion magnet (VWAP play R0 rule).',
    'vwap_above': 'Entry above/below session VWAP.',
    'va_pos_prior': 'Entry vs prior-day value area (acceptance/rejection of prior value).',
    'va_pos_dev': 'Entry vs developing value area.',
    'open_vs_prior_va': 'Where today opened relative to prior value (gap into/out of value).',
    'btr_timing': 'Break->retest tempo: too fast = no pullback structure; a window allows a clean retest.',
    'retest_within_10min': 'Retest occurs within 10 min of the break (fresh structure).',
    'bars_since_sweep': 'Recency of the liquidity sweep before the FVG.',
    'sweep_type': 'Reclaim (close-back grab) vs tag (mere touch) of the swept level.',
    'swept_tightness': 'How tightly the FVG coincides with the swept level.',
    'level_touch': 'How many times the swept level was tested before entry.',
    'level_virgin': 'First-touch (virgin) swept level vs re-tested.',
    'confluence_stack': 'Number of distinct levels stacked in the FVG zone.',
    'clean_runway': 'No opposing level between entry and the target magnet.',
    'magnet_per_fvg': 'Target distance normalized by FVG size.',
    'magnet_per_atr': 'Target distance normalized by daily ATR.',
    'macro_trend': 'Daily-EMA regime (prior-day) — beta of the prevailing tape.',
    'regime_alignment': 'Trade direction aligned vs counter to macro trend.',
    'vixy_regime': 'Volatility regime (VIXY percentile, prior close).',
    'prior_day_type': 'Prior session character (trend/range/reversal).',
    'open_vs_prior_va2': '',
    'direction': 'Long vs short (structural side).',
    'or_width': 'Opening-range width as-of entry (balance vs expansion day).',
    'price_above_dev_vwap': 'Entry above/below developing VWAP.',
    'variant': 'FVGC entry sub-type (bos/no_fvg/ifvg/protected_swing).',
}


def perm_pvalue(all_r: np.ndarray, subset_mask: np.ndarray, n_perms: int, rng) -> float:
    """1-sided: P(random same-size subset mean R >= observed subset mean R)."""
    n = int(subset_mask.sum())
    if n == 0:
        return 1.0
    obs = all_r[subset_mask].mean()
    idx = np.arange(len(all_r))
    ge = 0
    for _ in range(n_perms):
        samp = rng.choice(idx, size=n, replace=False)
        if all_r[samp].mean() >= obs:
            ge += 1
    return (ge + 1) / (n_perms + 1)


def run():
    df = load_tradeable()
    train, _ = train_test(df)
    yrs = span_years(train)
    base = cohort_metrics(train, span_years=yrs)
    all_r = train[R_COL].to_numpy(dtype=float)
    rng = np.random.default_rng(42)

    buckets = factor_buckets(train)
    rows = []
    for fname, series in buckets.items():
        best = None
        for bval, idx in series.groupby(series).groups.items():
            if str(bval) in DEGENERATE:
                continue
            sub = train.loc[idx]
            if len(sub) < MIN_N:
                continue
            m = cohort_metrics(sub, span_years=yrs)
            lift = m['expectancy_r'] - base['expectancy_r']
            if best is None or lift > best['lift_er']:
                best = {'bucket': bval, 'mask': series.eq(bval).to_numpy(),
                        'lift_er': lift, **m}
        if best is None:
            continue
        p = perm_pvalue(all_r, best['mask'], N_PERMS, rng)
        mech = MECHANISM.get(fname, '')
        rows.append({
            'factor': fname, 'best_bucket': best['bucket'], 'n': best['n'],
            'per_year': best['per_year'], 'wr': best['wr'],
            'expectancy_r': best['expectancy_r'], 'pf': best['pf'],
            'lift_er': round(best['lift_er'], 4), 'perm_p': round(p, 4),
            'significant': p < 0.05, 'has_mechanism': bool(mech),
            'survivor': (best['lift_er'] > 0 and p < 0.05 and best['n'] >= MIN_N and bool(mech)),
            'mechanism': mech,
        })

    out = pd.DataFrame(rows).sort_values('lift_er', ascending=False)
    out.to_csv(RESULTS_DIR / 'phase_c_factor_ranking.csv', index=False)

    print(f"Train baseline PF={base['pf']} E[R]={base['expectancy_r']} n={base['n']}, {yrs:.1f}yr\n")
    cols = ['factor', 'best_bucket', 'n', 'per_year', 'wr', 'expectancy_r', 'pf',
            'lift_er', 'perm_p', 'survivor']
    with pd.option_context('display.width', 170, 'display.max_rows', None):
        print(out[cols].to_string(index=False))
    surv = out[out['survivor']]
    print(f"\nSurvivors ({len(surv)}): {list(surv['factor'])}")
    print("Wrote results/phase_c_factor_ranking.csv")


if __name__ == '__main__':
    run()
