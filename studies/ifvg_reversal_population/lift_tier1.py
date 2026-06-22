#!/usr/bin/env python3
"""Tier 1 lift tables — factors where Tempo explicitly asserts edge.

Runs all 4 tier 1 factors plus the 2 sweep-cascade factors from enrichment.
Writes per-factor CSVs and prints a unified comparison.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pandas as pd

from studies.ifvg_reversal_population.lift_table import build_lift_table, print_table

POP_PATH = Path('studies/ifvg_reversal_population/results/population_enriched.csv')
OUT_DIR = Path('studies/ifvg_reversal_population/results/lift')
OUT_DIR.mkdir(exist_ok=True, parents=True)


def main():
    df = pd.read_csv(POP_PATH)
    print(f"Population: N={len(df)}\n")

    # 1. gap_size_pts  — Tempo "8-15 ideal"
    t = build_lift_table(df, 'gap_size_pts',
                         bucketer=[0, 8, 10, 12, 15, 20, 30, 1000])
    print_table(t, "Factor: gap_size_pts  (Tempo: 8-15 ideal)")
    t.to_csv(OUT_DIR / 'gap_size_pts.csv', index=False)

    # 2. inversion_body_fraction  — Tempo "strong momentum"
    t = build_lift_table(df, 'inversion_body_fraction',
                         bucketer=[0, 0.3, 0.5, 0.7, 0.9, 1.0])
    print_table(t, "Factor: inversion_body_fraction  (Tempo: strong momentum)")
    t.to_csv(OUT_DIR / 'inversion_body_fraction.csv', index=False)

    # 3. sweep_level  — Tempo tier list
    t = build_lift_table(df, 'sweep_level')
    print_table(t, "Factor: sweep_level  (Tempo: tier list)")
    t.to_csv(OUT_DIR / 'sweep_level.csv', index=False)

    # 4. pd_position  — Tempo "right side of premium/discount"
    t = build_lift_table(df, 'pd_position',
                         bucketer=[-0.5, 0.25, 0.4, 0.5, 0.6, 0.75, 1.5])
    print_table(t, "Factor: pd_position  (Tempo: right side of P/D)")
    t.to_csv(OUT_DIR / 'pd_position.csv', index=False)

    # 5. prior_same_dir_sweep_count  — Tempo stacked liquidity
    t = build_lift_table(df, 'prior_same_dir_sweep_count')
    print_table(t, "Factor: prior_same_dir_sweep_count  (stacked liquidity)")
    t.to_csv(OUT_DIR / 'prior_same_dir_sweep_count.csv', index=False)

    # 6. remaining_same_dir_unswept  — Tempo "still nearby = magnet against us"
    t = build_lift_table(df, 'remaining_same_dir_unswept')
    print_table(t, "Factor: remaining_same_dir_unswept  (magnet against us)")
    t.to_csv(OUT_DIR / 'remaining_same_dir_unswept.csv', index=False)

    print(f"\nAll lift tables saved under {OUT_DIR}")


if __name__ == '__main__':
    main()
