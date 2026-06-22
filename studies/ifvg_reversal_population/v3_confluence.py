#!/usr/bin/env python3
"""v3 confluence — direction-aware factor stack, evidence-derived from factor_ranking.

Builds two parallel confluence stacks:

SHORT factors (8) — backed by 15+ significantly positive cells in factor ranking:
  1. prior_same_dir_sweep_count >= 1 (cascade)
  2. pd_position in [0.50, 0.75] (premium, sweet spot)
  3. inversion_body_fraction in [0.7, 0.9] (strong but not extreme momentum)
  4. sweep_level in {prev_day_high, asia_high, london_high} (strong levels)
  5. gap_size_pts in [10, 20] (validated band)
  6. ob_strength_ratio >= 2.0 (moderate OB present)
  7. smt_bearish_aligns (cross-instrument divergence)
  8. reaction_clean=True (no stall/nuke)

LONG factors (8) — using what evidence we have despite cohort headwind:
  1. prior_same_dir_sweep_count == 1 (original strong factor)
  2. pd_position in [0.40, 0.50] (discount for longs)
  3. inversion_body_fraction in [0.5, 0.7] (longs DON'T want 0.7-0.9, that was negative)
  4. sweep_level in {prev_day_low, asia_low, london_low, overnight_low, running_50pct_low}
  5. gap_size_pts in [8, 12]
  6. has_ob_confirm + ob_strength_ratio >= 2.0
  7. NOT is_near_ath_100pt (anti-pattern protection)
  8. reaction_clean=True

ANTI-PATTERNS (hard filters — ANY one excludes the trade):
  A1. is_chop_day = True
  A2. am_range_at_1030 < 100 (low-volatility morning)
  A3. killzone_minute >= 45 (10:15+ — bad time slot)
  A4. ath_swept_today = True
  A5. inversion_body_fraction > 0.9 (too-extreme body)
  A6. remaining_same_dir_unswept >= 1 (magnets against trade)

Score = number of factors lit (0-8). Anti-patterns are HARD filter — if any
fire, the trade is rejected before scoring.

Output:
  - per-row v3_score_long, v3_score_short, v3_anti_pattern flags
  - per-threshold lift table (IS / OOS / both)
  - comparison vs v2 baseline at same thresholds
  - bootstrap CI on the score-threshold PFs

This is the "v3 candidate model" for OOS validation.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import numpy as np
import pandas as pd

POP_PATH = Path('studies/ifvg_reversal_population/results/population_scored.csv')
OUT_DIR = Path('studies/ifvg_reversal_population/results/v3')
OUT_DIR.mkdir(parents=True, exist_ok=True)

OOS_START = '2025-05-17'


# =====================================================================
# Direction-aware factor definitions
# =====================================================================

SHORT_FACTORS = {
    'cascade':       lambda r: r['prior_same_dir_sweep_count'] >= 1,
    'pd_premium':    lambda r: 0.50 <= r['pd_position'] <= 0.75,
    'strong_body':   lambda r: 0.70 <= r['inversion_body_fraction'] <= 0.90,
    'strong_level':  lambda r: r['sweep_level'] in ('prev_day_high', 'asia_high', 'london_high'),
    'gap_sweet':     lambda r: 10 <= r['gap_size_pts'] <= 20,
    'ob_strong':     lambda r: bool(r.get('has_ob_confirm', False)) and (r.get('ob_strength_ratio') or 0) >= 2.0,
    'smt_bearish':   lambda r: bool(r.get('smt_bearish_at_sweep', False)),
    'clean_react':   lambda r: bool(r.get('reaction_clean', False)),
}

LONG_FACTORS = {
    'cascade_1':     lambda r: r['prior_same_dir_sweep_count'] == 1,
    'pd_discount':   lambda r: 0.40 <= r['pd_position'] <= 0.50,
    'moderate_body': lambda r: 0.50 <= r['inversion_body_fraction'] <= 0.70,
    'long_level':    lambda r: r['sweep_level'] in ('prev_day_low', 'asia_low', 'london_low', 'overnight_low', 'running_50pct_low'),
    'gap_8_12':      lambda r: 8 <= r['gap_size_pts'] <= 12,
    'ob_strong':     lambda r: bool(r.get('has_ob_confirm', False)) and (r.get('ob_strength_ratio') or 0) >= 2.0,
    'far_from_ath':  lambda r: not bool(r.get('is_near_ath_100pt', False)),
    'clean_react':   lambda r: bool(r.get('reaction_clean', False)),
}

ANTI_PATTERNS = {
    'chop_day':         lambda r: bool(r.get('is_chop_day', False)),
    'low_am_range':     lambda r: (r.get('am_range_at_1030') or 0) < 100,
    'late_killzone':    lambda r: (r.get('killzone_minute') or 0) >= 45,
    'ath_swept_today':  lambda r: bool(r.get('ath_swept_today', False)),
    'body_too_extreme': lambda r: (r.get('inversion_body_fraction') or 0) > 0.90,
    'magnets_against':  lambda r: (r.get('remaining_same_dir_unswept') or 0) >= 1,
}


# =====================================================================
# Scoring + analysis
# =====================================================================

def score_direction(df: pd.DataFrame, factors: dict) -> pd.Series:
    s = pd.Series(0, index=df.index, dtype=int)
    for fn in factors.values():
        s += df.apply(fn, axis=1).astype(int)
    return s


def hits_any_anti(df: pd.DataFrame) -> pd.Series:
    s = pd.Series(False, index=df.index)
    for fn in ANTI_PATTERNS.values():
        s |= df.apply(fn, axis=1)
    return s


def bootstrap_pf(pnl, iters=1000):
    if len(pnl) < 10:
        return float('nan'), float('nan')
    rng = np.random.default_rng(42)
    pfs = np.empty(iters)
    for i in range(iters):
        s = pnl[rng.integers(0, len(pnl), len(pnl))]
        gw = s[s > 0].sum(); gl = abs(s[s < 0].sum()) or 1e-9
        pfs[i] = gw / gl
    return float(np.percentile(pfs, 5)), float(np.percentile(pfs, 95))


def cell_stats(df):
    w = (df['r_multiple'] > 0).sum(); l = (df['r_multiple'] < 0).sum()
    gw = df.loc[df['r_multiple'] > 0, 'pnl_pts'].sum()
    gl = abs(df.loc[df['r_multiple'] < 0, 'pnl_pts'].sum()) or 1e-9
    pf_lo, pf_hi = bootstrap_pf(df['pnl_pts'].values)
    return {
        'n': len(df),
        'wr': round(w / max(w + l, 1) * 100, 1),
        'pf': round(gw / gl, 2),
        'avg_r': round(df['r_multiple'].mean(), 3),
        'total_r': round(df['r_multiple'].sum(), 1),
        'pf_ci_low': round(pf_lo, 2),
        'pf_ci_high': round(pf_hi, 2),
    }


def threshold_sweep(df, score_col, anti_col, label):
    print(f"\n--- {label} ---")
    rows = []
    for thresh in range(0, 9):
        survivors = df[~df[anti_col]]
        cell = survivors[survivors[score_col] >= thresh]
        if len(cell) < 5:
            continue
        s = cell_stats(cell)
        rows.append({'threshold': f'score >= {thresh}', **s})
    out = pd.DataFrame(rows)
    print(out.to_string(index=False))
    return out


def main():
    df = pd.read_csv(POP_PATH)
    df['date'] = pd.to_datetime(df['entry_ts'], utc=True, format='mixed').dt.date.astype(str)
    df['cohort'] = df['date'].apply(lambda d: 'OOS' if d >= OOS_START else 'IS')
    print(f"Population: {len(df)} rows, IS={len(df[df['cohort']=='IS'])}, OOS={len(df[df['cohort']=='OOS'])}\n")

    # Compute scores per direction + anti
    print("Computing v3 scores + anti-pattern flags...")
    df['v3_score_long']  = score_direction(df, LONG_FACTORS)
    df['v3_score_short'] = score_direction(df, SHORT_FACTORS)
    df['v3_anti_hit']    = hits_any_anti(df)

    # Direction-relevant score
    df['v3_score'] = df.apply(
        lambda r: r['v3_score_short'] if r['direction']=='short' else r['v3_score_long'],
        axis=1,
    )

    # ============= Lit-rate sanity =============
    print(f"\nAnti-pattern hit rate: {df['v3_anti_hit'].mean()*100:.1f}%")
    print(f"  -- per anti-pattern:")
    for name, fn in ANTI_PATTERNS.items():
        rate = df.apply(fn, axis=1).mean() * 100
        print(f"    {name:20} {rate:5.1f}%")
    print()
    print(f"Score distributions (all trades):")
    for direction in ('long', 'short'):
        sub = df[df['direction'] == direction]
        col = 'v3_score_long' if direction=='long' else 'v3_score_short'
        print(f"  {direction}: {sub[col].value_counts().sort_index().to_dict()}")
    print()

    # ============= Threshold sweep per direction × cohort =============
    print("=" * 78)
    print("v3 THRESHOLD SWEEPS")
    print("=" * 78)

    for direction in ('short', 'long'):
        score_col = f'v3_score_{direction}'
        for cohort in ('IS', 'OOS'):
            sub = df[(df['direction'] == direction) & (df['cohort'] == cohort)].copy()
            if len(sub) < 30:
                continue
            label = f"{direction.upper()} | {cohort}"
            threshold_sweep(sub, score_col, 'v3_anti_hit', label)

    # ============= Comparison with v2 =============
    print("\n" + "=" * 78)
    print("COMPARISON: v3 (direction-aware) vs v2 (legacy 5-factor)")
    print("=" * 78)
    # Compute v2 score using existing confluence_score column
    if 'confluence_score' in df.columns:
        for cohort in ('IS', 'OOS'):
            sub = df[df['cohort'] == cohort]
            print(f"\n--- {cohort} ---")
            print("v2 thresholds (existing confluence_score):")
            rows = []
            for t in range(0, 6):
                cell = sub[sub['confluence_score'] >= t]
                if len(cell) < 5:
                    continue
                s = cell_stats(cell)
                rows.append({'threshold': f'v2 >= {t}', **s})
            print(pd.DataFrame(rows).to_string(index=False))

            print("\nv3 SHORT thresholds (with anti-pattern filter):")
            short = sub[sub['direction'] == 'short']
            short_clean = short[~short['v3_anti_hit']]
            rows = []
            for t in range(0, 9):
                cell = short_clean[short_clean['v3_score_short'] >= t]
                if len(cell) < 5:
                    continue
                s = cell_stats(cell)
                rows.append({'threshold': f'v3_short >= {t}', **s})
            print(pd.DataFrame(rows).to_string(index=False))

            print("\nv3 LONG thresholds (with anti-pattern filter):")
            long = sub[sub['direction'] == 'long']
            long_clean = long[~long['v3_anti_hit']]
            rows = []
            for t in range(0, 9):
                cell = long_clean[long_clean['v3_score_long'] >= t]
                if len(cell) < 5:
                    continue
                s = cell_stats(cell)
                rows.append({'threshold': f'v3_long >= {t}', **s})
            print(pd.DataFrame(rows).to_string(index=False))

    # Persist scored CSV
    df.to_csv(POP_PATH, index=False)
    print(f"\nWrote v3 score columns to {POP_PATH}")


if __name__ == '__main__':
    main()
