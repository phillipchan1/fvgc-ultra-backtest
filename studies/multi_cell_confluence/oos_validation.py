"""Phase E: OOS holdout validation.

The Phase D cell files (results/cells/<cell>.csv) already contain conf_count,
veto_count, and conf_tier computed on the FULL frame using IS-fit factor lists
and bin edges. So OOS validation = filter those files to split==OOS and
compute the same tier table.

Output:
- results/oos_validation_per_cell.csv (per-cell IS vs OOS tier comparison)
- Console summary marking cells where 4+ WR drops > 10pp IS->OOS
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pandas as pd

from studies.multi_cell_confluence.tier_construction import TIER_LABELS, tier_summary  # noqa: E402
from studies.multi_cell_confluence.utils import RESULTS_DIR  # noqa: E402

OOS_WR_DROP_LIMIT_PP = 10.0
PROVISIONAL_MIN_N = 5


def aggregate_tiers(df: pd.DataFrame, min_conf: int, span_days: float) -> dict:
    """Compute cell_metrics on rows with conf_count >= min_conf."""
    from studies.multi_cell_confluence.utils import cell_metrics_with_freq
    sub = df[df['conf_count'] >= min_conf]
    m = cell_metrics_with_freq(sub, total_span_days=span_days)
    m['min_conf'] = min_conf
    return m


def main():
    with open(RESULTS_DIR / 'cell_configs.json') as f:
        configs = json.load(f)

    cells_dir = RESULTS_DIR / 'cells'
    all_rows = []
    verdicts = []

    print('=' * 78)
    print('  OOS VALIDATION (IS factor lists frozen, applied to OOS data)')
    print('=' * 78)

    for cell, cfg in configs.items():
        path = cells_dir / f'{cell}.csv'
        if not path.exists():
            continue
        df = pd.read_csv(path)

        is_slice = df[df['split'] == 'IS']
        oos_slice = df[df['split'] == 'OOS']
        oos_span = max(1, (pd.to_datetime(oos_slice['date']).max()
                           - pd.to_datetime(oos_slice['date']).min()).days)

        # Raw IS, raw OOS
        is_raw = tier_summary(is_slice, TIER_LABELS, span_days=cfg['is_span_days'])
        oos_raw = tier_summary(oos_slice, TIER_LABELS, span_days=oos_span)

        # Clean IS, clean OOS (veto_count == 0)
        is_clean = tier_summary(is_slice[is_slice['veto_count'] == 0],
                                TIER_LABELS, span_days=cfg['is_span_days'])
        oos_clean = tier_summary(oos_slice[oos_slice['veto_count'] == 0],
                                 TIER_LABELS, span_days=oos_span)

        for tab, view, sample in [(is_raw, 'raw', 'IS'),
                                    (oos_raw, 'raw', 'OOS'),
                                    (is_clean, 'clean', 'IS'),
                                    (oos_clean, 'clean', 'OOS')]:
            tab = tab.copy()
            tab['cell'] = cell
            tab['view'] = view
            tab['sample'] = sample
            all_rows.append(tab)

        # Verdict for the 4+ raw tier
        is_4plus = is_raw[is_raw['tier'] == '4+'].iloc[0]
        oos_4plus = oos_raw[oos_raw['tier'] == '4+'].iloc[0]
        is_wr = is_4plus['wr_pct']
        oos_wr = oos_4plus['wr_pct']
        is_n = int(is_4plus['n'])
        oos_n = int(oos_4plus['n'])

        if pd.notna(oos_wr) and pd.notna(is_wr):
            drop = is_wr - oos_wr
        else:
            drop = float('nan')

        if oos_n < PROVISIONAL_MIN_N:
            verdict = f'PROVISIONAL (OOS n={oos_n} too thin)'
        elif pd.isna(drop):
            verdict = 'INSUFFICIENT DATA'
        elif drop > OOS_WR_DROP_LIMIT_PP:
            verdict = f'FAIL (OOS WR drop {drop:.1f}pp > {OOS_WR_DROP_LIMIT_PP}pp)'
        else:
            verdict = 'PASS'

        # Clean view secondary verdict
        is_4plus_clean = is_clean[is_clean['tier'] == '4+'].iloc[0]
        oos_4plus_clean = oos_clean[oos_clean['tier'] == '4+'].iloc[0]

        verdicts.append({
            'cell': cell,
            'is_n_4plus': is_n,
            'is_wr_4plus': is_wr,
            'is_pf_4plus': is_4plus['pf_at_2r'],
            'oos_n_4plus': oos_n,
            'oos_wr_4plus': oos_wr,
            'oos_pf_4plus': oos_4plus['pf_at_2r'],
            'wr_drop_pp': round(drop, 1) if pd.notna(drop) else float('nan'),
            'verdict_raw': verdict,
            'is_n_4plus_clean': int(is_4plus_clean['n']),
            'is_wr_4plus_clean': is_4plus_clean['wr_pct'],
            'oos_n_4plus_clean': int(oos_4plus_clean['n']),
            'oos_wr_4plus_clean': oos_4plus_clean['wr_pct'],
        })

        print(f'\n--- {cell} ---')
        print('  4+ tier RAW:')
        print(f'    IS:  n={is_n:>3d}  WR={is_wr:>5.1f}%  PF@2R={is_4plus["pf_at_2r"]:>5.2f}  '
              f'hit_2R={is_4plus["hit_2_0R_pct"]:>5.1f}%  hit_3R={is_4plus["hit_3_0R_pct"]:>5.1f}%')
        if oos_n > 0:
            print(f'    OOS: n={oos_n:>3d}  WR={oos_wr:>5.1f}%  PF@2R={oos_4plus["pf_at_2r"]:>5.2f}  '
                  f'hit_2R={oos_4plus["hit_2_0R_pct"]:>5.1f}%  hit_3R={oos_4plus["hit_3_0R_pct"]:>5.1f}%')
        else:
            print(f'    OOS: n=0 (no qualifying trades)')
        print(f'  Verdict: {verdict}')

    final = pd.concat(all_rows, ignore_index=True)
    front = ['cell', 'view', 'sample', 'tier', 'n', 'wins', 'losses', 'wr_pct', 'pf_at_2r',
             'hit_1_0R_pct', 'hit_2_0R_pct', 'hit_3_0R_pct', 'hit_5_0R_pct',
             'n_1r_plus', 'median_mfe_r_1r_plus', 'trades_per_month']
    rest = [c for c in final.columns if c not in front]
    final = final[front + rest]
    final.to_csv(RESULTS_DIR / 'oos_validation_per_cell.csv', index=False)

    verdicts_df = pd.DataFrame(verdicts)
    verdicts_df.to_csv(RESULTS_DIR / 'oos_verdicts.csv', index=False)

    # === Aggregated tier views (2+, 3+) for stability checks ===
    print('\n' + '=' * 78)
    print('  AGGREGATED VIEW — conf_count >= K (K in {2,3,4})')
    print('=' * 78)
    agg_rows = []
    for cell, cfg in configs.items():
        path = cells_dir / f'{cell}.csv'
        if not path.exists():
            continue
        df = pd.read_csv(path)
        is_slice = df[df['split'] == 'IS']
        oos_slice = df[df['split'] == 'OOS']
        oos_span = max(1, (pd.to_datetime(oos_slice['date']).max()
                           - pd.to_datetime(oos_slice['date']).min()).days)
        for k in (2, 3, 4):
            is_agg = aggregate_tiers(is_slice, k, cfg['is_span_days'])
            oos_agg = aggregate_tiers(oos_slice, k, oos_span)
            agg_rows.append({'cell': cell, 'min_conf': k, 'sample': 'IS', **is_agg})
            agg_rows.append({'cell': cell, 'min_conf': k, 'sample': 'OOS', **oos_agg})

    agg_df = pd.DataFrame(agg_rows)
    for k in (2, 3, 4):
        print(f'\n--- conf_count >= {k} ---')
        view = agg_df[agg_df['min_conf'] == k].pivot_table(
            index='cell', columns='sample',
            values=['n', 'wr_pct', 'pf_at_2r', 'hit_2_0R_pct', 'hit_3_0R_pct',
                    'median_mfe_r_1r_plus', 'trades_per_month'],
            aggfunc='first')
        # Compute WR drop
        is_wr = view[('wr_pct', 'IS')]
        oos_wr = view[('wr_pct', 'OOS')]
        view[('wr_drop_pp', '')] = (is_wr - oos_wr).round(1)
        print(view.to_string())
    agg_df.to_csv(RESULTS_DIR / 'oos_aggregated_tiers.csv', index=False)
    print(f'\nWrote {RESULTS_DIR / "oos_aggregated_tiers.csv"}')

    print('\n' + '=' * 78)
    print('  VERDICT SUMMARY (4+ tier RAW)')
    print('=' * 78)
    cols = ['cell', 'is_n_4plus', 'is_wr_4plus', 'is_pf_4plus',
            'oos_n_4plus', 'oos_wr_4plus', 'oos_pf_4plus',
            'wr_drop_pp', 'verdict_raw']
    print(verdicts_df[cols].to_string(index=False))

    print(f'\nWrote {RESULTS_DIR / "oos_validation_per_cell.csv"}')
    print(f'Wrote {RESULTS_DIR / "oos_verdicts.csv"}')


if __name__ == '__main__':
    main()
