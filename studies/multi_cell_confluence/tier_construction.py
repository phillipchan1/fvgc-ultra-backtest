"""Phase D: Tier construction with pro-stack + veto refinement.

For each cell, on IS data (protected_swing excluded):
1. From the factor mining shortlist, split into pro (+lift) and anti (-lift) candidates.
2. Greedy-select up to K_PRO pro factors (corr < 0.5 with already-selected pros).
3. Greedy-select up to K_VETO veto factors (corr < 0.5 with selected pros AND with
   already-selected vetos -- this naturally excludes anti-factors that are just
   inverses of pros).
4. Build conf_count = sum of pros active; veto_count = sum of vetos active.
5. Tier by conf_count bins {0-1, 2, 3, 4+}; report two views:
   - Raw (no veto check)
   - Clean (veto_count == 0)
6. Save cell configs as JSON for OOS phase.

Output: results/tier_table_per_cell.csv
        results/cell_configs.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pandas as pd

from studies.multi_cell_confluence.factor_mining import build_factor_masks  # noqa: E402
from studies.multi_cell_confluence.utils import (  # noqa: E402
    DIRECTIONS,
    RESULTS_DIR,
    WINDOWS,
    cell_filter,
    cell_metrics_with_freq,
    load_analysis_frame,
)

K_PRO = 7
K_VETO = 3
CORR_THRESHOLD = 0.5
MIN_LIFT_PP = 5.0
MIN_BUCKET_N = 20

TIER_BINS = [-0.5, 1.5, 2.5, 3.5, 99]
TIER_LABELS = ['0-1', '2', '3', '4+']


def greedy_select(candidates: list[tuple[str, float]],
                  masks: dict[str, pd.Series],
                  cell_idx: pd.Index,
                  must_be_independent_of: list[str],
                  k: int,
                  corr_threshold: float) -> list[str]:
    """Greedy pick up to k items from `candidates` (already sorted by importance).

    A candidate is rejected if its boolean mask correlates (|pearson|) >= corr_threshold
    with any already-selected factor OR any factor in `must_be_independent_of`.

    Correlations computed only on `cell_idx` rows.
    """
    selected: list[str] = []
    for factor_id, _score in candidates:
        if len(selected) >= k:
            break
        cand_mask = masks[factor_id].reindex(cell_idx).astype(int)
        if cand_mask.nunique() < 2:
            continue
        check_against = list(must_be_independent_of) + selected
        ok = True
        for other_id in check_against:
            other_mask = masks[other_id].reindex(cell_idx).astype(int)
            if other_mask.nunique() < 2:
                continue
            c = cand_mask.corr(other_mask)
            if pd.notna(c) and abs(c) >= corr_threshold:
                ok = False
                break
        if ok:
            selected.append(factor_id)
    return selected


def tier_summary(sub: pd.DataFrame, tier_labels: list[str], span_days: float) -> pd.DataFrame:
    """Compute per-tier metrics for a slice. Returns one row per tier."""
    rows = []
    for label in tier_labels:
        s = sub[sub['conf_tier'] == label]
        m = cell_metrics_with_freq(s, total_span_days=span_days)
        m['tier'] = label
        rows.append(m)
    return pd.DataFrame(rows)


def main():
    df = load_analysis_frame()
    is_df = df[df['split'] == 'IS'].copy()
    is_excl = is_df[is_df['variant'] != 'protected_swing'].copy()
    is_span_days = (is_excl['date'].max() - is_excl['date'].min()).days

    with open(RESULTS_DIR / 'is_quantiles.json') as f:
        quantiles = json.load(f)

    print('Building factor masks on full frame...')
    masks = build_factor_masks(df, quantiles)

    shortlist = pd.read_csv(RESULTS_DIR / 'factor_shortlist_per_cell.csv')

    cell_configs = {}
    all_tier_rows = []

    for window in WINDOWS:
        for direction in DIRECTIONS:
            cell = f'{window}_{direction}'
            cell_is = cell_filter(df, window, direction,
                                  exclude_protected_swing=True, is_only=True)
            if len(cell_is) < MIN_BUCKET_N * 2:
                continue

            cell_shortlist = shortlist[shortlist['cell'] == cell].copy()
            if cell_shortlist.empty:
                continue

            pro_candidates = [
                (r.factor_id, r.lift_pp)
                for r in cell_shortlist[cell_shortlist['lift_pp'] >= MIN_LIFT_PP]
                    .sort_values('lift_pp', ascending=False).itertuples()
            ]
            anti_candidates = [
                (r.factor_id, r.lift_pp)
                for r in cell_shortlist[cell_shortlist['lift_pp'] <= -MIN_LIFT_PP]
                    .sort_values('lift_pp', ascending=True).itertuples()
            ]

            # Select pros
            pros = greedy_select(pro_candidates, masks, cell_is.index,
                                 must_be_independent_of=[],
                                 k=K_PRO, corr_threshold=CORR_THRESHOLD)
            # Select vetos (must be independent of selected pros AND each other)
            vetos = greedy_select(anti_candidates, masks, cell_is.index,
                                  must_be_independent_of=pros,
                                  k=K_VETO, corr_threshold=CORR_THRESHOLD)

            # Build conf_count and veto_count on the full frame for this cell
            cell_full = cell_filter(df, window, direction,
                                    exclude_protected_swing=True,
                                    is_only=False, oos_only=False)
            conf_count = sum(masks[p].reindex(cell_full.index).astype(int) for p in pros)
            veto_count = sum(masks[v].reindex(cell_full.index).astype(int) for v in vetos) \
                if vetos else pd.Series(0, index=cell_full.index)
            cell_full = cell_full.copy()
            cell_full['conf_count'] = conf_count.astype(int) if hasattr(conf_count, 'astype') else 0
            cell_full['veto_count'] = veto_count.astype(int) if hasattr(veto_count, 'astype') else 0
            cell_full['conf_tier'] = pd.cut(cell_full['conf_count'],
                                            bins=TIER_BINS, labels=TIER_LABELS).astype(str)

            cell_configs[cell] = {
                'pros': pros,
                'pro_lifts': {p: float(dict(pro_candidates)[p]) for p in pros},
                'vetos': vetos,
                'veto_lifts': {v: float(dict(anti_candidates)[v]) for v in vetos},
                'tier_bins': TIER_BINS,
                'tier_labels': TIER_LABELS,
                'n_is': int(len(cell_is)),
                'is_span_days': int(is_span_days),
            }

            # IS tier summary, raw
            is_slice = cell_full[cell_full['split'] == 'IS']
            raw_tab = tier_summary(is_slice, TIER_LABELS, is_span_days)
            raw_tab['cell'] = cell
            raw_tab['view'] = 'raw'
            raw_tab['sample'] = 'IS'

            # IS tier summary, clean (veto_count == 0)
            clean_slice = is_slice[is_slice['veto_count'] == 0]
            clean_tab = tier_summary(clean_slice, TIER_LABELS, is_span_days)
            clean_tab['cell'] = cell
            clean_tab['view'] = 'clean'
            clean_tab['sample'] = 'IS'

            all_tier_rows.append(raw_tab)
            all_tier_rows.append(clean_tab)

            # Save the full annotated cell df (IS+OOS) for downstream phases
            (RESULTS_DIR / 'cells').mkdir(parents=True, exist_ok=True)
            cell_full.to_csv(RESULTS_DIR / 'cells' / f'{cell}.csv', index=False)

            print(f'\n--- {cell} (n_IS={len(cell_is)}) ---')
            print(f'  PROS ({len(pros)}): {pros}')
            print(f'  VETOS ({len(vetos)}): {vetos}')
            print('  Tier table (RAW IS):')
            for _, row in raw_tab.iterrows():
                print(f'    tier {row["tier"]:>3s}  n={row["n"]:>4d}  WR={row["wr_pct"]:>5.1f}%  '
                      f'PF@2R={row["pf_at_2r"]:>5.2f}  hit_2R={row["hit_2_0R_pct"]:>5.1f}%  '
                      f'hit_3R={row["hit_3_0R_pct"]:>5.1f}%  hit_5R={row["hit_5_0R_pct"]:>5.1f}%  '
                      f'MFE_1R+={row["median_mfe_r_1r_plus"]:>4.2f}R  freq={row["trades_per_month"]:>5.2f}/mo')
            if vetos:
                print('  Tier table (CLEAN IS, veto_count==0):')
                for _, row in clean_tab.iterrows():
                    if row['n'] >= 10:
                        print(f'    tier {row["tier"]:>3s}  n={row["n"]:>4d}  WR={row["wr_pct"]:>5.1f}%  '
                              f'PF@2R={row["pf_at_2r"]:>5.2f}  hit_2R={row["hit_2_0R_pct"]:>5.1f}%  '
                              f'hit_3R={row["hit_3_0R_pct"]:>5.1f}%  freq={row["trades_per_month"]:>5.2f}/mo')

    final = pd.concat(all_tier_rows, ignore_index=True)
    front = ['cell', 'view', 'sample', 'tier', 'n', 'wins', 'losses', 'wr_pct', 'pf_at_2r',
             'hit_1_0R_pct', 'hit_2_0R_pct', 'hit_3_0R_pct', 'hit_5_0R_pct',
             'n_1r_plus', 'median_mfe_r_1r_plus', 'trades_per_month']
    rest = [c for c in final.columns if c not in front]
    final = final[front + rest]
    final.to_csv(RESULTS_DIR / 'tier_table_per_cell.csv', index=False)

    with open(RESULTS_DIR / 'cell_configs.json', 'w') as f:
        json.dump(cell_configs, f, indent=2)

    print(f'\nWrote {RESULTS_DIR / "tier_table_per_cell.csv"}')
    print(f'Wrote {RESULTS_DIR / "cell_configs.json"}')


if __name__ == '__main__':
    main()
