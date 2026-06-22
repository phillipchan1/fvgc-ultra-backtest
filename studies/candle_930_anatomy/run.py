"""
9:30 Candle Anatomy Study.

Q: Does the *shape* of the 9:30 RTH open candle (body/range ratio, wick
direction, close position, relative size, hammer/star/doji flags) predict
FVGC trade quality (hit_2R)?

Methodology guardrails:
  - IS = 2018-2022, OOS = 2023-2026 (strict split, frozen rule on OOS)
  - Year-by-year required (>=7 of 9 yrs positive)
  - n >= 100 per bucket for actionable cells
  - Many derived features -> high multiple-comparison risk. Treat OOS +
    year stability as the only credible filter.
  - Kill criterion: no shape feature with >= +5pp lift on hit_2R in OOS.

Outputs (results/):
  candle_shape.csv               Per-day derived shape features
  q2_single_feature_scan.csv     Q2 — per-feature bucket scan (IS+OOS)
  q3_direction_match.csv         Q3 — decisive vs absorption x direction match
  q4_decisive_vs_absorption.csv  Q4 — backward look: 2R-hits vs not
  q5_walk_forward.csv            Q5 — IS-picked rule, frozen on OOS
  q6_vp_stack.csv                Q6 — stack with n_vp_targets >= 1
  yearly_stability.csv           Year-by-year for selected rule
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
STUDY = Path(__file__).resolve().parent
OUT = STUDY / 'results'
OUT.mkdir(parents=True, exist_ok=True)

IS_MAX_YEAR = 2022
OOS_MIN_YEAR = 2023

# -------------------------------------------------------------------------
# 1) Build 9:30 candle OHLC + shape features from 1m bars
# -------------------------------------------------------------------------
print('=' * 70)
print('9:30 Candle Anatomy Study')
print('=' * 70)
print('Loading 1m bars...')
bars = pd.read_parquet(ROOT / 'data/consolidated/nq-front-month.ohlcv-1m.parquet')
bars['ny'] = bars['timestamp_ny']
bars['date'] = bars['ny'].dt.date
bars['t'] = bars['ny'].dt.time

from datetime import time as dtime
c930 = bars[bars['t'] == dtime(9, 30)].copy()
c930 = c930.sort_values('ny').drop_duplicates('date', keep='first')
print(f'9:30 candles found: {len(c930):,} days')

c930 = c930[['date', 'open', 'high', 'low', 'close']].rename(columns={
    'open': 'c930_open', 'high': 'c930_high',
    'low': 'c930_low', 'close': 'c930_close',
})

# Derived shape features
c930['c930_range'] = c930['c930_high'] - c930['c930_low']
c930['c930_body'] = (c930['c930_close'] - c930['c930_open']).abs()
c930['c930_dir'] = np.where(c930['c930_close'] >= c930['c930_open'],
                            'bullish', 'bearish')

# Avoid div-by-zero
r = c930['c930_range'].replace(0, np.nan)

c930['body_range_ratio'] = (c930['c930_body'] / r).clip(0, 1)

# Wick percentages of range
top = c930[['c930_open', 'c930_close']].max(axis=1)
bot = c930[['c930_open', 'c930_close']].min(axis=1)
c930['upper_wick_pct'] = ((c930['c930_high'] - top) / r).clip(lower=0)
c930['lower_wick_pct'] = ((bot - c930['c930_low']) / r).clip(lower=0)

# Close position in range: 0 = low, 1 = high
c930['close_pos'] = ((c930['c930_close'] - c930['c930_low']) / r).clip(0, 1)

# Relative size — z-score vs trailing 20-day mean/std of range
c930 = c930.sort_values('date').reset_index(drop=True)
roll = c930['c930_range'].rolling(20, min_periods=10)
c930['range_mean20'] = roll.mean()
c930['range_std20'] = roll.std()
c930['range_z'] = ((c930['c930_range'] - c930['range_mean20'])
                   / c930['range_std20'])

# Shape flags
# - doji: body/range <= 0.10
# - hammer-like: bull body, lower_wick_pct >= 0.5
# - shooting-star-like: bear body, upper_wick_pct >= 0.5
# - marubozu (decisive): body/range >= 0.80
c930['is_doji'] = (c930['body_range_ratio'] <= 0.10).astype('Int64')
c930['is_marubozu'] = (c930['body_range_ratio'] >= 0.80).astype('Int64')
c930['is_hammer'] = ((c930['c930_dir'] == 'bullish')
                    & (c930['lower_wick_pct'] >= 0.50)
                    & (c930['body_range_ratio'] < 0.50)).astype('Int64')
c930['is_shooting_star'] = ((c930['c930_dir'] == 'bearish')
                            & (c930['upper_wick_pct'] >= 0.50)
                            & (c930['body_range_ratio'] < 0.50)).astype('Int64')

c930.to_csv(OUT / 'candle_shape.csv', index=False)
print(f'Per-day shape features written. cols={list(c930.columns)}')

# -------------------------------------------------------------------------
# 2) Join to baseline trades
# -------------------------------------------------------------------------
trades = pd.read_csv(ROOT / 'studies/baseline/results/trades.csv',
                     parse_dates=['timestamp'])
trades = trades[trades['outcome'] != 'skip'].copy()
trades['date'] = trades['timestamp'].dt.date
trades['year'] = trades['timestamp'].dt.year
trades['is_in_is'] = trades['year'] <= IS_MAX_YEAR
trades['is_in_oos'] = trades['year'] >= OOS_MIN_YEAR

df = trades.merge(c930, on='date', how='left')
df = df.dropna(subset=['c930_range']).copy()
print(f'\nTrades after join: {len(df):,}  '
      f'(IS={df.is_in_is.sum():,} / OOS={df.is_in_oos.sum():,})')
base = df['hit_2_0R'].mean()
print(f'Base hit_2R rate: {base:.4f}')

# -------------------------------------------------------------------------
# Q1+Q2 — Single-feature scan (continuous + flags)
# -------------------------------------------------------------------------
print('\n' + '-' * 70)
print('Q2 — Single-feature bucket scan (IS/OOS)')
print('-' * 70)

CONT_FEATURES = {
    'body_range_ratio': [0, 0.2, 0.4, 0.6, 0.8, 1.01],
    'upper_wick_pct':   [0, 0.1, 0.25, 0.5, 1.01],
    'lower_wick_pct':   [0, 0.1, 0.25, 0.5, 1.01],
    'close_pos':        [0, 0.2, 0.4, 0.6, 0.8, 1.01],
    'range_z':          [-5, -1, -0.25, 0.25, 1, 5],
    'c930_range':       [0, 5, 10, 20, 40, 1000],
}
FLAGS = ['is_doji', 'is_marubozu', 'is_hammer', 'is_shooting_star']

rows = []
for feat, edges in CONT_FEATURES.items():
    cat_all = pd.cut(df[feat], bins=edges, include_lowest=True)
    for cat in cat_all.cat.categories:
        for split_label, sub in [('IS', df[df.is_in_is]), ('OOS', df[df.is_in_oos]),
                                  ('ALL', df)]:
            mask = pd.cut(sub[feat], bins=edges, include_lowest=True) == cat
            cohort = sub[mask]
            if len(cohort) == 0:
                continue
            rest = sub[~mask]
            rows.append({
                'feature': feat,
                'bucket': str(cat),
                'split': split_label,
                'n': len(cohort),
                'p_hit_2R': cohort['hit_2_0R'].mean(),
                'lift_pp_vs_rest': ((cohort['hit_2_0R'].mean()
                                     - rest['hit_2_0R'].mean()) * 100)
                                    if len(rest) else None,
                'n_rest': len(rest),
            })

for flag in FLAGS:
    for split_label, sub in [('IS', df[df.is_in_is]), ('OOS', df[df.is_in_oos]),
                              ('ALL', df)]:
        cohort = sub[sub[flag] == 1]
        rest = sub[sub[flag] == 0]
        if len(cohort) == 0:
            continue
        rows.append({
            'feature': flag,
            'bucket': '==1',
            'split': split_label,
            'n': len(cohort),
            'p_hit_2R': cohort['hit_2_0R'].mean(),
            'lift_pp_vs_rest': ((cohort['hit_2_0R'].mean()
                                 - rest['hit_2_0R'].mean()) * 100)
                                if len(rest) else None,
            'n_rest': len(rest),
        })

scan = pd.DataFrame(rows)
scan.to_csv(OUT / 'q2_single_feature_scan.csv', index=False)

# Print most extreme OOS cells with n>=100
print('\nTop OOS cells by |lift|, n>=100:')
oos_sig = (scan[(scan['split'] == 'OOS') & (scan['n'] >= 100)]
           .assign(absl=lambda x: x['lift_pp_vs_rest'].abs())
           .sort_values('absl', ascending=False).head(15))
print(oos_sig[['feature', 'bucket', 'n', 'p_hit_2R', 'lift_pp_vs_rest']]
      .to_string(index=False, float_format=lambda x: f'{x:.3f}'))

# -------------------------------------------------------------------------
# Q3 — Direction match × decisiveness
# -------------------------------------------------------------------------
print('\n' + '-' * 70)
print('Q3 — Direction match x decisiveness (body_range_ratio)')
print('-' * 70)
df['dir_match'] = ((df['direction'] == 'long') & (df['c930_dir'] == 'bullish')) \
                | ((df['direction'] == 'short') & (df['c930_dir'] == 'bearish'))
df['decisive'] = df['body_range_ratio'] >= 0.6
df['absorption'] = df['body_range_ratio'] <= 0.3

rows = []
for split_label, sub in [('IS', df[df.is_in_is]), ('OOS', df[df.is_in_oos]),
                          ('ALL', df)]:
    for match_label, m in [('match', sub['dir_match']),
                            ('opposed', ~sub['dir_match'])]:
        for shape_label, s in [('decisive', sub['decisive']),
                                ('absorption', sub['absorption']),
                                ('mid', ~sub['decisive'] & ~sub['absorption']),
                                ('any', np.ones(len(sub), dtype=bool))]:
            cohort = sub[m & s]
            if len(cohort) == 0:
                continue
            rows.append({
                'split': split_label, 'match': match_label, 'shape': shape_label,
                'n': len(cohort),
                'p_hit_2R': cohort['hit_2_0R'].mean(),
                'p_hit_3R': cohort['hit_3_0R'].mean(),
            })
q3 = pd.DataFrame(rows)
q3.to_csv(OUT / 'q3_direction_match.csv', index=False)
print(q3.to_string(index=False, float_format=lambda x: f'{x:.3f}'))

# -------------------------------------------------------------------------
# Q4 — Backward look: 2R-hits vs not, what did 9:30 look like?
# -------------------------------------------------------------------------
print('\n' + '-' * 70)
print('Q4 — Backward: shape profile of 2R-hits vs non-hits')
print('-' * 70)
rows = []
for split_label, sub in [('IS', df[df.is_in_is]), ('OOS', df[df.is_in_oos]),
                          ('ALL', df)]:
    for hit_label, hmask in [('hit_2R', sub['hit_2_0R'] == True),
                              ('no_hit_2R', sub['hit_2_0R'] != True)]:
        cohort = sub[hmask]
        if len(cohort) == 0:
            continue
        rows.append({
            'split': split_label, 'cohort': hit_label, 'n': len(cohort),
            'mean_body_range_ratio': cohort['body_range_ratio'].mean(),
            'mean_close_pos': cohort['close_pos'].mean(),
            'mean_range_z': cohort['range_z'].mean(),
            'mean_upper_wick_pct': cohort['upper_wick_pct'].mean(),
            'mean_lower_wick_pct': cohort['lower_wick_pct'].mean(),
            'pct_dir_match': cohort['dir_match'].mean(),
            'pct_decisive': cohort['decisive'].mean(),
            'pct_absorption': cohort['absorption'].mean(),
        })
q4 = pd.DataFrame(rows)
q4.to_csv(OUT / 'q4_decisive_vs_absorption.csv', index=False)
print(q4.to_string(index=False, float_format=lambda x: f'{x:.3f}'))

# -------------------------------------------------------------------------
# Q5 — Walk-forward: pick best rule on IS, freeze on OOS
# Candidate rules from prior scan; require n_IS>=200 and lift_IS>=3pp.
# -------------------------------------------------------------------------
print('\n' + '-' * 70)
print('Q5 — Walk-forward (IS-picked rule frozen on OOS)')
print('-' * 70)
CANDIDATES = []
for feat, edges in CONT_FEATURES.items():
    cats = pd.cut(df[feat], bins=edges, include_lowest=True).cat.categories
    for cat in cats:
        CANDIDATES.append((feat, cat))
for flag in FLAGS:
    CANDIDATES.append((flag, '==1'))

def in_bucket(series, feat, cat):
    if isinstance(cat, str) and cat == '==1':
        return series[feat] == 1
    return pd.cut(series[feat], bins=CONT_FEATURES[feat],
                  include_lowest=True) == cat

is_df = df[df.is_in_is]
oos_df = df[df.is_in_oos]
base_is = is_df['hit_2_0R'].mean()

rule_rows = []
for feat, cat in CANDIDATES:
    m_is = in_bucket(is_df, feat, cat)
    cohort_is = is_df[m_is]
    if len(cohort_is) < 200:
        continue
    rest_is = is_df[~m_is]
    lift_is = (cohort_is['hit_2_0R'].mean() - rest_is['hit_2_0R'].mean()) * 100
    m_oos = in_bucket(oos_df, feat, cat)
    cohort_oos = oos_df[m_oos]
    rest_oos = oos_df[~m_oos]
    lift_oos = ((cohort_oos['hit_2_0R'].mean() - rest_oos['hit_2_0R'].mean()) * 100
                 if len(cohort_oos) and len(rest_oos) else None)
    rule_rows.append({
        'feature': feat, 'bucket': str(cat), '_cat': cat,
        'n_IS': len(cohort_is), 'p_hit_2R_IS': cohort_is['hit_2_0R'].mean(),
        'lift_pp_IS': lift_is,
        'n_OOS': len(cohort_oos),
        'p_hit_2R_OOS': cohort_oos['hit_2_0R'].mean() if len(cohort_oos) else None,
        'lift_pp_OOS': lift_oos,
    })
rules = pd.DataFrame(rule_rows).sort_values('lift_pp_IS', ascending=False)
rules.drop(columns=['_cat']).to_csv(OUT / 'q5_walk_forward.csv', index=False)
print(rules.drop(columns=['_cat']).to_string(index=False,
                                              float_format=lambda x: f'{x:.3f}'))

# Best IS rule with n>=200, evaluate yearly
best = rules.iloc[0]
BEST_FEAT = best.feature
BEST_CAT = best._cat
print(f'\nBest IS rule: feature={BEST_FEAT} bucket={best.bucket} '
      f'lift_IS={best.lift_pp_IS:.2f}pp lift_OOS={best.lift_pp_OOS}')

# -------------------------------------------------------------------------
# Q3.5 — Year-by-year for the best IS rule
# -------------------------------------------------------------------------
print('\n' + '-' * 70)
print(f'Yearly stability for best rule: {best.feature} {best.bucket}')
print('-' * 70)
def mask_for(d, feat, cat):
    return in_bucket(d, feat, cat)

yrs = sorted(df['year'].unique())
yr_rows = []
for yr in yrs:
    sub = df[df['year'] == yr]
    m = mask_for(sub, BEST_FEAT, BEST_CAT)
    cohort = sub[m]
    rest = sub[~m]
    yr_rows.append({
        'year': int(yr),
        'n_cohort': len(cohort), 'n_rest': len(rest),
        'p_hit_2R_cohort': cohort['hit_2_0R'].mean() if len(cohort) else None,
        'p_hit_2R_rest': rest['hit_2_0R'].mean() if len(rest) else None,
        'lift_pp': ((cohort['hit_2_0R'].mean() - rest['hit_2_0R'].mean()) * 100
                     if len(cohort) and len(rest) else None),
        'positive': (cohort['hit_2_0R'].mean() > rest['hit_2_0R'].mean()
                      if len(cohort) and len(rest) else None),
    })
yearly = pd.DataFrame(yr_rows)
yearly.to_csv(OUT / 'yearly_stability.csv', index=False)
print(yearly.to_string(index=False, float_format=lambda x: f'{x:.3f}'))
pos = yearly['positive'].sum()
total = yearly['positive'].notna().sum()
print(f'\nPositive years: {pos}/{total} (need >=7/9)')

# -------------------------------------------------------------------------
# Q6 — Stack with n_vp_targets >= 1
# -------------------------------------------------------------------------
print('\n' + '-' * 70)
print('Q6 — Stack with n_vp_targets >= 1')
print('-' * 70)
vp = pd.read_csv(ROOT / 'data/levels/daily_volume_profile.csv',
                  parse_dates=['date'])
vp['date'] = vp['date'].dt.date
df2 = df.merge(vp[['date', 'poc', 'vah', 'val']], on='date', how='left')

is_long = (df2['direction'] == 'long').to_numpy()
ep = df2['entry_price'].to_numpy()
sl_dist = df2['sl_dist'].to_numpy()

def signed_R(level):
    diff = level - ep
    return np.where(is_long, diff, -diff) / sl_dist

def in_zone(r):
    with np.errstate(invalid='ignore'):
        return (r >= 0.5) & (r <= 3.0)

poc_in = in_zone(signed_R(df2['poc'].to_numpy().astype(float)))
vah_in = in_zone(signed_R(df2['vah'].to_numpy().astype(float)))
val_in = in_zone(signed_R(df2['val'].to_numpy().astype(float)))
df2['n_vp'] = poc_in.astype(int) + vah_in.astype(int) + val_in.astype(int)
df2['has_vp'] = df2['n_vp'] >= 1

# Use the winning rule from Q5
df2['rule_pass'] = mask_for(df2, BEST_FEAT, BEST_CAT)

rows = []
for split_label, sub in [('IS', df2[df2.is_in_is]),
                          ('OOS', df2[df2.is_in_oos]),
                          ('ALL', df2)]:
    cohorts = [
        ('baseline', np.ones(len(sub), dtype=bool)),
        ('has_vp',           sub['has_vp'].to_numpy()),
        ('rule_pass',        sub['rule_pass'].to_numpy()),
        ('has_vp AND rule',  (sub['has_vp'] & sub['rule_pass']).to_numpy()),
        ('has_vp AND ~rule', (sub['has_vp'] & ~sub['rule_pass']).to_numpy()),
        ('~has_vp AND rule', (~sub['has_vp'] & sub['rule_pass']).to_numpy()),
    ]
    for label, mask in cohorts:
        c = sub[mask]
        if len(c) == 0:
            continue
        rows.append({
            'split': split_label, 'cohort': label, 'n': len(c),
            'p_hit_2R': c['hit_2_0R'].mean(),
            'p_hit_3R': c['hit_3_0R'].mean(),
        })
q6 = pd.DataFrame(rows)
q6.to_csv(OUT / 'q6_vp_stack.csv', index=False)
print(q6.to_string(index=False, float_format=lambda x: f'{x:.3f}'))

print('\n' + '=' * 70)
print('Done. Artifacts in:', OUT)
print('=' * 70)
