"""
Speed-of-Move Continuation Study.

Q: Among trades that hit 1R, does bars_to_1R predict hit_2R / hit_3R?
   If yes, this becomes a trade management rule ("hold for runner if 1R hit
   fast; otherwise scratch at 1R") rather than an entry filter.

Methodology guardrails:
  - IS = 2018-2022, OOS = 2023-2026 (strict split)
  - Threshold chosen from IS only; OOS is frozen-validation
  - Year-by-year required (>=7 of 9 yrs positive)
  - n >= 100 per bucket for actionable cells
  - Survivorship caveat: only hit_1R=True trades have bars_to_1R; non-hits are
    irrelevant for the management rule.

Outputs (results/):
  curve_P_hit2R.csv           Q1 — P(hit_2R|bars_to_1R bucket) curve
  threshold_search.csv        Q2 — fast vs slow per candidate N
  yearly_stability.csv        Q3 — hit_2R rate × year × bucket
  is_oos_validation.csv       Q4 — IS-picked threshold frozen on OOS
  vp_x_speed.csv              Q5 — VP filter stacked with speed filter
  management_rule_expectancy.csv  Q6 — TP=1R vs TP=2R vs dynamic
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
# Load
# -------------------------------------------------------------------------
trades = pd.read_csv(ROOT / 'studies/baseline/results/trades.csv',
                    parse_dates=['timestamp', 'exit_time'])
trades = trades[trades['outcome'] != 'skip'].copy()
trades['year'] = trades['timestamp'].dt.year
trades['date'] = trades['timestamp'].dt.date
trades['is_in_is'] = trades['year'] <= IS_MAX_YEAR
trades['is_in_oos'] = trades['year'] >= OOS_MIN_YEAR

print('=' * 70)
print('Speed-of-Move Continuation Study')
print('=' * 70)
print(f'Total non-skip trades:    {len(trades):,}')
print(f'  IS  ({trades["year"].min()}-{IS_MAX_YEAR}): {trades["is_in_is"].sum():,}')
print(f'  OOS ({OOS_MIN_YEAR}-{trades["year"].max()}): {trades["is_in_oos"].sum():,}')
print(f'Base hit_2R rate (all):   {trades["hit_2_0R"].mean():.4f}')
print(f'Base hit_2R rate (IS):    {trades.loc[trades.is_in_is, "hit_2_0R"].mean():.4f}')
print(f'Base hit_2R rate (OOS):   {trades.loc[trades.is_in_oos, "hit_2_0R"].mean():.4f}')

# Hit_1R sub-population — these have a valid bars_to_1R
h1 = trades[trades['hit_1_0R'] == True].copy()
h1['bars'] = h1['bars_to_1_0R'].astype(int)
print(f'\nhit_1R sub-population:    {len(h1):,}')
print(f'  P(hit_2R | hit_1R):     {h1["hit_2_0R"].mean():.4f}')
print(f'  P(hit_3R | hit_1R):     {h1["hit_3_0R"].mean():.4f}')
print(f'  P(hit_5R | hit_1R):     {h1["hit_5_0R"].mean():.4f}')


# -------------------------------------------------------------------------
# Q1 — Conditional curve P(hit_2R | bars_to_1R bucket)
# -------------------------------------------------------------------------
print('\n' + '-' * 70)
print('Q1 — P(hit_NR | bars_to_1R bucket)')
print('-' * 70)
bins = [(1, 2), (2, 3), (3, 4), (4, 5), (5, 6), (6, 8), (8, 10),
        (10, 15), (15, 20), (20, 30), (30, 50), (50, 100), (100, 99999)]
rows = []
for lo, hi in bins:
    sub = h1[(h1['bars'] >= lo) & (h1['bars'] < hi)]
    if len(sub) == 0:
        continue
    rows.append({
        'bars_lo': lo, 'bars_hi': hi, 'n': len(sub),
        'p_hit_2R': sub['hit_2_0R'].mean(),
        'p_hit_3R': sub['hit_3_0R'].mean(),
        'p_hit_5R': sub['hit_5_0R'].mean(),
    })
curve = pd.DataFrame(rows)
curve.to_csv(OUT / 'curve_P_hit2R.csv', index=False)
print(curve.to_string(index=False, float_format=lambda x: f'{x:.3f}'))


# -------------------------------------------------------------------------
# Q2 — Threshold sweep
# -------------------------------------------------------------------------
print('\n' + '-' * 70)
print('Q2 — Threshold sweep (fast = bars_to_1R <= N within hit_1R)')
print('-' * 70)
# Whole-population (treat non-hit_1R as bars_to_1R = inf)
trades['bars_to_1R'] = trades['bars_to_1_0R']
ths = [2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 25, 30]
rows = []
for N in ths:
    fast = h1[h1['bars'] <= N]
    slow = h1[h1['bars'] > N]
    rows.append({
        'N': N,
        'n_fast': len(fast),
        'p_hit_2R_fast': fast['hit_2_0R'].mean(),
        'p_hit_3R_fast': fast['hit_3_0R'].mean(),
        'p_hit_5R_fast': fast['hit_5_0R'].mean(),
        'n_slow': len(slow),
        'p_hit_2R_slow': slow['hit_2_0R'].mean(),
        'p_hit_3R_slow': slow['hit_3_0R'].mean(),
        'p_hit_5R_slow': slow['hit_5_0R'].mean(),
        'lift_2R_pp': (fast['hit_2_0R'].mean() - slow['hit_2_0R'].mean()) * 100,
        'lift_3R_pp': (fast['hit_3_0R'].mean() - slow['hit_3_0R'].mean()) * 100,
    })
sweep = pd.DataFrame(rows)
sweep.to_csv(OUT / 'threshold_search.csv', index=False)
print(sweep.to_string(index=False, float_format=lambda x: f'{x:.3f}'))

# IS-only threshold sweep (so that we can pick a threshold from IS)
print('\nIS-only threshold sweep:')
h1_is = h1[h1['is_in_is']]
h1_oos = h1[h1['is_in_oos']]
rows = []
for N in ths:
    fast = h1_is[h1_is['bars'] <= N]
    slow = h1_is[h1_is['bars'] > N]
    rows.append({
        'N': N,
        'n_fast_IS': len(fast),
        'p_hit_2R_fast_IS': fast['hit_2_0R'].mean(),
        'p_hit_3R_fast_IS': fast['hit_3_0R'].mean(),
        'n_slow_IS': len(slow),
        'p_hit_2R_slow_IS': slow['hit_2_0R'].mean(),
        'p_hit_3R_slow_IS': slow['hit_3_0R'].mean(),
        'lift_2R_pp_IS': (fast['hit_2_0R'].mean() - slow['hit_2_0R'].mean()) * 100,
    })
sweep_is = pd.DataFrame(rows)
sweep_is.to_csv(OUT / 'threshold_search_IS.csv', index=False)
print(sweep_is.to_string(index=False, float_format=lambda x: f'{x:.3f}'))


# -------------------------------------------------------------------------
# Q4 — IS/OOS validation
# Pick threshold N* that maximises hit_2R lift in IS subject to n_fast_IS>=100.
# Then evaluate frozen on OOS.
# -------------------------------------------------------------------------
print('\n' + '-' * 70)
print('Q4 — IS/OOS frozen validation')
print('-' * 70)
candidates = sweep_is[(sweep_is['n_fast_IS'] >= 100) & (sweep_is['n_slow_IS'] >= 100)]
if len(candidates) == 0:
    raise RuntimeError('No threshold passed n>=100 in IS')
best = candidates.sort_values('lift_2R_pp_IS', ascending=False).iloc[0]
N_STAR = int(best['N'])
print(f'Selected threshold N* = {N_STAR} (IS lift {best["lift_2R_pp_IS"]:.1f}pp on hit_2R)')

# Frozen evaluation
rows = []
for split, sub in [('IS', h1_is), ('OOS', h1_oos), ('ALL', h1)]:
    fast = sub[sub['bars'] <= N_STAR]
    slow = sub[sub['bars'] > N_STAR]
    rows.append({
        'split': split,
        'N_star': N_STAR,
        'n_fast': len(fast),
        'p_hit_2R_fast': fast['hit_2_0R'].mean() if len(fast) else None,
        'p_hit_3R_fast': fast['hit_3_0R'].mean() if len(fast) else None,
        'n_slow': len(slow),
        'p_hit_2R_slow': slow['hit_2_0R'].mean() if len(slow) else None,
        'p_hit_3R_slow': slow['hit_3_0R'].mean() if len(slow) else None,
        'lift_2R_pp': (fast['hit_2_0R'].mean() - slow['hit_2_0R'].mean()) * 100 if len(fast) and len(slow) else None,
        'lift_3R_pp': (fast['hit_3_0R'].mean() - slow['hit_3_0R'].mean()) * 100 if len(fast) and len(slow) else None,
    })
is_oos = pd.DataFrame(rows)
is_oos.to_csv(OUT / 'is_oos_validation.csv', index=False)
print(is_oos.to_string(index=False, float_format=lambda x: f'{x:.3f}'))


# -------------------------------------------------------------------------
# Q3 — Year-by-year stability
# -------------------------------------------------------------------------
print('\n' + '-' * 70)
print(f'Q3 — Yearly stability at N* = {N_STAR}')
print('-' * 70)
rows = []
for yr in sorted(h1['year'].unique()):
    sub = h1[h1['year'] == yr]
    fast = sub[sub['bars'] <= N_STAR]
    slow = sub[sub['bars'] > N_STAR]
    rows.append({
        'year': int(yr),
        'n_total': len(sub),
        'n_fast': len(fast),
        'n_slow': len(slow),
        'p_hit_2R_fast': fast['hit_2_0R'].mean() if len(fast) else None,
        'p_hit_2R_slow': slow['hit_2_0R'].mean() if len(slow) else None,
        'lift_pp': ((fast['hit_2_0R'].mean() - slow['hit_2_0R'].mean()) * 100)
                   if len(fast) and len(slow) else None,
        'positive': (fast['hit_2_0R'].mean() > slow['hit_2_0R'].mean())
                    if len(fast) and len(slow) else None,
    })
yearly = pd.DataFrame(rows)
yearly.to_csv(OUT / 'yearly_stability.csv', index=False)
print(yearly.to_string(index=False, float_format=lambda x: f'{x:.3f}'))
pos = yearly['positive'].sum()
total = yearly['positive'].notna().sum()
print(f'\nPositive years: {pos}/{total} (need >=7/9)')


# -------------------------------------------------------------------------
# Q5 — VP × speed stacking
# -------------------------------------------------------------------------
print('\n' + '-' * 70)
print('Q5 — VP × speed stacking')
print('-' * 70)
# Compute n_vp_targets from daily_volume_profile
vp = pd.read_csv(ROOT / 'data/levels/daily_volume_profile.csv', parse_dates=['date'])
vp['date'] = vp['date'].dt.date
df = trades.merge(vp[['date', 'poc', 'vah', 'val']], on='date', how='left')

is_long = df['direction'].to_numpy() == 'long'
ep = df['entry_price'].to_numpy()
sl_dist = df['sl_dist'].to_numpy()


def signed_R(level: np.ndarray) -> np.ndarray:
    diff = level - ep
    return np.where(is_long, diff, -diff) / sl_dist


def in_zone(r: np.ndarray) -> np.ndarray:
    with np.errstate(invalid='ignore'):
        return (r >= 0.5) & (r <= 3.0)


poc_in = in_zone(signed_R(df['poc'].to_numpy().astype(float)))
vah_in = in_zone(signed_R(df['vah'].to_numpy().astype(float)))
val_in = in_zone(signed_R(df['val'].to_numpy().astype(float)))
df['n_vp_targets'] = (poc_in.astype(int) + vah_in.astype(int) + val_in.astype(int))

# Speed flag (within trades that hit 1R)
df['fast'] = ((df['hit_1_0R'] == True) & (df['bars_to_1_0R'] <= N_STAR))
df['has_vp'] = (df['n_vp_targets'] >= 1)

print(f'n_vp_targets distribution: {df["n_vp_targets"].value_counts().to_dict()}')

# Universe = all non-skip; hit_2R measured on full universe
rows = []
for label, mask in [
    ('all (baseline)',          np.ones(len(df), dtype=bool)),
    ('n_vp >= 1',               df['has_vp'].to_numpy()),
    ('fast (hit_1R<=N*)',       df['fast'].to_numpy()),
    ('n_vp >= 1 AND fast',      (df['has_vp'] & df['fast']).to_numpy()),
    ('n_vp == 0',               (~df['has_vp']).to_numpy()),
    ('slow (hit_1R, bars>N*)',  ((df['hit_1_0R'] == True) & (df['bars_to_1_0R'] > N_STAR)).to_numpy()),
    ('n_vp >= 1 AND slow',      (df['has_vp'] & (df['hit_1_0R'] == True) & (df['bars_to_1_0R'] > N_STAR)).to_numpy()),
]:
    sub = df[mask]
    rows.append({
        'cohort': label,
        'n': len(sub),
        'p_hit_1R': sub['hit_1_0R'].mean() if len(sub) else None,
        'p_hit_2R': sub['hit_2_0R'].mean() if len(sub) else None,
        'p_hit_3R': sub['hit_3_0R'].mean() if len(sub) else None,
    })
vp_speed = pd.DataFrame(rows)
vp_speed.to_csv(OUT / 'vp_x_speed.csv', index=False)
print(vp_speed.to_string(index=False, float_format=lambda x: f'{x:.3f}'))

# Same table on OOS only
print('\nOOS only:')
rows = []
df_oos = df[df['is_in_oos']]
for label, mask in [
    ('all OOS',                 np.ones(len(df_oos), dtype=bool)),
    ('n_vp >= 1',               df_oos['has_vp'].to_numpy()),
    ('fast',                    df_oos['fast'].to_numpy()),
    ('n_vp >= 1 AND fast',      (df_oos['has_vp'] & df_oos['fast']).to_numpy()),
]:
    sub = df_oos[mask]
    rows.append({
        'cohort': label,
        'n': len(sub),
        'p_hit_2R': sub['hit_2_0R'].mean() if len(sub) else None,
        'p_hit_3R': sub['hit_3_0R'].mean() if len(sub) else None,
    })
vp_speed_oos = pd.DataFrame(rows)
vp_speed_oos.to_csv(OUT / 'vp_x_speed_oos.csv', index=False)
print(vp_speed_oos.to_string(index=False, float_format=lambda x: f'{x:.3f}'))


# -------------------------------------------------------------------------
# Q6 — Management rule expectancy
# Per-trade expected R under three strategies:
#   A: TP=1R              -> hit_1R: +1, else -1
#   B: TP=2R              -> hit_2R: +2, hit_1R & not hit_2R: -1 (conservative),
#                            no hit_1R: -1
#   C: Dynamic (fast hold)-> if hit_1R & bars<=N*: same as B; else same as A
# All strategies assume SL = -1R; trades that never hit 1R go -1R.
# -------------------------------------------------------------------------
print('\n' + '-' * 70)
print(f'Q6 — Management rule expectancy (N* = {N_STAR})')
print('-' * 70)
# Conservative B: hit_1R but not hit_2R = -1R
# Optimistic B: such trades = +1R (best case: assume the engine would have moved
#               SL to BE; report both)


def strategy_R(sub: pd.DataFrame, mode: str, N: int) -> pd.Series:
    h1 = sub['hit_1_0R'] == True
    h2 = sub['hit_2_0R'] == True
    fast = h1 & (sub['bars_to_1_0R'] <= N)
    if mode == 'TP_1R':
        return np.where(h1, 1.0, -1.0)
    if mode == 'TP_2R_cons':  # conservative: hit_1R-not-2R = -1R
        return np.where(h2, 2.0, -1.0)
    if mode == 'TP_2R_BE':    # break-even after 1R touched
        return np.where(h2, 2.0, np.where(h1, 0.0, -1.0))
    if mode == 'dyn_cons':    # fast hold to 2R (cons), slow exit at 1R
        return np.where(fast, np.where(h2, 2.0, -1.0),
                np.where(h1, 1.0, -1.0))
    if mode == 'dyn_BE':      # fast hold to 2R (with BE after 1R), slow exit at 1R
        return np.where(fast, np.where(h2, 2.0, 0.0),
                np.where(h1, 1.0, -1.0))
    raise ValueError(mode)


rows = []
for split, sub in [('IS', trades[trades.is_in_is]),
                   ('OOS', trades[trades.is_in_oos]),
                   ('ALL', trades)]:
    row = {'split': split, 'n_trades': len(sub)}
    for mode in ['TP_1R', 'TP_2R_cons', 'TP_2R_BE', 'dyn_cons', 'dyn_BE']:
        r = strategy_R(sub, mode, N_STAR)
        row[f'{mode}_mean_R'] = float(np.mean(r))
        row[f'{mode}_total_R'] = float(np.sum(r))
        row[f'{mode}_win_pct'] = float(np.mean(np.array(r) > 0))
    rows.append(row)
mgmt = pd.DataFrame(rows)
mgmt.to_csv(OUT / 'management_rule_expectancy.csv', index=False)
print(mgmt.to_string(index=False, float_format=lambda x: f'{x:.4f}'))

# Sub-tally: for hit_1R cohort, slow vs fast hit_2R rates (just to confirm the
# "scratch at 1R if slow" cohort is genuinely sub-baseline)
slow_h1 = h1[h1['bars'] > N_STAR]
print(f'\nSlow cohort (hit_1R, bars>{N_STAR}): n={len(slow_h1)}, '
      f'P(hit_2R) = {slow_h1["hit_2_0R"].mean():.3f} vs '
      f'P(hit_2R | hit_1R) overall = {h1["hit_2_0R"].mean():.3f}')


print('\n' + '=' * 70)
print('Done. Artifacts in:', OUT)
print('=' * 70)
