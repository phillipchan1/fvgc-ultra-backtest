#!/usr/bin/env python3
"""Morning briefing CLI for the OR-width forecast.

Run from repo root, after `python studies/or_width_predictor/run.py` has
generated the trained model files.

Examples:
  python studies/or_width_predictor/predict_today.py
      → forecast for the most recent trading day in the data

  python studies/or_width_predictor/predict_today.py --date 2026-04-24
      → forecast for a specific date

  python studies/or_width_predictor/predict_today.py --date 2026-04-24 --stage plus_5min
      → updated forecast after the 9:30–9:35 candle prints
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

STUDY_DIR = Path(__file__).resolve().parent
RESULTS_DIR = STUDY_DIR / 'results'

STAGES = {
    'cold_start': '9:29 — before the bell',
    'plus_5min':  '9:35 — after first 5-min candle',
    'plus_15min': '9:45 — after first 15-min candle',
}


def load_model(stage: str) -> dict:
    path = RESULTS_DIR / f'model_{stage}.json'
    return json.loads(path.read_text())


def predict_with_drivers(model: dict, row: pd.Series) -> dict:
    feats = model['feature_names']
    coef = np.array(model['coef'])
    mu = np.array(model['feat_mean'])
    sd = np.array(model['feat_std'])
    sd_safe = np.where(sd == 0, 1, sd)
    intercept = model['intercept']
    train_resid = np.array(model['train_residuals'])

    # Pull this day's feature vector
    x = row[feats].values.astype(float)
    if np.any(np.isnan(x)):
        missing = [f for f, v in zip(feats, x) if np.isnan(v)]
        return {'error': f'missing features: {missing}'}

    z = (x - mu) / sd_safe
    log_contrib = z * coef
    log_pred = intercept + log_contrib.sum()
    point = float(np.exp(log_pred))

    # 80% interval from training residuals
    lo = float(np.exp(log_pred + np.quantile(train_resid, 0.10)))
    hi = float(np.exp(log_pred + np.quantile(train_resid, 0.90)))

    # Driver decomposition. Each feature's pts contribution ≈ its share of
    # the log-space deviation, scaled by exp().
    drivers = []
    for f, val, zi, lc in zip(feats, x, z, log_contrib):
        # pts contribution = how many pts wider/tighter than baseline did
        # this feature push us. Baseline = exp(intercept).
        baseline = float(np.exp(intercept))
        with_feat_only = float(np.exp(intercept + lc))
        delta = with_feat_only - baseline
        drivers.append({
            'feature': f,
            'value': val,
            'z': zi,
            'pts_delta': delta,
        })
    drivers = sorted(drivers, key=lambda d: abs(d['pts_delta']), reverse=True)

    return {
        'point': point,
        'lo80': lo,
        'hi80': hi,
        'baseline': float(np.exp(intercept)),
        'drivers': drivers,
    }


def latest_quintile(features_df: pd.DataFrame, point: float, lookback: int = 60) -> str:
    """Where does the forecast sit in the recent history of actual ORs?"""
    recent = features_df.tail(lookback)['or_45min_range'].dropna()
    if len(recent) < 10:
        return 'n/a'
    pct = (recent < point).mean() * 100
    if pct < 20: return f'Q1 tight ({pct:.0f}th pct of last {lookback} days)'
    if pct < 40: return f'Q2 ({pct:.0f}th pct)'
    if pct < 60: return f'Q3 typical ({pct:.0f}th pct)'
    if pct < 80: return f'Q4 ({pct:.0f}th pct)'
    return f'Q5 wide ({pct:.0f}th pct)'


def format_briefing(date: str, stage: str, result: dict, q_label: str,
                    perf: dict, top_n_drivers: int = 6) -> str:
    if 'error' in result:
        return f'ERROR for {date} {stage}: {result["error"]}'

    pt, lo, hi = result['point'], result['lo80'], result['hi80']
    lines = [
        '',
        '=' * 60,
        f'NQ 45-MIN OR FORECAST — {date}',
        f'Stage: {stage}  ({STAGES[stage]})',
        '=' * 60,
        '',
        f'  Predicted OR:  {pt:>5.0f} pts',
        f'  80% range:     {lo:>5.0f} – {hi:.0f} pts',
        f'  vs recent:     {q_label}',
        '',
        f'  Model:  MAE {perf.get("mae_pts", "?"):.0f} pts  '
        f'(±{perf.get("mae_pts", 0):.0f} typical) | '
        f'rho {perf.get("spearman_rho", 0):.2f} | '
        f'R² {perf.get("r2", 0):.2f}',
        '',
        f'  Top drivers vs baseline ({result["baseline"]:.0f} pts):',
    ]
    for d in result['drivers'][:top_n_drivers]:
        sign = '+' if d['pts_delta'] >= 0 else '-'
        lines.append(
            f'    {sign} {d["feature"]:24s}  '
            f'value={d["value"]:>8.2f}  z={d["z"]:+.2f}  '
            f'→ {d["pts_delta"]:+6.1f} pts'
        )
    lines.append('')
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--date', type=str, default=None,
                        help='YYYY-MM-DD. Default: most recent trading day.')
    parser.add_argument('--stage', type=str, default='all',
                        choices=['cold_start', 'plus_5min', 'plus_15min', 'all'])
    args = parser.parse_args()

    feats = pd.read_csv(RESULTS_DIR / 'features.csv', parse_dates=['date'])
    perf = pd.read_csv(RESULTS_DIR / 'walkforward_performance.csv').set_index('model').to_dict('index')

    if args.date:
        target_date = pd.to_datetime(args.date).date()
        row_df = feats[feats['date'].dt.date == target_date]
        if row_df.empty:
            print(f'No data for {target_date}.')
            return
    else:
        row_df = feats.tail(1)
        target_date = row_df['date'].iloc[0].date()

    row = row_df.iloc[0]

    stages = list(STAGES.keys()) if args.stage == 'all' else [args.stage]
    for stage in stages:
        model = load_model(stage)
        result = predict_with_drivers(model, row)
        if 'error' not in result:
            q_label = latest_quintile(feats, result['point'])
        else:
            q_label = ''
        print(format_briefing(str(target_date), stage, result, q_label,
                              perf.get(stage, {})))

    # If we have the actual OR (a past day), show it
    actual = row.get('or_45min_range')
    if pd.notna(actual):
        print(f'  ACTUAL 45-min OR: {actual:.0f} pts\n')


if __name__ == '__main__':
    main()
