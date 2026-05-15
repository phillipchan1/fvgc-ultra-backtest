"""Phase F: Regime breakdown (NQ 60-day return: bull / bear / neutral).

For each cell at thresholds conf_count >= {2, 3, 4}, compute WR per regime
on IS+OOS combined. Flag cells where max-min WR > 15pp AND each regime has
n >= 10.

Output: results/regime_breakdown_per_cell.csv
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pandas as pd

from studies.multi_cell_confluence.utils import RESULTS_DIR, cell_metrics  # noqa: E402

REGIMES = ['bear', 'neutral', 'bull']
WR_SPREAD_LIMIT_PP = 15.0
MIN_REGIME_N = 10


def main():
    cells_dir = RESULTS_DIR / 'cells'
    rows = []

    print('=' * 78)
    print('  REGIME BREAKDOWN (IS+OOS combined)')
    print('=' * 78)

    for cell_csv in sorted(cells_dir.glob('*.csv')):
        cell = cell_csv.stem
        df = pd.read_csv(cell_csv)
        # Use only trades with a regime label (drop first 60 trading days)
        df = df[df['regime_60d'].isin(REGIMES)]
        if df.empty:
            continue

        print(f'\n--- {cell} ---')
        for k in (2, 3, 4):
            sub = df[df['conf_count'] >= k]
            if len(sub) == 0:
                continue
            row = {'cell': cell, 'min_conf': k}
            wrs = {}
            for r in REGIMES:
                slc = sub[sub['regime_60d'] == r]
                m = cell_metrics(slc)
                row[f'n_{r}'] = m['n']
                row[f'wr_{r}'] = m['wr_pct']
                row[f'pf_{r}'] = m['pf_at_2r']
                wrs[r] = m['wr_pct']
            # Spread (only if all regimes have at least MIN_REGIME_N)
            qualifying = [wrs[r] for r in REGIMES if row[f'n_{r}'] >= MIN_REGIME_N and pd.notna(wrs[r])]
            if len(qualifying) >= 2:
                spread = max(qualifying) - min(qualifying)
                row['wr_spread_pp'] = round(spread, 1)
                if len(qualifying) == 3 and spread > WR_SPREAD_LIMIT_PP:
                    row['regime_verdict'] = f'REGIME-DEPENDENT (spread {spread:.1f}pp)'
                elif len(qualifying) == 3:
                    row['regime_verdict'] = 'REGIME-ROBUST'
                else:
                    row['regime_verdict'] = f'GAP (only {len(qualifying)} regimes with n>={MIN_REGIME_N})'
            else:
                row['wr_spread_pp'] = float('nan')
                row['regime_verdict'] = 'INSUFFICIENT DATA'
            rows.append(row)

            line = f'  conf>={k}:  '
            for r in REGIMES:
                n = row[f'n_{r}']
                wr = row[f'wr_{r}']
                wr_str = f'{wr:.1f}%' if pd.notna(wr) else '   --'
                line += f'{r}: n={n:>3d} WR={wr_str:>6s}  '
            line += f' spread={row["wr_spread_pp"] if pd.notna(row["wr_spread_pp"]) else "  --"}  {row["regime_verdict"]}'
            print(line)

    out = pd.DataFrame(rows)
    out.to_csv(RESULTS_DIR / 'regime_breakdown_per_cell.csv', index=False)
    print(f'\nWrote {RESULTS_DIR / "regime_breakdown_per_cell.csv"}')


if __name__ == '__main__':
    main()
