"""
Higher-R targets — base-rate decay, per-target survivor diffs, runner signature.

Builds on studies/discovery_2R_hits/ (which already has target-parameterized
run.py outputting results_<target>/). This module synthesizes ACROSS targets
to answer:

  Q1. How does base rate decay with R?
  Q2. Which features survive at hit_3R vs hit_5R vs hit_2R? Overlap?
  Q3. Is the n_vp_targets monotonicity preserved at higher R?
  Q4. Runner signature — among hit_2R=True, what predicts hit_5R=True?
  Q5. Best single + 2-feat filter per target subject to n_OOS floor.
  Q6. Walk-forward 2018-2022 vs 2023-2026 (stricter than parent's 2018-23 / 2024-26).

Outputs to studies/higher_R_targets/results/:
  base_rate_decay.csv
  per_target_top_survivors.csv
  survivor_overlap.csv
  n_vp_targets_x_target.csv
  vp_only_target_x_target.csv
  runner_signature.csv
  best_multi_R_cells.csv
  walk_forward_strict.csv

Run:
  python3 studies/higher_R_targets/run.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl

ROOT = Path(__file__).resolve().parents[2]
PARENT_DIR = ROOT / 'studies/discovery_2R_hits'
OUT = Path(__file__).resolve().parent / 'results'
OUT.mkdir(exist_ok=True)

TARGETS = ['hit_1_5R', 'hit_2_0R', 'hit_2_5R', 'hit_3_0R',
           'hit_4_0R', 'hit_5_0R']
R_VALUE = {'hit_1_5R': 1.5, 'hit_2_0R': 2.0, 'hit_2_5R': 2.5,
           'hit_3_0R': 3.0, 'hit_4_0R': 4.0, 'hit_5_0R': 5.0}

# n-floor per target — cells thin out at higher R
N_FLOOR = {'hit_1_5R': 100, 'hit_2_0R': 100, 'hit_2_5R': 100,
           'hit_3_0R': 100, 'hit_4_0R': 50, 'hit_5_0R': 30}

IS_LAST_YEAR_LOOSE = 2023   # parent uses 2018-2023 / 2024-2026
IS_LAST_YEAR_STRICT = 2022  # stricter walk-forward 2018-2022 / 2023-2026


# ===========================================================================
# Load base trades + raw level data for v4-style feature engineering
# ===========================================================================
print('=' * 70)
print('Higher-R Targets Study')
print('=' * 70)

trades = pl.read_csv(ROOT / 'studies/baseline/results/trades.csv',
                     try_parse_dates=True).filter(pl.col('outcome') != 'skip')
levels = pl.read_csv(ROOT / 'data/levels/liquidity_levels.csv',
                     try_parse_dates=True)
vp = pl.read_csv(ROOT / 'data/levels/daily_volume_profile.csv',
                 try_parse_dates=True)

trades = trades.with_columns([
    pl.col('timestamp').dt.date().alias('date'),
    pl.col('timestamp').dt.year().alias('year'),
    (pl.col('timestamp').dt.hour().cast(pl.Int32) * 60
     + pl.col('timestamp').dt.minute().cast(pl.Int32)).alias('mod'),
])

core = levels.filter(~pl.col('group').str.starts_with('htf_'))
core_wide = core.select(['date', 'level_name', 'price']).pivot(
    values='price', index='date', on='level_name', aggregate_function='first'
)
df = trades.join(core_wide, on='date', how='left').join(vp, on='date', how='left')

SESSION_LEVELS = ['prev_day_high', 'prev_day_low', 'asia_high', 'asia_low',
                  'london_high', 'london_low', '6am_high', '6am_low',
                  'overnight_high', 'overnight_low', 'nwog_high', 'nwog_low',
                  'bsl_level', 'ssl_level']
VP_LEVELS = ['poc', 'vah', 'val']

sl = df['sl_dist'].to_numpy()
is_long = (df['direction'].to_numpy() == 'long')
ep = df['entry_price'].to_numpy()


def count_targets(level_names) -> np.ndarray:
    n = np.zeros(df.height, dtype=np.int32)
    for name in level_names:
        if name not in df.columns:
            continue
        lvl = df[name].to_numpy().astype(float)
        diff = lvl - ep
        r_signed = np.where(is_long, diff, -diff) / sl
        with np.errstate(invalid='ignore'):
            m = (r_signed >= 0.5) & (r_signed <= 3.0)
        n += m.astype(np.int32)
    return n


df = df.with_columns([
    pl.Series('n_session_targets', count_targets(SESSION_LEVELS)),
    pl.Series('n_vp_targets', count_targets(VP_LEVELS)),
])
df = df.with_columns([
    (pl.col('n_session_targets') + pl.col('n_vp_targets')).alias('n_all_targets'),
    ((pl.col('n_session_targets') == 0)
     & (pl.col('n_vp_targets') >= 1)).alias('vp_only_target'),
])

pdf = df.to_pandas()

# Mark IS/OOS for both splits
pdf['is_loose_IS'] = pdf['year'] <= IS_LAST_YEAR_LOOSE
pdf['is_loose_OOS'] = pdf['year'] >= IS_LAST_YEAR_LOOSE + 1
pdf['is_strict_IS'] = pdf['year'] <= IS_LAST_YEAR_STRICT
pdf['is_strict_OOS'] = pdf['year'] >= IS_LAST_YEAR_STRICT + 1

# Merge parent's feature_matrix (carries macro_window, range_regime, etc.)
fm = pl.read_parquet(PARENT_DIR / 'results/feature_matrix.parquet').to_pandas()
# Bring just the engineered categoricals (parent's columns minus duplicates)
parent_features = [c for c in fm.columns
                   if c not in pdf.columns
                   and c not in ('timestamp', 'date', 'year', 'is_oos',
                                 'direction', 'variant', 'sl_dist')]
pdf = pdf.merge(fm[['timestamp'] + parent_features], on='timestamp', how='left')

print(f'Trade frame: {len(pdf):,} non-skip trades, '
      f'cols={len(pdf.columns)}, years={sorted(pdf.year.unique().tolist())}')


# ===========================================================================
# Q1 — Base-rate decay table
# ===========================================================================
print('\n' + '-' * 70)
print('Q1 — Base-rate decay across R targets')
print('-' * 70)
rows = []
for t in TARGETS:
    rows.append({
        'target': t,
        'R': R_VALUE[t],
        'base_all': pdf[t].mean(),
        'base_loose_IS_2018_2023': pdf.loc[pdf.is_loose_IS, t].mean(),
        'base_loose_OOS_2024_2026': pdf.loc[pdf.is_loose_OOS, t].mean(),
        'base_strict_IS_2018_2022': pdf.loc[pdf.is_strict_IS, t].mean(),
        'base_strict_OOS_2023_2026': pdf.loc[pdf.is_strict_OOS, t].mean(),
        'n_total': pdf[t].notna().sum(),
    })
decay = pd.DataFrame(rows)
decay.to_csv(OUT / 'base_rate_decay.csv', index=False)
print(decay.to_string(index=False, float_format=lambda x: f'{x:.4f}'))


# ===========================================================================
# Q3 — n_vp_targets monotonicity at every R target
# ===========================================================================
print('\n' + '-' * 70)
print('Q3 — n_vp_targets × R target (full sample)')
print('-' * 70)
pdf['n_vp_clip'] = pdf['n_vp_targets'].clip(upper=3)
rows = []
for nvp in [0, 1, 2, 3]:
    sub = pdf[pdf['n_vp_clip'] == nvp]
    rows.append({
        'n_vp_targets': nvp,
        'n': len(sub),
        **{t: sub[t].mean() for t in TARGETS},
    })
vp_pivot = pd.DataFrame(rows)
vp_pivot.to_csv(OUT / 'n_vp_targets_x_target.csv', index=False)
print(vp_pivot.to_string(index=False, float_format=lambda x: f'{x:.4f}'))

# Same with vp_only_target flag
print('\nvp_only_target × R target:')
rows = []
for flag in [False, True]:
    sub = pdf[pdf['vp_only_target'] == flag]
    rows.append({
        'vp_only_target': flag,
        'n': len(sub),
        **{t: sub[t].mean() for t in TARGETS},
    })
vp_only = pd.DataFrame(rows)
vp_only.to_csv(OUT / 'vp_only_target_x_target.csv', index=False)
print(vp_only.to_string(index=False, float_format=lambda x: f'{x:.4f}'))

# OOS-strict view (this is the validation slice that matters)
print('\nn_vp_targets × R target (strict OOS 2023-2026 only):')
rows = []
for nvp in [0, 1, 2, 3]:
    sub = pdf[(pdf['n_vp_clip'] == nvp) & pdf['is_strict_OOS']]
    rows.append({
        'n_vp_targets': nvp,
        'n_oos': len(sub),
        **{t: sub[t].mean() for t in TARGETS},
    })
vp_oos = pd.DataFrame(rows)
vp_oos.to_csv(OUT / 'n_vp_targets_x_target_strict_oos.csv', index=False)
print(vp_oos.to_string(index=False, float_format=lambda x: f'{x:.4f}'))


# ===========================================================================
# Q2 — Per-target top survivors (read from parent results)
# ===========================================================================
print('\n' + '-' * 70)
print('Q2 — Per-target top survivors (from parent scan)')
print('-' * 70)


def load_parent_scan(target: str) -> pd.DataFrame:
    sub = ('results' if target == 'hit_2_0R' else f'results_{target}')
    p = PARENT_DIR / sub / 'single_feature_ranked.csv'
    if not p.exists():
        return pd.DataFrame()
    return pd.read_csv(p).assign(target=target)


all_scans = []
for t in TARGETS:
    s = load_parent_scan(t)
    if s.empty:
        print(f'  (missing scan output for {t})')
        continue
    s['n_floor_pass'] = (s['n_is'] >= N_FLOOR[t]) & (s['n_oos'] >= N_FLOOR[t])
    s['is_survivor'] = (s['lift_is_pp'] >= 3) & (s['lift_oos_pp'] >= 3) & s['n_floor_pass']
    all_scans.append(s)
combined = pd.concat(all_scans, ignore_index=True) if all_scans else pd.DataFrame()
combined.to_csv(OUT / 'per_target_full_scan.csv', index=False)

# Top survivors per target, by ranking score
top_rows = []
for t in TARGETS:
    sub = combined[(combined.target == t) & combined.is_survivor]
    sub = sub.sort_values('lift_oos_pp', ascending=False).head(10)
    if len(sub):
        sub = sub[['target', 'feature', 'value',
                   'n_is', 'r_is', 'lift_is_pp',
                   'n_oos', 'r_oos', 'lift_oos_pp', 'score']]
        top_rows.append(sub)
top_per_target = pd.concat(top_rows, ignore_index=True) if top_rows else pd.DataFrame()
top_per_target.to_csv(OUT / 'per_target_top_survivors.csv', index=False)
print(f'Survivors per target: '
      f'{ {t: int((combined.target == t).sum() and combined[(combined.target == t) & combined.is_survivor].shape[0]) for t in TARGETS} }')

# Survivor overlap matrix — which (feature, value) cells are survivors across targets?
print('\nSurvivor overlap across targets:')
combined['key'] = combined['feature'].astype(str) + '|' + combined['value'].astype(str)
pivot = (combined[combined.is_survivor]
         .pivot_table(index='key', columns='target', values='lift_oos_pp',
                      aggfunc='first'))
pivot['n_targets_survived'] = pivot.notna().sum(axis=1)
pivot = pivot.sort_values('n_targets_survived', ascending=False)
pivot.to_csv(OUT / 'survivor_overlap.csv')
print(pivot.head(15).to_string(float_format=lambda x: f'{x:.2f}'))


# ===========================================================================
# Q4 — Runner signature: among hit_2R=True, what predicts hit_5R=True?
# ===========================================================================
print('\n' + '-' * 70)
print('Q4 — Runner signature (conditioning on hit_2R)')
print('-' * 70)
runners = pdf[pdf['hit_2_0R'] == True].copy()
runners['pct_to_5R'] = runners['hit_5_0R'].astype(float)
base_runner_5R = runners['pct_to_5R'].mean()
base_runner_3R = runners['hit_3_0R'].mean()
base_runner_4R = runners['hit_4_0R'].mean()
print(f'Conditional base rates (sample = hit_2R=True, n={len(runners):,}):')
print(f'  P(hit_3R | hit_2R) = {base_runner_3R:.4f}')
print(f'  P(hit_4R | hit_2R) = {base_runner_4R:.4f}')
print(f'  P(hit_5R | hit_2R) = {base_runner_5R:.4f}')

# Scan candidate features for runner lift
cand_features = ['variant', 'direction', 'macro_window', 'gap_bucket',
                 'range_regime', 'prior_day_type', 'sl_dist_bucket',
                 'ath_dist_bucket', 'lvls_within_1R_bucket',
                 'n_targets_in_dir_bucket', 'n_vp_clip', 'vp_only_target',
                 'or_15min_state', 'or_45min_state', 'entry_bucket',
                 'pdr_position', 'dow']

rows = []
for feat in cand_features:
    if feat not in runners.columns:
        continue
    for val, idx in runners.groupby(feat, dropna=True).groups.items():
        sub = runners.loc[idx]
        if len(sub) < 30:
            continue
        rows.append({
            'feature': feat,
            'value': str(val),
            'n_runner': len(sub),
            'p_hit_3R_given_hit_2R': sub['hit_3_0R'].mean(),
            'p_hit_4R_given_hit_2R': sub['hit_4_0R'].mean(),
            'p_hit_5R_given_hit_2R': sub['hit_5_0R'].mean(),
            'lift_5R_pp_vs_base': (sub['hit_5_0R'].mean() - base_runner_5R) * 100,
            'lift_3R_pp_vs_base': (sub['hit_3_0R'].mean() - base_runner_3R) * 100,
            'n_oos_runner': int(sub['is_strict_OOS'].sum()),
            'p_hit_5R_oos': (sub.loc[sub.is_strict_OOS, 'hit_5_0R'].mean()
                             if sub.is_strict_OOS.sum() else float('nan')),
        })
runner = pd.DataFrame(rows).sort_values('lift_5R_pp_vs_base', ascending=False)
runner.to_csv(OUT / 'runner_signature.csv', index=False)
print('\nTop 15 runner predictors (lift on P(hit_5R | hit_2R), n_runner>=30):')
print(runner.head(15).to_string(index=False, float_format=lambda x: f'{x:.4f}'))
print('\nBottom 10 (anti-runner — fizzle-after-2R cohorts):')
print(runner.tail(10).to_string(index=False, float_format=lambda x: f'{x:.4f}'))


# ===========================================================================
# Q5 — Best multi-R consistent cells
# ===========================================================================
print('\n' + '-' * 70)
print('Q5 — Best filter per target (n_oos floor enforced)')
print('-' * 70)
rows = []
for t in TARGETS:
    sub = combined[combined.target == t]
    sub = sub[(sub.n_oos >= N_FLOOR[t])
              & (sub.lift_is_pp >= 3) & (sub.lift_oos_pp >= 3)]
    if not len(sub):
        rows.append({'target': t, 'best': '(no survivor)'})
        continue
    best = sub.sort_values('lift_oos_pp', ascending=False).iloc[0]
    rows.append({
        'target': t,
        'feature': best['feature'],
        'value': best['value'],
        'n_is': int(best['n_is']),
        'n_oos': int(best['n_oos']),
        'r_is': best['r_is'],
        'r_oos': best['r_oos'],
        'lift_is_pp': best['lift_is_pp'],
        'lift_oos_pp': best['lift_oos_pp'],
    })
best_per = pd.DataFrame(rows)
best_per.to_csv(OUT / 'best_multi_R_cells.csv', index=False)
print(best_per.to_string(index=False, float_format=lambda x: f'{x:.4f}'))


# ===========================================================================
# Q6 — Walk-forward strict (2018-2022 → 2023-2026) on top finding
# ===========================================================================
print('\n' + '-' * 70)
print('Q6 — Walk-forward STRICT (IS=2018-2022, OOS=2023-2026)')
print('-' * 70)
# Evaluate n_vp_targets buckets on the strict split for every R target
rows = []
for nvp in [0, 1, 2, 3]:
    sub = pdf[pdf['n_vp_clip'] == nvp]
    n_is = sub.is_strict_IS.sum()
    n_oos = sub.is_strict_OOS.sum()
    if n_is < 30 or n_oos < 30:
        continue
    row = {'n_vp_targets': nvp, 'n_is': int(n_is), 'n_oos': int(n_oos)}
    for t in TARGETS:
        base_is = pdf.loc[pdf.is_strict_IS, t].mean()
        base_oos = pdf.loc[pdf.is_strict_OOS, t].mean()
        r_is = sub.loc[sub.is_strict_IS, t].mean()
        r_oos = sub.loc[sub.is_strict_OOS, t].mean()
        row[f'{t}_lift_is_pp'] = (r_is - base_is) * 100
        row[f'{t}_lift_oos_pp'] = (r_oos - base_oos) * 100
        row[f'{t}_rate_oos'] = r_oos
    rows.append(row)
wf = pd.DataFrame(rows)
wf.to_csv(OUT / 'walk_forward_strict_n_vp_targets.csv', index=False)
print(wf.to_string(index=False, float_format=lambda x: f'{x:.4f}'))

# Same for vp_only_target=True
print('\nvp_only_target=True on strict IS/OOS:')
rows = []
for flag in [True, False]:
    sub = pdf[pdf['vp_only_target'] == flag]
    n_is = sub.is_strict_IS.sum()
    n_oos = sub.is_strict_OOS.sum()
    row = {'vp_only_target': flag, 'n_is': int(n_is), 'n_oos': int(n_oos)}
    for t in TARGETS:
        base_is = pdf.loc[pdf.is_strict_IS, t].mean()
        base_oos = pdf.loc[pdf.is_strict_OOS, t].mean()
        r_is = sub.loc[sub.is_strict_IS, t].mean()
        r_oos = sub.loc[sub.is_strict_OOS, t].mean()
        row[f'{t}_lift_is_pp'] = (r_is - base_is) * 100
        row[f'{t}_lift_oos_pp'] = (r_oos - base_oos) * 100
        row[f'{t}_rate_oos'] = r_oos
    rows.append(row)
wf_vp_only = pd.DataFrame(rows)
wf_vp_only.to_csv(OUT / 'walk_forward_strict_vp_only.csv', index=False)
print(wf_vp_only.to_string(index=False, float_format=lambda x: f'{x:.4f}'))


# ===========================================================================
# Year-by-year stability of n_vp_targets>=2 across all targets
# ===========================================================================
print('\n' + '-' * 70)
print('Yearly stability of n_vp_targets>=2 vs base, per target')
print('-' * 70)
pdf['nvp_ge2'] = pdf['n_vp_targets'] >= 2
rows = []
for yr in sorted(pdf['year'].unique()):
    yr_df = pdf[pdf['year'] == yr]
    yr_sub = yr_df[yr_df['nvp_ge2']]
    row = {'year': int(yr), 'n_total': len(yr_df), 'n_ge2': len(yr_sub)}
    for t in TARGETS:
        if len(yr_sub) == 0:
            continue
        row[f'{t}_base'] = yr_df[t].mean()
        row[f'{t}_ge2'] = yr_sub[t].mean()
        row[f'{t}_lift_pp'] = (yr_sub[t].mean() - yr_df[t].mean()) * 100
    rows.append(row)
yearly = pd.DataFrame(rows)
yearly.to_csv(OUT / 'yearly_n_vp_ge2_by_target.csv', index=False)
# Print compact lift-only view
lift_cols = ['year', 'n_ge2'] + [f'{t}_lift_pp' for t in TARGETS]
print(yearly[lift_cols].to_string(index=False, float_format=lambda x: f'{x:.1f}'))


print('\n' + '=' * 70)
print(f'Done. Artifacts: {OUT}')
print('=' * 70)
