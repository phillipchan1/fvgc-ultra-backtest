"""Cross-timeframe audit: apply 8yr v2 NEW stacks to 30s/1m/2m/3m baselines.

Question: are the M1 Long / M2 Long / M3 Long stacks viable on higher
timeframes, or are they 30s-only (like M1 Short)?

Method: for each TF baseline (studies/baseline*), enrich trades with
trading_days.csv + 60d regime, apply each play's pros+vetos using the
SAME 30s-IS quantile cutoffs (apples-to-apples), measure WR at the
primary operating tier (3+ for M1L/M3L, 4+ for M2L).

Note: this audit is WR-only (no PF) because regenerating hit_X_R via the
MFE walk for each TF would be expensive and the WR signal alone is
decisive. See REPORT.md for full IS/OOS PF on 30s.

Output: results/cross_tf_audit.csv

Verdict (2026-05-18): 30s is the only viable bar size for all three
plays. WR drops 9-15pp on 1m. 2m/3m samples too thin to validate.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import numpy as np
import pandas as pd

from studies.multi_cell_confluence.factor_mining import (  # noqa: E402
    build_factor_masks, fit_quantiles,
)
from studies.multi_cell_confluence.utils import (  # noqa: E402
    compute_60d_regime, derive_macro_window,
)
from studies.multi_cell_8yr_v2.utils import (  # noqa: E402
    ANALYSIS_FRAME_PATH, RESULTS_DIR, TRADING_DAYS_PATH,
)


TFS = [
    ('baseline', '30s'),
    ('baseline_1m', '1m'),
    ('baseline_2m', '2m'),
    ('baseline_3m', '3m'),
]

CELL_TIERS = {'M1_long': 3, 'M2_long': 4, 'M3_long': 3}


def enrich_tf(trades_path: Path, td: pd.DataFrame, regime: pd.DataFrame) -> pd.DataFrame:
    df = pd.read_csv(trades_path)
    df = df[df['outcome'].isin(['win', 'loss'])].copy()
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    if 'date' in df.columns:
        df['date'] = pd.to_datetime(df['date'])
    else:
        df['date'] = df['timestamp'].dt.normalize()
    df['macro_window'] = derive_macro_window(df['timestamp'])
    df = df[df['macro_window'].notna() & (df['variant'] != 'protected_swing')]
    df = df.merge(td, on='date', how='left')
    df = df.merge(regime, on='date', how='left')
    df['split'] = np.where(df['timestamp'] >= pd.Timestamp('2025-01-01'), 'OOS', 'IS')
    return df


def main():
    ROOT = Path(__file__).resolve().parent.parent.parent

    # Reference quantile cutoffs: 8yr-IS on 30s enriched (apples-to-apples)
    df30 = pd.read_csv(ANALYSIS_FRAME_PATH)
    df30['date'] = pd.to_datetime(df30['date'])
    is_excl_30 = df30[(df30['split'] == 'IS') & (df30['variant'] != 'protected_swing')]
    quantiles = fit_quantiles(is_excl_30)
    print('Using 30s-IS quantile cutoffs for all TFs.')

    td = pd.read_csv(TRADING_DAYS_PATH)
    td['date'] = pd.to_datetime(td['date'])
    regime = compute_60d_regime(td)

    with open(RESULTS_DIR / 'cell_configs_8yr.json') as f:
        cfg = json.load(f)

    rows = []
    for d, lbl in TFS:
        p = ROOT / 'studies' / d / 'results' / 'trades.csv'
        if not p.exists():
            print(f'  skip {lbl}: {p} not found')
            continue
        df = enrich_tf(p, td, regime)
        for cell, tier_min in CELL_TIERS.items():
            w, dirn = cell.split('_')
            sub = df[(df['macro_window'] == w) & (df['direction'] == dirn)].copy()
            if len(sub) == 0:
                rows.append({'tf': lbl, 'cell': cell, 'tier_min': tier_min,
                             'n': 0, 'wr_pct': float('nan')})
                continue
            masks = build_factor_masks(sub, quantiles)
            idx = sub.index
            conf = pd.Series(0, index=idx, dtype=int)
            for pp in cfg[cell]['pros']:
                if pp in masks:
                    conf += masks[pp].reindex(idx).fillna(False).astype(int)
            veto = pd.Series(0, index=idx, dtype=int)
            for vv in cfg[cell]['vetos']:
                if vv in masks:
                    veto += masks[vv].reindex(idx).fillna(False).astype(int)
            sub['conf'] = conf.values
            sub['veto'] = veto.values
            clean = sub[(sub['veto'] == 0) & (sub['conf'] >= tier_min)]
            n = len(clean)
            wins = int((clean['outcome'] == 'win').sum())
            wr = round(100 * wins / n, 1) if n else float('nan')
            rows.append({'tf': lbl, 'cell': cell, 'tier_min': tier_min,
                         'n': n, 'wr_pct': wr})

    out = pd.DataFrame(rows)
    out_path = RESULTS_DIR / 'cross_tf_audit.csv'
    out.to_csv(out_path, index=False)
    print(f'\nWrote {out_path}')

    print('\nWR% by TF / cell:')
    print(out.pivot_table(index=['cell', 'tier_min'], columns='tf',
                          values='wr_pct', aggfunc='first').to_string())
    print('\nn by TF / cell:')
    print(out.pivot_table(index=['cell', 'tier_min'], columns='tf',
                          values='n', aggfunc='first').to_string())

    print('\nVerdict: 30s is the only viable bar size for all 3 plays.')


if __name__ == '__main__':
    main()
