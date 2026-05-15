"""Phase G: build analysis.md + per-cell trade subset CSVs.

This is the final synthesis step. It does NOT recompute any metrics — it
reads the CSVs from prior phases and assembles them into the report. The
human-readable markdown lives in studies/multi_cell_confluence/analysis.md.

It also computes per-cell exit-strategy EV tables (TP@1R/2R/3R/5R + scaling
variants) using only the hit_X_R columns (no buggy mfe_r).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pandas as pd

from studies.multi_cell_confluence.utils import RESULTS_DIR, STUDY_DIR  # noqa: E402


def compute_ev_table(sub: pd.DataFrame) -> pd.DataFrame:
    """For a slice of trades, compute EV/R per exit strategy.

    Uses hit_X_R columns only — does NOT use the buggy mfe_r.
    Stops are 1R; 'losses' = trades that didn't hit 1R = stopped out.
    """
    n = len(sub)
    if n == 0:
        return pd.DataFrame()

    # Hit rates
    h = {}
    for r in ['1_0', '1_5', '2_0', '2_5', '3_0', '4_0', '5_0']:
        col = f'hit_{r}R'
        h[r] = sub[col].astype(bool).mean() if col in sub.columns else 0
    # Loss rate = didn't hit 1R
    p_loss = 1 - h['1_0']

    rows = []
    # Fixed TP strategies
    for tp_r in ['1_0', '2_0', '3_0', '5_0']:
        p_win = h[tp_r]
        ev = p_win * float(tp_r.replace('_', '.')) - (1 - p_win) * 1.0
        rows.append({
            'strategy': f'TP fixed @ {tp_r.replace("_", ".")}R',
            'p_win': round(p_win * 100, 1),
            'ev_per_trade_R': round(ev, 3),
            'note': f'win = {tp_r.replace("_", ".")}R; loss = -1R',
        })

    # Scaling: 1/2 @ 1R + 1/2 @ 2R (BE stop on runner after 1R hit)
    # Outcomes:
    #   - p_loss: both halves stop at 1R (full -1R)
    #   - p_hit_1r_not_2r = h_1_0 - h_2_0: half locks +0.5R, half BE = +0.5R total
    #   - p_hit_2r = h_2_0: half locks +0.5R, half locks +1.0R = +1.5R total
    p_hit_1r_only = h['1_0'] - h['2_0']
    ev_a = p_loss * -1.0 + p_hit_1r_only * 0.5 + h['2_0'] * 1.5
    rows.append({
        'strategy': '1/2 @ 1R + 1/2 @ 2R (BE stop runner)',
        'p_win': round((1 - p_loss) * 100, 1),
        'ev_per_trade_R': round(ev_a, 3),
        'note': 'half at 1R locks; remainder BE-stopped or +2R',
    })

    # Scaling: 1/3 @ 1R + 1/3 @ 2R + 1/3 @ 5R (BE stop on runner)
    p_hit_2r_not_5r = h['2_0'] - h['5_0']
    # If hit 1R only: first third +1/3*1, second/third BE = +0.333
    # If hit 2R not 5R: first third +1/3, second third +2/3, third BE = +1.0
    # If hit 5R: first third +1/3, second third +2/3, third third +5/3 = +2.667
    ev_b = p_loss * -1.0 + p_hit_1r_only * (1/3) + p_hit_2r_not_5r * 1.0 + h['5_0'] * (1/3 + 2/3 + 5/3)
    rows.append({
        'strategy': '1/3 @ 1R + 1/3 @ 2R + 1/3 @ 5R (BE stop runner)',
        'p_win': round((1 - p_loss) * 100, 1),
        'ev_per_trade_R': round(ev_b, 3),
        'note': 'three-stage scale; runner BE-stopped if 5R not reached',
    })

    return pd.DataFrame(rows)


def export_tradeable_subsets():
    """Save per-cell trade CSVs at the recommended threshold for each surviving cell."""
    targets = [
        ('M1_short', 2),  # W1 reference, 2+ is robust
        ('M2_long', 3),   # 3+ is the OOS-stable threshold
        ('M3_short', 3),  # 3+ OOS-pass but regime-dependent
    ]
    out = {}
    cells_dir = RESULTS_DIR / 'cells'
    for cell, k in targets:
        df = pd.read_csv(cells_dir / f'{cell}.csv')
        sub = df[df['conf_count'] >= k].copy()
        cols = ['date', 'timestamp', 'direction', 'variant',
                'conf_count', 'veto_count', 'outcome',
                'hit_1_0R', 'hit_2_0R', 'hit_3_0R', 'hit_5_0R',
                'split', 'regime_60d']
        sub = sub[[c for c in cols if c in sub.columns]].sort_values('timestamp')
        path = cells_dir / f'{cell}_{k}plus.csv'
        sub.to_csv(path, index=False)
        out[(cell, k)] = (path, sub)
        print(f'Wrote {path}  ({len(sub)} trades)')
    return out


def main():
    print('Building report artifacts...')
    subsets = export_tradeable_subsets()

    print('\nEV tables:')
    for (cell, k), (_, sub) in subsets.items():
        ev = compute_ev_table(sub)
        ev_path = RESULTS_DIR / f'ev_{cell}_{k}plus.csv'
        ev.to_csv(ev_path, index=False)
        print(f'\n  {cell} conf>={k}  (n={len(sub)})')
        print(ev.to_string(index=False))
        print(f'  Wrote {ev_path}')

    print('\nReport scripts done. Now edit analysis.md by hand (or extend this script).')


if __name__ == '__main__':
    main()
