#!/usr/bin/env python3
"""v3.1 confluence — regime + direction-aware, fully evidence-derived.

Three-layer structure based on systematic factor ranking:

LAYER 1 — ANTI-PATTERN HARD SKIPS (ANY one excludes):
  A1. is_chop_day = True
  A2. or_15min_range < 67  (very low OR = sig negative bucket)
  A3. killzone_minute >= 45  (10:15+ = sig negative bucket)
  A4. ath_swept_today = True
  A5. inversion_body_fraction > 0.90  (too-extreme body)
  A6. remaining_same_dir_unswept >= 1
  A7. am_range_at_1030 in (50, 100)  (chop-y morning)

LAYER 2 — DIRECTION-AWARE SETUP SCORE (count factors lit):

SHORT factors (8):
  s1. sweep_level in {prev_day_high, asia_high, london_high} (premium tier sweep)
  s2. or_15min_range >= 90  (universal positive in factor ranking)
  s3. prior_day_type in {reversal_down, trend_down}  (PF 1.5+ in ranking)
  s4. prior_day_close_position <= 0.30  (yesterday closed near low)
  s5. gap_size_pts in [10, 20]  (sweet-spot band)
  s6. ob_strength_ratio >= 2.0  (moderate OB confirm)
  s7. pd_position in [0.50, 0.75]  (premium)
  s8. smt_bearish_at_sweep = True  (cross-instrument divergence)

LONG factors (8):
  l1. or_45min_range >= 137  (the long-positive OR bucket — PF 1.45)
  l2. prior_day_type in {reversal_up, trend_up}
  l3. prior_day_directional_changes >= 4  (moderate intraday chop)
  l4. prior_day_range_atr_ratio >= 0.74  (moderate vol regime)
  l5. or_15min_range >= 88  (universal OR)
  l6. sweep_level in {prev_day_low, asia_low, overnight_low, london_low, daily_50pct_low}
  l7. pd_position in [0.25, 0.50]  (discount)
  l8. NOT is_near_ath_100pt  (distance to ATH >= 100pt — anti the long-killer)

Score = number of factors lit (0-8). Threshold tested 0-8.

Output:
  - per-row v3_1_score_long, v3_1_score_short, v3_1_anti_hit
  - per-threshold lift table (IS / OOS) per direction
  - comparison vs v3 baseline at same thresholds
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import numpy as np
import pandas as pd

POP_PATH = Path('studies/ifvg_reversal_population/results/population_scored.csv')
OUT_DIR = Path('studies/ifvg_reversal_population/results/v3_1')
OUT_DIR.mkdir(parents=True, exist_ok=True)

OOS_START = '2025-05-17'


SHORT_LEVELS = {'prev_day_high', 'asia_high', 'london_high', 'daily_50pct_high'}
LONG_LEVELS = {'prev_day_low', 'asia_low', 'overnight_low', 'london_low', 'daily_50pct_low'}


SHORT_FACTORS = {
    's1_sweep_tier_high':   lambda r: r['sweep_level'] in SHORT_LEVELS,
    's2_or15_strong':       lambda r: (r.get('or_15min_range') or 0) >= 90,
    's3_prior_type_bearish':lambda r: r.get('prior_day_type') in ('reversal_down', 'trend_down'),
    's4_prior_close_low':   lambda r: (r.get('prior_day_close_position') or 1.0) <= 0.30,
    's5_gap_sweet':         lambda r: 10 <= r['gap_size_pts'] <= 20,
    's6_ob_strong':         lambda r: bool(r.get('has_ob_confirm', False)) and (r.get('ob_strength_ratio') or 0) >= 2.0,
    's7_pd_premium':        lambda r: 0.50 <= r['pd_position'] <= 0.75,
    's8_smt_bearish':       lambda r: bool(r.get('smt_bearish_at_sweep', False)),
}

LONG_FACTORS = {
    'l1_or45_strong':       lambda r: (r.get('or_45min_range') or 0) >= 137,
    'l2_prior_type_bullish':lambda r: r.get('prior_day_type') in ('reversal_up', 'trend_up'),
    'l3_prior_dir_changes': lambda r: (r.get('prior_day_directional_changes') or 0) >= 4,
    'l4_prior_atr_moderate':lambda r: (r.get('prior_day_range_atr_ratio') or 0) >= 0.74,
    'l5_or15_moderate':     lambda r: (r.get('or_15min_range') or 0) >= 88,
    'l6_sweep_tier_low':    lambda r: r['sweep_level'] in LONG_LEVELS,
    'l7_pd_discount':       lambda r: 0.25 <= r['pd_position'] <= 0.50,
    'l8_far_from_ath':      lambda r: not bool(r.get('is_near_ath_100pt', False)),
}

ANTI_PATTERNS = {
    'a1_chop_day':          lambda r: bool(r.get('is_chop_day', False)),
    'a2_or15_very_low':     lambda r: (r.get('or_15min_range') or 999) < 67,
    'a3_late_killzone':     lambda r: (r.get('killzone_minute') or 0) >= 45,
    'a4_ath_swept_today':   lambda r: bool(r.get('ath_swept_today', False)),
    'a5_body_too_extreme':  lambda r: (r.get('inversion_body_fraction') or 0) > 0.90,
    'a6_magnets_against':   lambda r: (r.get('remaining_same_dir_unswept') or 0) >= 1,
    'a7_amrange_chop':      lambda r: 50 < (r.get('am_range_at_1030') or 0) < 100,
}


# =====================================================================
# Helpers
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


def threshold_sweep(df, score_col, label):
    rows = []
    for thresh in range(0, 9):
        cell = df[df[score_col] >= thresh]
        if len(cell) < 5:
            continue
        s = cell_stats(cell)
        rows.append({'threshold': f'>= {thresh}', **s})
    out = pd.DataFrame(rows)
    print(f"\n  --- {label} ---")
    print(out.to_string(index=False))
    return out


def main():
    df = pd.read_csv(POP_PATH)
    df['date'] = pd.to_datetime(df['entry_ts'], utc=True, format='mixed').dt.date.astype(str)
    df['cohort'] = df['date'].apply(lambda d: 'OOS' if d >= OOS_START else 'IS')
    print(f"Population: {len(df)} rows, IS={len(df[df['cohort']=='IS'])}, OOS={len(df[df['cohort']=='OOS'])}\n")

    print("Computing v3.1 scores + anti-pattern flag...")
    df['v3_1_score_long']  = score_direction(df, LONG_FACTORS)
    df['v3_1_score_short'] = score_direction(df, SHORT_FACTORS)
    df['v3_1_anti_hit']    = hits_any_anti(df)
    df['v3_1_score'] = df.apply(
        lambda r: r['v3_1_score_short'] if r['direction'] == 'short' else r['v3_1_score_long'],
        axis=1,
    )

    # Lit-rate sanity
    print(f"\nAnti-pattern hit rate: {df['v3_1_anti_hit'].mean()*100:.1f}%")
    for name, fn in ANTI_PATTERNS.items():
        print(f"  {name:24}  {df.apply(fn, axis=1).mean()*100:5.1f}%")
    print()
    print("Survivors after anti-filter:")
    survivors = df[~df['v3_1_anti_hit']]
    print(f"  N={len(survivors)} ({len(survivors)/len(df)*100:.0f}%)")
    print(f"  PF on survivors (any direction): {cell_stats(survivors)['pf']}")
    print()
    print(f"Per-direction score distributions (survivors only):")
    for direction in ('short', 'long'):
        sub = survivors[survivors['direction'] == direction]
        col = f'v3_1_score_{direction}'
        print(f"  {direction}: {sub[col].value_counts().sort_index().to_dict()}")
    print()

    # ============= Threshold sweeps per direction × cohort =============
    print("=" * 78)
    print("v3.1 THRESHOLD SWEEPS (anti-pattern filter applied)")
    print("=" * 78)

    for direction in ('short', 'long'):
        score_col = f'v3_1_score_{direction}'
        for cohort in ('IS', 'OOS'):
            sub = survivors[(survivors['direction'] == direction) &
                            (survivors['cohort'] == cohort)].copy()
            if len(sub) < 20:
                continue
            label = f"{direction.upper()} | {cohort}"
            threshold_sweep(sub, score_col, label)
        print()

    # ============= Direct comparison: v2 → v3 → v3.1 on OOS =============
    print("\n" + "=" * 78)
    print("PROGRESSION OOS COMPARISON")
    print("=" * 78)

    oos = df[df['cohort'] == 'OOS']
    oos_survive = survivors[survivors['cohort'] == 'OOS']

    print("\nv2 confluence (OOS):")
    rows = []
    for t in range(0, 6):
        cell = oos[oos['confluence_score'] >= t]
        if len(cell) < 5: continue
        rows.append({'threshold': f'v2 >= {t}', **cell_stats(cell)})
    print(pd.DataFrame(rows).to_string(index=False))

    print("\nv3 SHORT (OOS, w/v3 anti-filter):")
    if 'v3_score_short' in df.columns and 'v3_anti_hit' in df.columns:
        v3_oos = df[(df['cohort'] == 'OOS') & ~df['v3_anti_hit']]
        rows = []
        for t in range(0, 9):
            cell = v3_oos[(v3_oos['direction'] == 'short') & (v3_oos['v3_score_short'] >= t)]
            if len(cell) < 5: continue
            rows.append({'threshold': f'v3_short >= {t}', **cell_stats(cell)})
        print(pd.DataFrame(rows).to_string(index=False))

    print("\nv3.1 SHORT (OOS, w/v3.1 anti-filter):")
    rows = []
    for t in range(0, 9):
        cell = oos_survive[(oos_survive['direction'] == 'short') & (oos_survive['v3_1_score_short'] >= t)]
        if len(cell) < 5: continue
        rows.append({'threshold': f'v3_1_short >= {t}', **cell_stats(cell)})
    print(pd.DataFrame(rows).to_string(index=False))

    print("\nv3.1 LONG (OOS, w/v3.1 anti-filter):")
    rows = []
    for t in range(0, 9):
        cell = oos_survive[(oos_survive['direction'] == 'long') & (oos_survive['v3_1_score_long'] >= t)]
        if len(cell) < 5: continue
        rows.append({'threshold': f'v3_1_long >= {t}', **cell_stats(cell)})
    print(pd.DataFrame(rows).to_string(index=False))

    print("\nv3.1 COMBINED (either direction at score>=N, w/anti-filter):")
    rows = []
    for t in range(0, 9):
        cell = oos_survive[oos_survive['v3_1_score'] >= t]
        if len(cell) < 5: continue
        rows.append({'threshold': f'v3_1_combined >= {t}', **cell_stats(cell)})
    print(pd.DataFrame(rows).to_string(index=False))

    # Persist scored CSV
    df.to_csv(POP_PATH, index=False)
    print(f"\nWrote v3.1 columns to {POP_PATH}")


if __name__ == '__main__':
    main()
