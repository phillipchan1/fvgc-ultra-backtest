#!/usr/bin/env python3
"""Systematic single-factor lift ranking across ALL columns in population_scored.csv.

For every column with enough variance, bucket the trades and compute:
  - WR, PF, avg_R per bucket
  - Bootstrap CI on PF
  - Lift vs baseline (full-cohort PF)

Output: one ranked CSV per direction (long/short) with all (factor, bucket, lift)
rows sorted by absolute lift. Plus a markdown summary of top positive and top
negative cells.

This is the input to building a v3 confluence stack with evidence.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import numpy as np
import pandas as pd

POP_PATH = Path('studies/ifvg_reversal_population/results/population_scored.csv')
OUT_DIR = Path('studies/ifvg_reversal_population/results/factor_ranking')
OUT_DIR.mkdir(parents=True, exist_ok=True)


# Factors to skip (IDs, timestamps, derived from outcome, redundant)
SKIP_COLS = {
    'entry_ts', 'exit_ts', 'sweep_ts', 'gap_created_at',
    'entry_price', 'exit_price', 'level_price', 'ath_at_entry',
    'session_high_at_entry', 'dealing_range_low', 'dealing_range_high',
    'pnl_pts', 'r_multiple', 'exit_reason', 'bars_held', 'stop_distance_pts',
    'cohort', 'date', '_bucket',
    # MFE/MAE leak post-entry information about the outcome
    'mfe_pts', 'mae_pts', 'mfe_r', 'mae_r', 'bars_to_invalidation',
    # OB info derived from intra-trade — keep boolean only
    'ob_engulfing_body_pts', 'ob_engulfed_body_pts',
    'ob_confirm_bar_offset',
    # Prior sweep names — too cardinal
    'prior_same_dir_sweep_levels', 'remaining_same_dir_unswept_levels',
    'red_folder_event_names',
    # Confluence/anti — derived
    'confluence_score', 'hits_anti_pattern',
}

# Manual bucket specs for known continuous factors
BUCKET_SPECS = {
    'gap_size_pts':                  [0, 6, 8, 10, 12, 15, 20, 30, 1000],
    'sweep_penetration_pts':         [0, 2, 5, 10, 20, 50, 200],
    'inversion_body_fraction':       [0, 0.3, 0.5, 0.7, 0.9, 1.0],
    'pd_position':                   [-1, 0.25, 0.4, 0.5, 0.6, 0.75, 1.5],
    'inversion_latency_s':           [0, 30, 60, 120, 300, 600, 9999],
    'killzone_minute':               [-1, 15, 30, 45, 60, 75, 91],
    'am_range_at_1030':              [0, 50, 100, 200, 400, 9999],
    'distance_to_ath_pts':           [0, 30, 50, 100, 300, 1000, 99999],
    'pct_below_ath':                 [0, 0.005, 0.01, 0.02, 0.05, 0.1, 1.0],
    'ob_strength_ratio':             [0, 1.0, 1.5, 2.0, 3.0, 5.0, 100],
    'prior_same_dir_sweep_count':    [-1, 0, 1, 2, 3, 10],
    'remaining_same_dir_unswept':    [-1, 0, 1, 2, 10],
}


def baseline_stats(df: pd.DataFrame) -> dict:
    w = (df['r_multiple'] > 0).sum()
    l = (df['r_multiple'] < 0).sum()
    gw = df.loc[df['r_multiple'] > 0, 'pnl_pts'].sum()
    gl = abs(df.loc[df['r_multiple'] < 0, 'pnl_pts'].sum()) or 1e-9
    return {
        'n': len(df),
        'wr': w / max(w + l, 1) * 100,
        'pf': gw / gl,
        'avg_r': df['r_multiple'].mean(),
    }


def bootstrap_pf(pnl: np.ndarray, iters: int = 500) -> tuple[float, float]:
    if len(pnl) < 10:
        return float('nan'), float('nan')
    rng = np.random.default_rng(42)
    pfs = np.empty(iters)
    for i in range(iters):
        s = pnl[rng.integers(0, len(pnl), len(pnl))]
        gw = s[s > 0].sum()
        gl = abs(s[s < 0].sum())
        pfs[i] = gw / max(gl, 1e-9)
    return float(np.percentile(pfs, 5)), float(np.percentile(pfs, 95))


def bucketize(series: pd.Series, factor: str) -> pd.Series:
    """Bucket a column into discrete labels."""
    if factor in BUCKET_SPECS:
        return pd.cut(series, bins=BUCKET_SPECS[factor], include_lowest=True)

    # Boolean -> direct
    if series.dtype == bool or set(series.dropna().unique()) <= {True, False, 0, 1, 0.0, 1.0}:
        return series.astype('object')

    # Categorical / object -> direct
    if series.dtype == 'object':
        # Cap cardinality
        uniq = series.nunique(dropna=True)
        if uniq > 30:
            return None
        return series

    # Numeric continuous without manual spec -> quartile cut
    try:
        return pd.qcut(series, q=4, duplicates='drop')
    except (ValueError, TypeError):
        return None


def factor_lift(df: pd.DataFrame, baseline_pf: float) -> pd.DataFrame:
    rows = []
    for col in df.columns:
        if col in SKIP_COLS:
            continue
        if df[col].isna().all():
            continue
        if df[col].nunique(dropna=True) < 2:
            continue
        buckets = bucketize(df[col], col)
        if buckets is None:
            continue
        for label, g in df.groupby(buckets, observed=True, dropna=False):
            if len(g) < 30:
                continue
            stats = baseline_stats(g)
            pf_lo, pf_hi = bootstrap_pf(g['pnl_pts'].values)
            rows.append({
                'factor': col,
                'bucket': str(label),
                'n': stats['n'],
                'wr_pct': round(stats['wr'], 1),
                'pf': round(stats['pf'], 2),
                'avg_r': round(stats['avg_r'], 3),
                'pf_ci_low': round(pf_lo, 2),
                'pf_ci_high': round(pf_hi, 2),
                'pf_lift_vs_baseline': round(stats['pf'] - baseline_pf, 2),
                'sig_positive': pf_lo > 1.0,
                'sig_negative': pf_hi < 1.0,
            })
    out = pd.DataFrame(rows)
    return out.sort_values('pf_lift_vs_baseline', ascending=False).reset_index(drop=True)


def main():
    df = pd.read_csv(POP_PATH)
    print(f"Population: {len(df)} rows, {len(df.columns)} columns\n")

    # Run for each direction separately + combined
    for direction in ('all', 'long', 'short'):
        if direction == 'all':
            sub = df.copy()
        else:
            sub = df[df['direction'] == direction].copy()
        if len(sub) < 30:
            continue
        baseline = baseline_stats(sub)
        print(f"=== {direction.upper()} cohort baseline: "
              f"N={baseline['n']}, WR={baseline['wr']:.1f}%, PF={baseline['pf']:.2f} ===")

        lift = factor_lift(sub, baseline['pf'])
        out_path = OUT_DIR / f'factor_lift_{direction}.csv'
        lift.to_csv(out_path, index=False)
        print(f"  wrote {out_path}  ({len(lift)} factor-bucket rows)")

        # Top 15 positive lift, sig
        pos = lift[lift['sig_positive']].head(15)
        if len(pos):
            print(f"\n  Top {len(pos)} sig-positive cells (CI excludes 1.0):")
            print(pos[['factor', 'bucket', 'n', 'wr_pct', 'pf',
                       'pf_ci_low', 'pf_ci_high', 'pf_lift_vs_baseline']].to_string(index=False))

        # Top 10 sig-negative
        neg = lift[lift['sig_negative']].tail(10)
        if len(neg):
            print(f"\n  Bottom {len(neg)} sig-negative cells (CI excludes 1.0):")
            print(neg[['factor', 'bucket', 'n', 'wr_pct', 'pf',
                       'pf_ci_low', 'pf_ci_high', 'pf_lift_vs_baseline']].to_string(index=False))
        print()


if __name__ == '__main__':
    main()
