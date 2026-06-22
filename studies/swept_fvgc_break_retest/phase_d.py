#!/usr/bin/env python3
"""
Phase D — tiered cohort mining (IN-SAMPLE / train).

Curated, mechanism-grounded candidate FILTERS (Phase-C survivors + the strongest
mechanism near-misses, each tagged). Enumerate 1/2/3-factor AND-combos, keep
N>=MIN_N, rank by composite = PF * WR * log(n) but ALWAYS report E[R] + freq
alongside (never select on WR alone). Correlation-aware: drop combos whose two
filters are near-duplicate (|corr|>0.85).

Outputs: results/phase_d_cohorts.csv, results/phase_d_top_cohorts.json
"""

from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from studies.swept_fvgc_break_retest.metrics import cohort_metrics, span_years  # noqa: E402
from studies.swept_fvgc_break_retest.splits import load_tradeable, train_test  # noqa: E402
from studies.swept_fvgc_break_retest.splits import _magnet_group_class  # noqa: E402

RESULTS_DIR = Path(__file__).resolve().parent / 'results'
MIN_N = 40
CORR_DROP = 0.85


def candidate_filters(df: pd.DataFrame) -> dict[str, tuple[pd.Series, str]]:
    """name -> (boolean mask, tag in {survivor, exploratory, protective})."""
    inside = df['inside_htf_fvg'].astype(str).isin(['True', 'true'])
    pos = pd.to_numeric(df['htf_position_within_gap'], errors='coerce')
    mg = df['magnet_group'].map(_magnet_group_class)
    f = {
        # --- Phase-C survivors (deduped) ---
        'short': (df['direction'] == 'short', 'survivor'),
        'below_vwap': (df['vwap_above'].astype(str).isin(['False', 'false']), 'survivor'),
        'open_above_prior_va': (df['open_vs_prior_va'] == 'above', 'survivor'),
        'vixy_normal': (df['vixy_regime'] == 'normal', 'survivor'),
        'far_magnet': (pd.to_numeric(df['magnet_dist_R'], errors='coerce') > 3, 'survivor'),
        'htf_mid': (inside & pos.between(0.33, 0.66), 'survivor'),
        # --- protective filters (strong anti-signals -> exclude their bad bucket) ---
        'not_target_htf': (mg != 'htf', 'protective'),
        'not_htf_far': (~(inside & (pos > 0.66)), 'protective'),
        'r0_ge_10': (df['r0_ge_10pt'].astype(str).isin(['True', 'true']), 'protective'),
        'not_ifvg': (df['variant'] != 'ifvg', 'protective'),
        # --- mechanism near-misses (exploratory) ---
        'bsl_ssl': (df['swept_level_provenance'] == 'bsl_ssl', 'exploratory'),
        'btr_4_6': (df['bars_break_to_retest_bucket'] == '4-6', 'exploratory'),
        'level_touch_3_5': (pd.to_numeric(df['level_touch_count'], errors='coerce').between(3, 5), 'exploratory'),
        'reclaim': (df['sweep_type'] == 'reclaim', 'exploratory'),
    }
    return f


def run():
    df = load_tradeable()
    train, _ = train_test(df)
    yrs = span_years(train)
    base = cohort_metrics(train, span_years=yrs)
    filters = candidate_filters(train)
    names = list(filters)
    masks = {n: m.to_numpy() for n, (m, _t) in filters.items()}
    tags = {n: t for n, (_m, t) in filters.items()}

    # pairwise correlation to drop near-duplicate pairs in combos
    corr = {}
    for a, b in itertools.combinations(names, 2):
        ma, mb = masks[a].astype(float), masks[b].astype(float)
        if ma.std() > 0 and mb.std() > 0:
            corr[(a, b)] = abs(np.corrcoef(ma, mb)[0, 1])
        else:
            corr[(a, b)] = 0.0

    rows = []
    for k in (1, 2, 3):
        for combo in itertools.combinations(names, k):
            # skip near-duplicate pairs
            if any(corr.get(tuple(sorted(p)), 0.0) > CORR_DROP
                   for p in itertools.combinations(combo, 2)):
                continue
            mask = np.ones(len(train), dtype=bool)
            for c in combo:
                mask &= masks[c]
            n = int(mask.sum())
            if n < MIN_N:
                continue
            sub = train[mask]
            m = cohort_metrics(sub, span_years=yrs)
            pf = m['pf'] if isinstance(m['pf'], (int, float)) else None
            if pf is None or pf <= 0:
                composite = None
            else:
                composite = pf * (m['wr'] or 0) * np.log(n)
            combo_tags = sorted({tags[c] for c in combo})
            rows.append({
                'k': k, 'cohort': ' & '.join(combo), 'n': n, 'per_year': m['per_year'],
                'wr': m['wr'], 'expectancy_r': m['expectancy_r'], 'pf': pf,
                'lift_er': round(m['expectancy_r'] - base['expectancy_r'], 4),
                'composite': round(composite, 4) if composite else None,
                'tags': ','.join(combo_tags),
                'all_survivor': all(tags[c] in ('survivor', 'protective') for c in combo),
            })

    out = pd.DataFrame(rows).sort_values('composite', ascending=False, na_position='last')
    out.to_csv(RESULTS_DIR / 'phase_d_cohorts.csv', index=False)

    print(f"Train baseline PF={base['pf']} E[R]={base['expectancy_r']} n={base['n']}\n")
    cols = ['k', 'cohort', 'n', 'per_year', 'wr', 'expectancy_r', 'pf', 'lift_er', 'composite']
    print("Top cohorts by composite (PF x WR x log n), N>=40:")
    with pd.option_context('display.width', 200, 'display.max_colwidth', 60):
        print(out.head(20)[cols].to_string(index=False))
        print("\nTop cohorts using ONLY survivor/protective filters:")
        clean = out[out['all_survivor']].head(12)
        print(clean[cols].to_string(index=False))
        print("\nHighest E[R] cohorts (N>=40):")
        print(out.sort_values('expectancy_r', ascending=False).head(12)[cols].to_string(index=False))

    # freeze top cohorts for Phase E: clean-survivor + top-composite + top-E[R]
    # (the high-E[R] runner family has low WR -> low composite, so include it
    #  explicitly so OOS actually tests it).
    by_er = out[out['n'] >= MIN_N].sort_values('expectancy_r', ascending=False).head(6)
    top = pd.concat([out[out['all_survivor']].head(5), out.head(5), by_er]).drop_duplicates('cohort')
    defs = [{'cohort': r['cohort'].split(' & '), 'tags': r['tags'],
             'train': {k: r[k] for k in ['n', 'wr', 'expectancy_r', 'pf', 'per_year', 'lift_er']}}
            for _, r in top.iterrows()]
    (RESULTS_DIR / 'phase_d_top_cohorts.json').write_text(json.dumps(defs, indent=2, default=str))
    print(f"\nWrote phase_d_cohorts.csv ({len(out)} combos) + phase_d_top_cohorts.json ({len(defs)} frozen)")


if __name__ == '__main__':
    run()
