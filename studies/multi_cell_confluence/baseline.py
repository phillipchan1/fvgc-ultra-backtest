"""Phase B: Per-cell baseline.

For each (window, direction) cell on IS data, protected_swing excluded:
compute n, WR, PF@2R, full hit_X_R ladder, median_mfe_r among 1R+, trades/month.

Also computes:
- Full-sample (IS+OOS) baseline for context
- protected_swing-included variant for delta tracking
- A "global baseline" row across all cells

Output: results/baseline_per_cell.csv
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pandas as pd

from studies.multi_cell_confluence.utils import (  # noqa: E402
    DIRECTIONS,
    RESULTS_DIR,
    WINDOWS,
    cell_filter,
    cell_metrics_with_freq,
    load_analysis_frame,
)


def main():
    df = load_analysis_frame()
    print(f'Loaded {len(df)} trades from analysis frame.\n')

    is_df = df[df['split'] == 'IS']
    is_span_days = (is_df['date'].max() - is_df['date'].min()).days

    rows = []

    # Global baselines for context
    for label, sub in [
        ('ALL_IS_excl_protswing',
         is_df[is_df['variant'] != 'protected_swing']),
        ('ALL_IS_incl_protswing', is_df),
        ('ALL_FULL_excl_protswing',
         df[df['variant'] != 'protected_swing']),
    ]:
        m = cell_metrics_with_freq(sub, total_span_days=is_span_days)
        m.update({'cell': label, 'macro_window': 'ALL', 'direction': 'ALL',
                  'variant_filter': 'see_label', 'sample': 'see_label'})
        rows.append(m)

    # Per-cell baselines (IS only, protected_swing excluded — the primary table)
    for window in WINDOWS:
        for direction in DIRECTIONS:
            sub = cell_filter(df, window, direction,
                              exclude_protected_swing=True, is_only=True)
            m = cell_metrics_with_freq(sub, total_span_days=is_span_days)
            m.update({
                'cell': f'{window}_{direction}',
                'macro_window': window,
                'direction': direction,
                'variant_filter': 'excl_protswing',
                'sample': 'IS',
            })
            rows.append(m)

    # Per-cell variant: protected_swing included (for delta tracking)
    for window in WINDOWS:
        for direction in DIRECTIONS:
            sub = cell_filter(df, window, direction,
                              exclude_protected_swing=False, is_only=True)
            m = cell_metrics_with_freq(sub, total_span_days=is_span_days)
            m.update({
                'cell': f'{window}_{direction}__incl_protswing',
                'macro_window': window,
                'direction': direction,
                'variant_filter': 'incl_protswing',
                'sample': 'IS',
            })
            rows.append(m)

    out = pd.DataFrame(rows)
    # Reorder columns for readability
    front = ['cell', 'macro_window', 'direction', 'variant_filter', 'sample',
             'n', 'wins', 'losses', 'wr_pct', 'pf_at_2r',
             'hit_1_0R_pct', 'hit_1_5R_pct', 'hit_2_0R_pct', 'hit_2_5R_pct',
             'hit_3_0R_pct', 'hit_4_0R_pct', 'hit_5_0R_pct',
             'n_1r_plus', 'median_mfe_r_1r_plus', 'trades_per_month']
    rest = [c for c in out.columns if c not in front]
    out = out[front + rest]

    print('=== PER-CELL BASELINE (IS, protected_swing excluded) ===')
    primary = out[(out['sample'] == 'IS') & (out['variant_filter'] == 'excl_protswing')]
    print(primary[front].to_string(index=False))

    print('\n=== protected_swing delta (IS only) ===')
    delta_cols = ['cell', 'n', 'wr_pct', 'pf_at_2r', 'median_mfe_r_1r_plus']
    incl = out[out['variant_filter'] == 'incl_protswing'].set_index('macro_window').reset_index()
    excl = out[(out['sample'] == 'IS') & (out['variant_filter'] == 'excl_protswing')].set_index('macro_window').reset_index()
    print('\n  (excl - incl) for WR_pct shows how much protected_swing drags each cell:')
    for w in WINDOWS:
        for d in DIRECTIONS:
            er = excl[(excl['macro_window'] == w) & (excl['direction'] == d)]
            ir = incl[(incl['macro_window'] == w) & (incl['direction'] == d)]
            if len(er) and len(ir):
                e = er.iloc[0]
                i = ir.iloc[0]
                delta = (e['wr_pct'] - i['wr_pct']) if pd.notna(e['wr_pct']) and pd.notna(i['wr_pct']) else float('nan')
                print(f'  {w}_{d}: excl WR={e["wr_pct"]:.1f}% (n={e["n"]})  '
                      f'incl WR={i["wr_pct"]:.1f}% (n={i["n"]})  delta={delta:+.1f}pp')

    out_path = RESULTS_DIR / 'baseline_per_cell.csv'
    out.to_csv(out_path, index=False)
    print(f'\nWrote {out_path}')


if __name__ == '__main__':
    main()
