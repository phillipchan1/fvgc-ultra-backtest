#!/usr/bin/env python3
"""Tier 1 lift tables using MFE_R as the metric.

For each factor, bucket by value and compute:
  N, avg MFE_R, median MFE_R, p75 MFE_R, pct >= 2R, pct >= 3R,
  WR_at_2R (% reaching 2R), WR_at_3R (% reaching 3R),
  avg MAE_R (worst drawdown before invalidation)

Then a "score table": rank buckets by avg MFE_R AND by WR-to-2R simultaneously.
The buckets that win on BOTH = the goldilocks subsets.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import numpy as np
import pandas as pd

POP_PATH = Path('studies/ifvg_reversal_population/results/population_enriched.csv')


def mfe_summary(g: pd.DataFrame) -> dict:
    return {
        'n': len(g),
        'wr_pct': round((g['r_multiple'] > 0).mean() * 100, 1),
        'avg_mfe_r': round(g['mfe_r'].mean(), 2),
        'median_mfe_r': round(g['mfe_r'].median(), 2),
        'p75_mfe_r': round(g['mfe_r'].quantile(0.75), 2),
        'pct_to_2R': round((g['mfe_r'] >= 2).mean() * 100, 1),
        'pct_to_3R': round((g['mfe_r'] >= 3).mean() * 100, 1),
        'pct_to_5R': round((g['mfe_r'] >= 5).mean() * 100, 1),
        'avg_mae_r': round(g['mae_r'].mean(), 2),
    }


def lift_mfe(df: pd.DataFrame, factor: str, bucketer=None, title: str = "") -> pd.DataFrame:
    work = df.copy()
    if callable(bucketer):
        work['_bucket'] = bucketer(work)
    elif isinstance(bucketer, list):
        work['_bucket'] = pd.cut(work[factor], bins=bucketer, include_lowest=True)
    else:
        work['_bucket'] = work[factor]

    rows = []
    for label, g in work.groupby('_bucket', observed=True, dropna=False):
        s = mfe_summary(g)
        s['bucket'] = str(label)
        rows.append(s)

    out = pd.DataFrame(rows).sort_values('bucket', key=lambda s: s.astype(str))
    cols = ['bucket', 'n', 'wr_pct', 'avg_mfe_r', 'median_mfe_r', 'p75_mfe_r',
            'pct_to_2R', 'pct_to_3R', 'pct_to_5R', 'avg_mae_r']
    if title:
        print(f"\n=== {title} ===")
    print(out[cols].to_string(index=False))
    return out


def main():
    df = pd.read_csv(POP_PATH)
    print(f"Population N={len(df)}")
    print(f"Overall: avg MFE_R={df['mfe_r'].mean():.2f}, "
          f"pct_to_2R={(df['mfe_r']>=2).mean()*100:.1f}%, "
          f"pct_to_3R={(df['mfe_r']>=3).mean()*100:.1f}%")

    # All tier 1 factors + the two cascade factors
    lift_mfe(df, 'sweep_level', title="sweep_level")
    lift_mfe(df, 'gap_size_pts', bucketer=[0, 8, 10, 12, 15, 20, 30, 1000],
             title="gap_size_pts")
    lift_mfe(df, 'inversion_body_fraction',
             bucketer=[0, 0.3, 0.5, 0.7, 0.9, 1.0],
             title="inversion_body_fraction")
    lift_mfe(df, 'pd_position',
             bucketer=[-0.5, 0.25, 0.4, 0.5, 0.6, 0.75, 1.5],
             title="pd_position")
    lift_mfe(df, 'prior_same_dir_sweep_count', title="prior_same_dir_sweep_count")
    lift_mfe(df, 'sweep_penetration_pts',
             bucketer=[0, 2, 5, 10, 20, 50, 200], title="sweep_penetration_pts")
    lift_mfe(df, 'gap_tf', title="gap_tf")

    # Confluence score combined
    df['confluence_score'] = df.get('confluence_score',
                                    _score_inline(df))
    lift_mfe(df, 'confluence_score', title="confluence_score (combined)")


def _score_inline(df):
    """Re-compute confluence score if not present (factors from Step 3)."""
    score = pd.Series(0, index=df.index)
    score += (df['gap_size_pts'].between(10, 12, inclusive='left')).astype(int)
    score += (df['inversion_body_fraction'].between(0.7, 0.9, inclusive='left')).astype(int)
    score += (df['sweep_level'] == 'prev_day_high').astype(int)
    score += (df['pd_position'].between(0.5, 0.6, inclusive='left')).astype(int)
    score += (df['prior_same_dir_sweep_count'] == 1).astype(int)
    return score


if __name__ == '__main__':
    main()
