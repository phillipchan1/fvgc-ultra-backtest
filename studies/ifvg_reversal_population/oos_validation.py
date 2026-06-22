#!/usr/bin/env python3
"""Step 4 — IS/OOS validation.

Split the 5-year cohort 80/20 by time:
  IS = 2021-05-17 .. 2025-05-16  (4 years, factor discovery)
  OOS = 2025-05-17 .. 2026-05-15 (1 year, hold-out test)

Two questions:
  Q1. Do the same factors carry lift on IS-only as they did on the full cohort?
      (If full-cohort factors were dominated by post-2025 luck, IS-only will look weaker.)
  Q2. Apply the IS-derived factor set + scoring to OOS. Does PF hold up?
      Primary test: score >= 2 OOS PF >= 1.30 -> model validates.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pandas as pd

from studies.ifvg_reversal_population.lift_table import build_lift_table, print_table
from studies.ifvg_reversal_population.confluence import (
    POSITIVE_FACTORS, ANTI_PATTERNS, score_row, hits_anti,
)

POP_PATH = Path('studies/ifvg_reversal_population/results/population_enriched.csv')
OUT_DIR = Path('studies/ifvg_reversal_population/results/lift')
OUT_DIR.mkdir(exist_ok=True, parents=True)

OOS_START = '2025-05-17'


def main():
    df = pd.read_csv(POP_PATH)
    df['date'] = pd.to_datetime(df['entry_ts'], utc=True, format='mixed').dt.date.astype(str)
    df['cohort'] = df['date'].apply(lambda d: 'OOS' if d >= OOS_START else 'IS')

    is_df = df[df['cohort'] == 'IS'].copy()
    oos_df = df[df['cohort'] == 'OOS'].copy()

    print(f"IS:  N={len(is_df)}  ({is_df['date'].min()} -> {is_df['date'].max()})")
    print(f"OOS: N={len(oos_df)}  ({oos_df['date'].min()} -> {oos_df['date'].max()})\n")

    # === Q1. Re-run tier-1 lift tables on IS only ===
    print("="*70)
    print("Q1: Do tier-1 factors still show lift on IS only?")
    print("="*70)

    t = build_lift_table(is_df, 'sweep_level')
    print_table(t, "IS-only: sweep_level")

    t = build_lift_table(is_df, 'gap_size_pts', bucketer=[0, 8, 10, 12, 15, 20, 30, 1000])
    print_table(t, "IS-only: gap_size_pts")

    t = build_lift_table(is_df, 'inversion_body_fraction',
                         bucketer=[0, 0.3, 0.5, 0.7, 0.9, 1.0])
    print_table(t, "IS-only: inversion_body_fraction")

    t = build_lift_table(is_df, 'pd_position',
                         bucketer=[-0.5, 0.25, 0.4, 0.5, 0.6, 0.75, 1.5])
    print_table(t, "IS-only: pd_position")

    t = build_lift_table(is_df, 'prior_same_dir_sweep_count')
    print_table(t, "IS-only: prior_same_dir_sweep_count")

    # === Q2. Confluence applied to OOS ===
    print("\n" + "="*70)
    print("Q2: OOS performance under IS-derived confluence scoring")
    print("="*70)

    for c in (is_df, oos_df):
        c['confluence_score'] = c.apply(score_row, axis=1)
        c['hits_anti_pattern'] = c.apply(hits_anti, axis=1)

    print("\nIS distribution:")
    print(is_df['confluence_score'].value_counts().sort_index().to_string())
    print("\nOOS distribution:")
    print(oos_df['confluence_score'].value_counts().sort_index().to_string())

    print("\n--- IS cumulative thresholds ---")
    _cumulative(is_df, 'IS')
    print("\n--- OOS cumulative thresholds ---")
    _cumulative(oos_df, 'OOS')

    print("\n--- Side-by-side comparison at each threshold ---")
    rows = []
    for thresh in range(0, 6):
        is_sub = is_df[is_df['confluence_score'] >= thresh]
        oos_sub = oos_df[oos_df['confluence_score'] >= thresh]
        rows.append({
            'threshold': f'score >= {thresh}',
            'IS_n': len(is_sub),
            'IS_pf': _pf(is_sub),
            'IS_wr': _wr(is_sub),
            'OOS_n': len(oos_sub),
            'OOS_pf': _pf(oos_sub),
            'OOS_wr': _wr(oos_sub),
        })
    cmp_df = pd.DataFrame(rows)
    print(cmp_df.to_string(index=False))
    cmp_df.to_csv(OUT_DIR / 'oos_validation.csv', index=False)

    # === Verdict ===
    oos_2plus = oos_df[oos_df['confluence_score'] >= 2]
    pf_oos = _pf(oos_2plus)
    print(f"\n\nVERDICT @ score >= 2:")
    print(f"  IS PF=1.47 / OOS PF={pf_oos}  (N OOS = {len(oos_2plus)})")
    if pf_oos == 'n/a':
        print("  -> no OOS trades at threshold; need more data")
    elif float(pf_oos) >= 1.30:
        print(f"  -> ✓ MODEL VALIDATES (OOS PF >= 1.30)")
    elif float(pf_oos) >= 1.00:
        print(f"  -> ⚠ degraded but still positive (1.00 <= PF < 1.30)")
    else:
        print(f"  -> ✗ OOS FAILS (PF < 1.00) — likely overfit on IS")


def _pf(d):
    if len(d) == 0:
        return 'n/a'
    gw = d.loc[d['r_multiple']>0, 'pnl_pts'].sum()
    gl = abs(d.loc[d['r_multiple']<0, 'pnl_pts'].sum()) or 1e-9
    return round(gw/gl, 2)


def _wr(d):
    if len(d) == 0:
        return 'n/a'
    w = (d['r_multiple']>0).sum()
    l = (d['r_multiple']<0).sum()
    return round(w/max(w+l,1)*100, 1)


def _cumulative(d, label):
    rows = []
    for thresh in range(0, 6):
        sub = d[d['confluence_score'] >= thresh]
        if len(sub) == 0:
            continue
        rows.append({
            'threshold': f'score >= {thresh}',
            'n': len(sub),
            'wr_pct': _wr(sub),
            'pf': _pf(sub),
            'avg_r': round(sub['r_multiple'].mean(), 3),
            'total_pnl_pts': round(sub['pnl_pts'].sum(), 1),
        })
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == '__main__':
    main()
