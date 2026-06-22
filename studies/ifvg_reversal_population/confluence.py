#!/usr/bin/env python3
"""Step 3 — confluence scoring.

For each trade, count how many of the 5 tier-1 positive factors are "lit". Then
bucket WR/PF by score to see if confluence scales as Tempo predicts.

Also tests an "anti-pattern filter" variant: pre-exclude trades hitting any of
the 3 anti-patterns identified in tier-1 lift tables, then score the survivors.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pandas as pd

from studies.ifvg_reversal_population.lift_table import build_lift_table, print_table

POP_PATH = Path('studies/ifvg_reversal_population/results/population_enriched.csv')
OUT_DIR = Path('studies/ifvg_reversal_population/results/lift')
OUT_DIR.mkdir(exist_ok=True, parents=True)


POSITIVE_FACTORS = {
    'f1_prior_cascade':   lambda r: r['prior_same_dir_sweep_count'] == 1,
    'f2_pd_just_past':    lambda r: 0.50 < r['pd_position'] <= 0.60,
    'f3_strong_body':     lambda r: 0.70 < r['inversion_body_fraction'] <= 0.90,
    'f4_pdh_sweep':       lambda r: r['sweep_level'] == 'prev_day_high',
    'f5_gap_sweet_spot':  lambda r: 10 < r['gap_size_pts'] <= 12,
}

ANTI_PATTERNS = {
    'a1_body_too_extreme':  lambda r: r['inversion_body_fraction'] > 0.90,
    'a2_gap_dead_zone':     lambda r: 12 < r['gap_size_pts'] <= 15,
    'a3_pdl_long':          lambda r: r['sweep_level'] == 'prev_day_low',
}


def score_row(row):
    return sum(1 for fn in POSITIVE_FACTORS.values() if fn(row))


def hits_anti(row):
    return any(fn(row) for fn in ANTI_PATTERNS.values())


def main():
    df = pd.read_csv(POP_PATH)
    print(f"Population: N={len(df)}\n")

    # --- Per-factor lit-rate sanity ---
    print("Lit rate per positive factor:")
    for name, fn in POSITIVE_FACTORS.items():
        lit = df.apply(fn, axis=1).sum()
        print(f"  {name:<22}: {lit:>4} / {len(df)}  ({lit/len(df)*100:.1f}%)")
    print()
    print("Hit rate per anti-pattern:")
    for name, fn in ANTI_PATTERNS.items():
        hit = df.apply(fn, axis=1).sum()
        print(f"  {name:<22}: {hit:>4} / {len(df)}  ({hit/len(df)*100:.1f}%)")
    print()

    # --- Compute confluence score ---
    df['confluence_score'] = df.apply(score_row, axis=1)
    df['hits_anti_pattern'] = df.apply(hits_anti, axis=1)

    # --- Lift table: pure additive score ---
    t = build_lift_table(df, 'confluence_score')
    print_table(t, "Confluence score (0-5) — pure additive, no exclusions")
    t.to_csv(OUT_DIR / 'confluence_pure.csv', index=False)

    # --- Lift table: cumulative thresholds (>=N) ---
    rows = []
    for thresh in range(0, 6):
        sub = df[df['confluence_score'] >= thresh]
        if len(sub) == 0:
            continue
        w = (sub['r_multiple'] > 0).sum()
        l = (sub['r_multiple'] < 0).sum()
        gw = sub.loc[sub['r_multiple']>0, 'pnl_pts'].sum()
        gl = abs(sub.loc[sub['r_multiple']<0, 'pnl_pts'].sum()) or 1e-9
        rows.append({
            'threshold': f'score >= {thresh}',
            'n': len(sub),
            'wr_pct': round(w/max(w+l,1)*100, 1),
            'pf': round(gw/gl, 2),
            'avg_r': round(sub['r_multiple'].mean(), 3),
            'total_pnl_pts': round(sub['pnl_pts'].sum(), 1),
        })
    print("\n=== Cumulative thresholds (score >= N) ===")
    print(pd.DataFrame(rows).to_string(index=False))
    pd.DataFrame(rows).to_csv(OUT_DIR / 'confluence_cumulative.csv', index=False)

    # --- Anti-pattern filter variant ---
    filtered = df[~df['hits_anti_pattern']].copy()
    print(f"\nAnti-pattern filter: {len(df)} -> {len(filtered)} survivors "
          f"({len(filtered)/len(df)*100:.0f}%)")
    t = build_lift_table(filtered, 'confluence_score')
    print_table(t, "Confluence score on anti-pattern survivors")
    t.to_csv(OUT_DIR / 'confluence_filtered.csv', index=False)

    rows = []
    for thresh in range(0, 6):
        sub = filtered[filtered['confluence_score'] >= thresh]
        if len(sub) == 0:
            continue
        w = (sub['r_multiple'] > 0).sum()
        l = (sub['r_multiple'] < 0).sum()
        gw = sub.loc[sub['r_multiple']>0, 'pnl_pts'].sum()
        gl = abs(sub.loc[sub['r_multiple']<0, 'pnl_pts'].sum()) or 1e-9
        rows.append({
            'threshold': f'score >= {thresh}',
            'n': len(sub),
            'wr_pct': round(w/max(w+l,1)*100, 1),
            'pf': round(gw/gl, 2),
            'avg_r': round(sub['r_multiple'].mean(), 3),
            'total_pnl_pts': round(sub['pnl_pts'].sum(), 1),
        })
    print("\n=== Filtered cumulative thresholds (score >= N, anti-patterns excluded) ===")
    print(pd.DataFrame(rows).to_string(index=False))
    pd.DataFrame(rows).to_csv(OUT_DIR / 'confluence_filtered_cumulative.csv', index=False)

    # --- Examine the high-score trades ---
    high = df[df['confluence_score'] >= 3].copy()
    print(f"\n=== Score >= 3 trades (N={len(high)}) ===")
    if len(high):
        cols = ['entry_ts','direction','sweep_level','gap_size_pts',
                'inversion_body_fraction','pd_position','prior_same_dir_sweep_count',
                'r_multiple','pnl_pts']
        print(high[cols].head(20).to_string(index=False))

    # --- Persist enriched + scored CSV ---
    out_path = POP_PATH.with_name('population_scored.csv')
    df.to_csv(out_path, index=False)
    print(f"\nWrote {out_path} ({len(df.columns)} columns)")


if __name__ == '__main__':
    main()
