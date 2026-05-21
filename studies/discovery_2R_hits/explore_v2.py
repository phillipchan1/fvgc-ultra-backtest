"""
v2 feature exploration. Goes beyond the macro/level features in run.py to test:
  A. FVG quality: age, size, entry offset within FVG
  B. Sequence: Nth signal of the day, minutes since open, prior winner today
  C. Pre-entry context: distance from RTH open, was at session H/L
  D. Volatility ladder: sl_dist vs candle_930 / overnight / 5d
  E. HTF momentum: 5d/20d price change, position in 20d range

Same IS/OOS / year-by-year guardrails as run.py.
Outputs to results_v2/.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import polars as pl

TARGET = sys.argv[1] if len(sys.argv) > 1 else 'hit_2_0R'
ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / ('results_v2' if TARGET == 'hit_2_0R' else f'results_v2_{TARGET}')
OUT.mkdir(exist_ok=True)
print(f'TARGET={TARGET}  OUT={OUT}')

# ---- Load ----
trades = pl.read_csv(ROOT / 'studies/baseline/results/trades.csv', try_parse_dates=True).filter(pl.col('outcome') != 'skip')
days = pl.read_csv(ROOT / 'data/trading_days/trading_days.csv', try_parse_dates=True).sort('date')
print(f'trades={trades.height}  days={days.height}')

trades = trades.with_columns([
    pl.col('timestamp').dt.date().alias('date'),
    pl.col('timestamp').dt.year().alias('year'),
    (pl.col('timestamp').dt.year() >= 2024).alias('is_oos'),
    (pl.col('timestamp').dt.hour().cast(pl.Int32) * 60
     + pl.col('timestamp').dt.minute().cast(pl.Int32)).alias('mod'),
])

# ---- HTF day-level momentum features ----
days = days.with_columns([
    pl.col('rth_close').shift(1).alias('prev_close'),
    pl.col('rth_close').shift(5).alias('close_5d_ago'),
    pl.col('rth_close').shift(20).alias('close_20d_ago'),
    pl.col('rth_high').shift(1).rolling_max(window_size=20).alias('high_20d'),
    pl.col('rth_low').shift(1).rolling_min(window_size=20).alias('low_20d'),
    pl.col('rth_range').shift(1).rolling_mean(window_size=5).alias('avg_range_5d'),
    pl.col('rth_range').shift(1).rolling_mean(window_size=20).alias('avg_range_20d'),
])

df = trades.join(days, on='date', how='left')

# ---- Derive new features ----
# A. FVG quality
df = df.with_columns([
    # FVG age in minutes (entry - fvg_created_at)
    ((pl.col('timestamp') - pl.col('fvg_created_at')).dt.total_seconds() / 60.0).alias('fvg_age_min'),
    # FVG size in pts
    (pl.col('fvg_top') - pl.col('fvg_bottom')).alias('fvg_size_pts'),
])
df = df.with_columns([
    (pl.col('fvg_size_pts') / pl.col('sl_dist')).alias('fvg_size_R'),
    # Entry offset within FVG: 0 = at fvg_bottom, 1 = at fvg_top, signed by direction
    pl.when(pl.col('fvg_top') == pl.col('fvg_bottom'))
    .then(0.5)
    .otherwise((pl.col('entry_price') - pl.col('fvg_bottom')) / (pl.col('fvg_top') - pl.col('fvg_bottom')))
    .alias('entry_pos_in_fvg'),
])

# Buckets
df = df.with_columns([
    pl.when(pl.col('fvg_age_min') < 5).then(pl.lit('lt_5min'))
    .when(pl.col('fvg_age_min') < 15).then(pl.lit('5-15min'))
    .when(pl.col('fvg_age_min') < 30).then(pl.lit('15-30min'))
    .when(pl.col('fvg_age_min') < 120).then(pl.lit('30-120min'))
    .when(pl.col('fvg_age_min') < 24 * 60).then(pl.lit('2-24h'))
    .otherwise(pl.lit('gt_24h'))
    .alias('fvg_age_bucket'),

    pl.when(pl.col('fvg_size_R') < 0.25).then(pl.lit('Q1_tiny'))
    .when(pl.col('fvg_size_R') < 0.5).then(pl.lit('Q2_small'))
    .when(pl.col('fvg_size_R') < 1.0).then(pl.lit('Q3_med'))
    .otherwise(pl.lit('Q4_large'))
    .alias('fvg_size_bucket'),

    pl.when(pl.col('entry_pos_in_fvg') < 0.2).then(pl.lit('deep_bottom'))
    .when(pl.col('entry_pos_in_fvg') < 0.5).then(pl.lit('lower_half'))
    .when(pl.col('entry_pos_in_fvg') < 0.8).then(pl.lit('upper_half'))
    .otherwise(pl.lit('near_top'))
    .alias('entry_pos_bucket'),
])

# B. Sequence -- order by timestamp within date
df = df.sort('timestamp').with_columns(
    pl.cum_count('timestamp').over('date').alias('signal_seq_today'),
)
# minutes since open (mod - 570)
df = df.with_columns((pl.col('mod') - 570).alias('min_since_open'))

# Has prior winner today? prior loser today?
# Compute cumulative count of prior wins/losses per day before each trade.
# Use shifted cumulative sum to exclude current row.
df = df.with_columns([
    (pl.col('outcome') == 'win').cast(pl.Int32).cum_sum().over('date').shift(1, fill_value=0).alias('prior_wins_today'),
    (pl.col('outcome') == 'loss').cast(pl.Int32).cum_sum().over('date').shift(1, fill_value=0).alias('prior_losses_today'),
])
df = df.with_columns([
    (pl.col('prior_wins_today') > 0).alias('has_prior_win'),
    (pl.col('prior_losses_today') > 0).alias('has_prior_loss'),
])
df = df.with_columns(
    pl.when(pl.col('signal_seq_today') == 1).then(pl.lit('1st'))
    .when(pl.col('signal_seq_today') == 2).then(pl.lit('2nd'))
    .when(pl.col('signal_seq_today') == 3).then(pl.lit('3rd'))
    .otherwise(pl.lit('4th+'))
    .alias('signal_seq_bucket')
)

# C. Pre-entry context
df = df.with_columns([
    (pl.col('entry_price') - pl.col('rth_open')).alias('entry_offset_from_open'),
])
df = df.with_columns(
    (pl.col('entry_offset_from_open') / pl.col('sl_dist')).alias('entry_offset_R'),
)
df = df.with_columns(
    pl.when(pl.col('entry_offset_R').abs() < 0.5).then(pl.lit('near_open'))
    .when(pl.col('entry_offset_R').abs() < 2.0).then(pl.lit('mid_offset'))
    .when(pl.col('entry_offset_R').abs() < 5.0).then(pl.lit('far_offset'))
    .otherwise(pl.lit('very_far'))
    .alias('entry_offset_bucket')
)

# Is entry above or below RTH open and does it match trade direction?
df = df.with_columns(
    (((pl.col('direction') == 'long') & (pl.col('entry_offset_from_open') > 0))
     | ((pl.col('direction') == 'short') & (pl.col('entry_offset_from_open') < 0))).alias('entry_with_open_bias')
)

# D. Volatility ladder
df = df.with_columns([
    (pl.col('sl_dist') / pl.col('candle_930_range').clip(0.25, None)).alias('sl_vs_candle930'),
    (pl.col('sl_dist') / pl.col('overnight_range').clip(0.25, None)).alias('sl_vs_on'),
    (pl.col('sl_dist') / pl.col('avg_range_5d').clip(1.0, None)).alias('sl_vs_5d'),
])
df = df.with_columns([
    pl.when(pl.col('sl_vs_candle930') < 0.5).then(pl.lit('lt_50pct_of_930'))
    .when(pl.col('sl_vs_candle930') < 1.0).then(pl.lit('50-100pct'))
    .when(pl.col('sl_vs_candle930') < 1.5).then(pl.lit('100-150pct'))
    .otherwise(pl.lit('gt_150pct'))
    .alias('sl_vs_930_bucket'),

    pl.when(pl.col('sl_vs_on') < 0.05).then(pl.lit('lt_5pct'))
    .when(pl.col('sl_vs_on') < 0.10).then(pl.lit('5-10pct'))
    .when(pl.col('sl_vs_on') < 0.20).then(pl.lit('10-20pct'))
    .when(pl.col('sl_vs_on') < 0.40).then(pl.lit('20-40pct'))
    .otherwise(pl.lit('gt_40pct'))
    .alias('sl_vs_on_bucket'),
])

# E. HTF momentum
df = df.with_columns([
    ((pl.col('prev_close') - pl.col('close_5d_ago')) / pl.col('close_5d_ago') * 100).alias('mom_5d_pct'),
    ((pl.col('prev_close') - pl.col('close_20d_ago')) / pl.col('close_20d_ago') * 100).alias('mom_20d_pct'),
    ((pl.col('prev_close') - pl.col('low_20d')) / (pl.col('high_20d') - pl.col('low_20d')).clip(1.0, None)).alias('pos_in_20d_range'),
])
df = df.with_columns([
    pl.when(pl.col('mom_5d_pct') < -3).then(pl.lit('strong_down'))
    .when(pl.col('mom_5d_pct') < -1).then(pl.lit('weak_down'))
    .when(pl.col('mom_5d_pct') < 1).then(pl.lit('flat'))
    .when(pl.col('mom_5d_pct') < 3).then(pl.lit('weak_up'))
    .otherwise(pl.lit('strong_up'))
    .alias('mom_5d_bucket'),

    pl.when(pl.col('mom_20d_pct') < -5).then(pl.lit('strong_down'))
    .when(pl.col('mom_20d_pct') < -2).then(pl.lit('weak_down'))
    .when(pl.col('mom_20d_pct') < 2).then(pl.lit('flat'))
    .when(pl.col('mom_20d_pct') < 5).then(pl.lit('weak_up'))
    .otherwise(pl.lit('strong_up'))
    .alias('mom_20d_bucket'),

    pl.when(pl.col('pos_in_20d_range') < 0.2).then(pl.lit('near_20d_low'))
    .when(pl.col('pos_in_20d_range') < 0.4).then(pl.lit('lower_mid'))
    .when(pl.col('pos_in_20d_range') < 0.6).then(pl.lit('middle'))
    .when(pl.col('pos_in_20d_range') < 0.8).then(pl.lit('upper_mid'))
    .otherwise(pl.lit('near_20d_high'))
    .alias('pos_20d_bucket'),
])

# Does trade direction match 5d/20d momentum?
df = df.with_columns([
    (((pl.col('direction') == 'long') & (pl.col('mom_5d_pct') > 1))
     | ((pl.col('direction') == 'short') & (pl.col('mom_5d_pct') < -1))).alias('match_5d_mom'),
    (((pl.col('direction') == 'long') & (pl.col('mom_20d_pct') > 2))
     | ((pl.col('direction') == 'short') & (pl.col('mom_20d_pct') < -2))).alias('match_20d_mom'),
])

print(f'after feature derivation: cols={len(df.columns)}')

FEATURES = [
    # A. FVG quality
    'fvg_age_bucket', 'fvg_size_bucket', 'entry_pos_bucket', 'fvg_direction',
    # B. Sequence
    'signal_seq_bucket', 'has_prior_win', 'has_prior_loss',
    # C. Pre-entry
    'entry_offset_bucket', 'entry_with_open_bias',
    # D. Vol ladder
    'sl_vs_930_bucket', 'sl_vs_on_bucket',
    # E. HTF momentum
    'mom_5d_bucket', 'mom_20d_bucket', 'pos_20d_bucket',
    'match_5d_mom', 'match_20d_mom',
]

base_is = df.filter(~pl.col('is_oos'))[TARGET].mean()
base_oos = df.filter(pl.col('is_oos'))[TARGET].mean()
print(f'\nBase rates IS={base_is:.4f} OOS={base_oos:.4f}')


def scan(name: str) -> list[dict]:
    rows = []
    for val in df[name].unique().to_list():
        if val is None:
            continue
        sub = df.filter(pl.col(name) == val)
        is_sub = sub.filter(~pl.col('is_oos'))
        oos_sub = sub.filter(pl.col('is_oos'))
        n_is, n_oos = is_sub.height, oos_sub.height
        if n_is < 30 or n_oos < 30:
            continue
        r_is = is_sub[TARGET].mean()
        r_oos = oos_sub[TARGET].mean()
        if r_is is None or r_oos is None:
            continue
        rows.append({
            'feature': name, 'value': str(val),
            'n_is': n_is, 'r_is': r_is, 'lift_is_pp': (r_is - base_is) * 100,
            'n_oos': n_oos, 'r_oos': r_oos, 'lift_oos_pp': (r_oos - base_oos) * 100,
            'n_total': n_is + n_oos,
            'score': (r_is - base_is) * 100 * math.sqrt(min(n_is, n_oos)),
        })
    return rows


all_rows = []
for f in FEATURES:
    all_rows.extend(scan(f))

ranked = pl.DataFrame(all_rows).sort('score', descending=True)
ranked.write_csv(OUT / 'single_feature_ranked.csv')

# Strict survivors: lift >= 3pp BOTH eras, n>=50 each
strict = ranked.filter(
    (pl.col('lift_is_pp') >= 3) & (pl.col('lift_oos_pp') >= 3)
    & (pl.col('n_is') >= 50) & (pl.col('n_oos') >= 50)
).sort('score', descending=True)
strict.write_csv(OUT / 'survivors_strict.csv')

# Anti
anti = ranked.filter(
    (pl.col('lift_is_pp') <= -3) & (pl.col('lift_oos_pp') <= -3)
    & (pl.col('n_is') >= 50) & (pl.col('n_oos') >= 50)
).sort('score')
anti.write_csv(OUT / 'anti_survivors.csv')

print(f'\nStrict survivors: {strict.height}')
print(strict.head(20).to_pandas().to_string(index=False))
print(f'\nAnti-survivors: {anti.height}')
if anti.height:
    print(anti.head(20).to_pandas().to_string(index=False))

# ---- Cross with v1 winner: n_targets_in_dir == 2 ----
# Reload v1 feature matrix to get n_targets_in_dir_bucket
fm_v1 = pl.read_parquet(ROOT / 'studies/discovery_2R_hits/results/feature_matrix.parquet')
df_x = df.join(fm_v1.select(['timestamp', 'n_targets_in_dir_bucket', 'range_regime', 'gap_bucket']), on='timestamp', how='left')

# For each new survivor, test stacked with n_targets==2 (only when n>=50 both eras)
stack_rows = []
hit_arr = df_x[TARGET].to_numpy()
is_arr = (~df_x['is_oos']).to_numpy()
oos_arr = df_x['is_oos'].to_numpy()
n_targets_2 = (df_x['n_targets_in_dir_bucket'].cast(pl.Utf8) == '2').to_numpy()

for r in strict.iter_rows(named=True):
    feat, val = r['feature'], r['value']
    m_feat = (df_x[feat].cast(pl.Utf8) == val).to_numpy()
    m = m_feat & n_targets_2
    n_is = int((m & is_arr).sum())
    n_oos = int((m & oos_arr).sum())
    if n_is < 30 or n_oos < 30:
        continue
    r_is = float(hit_arr[m & is_arr].mean())
    r_oos = float(hit_arr[m & oos_arr].mean())
    stack_rows.append({
        'stack': f'n_targets==2 & {feat}=={val}',
        'n_is': n_is, 'r_is': r_is, 'lift_is_pp': (r_is - base_is) * 100,
        'n_oos': n_oos, 'r_oos': r_oos, 'lift_oos_pp': (r_oos - base_oos) * 100,
        'score': (r_is - base_is) * 100 * math.sqrt(min(n_is, n_oos)),
    })

if stack_rows:
    stack_df = pl.DataFrame(stack_rows).sort('score', descending=True)
    stack_df.write_csv(OUT / 'stack_with_n_targets_2.csv')
    print(f'\nStacks with n_targets==2 (n>=30 each):')
    print(stack_df.head(15).to_pandas().to_string(index=False))

# Save full feature matrix
keep = ['timestamp', 'date', 'year', 'is_oos', 'variant', 'direction', TARGET] + FEATURES
df.select(keep).write_parquet(OUT / 'feature_matrix_v2.parquet')
print('\nDone.')
