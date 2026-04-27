#!/usr/bin/env python3
"""Study: OR-Width Predictor

Goal: produce a predicted 45-min OR range each morning, with a confidence
interval, that updates as the first 5 / 15 min print.

Three models:
  1. cold_start  — features observable strictly before 9:30
  2. plus_5min   — adds the 9:30 1-min candle + 5-min OR
  3. plus_15min  — adds the 15-min OR

Walk-forward validated by year (train on prior years, test on year Y).

Run from repo root:
  python studies/or_width_predictor/run.py

Outputs (results/):
  - features.csv              full feature table per day
  - feature_ranking.csv       univariate quintile ranking
  - bucket_detail.csv         per-feature quintile tables
  - walkforward_*.csv         out-of-sample predictions per model
  - permutation_importance.csv per-feature MAE-increase under shuffle
  - model_*.json              fitted coefficients (for predict_today.py)
  - report.md                 summary
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from studies.or_width_predictor.features import build_feature_table
from studies.or_width_predictor.analysis import rank_features
from studies.or_width_predictor.model import (
    fit_ridge, permutation_importance, walk_forward_predict, evaluate_predictions,
)

STUDY_DIR = Path(__file__).resolve().parent
RESULTS_DIR = STUDY_DIR / 'results'
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

TRADING_DAYS = ROOT / 'data' / 'trading_days' / 'trading_days.csv'
CANDLES_5M = ROOT / 'data' / 'consolidated' / 'nq-front-month.ohlcv-5m.csv'

TARGET = 'or_45min_range'

# Cold-start features: strictly observable before 9:30 ET.
# Excluded: pm_range (only 560 days coverage — TODO: backfill 8:00–9:30
# data, then add). Excluded: vix_zscore_20d (n=657, sparse early years).
FEATURES_COLD = [
    'overnight_range',
    'gap_abs',
    'gap_atr_ratio',
    'prior_day_range',
    'prior_day_close_position',
    'atr_5d',
    'atr_20d',
    'atr_ratio_5_20',
    'pdr_pctile_20d',
    'nr4_flag',
    'nr7_flag',
    'vixy_prior_close',
    'vix_5d_chg',
    'is_fomc_week',
    'is_opex_week',
    'has_red_folder_news',
    'has_pre_rth_news',
]

# At 9:35 we know the open candle and the 5-min OR.
FEATURES_PLUS_5MIN = FEATURES_COLD + [
    'or_5min_range',
    'candle_930_range',
    'candle_930_efficiency',
    'fvgs_first_5min',
]

# At 9:45 we know the 15-min OR — most of the answer.
FEATURES_PLUS_15MIN = FEATURES_PLUS_5MIN + [
    'or_15min_range',
    'fvgs_first_15min',
]

MODELS = {
    'cold_start': FEATURES_COLD,
    'plus_5min': FEATURES_PLUS_5MIN,
    'plus_15min': FEATURES_PLUS_15MIN,
}

# Univariate ranking pool (broader, includes leaky-but-informative features)
UNIVARIATE_FEATURES = list(set(
    FEATURES_PLUS_15MIN + [
        'pm_range', 'pm_volume', 'on_close_position',
        'vix_zscore_20d', 'vix_1d_chg', 'vixy_regime',
        'day_of_week_name', 'month_name', 'is_quad_witching',
        'is_month_start', 'is_month_end',
        'macro_2_range', 'atr_10d', 'gap_from_prior_close',
    ]
))


def _df_to_md(df: pd.DataFrame) -> str:
    if df.empty:
        return '_(empty)_'
    cols = list(df.columns)
    header = '| ' + ' | '.join(str(c) for c in cols) + ' |'
    sep = '| ' + ' | '.join('---' for _ in cols) + ' |'
    rows = []
    for _, r in df.iterrows():
        cells = []
        for c in cols:
            v = r[c]
            if isinstance(v, float):
                cells.append('' if pd.isna(v) else f'{v:.3f}')
            else:
                cells.append('' if pd.isna(v) else str(v))
        rows.append('| ' + ' | '.join(cells) + ' |')
    return '\n'.join([header, sep, *rows])


def save_model(model, path: Path) -> None:
    payload = {
        'feature_names': model.feature_names,
        'coef': model.coef.tolist(),
        'intercept': float(model.intercept),
        'feat_mean': model.feat_mean.tolist(),
        'feat_std': model.feat_std.tolist(),
        'resid_std': float(model.resid_std),
        'train_residuals': model.train_residuals.tolist(),
    }
    path.write_text(json.dumps(payload, indent=2))


def main():
    print('Building feature table...')
    df = build_feature_table(TRADING_DAYS, CANDLES_5M)
    df.to_csv(RESULTS_DIR / 'features.csv', index=False)
    print(f'  rows: {len(df)}, cols: {len(df.columns)}')
    print(f'  target {TARGET}: mean={df[TARGET].mean():.1f}, '
          f'std={df[TARGET].std():.1f}')

    print('\n[1] Univariate quintile ranking...')
    summary, detail = rank_features(df, UNIVARIATE_FEATURES, target=TARGET)
    summary.to_csv(RESULTS_DIR / 'feature_ranking.csv', index=False)
    detail.to_csv(RESULTS_DIR / 'bucket_detail.csv', index=False)
    cols = ['feature', 'n', 'spearman_rho', 'spread_z', 'monotonicity', 'score']
    print(summary[cols].head(12).to_string(index=False))

    print('\n[2] Walk-forward validation per model...')
    perf_rows = []
    for name, feats in MODELS.items():
        wf = walk_forward_predict(
            df, feats, TARGET,
            test_years=(2023, 2024, 2025, 2026),
            alpha=1.0,
        )
        wf.to_csv(RESULTS_DIR / f'walkforward_{name}.csv', index=False)
        stats = evaluate_predictions(wf)
        stats['model'] = name
        stats['n_features'] = len(feats)
        perf_rows.append(stats)
        print(f'  {name:12s}  n={stats["n"]:4d}  '
              f'MAE={stats["mae_pts"]:.1f}pts  '
              f'MAPE={stats["mape_pct"]:.1f}%  '
              f'R²={stats["r2"]:.3f}  '
              f'rho={stats["spearman_rho"]:.3f}  '
              f'cover80={stats["interval_coverage_80"]:.1%}')
    perf_df = pd.DataFrame(perf_rows)
    perf_df.to_csv(RESULTS_DIR / 'walkforward_performance.csv', index=False)

    print('\n[3] Fit final models (full data) + permutation importance...')
    final_models = {}
    importance_frames = []
    for name, feats in MODELS.items():
        clean = df.dropna(subset=feats + [TARGET])
        m = fit_ridge(clean, clean[TARGET], feats, alpha=1.0)
        final_models[name] = m
        save_model(m, RESULTS_DIR / f'model_{name}.json')

        imp = permutation_importance(m, clean, clean[TARGET], n_repeats=20)
        imp['model'] = name
        importance_frames.append(imp)
    imp_df = pd.concat(importance_frames, ignore_index=True)
    imp_df.to_csv(RESULTS_DIR / 'permutation_importance.csv', index=False)

    print('\n[4] Writing report...')
    write_report(perf_df, summary, imp_df)
    print(f'\nDone. See {RESULTS_DIR / "report.md"}')


def write_report(perf: pd.DataFrame, ranking: pd.DataFrame, importance: pd.DataFrame) -> None:
    lines = [
        '# OR-Width Predictor — Results',
        '',
        '## Walk-forward performance (out-of-sample, 2023–2026)',
        '',
        _df_to_md(perf[['model', 'n_features', 'n', 'mae_pts', 'mape_pct',
                        'r2', 'spearman_rho', 'interval_coverage_80']].round(3)),
        '',
        'Reading the table:',
        '- **MAE_pts**: average absolute error in NQ pts. Lower = tighter forecast.',
        '- **R²**: variance explained. 0.40 ≈ "useful," 0.60+ ≈ "strong."',
        '- **Spearman rho**: rank-correlation of forecast vs actual. ≥0.6 = the ranking is reliable.',
        '- **Cover80**: fraction of actual ORs inside the 80% prediction band.',
        '  Should be ~0.80 if calibrated.',
        '',
        '## Univariate feature ranking (top 20)',
        '',
        _df_to_md(ranking.head(20)[
            ['feature', 'n', 'spearman_rho', 'spread_z', 'monotonicity', 'score']
        ].round(3)),
        '',
        '## Permutation importance — cold-start model',
        '',
        '_Larger MAE increase = feature matters more in the multivariate model._',
        '',
        _df_to_md(
            importance[importance['model'] == 'cold_start']
            .sort_values('mae_increase_pts', ascending=False)
            .round(3)
        ),
        '',
        '## Permutation importance — plus_5min',
        '',
        _df_to_md(
            importance[importance['model'] == 'plus_5min']
            .sort_values('mae_increase_pts', ascending=False)
            .head(15)
            .round(3)
        ),
        '',
        '## Permutation importance — plus_15min',
        '',
        _df_to_md(
            importance[importance['model'] == 'plus_15min']
            .sort_values('mae_increase_pts', ascending=False)
            .head(15)
            .round(3)
        ),
    ]
    (RESULTS_DIR / 'report.md').write_text('\n'.join(lines))


if __name__ == '__main__':
    main()
