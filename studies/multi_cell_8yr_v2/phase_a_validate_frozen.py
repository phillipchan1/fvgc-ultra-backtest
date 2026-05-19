"""Phase A: Apply frozen factor stacks (from multi_cell_confluence/results/cell_configs.json)
to the 8yr analysis frame. Report drift.

For each of 6 published cells:
- Build masks for the cell's pros and vetos from the OLD stack
- Compute conf_count and veto_count per trade
- Tier into {0-1, 2, 3, 4+}
- Report WR / PF @ 2R / hit ladder per tier
- Two views: RAW (no veto filter) and CLEAN (veto_count == 0)
- Slice: ALL 8yr, IS (2018-2024), OOS (2025+), Notion training window (2023-10 -> 2025-09)
- Side-by-side vs Notion-claimed numbers for the 3 published cells

Output: results/phase_a_per_cell.csv
        results/phase_a_year_by_year.csv
        results/phase_a_summary.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pandas as pd

from studies.multi_cell_confluence.factor_mining import (  # noqa: E402
    build_factor_masks,
    fit_quantiles,
)
from studies.multi_cell_confluence.utils import (  # noqa: E402
    cell_filter,
    cell_metrics_with_freq,
)
from studies.multi_cell_8yr_v2.utils import (  # noqa: E402
    ANALYSIS_FRAME_PATH,
    OLD_CELL_CONFIGS_PATH,
    RESULTS_DIR,
    TIER_BINS,
    TIER_LABELS,
)


NOTION_CLAIMED = {
    'M2_long': {
        'is_wr_3plus': 66.4, 'oos_wr_3plus': 65.0,
        'is_pf_3plus': 1.72, 'oos_pf_3plus': 1.33,
        'is_wr_4plus': 73.9, 'oos_wr_4plus': 50.0,
        'window_label': 'Oct 2023 - Mar 2026 (30 mo)',
    },
    'M3_long': {
        'is_wr_3plus': 62.4, 'oos_wr_3plus': 41.2,
        'is_pf_3plus': 1.21, 'oos_pf_3plus': 1.09,
        'is_wr_4plus': 71.9, 'oos_wr_4plus': 20.0,
        'window_label': 'Oct 2023 - Mar 2026 (30 mo)',
    },
    'M1_short': {
        # From multi_cell_confluence numbers (not the 8yr_validation rerun)
        'is_wr_2plus': 68.5, 'oos_wr_2plus': 76.9,
        'is_pf_2plus': 2.44,
        'window_label': 'Oct 2023 - Mar 2026 (30 mo)',
    },
}


def load_old_configs() -> dict:
    with open(OLD_CELL_CONFIGS_PATH) as f:
        return json.load(f)


def apply_frozen_stack(cell_df: pd.DataFrame, masks: dict, pros: list[str],
                       vetos: list[str]) -> pd.DataFrame:
    """Add conf_count / veto_count / conf_tier to a cell slice."""
    cell_df = cell_df.copy()
    cell_idx = cell_df.index

    conf = pd.Series(0, index=cell_idx, dtype=int)
    for p in pros:
        if p in masks:
            conf += masks[p].reindex(cell_idx).fillna(False).astype(int)
        else:
            print(f'  WARN: pro factor {p} missing from masks (skipped)')

    veto = pd.Series(0, index=cell_idx, dtype=int)
    for v in vetos:
        if v in masks:
            veto += masks[v].reindex(cell_idx).fillna(False).astype(int)
        else:
            print(f'  WARN: veto factor {v} missing from masks (skipped)')

    cell_df['conf_count'] = conf.values
    cell_df['veto_count'] = veto.values
    cell_df['conf_tier'] = pd.cut(cell_df['conf_count'], bins=TIER_BINS,
                                  labels=TIER_LABELS).astype(str)
    return cell_df


def tier_metrics(sub: pd.DataFrame, span_days: float) -> pd.DataFrame:
    """Per-tier WR/PF/hits for a slice."""
    rows = []
    for tier in TIER_LABELS:
        s = sub[sub['conf_tier'] == tier]
        m = cell_metrics_with_freq(s, total_span_days=span_days)
        m['tier'] = tier
        rows.append(m)
    return pd.DataFrame(rows)


def evaluate_cell(cell_name: str, df: pd.DataFrame, masks_all: dict,
                  config: dict) -> dict:
    """Run all slices/views for one cell, return rich metrics dict."""
    window, direction = cell_name.split('_')
    pros = config['pros']
    vetos = config['vetos']

    cell_all = cell_filter(df, window=window, direction=direction,
                           exclude_protected_swing=True)
    if len(cell_all) == 0:
        return {'cell': cell_name, 'n_8yr': 0}

    cell_all = apply_frozen_stack(cell_all, masks_all, pros, vetos)

    slices = {
        'ALL_8yr': cell_all,
        'IS_2018_2024': cell_all[cell_all['split'] == 'IS'],
        'OOS_2025plus': cell_all[cell_all['split'] == 'OOS'],
        'NotionTrain_2023_10_to_2025_09': cell_all[
            (cell_all['date'] >= '2023-10-01') &
            (cell_all['date'] <= '2025-09-30')
        ],
        'NotionOOS_2025_10_to_2026_03': cell_all[
            (cell_all['date'] >= '2025-10-01') &
            (cell_all['date'] <= '2026-03-31')
        ],
    }

    out = {
        'cell': cell_name,
        'n_pros': len(pros),
        'n_vetos': len(vetos),
        'pros': pros,
        'vetos': vetos,
        'n_8yr': int(len(cell_all)),
    }

    for slice_name, sub in slices.items():
        if len(sub) == 0:
            out[f'{slice_name}__n'] = 0
            continue
        span = max((pd.to_datetime(sub['date']).max() -
                    pd.to_datetime(sub['date']).min()).days, 1)
        # RAW view
        raw_tiers = tier_metrics(sub, span_days=span)
        # CLEAN view (no vetos)
        clean = sub[sub['veto_count'] == 0]
        clean_tiers = tier_metrics(clean, span_days=span) if len(clean) else pd.DataFrame()

        out[f'{slice_name}__n'] = int(len(sub))
        out[f'{slice_name}__span_days'] = int(span)
        out[f'{slice_name}__raw_tiers'] = raw_tiers.to_dict(orient='records')
        out[f'{slice_name}__clean_tiers'] = clean_tiers.to_dict(orient='records')

    return out


def main():
    print('=' * 70)
    print('PHASE A: Frozen-stack validation on 8yr')
    print('=' * 70)

    df = pd.read_csv(ANALYSIS_FRAME_PATH)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df['date'] = pd.to_datetime(df['date'])
    print(f'Loaded analysis frame: {len(df)} trades, '
          f'{df["timestamp"].min().date()} -> {df["timestamp"].max().date()}')

    configs = load_old_configs()
    print(f'Loaded {len(configs)} cells from OLD cell_configs.json')

    # Build masks ONCE using OLD quantile cutoffs (we want to test the
    # old stack as-is — re-fitting quantiles on 8yr would be a different test).
    # Fit on the original IS window: Oct 2023 - Sep 2025.
    notion_train = df[(df['date'] >= '2023-10-01') &
                      (df['date'] <= '2025-09-30') &
                      (df['variant'] != 'protected_swing')]
    print(f'Fitting OLD quantiles on Notion training window: n={len(notion_train)}')
    quantiles_old = fit_quantiles(notion_train)
    masks_all = build_factor_masks(df, quantiles_old)
    print(f'Built {len(masks_all)} factor masks')

    # Evaluate every cell in OLD configs
    print('\n--- Evaluating cells ---')
    results = []
    for cell_name, config in configs.items():
        print(f'  {cell_name}...')
        r = evaluate_cell(cell_name, df, masks_all, config)
        results.append(r)

    # Persist
    out_json = RESULTS_DIR / 'phase_a_summary.json'
    with open(out_json, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f'\nWrote {out_json}')

    # Flat per-cell CSV — main tier breakdown for each slice
    flat_rows = []
    for r in results:
        cell = r['cell']
        for slice_name in ('ALL_8yr', 'IS_2018_2024', 'OOS_2025plus',
                           'NotionTrain_2023_10_to_2025_09',
                           'NotionOOS_2025_10_to_2026_03'):
            for view in ('raw_tiers', 'clean_tiers'):
                tier_data = r.get(f'{slice_name}__{view}', [])
                for td in tier_data:
                    flat_rows.append({
                        'cell': cell,
                        'slice': slice_name,
                        'view': view.replace('_tiers', ''),
                        'tier': td.get('tier'),
                        'n': td.get('n'),
                        'wr_pct': td.get('wr_pct'),
                        'pf_at_2r': td.get('pf_at_2r'),
                        'hit_2_0R_pct': td.get('hit_2_0R_pct'),
                        'hit_3_0R_pct': td.get('hit_3_0R_pct'),
                        'hit_5_0R_pct': td.get('hit_5_0R_pct'),
                        'median_mfe_r_1r_plus': td.get('median_mfe_r_1r_plus'),
                        'trades_per_month': td.get('trades_per_month'),
                    })
    flat_df = pd.DataFrame(flat_rows)
    out_csv = RESULTS_DIR / 'phase_a_per_cell.csv'
    flat_df.to_csv(out_csv, index=False)
    print(f'Wrote {out_csv} ({len(flat_df)} rows)')

    # Year-by-year per cell at primary tier (3+ for longs, 2+ for M1 short)
    print('\n--- Year-by-year per cell ---')
    primary_tier_min = {'M1_long': 3, 'M1_short': 2, 'M2_long': 3, 'M2_short': 3,
                        'M3_long': 3, 'M3_short': 3}
    yr_rows = []
    for r in results:
        cell = r['cell']
        cell_min = primary_tier_min.get(cell, 3)
        window, direction = cell.split('_')
        # Reconstruct cell_all with conf_tier from results... simpler: redo
        cell_all = cell_filter(df, window=window, direction=direction,
                               exclude_protected_swing=True)
        cell_all = apply_frozen_stack(cell_all, masks_all,
                                      configs[cell]['pros'],
                                      configs[cell]['vetos'])
        primary = cell_all[(cell_all['conf_count'] >= cell_min) &
                           (cell_all['veto_count'] == 0)]
        for yr, grp in primary.groupby('year'):
            wins = int((grp['outcome'] == 'win').sum())
            n = len(grp)
            wr = round(100 * wins / n, 1) if n else float('nan')
            hits_2r = int(grp.get('hit_2_0R', pd.Series(False, index=grp.index)).astype(bool).sum())
            yr_rows.append({
                'cell': cell, 'year': yr, 'tier_min': cell_min,
                'n': n, 'wr_pct': wr, 'hits_2r': hits_2r,
                'pf_at_2r': round((hits_2r * 2.0) / max(n - hits_2r, 1), 2),
            })
    yr_df = pd.DataFrame(yr_rows)
    out_yr = RESULTS_DIR / 'phase_a_year_by_year.csv'
    yr_df.to_csv(out_yr, index=False)
    print(f'Wrote {out_yr}')

    # Console summary
    print('\n' + '=' * 70)
    print('CELL SURVIVAL VERDICTS (frozen stack on 8yr, clean view)')
    print('=' * 70)
    for r in results:
        cell = r['cell']
        cell_min = primary_tier_min.get(cell, 3)
        all_clean = r.get('ALL_8yr__clean_tiers', [])
        # Find the primary-tier row (3+ for most, 2+ for M1_short)
        tgt_tier = '4+' if cell_min >= 4 else ('3' if cell_min == 3 else '2')
        # Actually we want >= tier_min, so aggregate
        # cell_min=3 -> tiers 3 + 4+; cell_min=2 -> tiers 2 + 3 + 4+
        keep = TIER_LABELS[TIER_LABELS.index(tgt_tier):] if tgt_tier in TIER_LABELS else []
        n_total = 0
        wins_total = 0
        for td in all_clean:
            if td.get('tier') in keep:
                n_total += td.get('n', 0)
                wr = td.get('wr_pct') or 0
                if td.get('n'):
                    wins_total += round((wr / 100.0) * td['n'])
        wr_total = round(100 * wins_total / n_total, 1) if n_total else float('nan')
        print(f'  {cell:12s}  n>={cell_min}: {n_total:4d} | WR {wr_total}% | '
              f'pros={r["pros"]} | vetos={r["vetos"]}')

    print('\nPhase A done.')


if __name__ == '__main__':
    main()
