"""
Feature discovery: which conditions predict trades reaching >=2R on the 30s baseline?

Methodology:
  - IS: 2018-2023 (full years). OOS: 2024-2026.
  - Era base rates: IS ~38%, OOS ~45% (HEAD).
  - Lift is measured against the matching era's base rate.
  - Single-feature buckets reported only if n>=50 in both IS and OOS and IS lift >= 3pp.
  - Survivors must also hold (lift >= 3pp) in OOS.
  - Year-by-year stability table for top survivors.
  - Ranking score: lift_pp_IS * sqrt(min(n_IS, n_OOS)).
  - Confluence stacks (2/3 features) only tested on survivors; require n_IS+OOS >= 100 total.

Outputs:
  results/feature_matrix.parquet  -- engineered trade-level features
  results/single_feature_ranked.csv  -- all single-feature buckets ranked
  results/survivors_yearly.csv  -- year-by-year for survivors
  results/stack_results.csv  -- confluence stacks
"""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path

import numpy as np
import polars as pl

# Target column can be overridden: python run.py hit_1_5R  (default: hit_2_0R)
TARGET = sys.argv[1] if len(sys.argv) > 1 else 'hit_2_0R'
ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
OUT = HERE / ('results' if TARGET == 'hit_2_0R' else f'results_{TARGET}')
OUT.mkdir(exist_ok=True)
print(f'TARGET={TARGET}  OUT={OUT}')

IS_YEARS = list(range(2018, 2024))   # 2018..2023
OOS_YEARS = [2024, 2025, 2026]


# ============================================================
# Load data
# ============================================================
print('Loading data...')
trades = pl.read_csv(ROOT / 'studies/baseline/results/trades.csv', try_parse_dates=True)
days = pl.read_csv(ROOT / 'data/trading_days/trading_days.csv', try_parse_dates=True)
levels = pl.read_csv(ROOT / 'data/levels/liquidity_levels.csv', try_parse_dates=True)
vp = pl.read_csv(ROOT / 'data/levels/daily_volume_profile.csv', try_parse_dates=True)

print(f'  trades raw={trades.height}  days={days.height}  levels={levels.height}  vp={vp.height}')

# Drop skip rows (signals filtered out by playbook rules — no executed trade, null hit_2_0R)
trades = trades.filter(pl.col('outcome') != 'skip')
print(f'  trades after skip filter: {trades.height}')

# ============================================================
# Day-level pre-compute: ATH (rolling all-time-prior), 5d rth_range avg
# ============================================================
days = days.sort('date')
days = days.with_columns([
    pl.col('rth_high').cum_max().shift(1).alias('ath_prior'),
    pl.col('rth_range').shift(1).rolling_mean(window_size=5).alias('rth_range_5d_avg'),
])

# ============================================================
# Pivot non-HTF levels to wide table (one row per date)
# ============================================================
core = levels.filter(~pl.col('group').str.starts_with('htf_'))
# Keep one price per (date, level_name) -- they're already unique by construction
core_wide = (
    core.select(['date', 'level_name', 'price'])
    .pivot(values='price', index='date', on='level_name', aggregate_function='first')
)
print(f'  core_wide cols={len(core_wide.columns)}')

days = days.join(core_wide, on='date', how='left').join(vp, on='date', how='left')

# ============================================================
# HTF FVG: number of FVGs whose mid is within 1R of entry
# Will be computed per-trade further down. Index by date.
# ============================================================
htf = levels.filter(pl.col('group').str.starts_with('htf_'))
# Keep only the mid (use price; available for both bullish/bearish HTF FVG entries).
htf_per_day = htf.select(['date', 'price'])

# ============================================================
# Join trades to days
# ============================================================
trades = trades.with_columns([
    pl.col('timestamp').dt.date().alias('date'),
    pl.col('timestamp').dt.year().alias('year'),
    (pl.col('timestamp').dt.year() >= 2024).alias('is_oos'),
    (pl.col('timestamp').dt.hour().cast(pl.Int32) * 60
     + pl.col('timestamp').dt.minute().cast(pl.Int32)).alias('mod'),
])

df = trades.join(days, on='date', how='left')
print(f'  after join: rows={df.height} cols={len(df.columns)}')

# ============================================================
# Derived features
# ============================================================
# Time-of-day
df = df.with_columns([
    pl.when(pl.col('mod') < 585).then(pl.lit('M1'))
    .when(pl.col('mod') < 600).then(pl.lit('M2'))
    .when(pl.col('mod') < 615).then(pl.lit('M3'))
    .otherwise(pl.lit('M4'))
    .alias('macro_window'),

    pl.when(pl.col('mod') < 575).then(pl.lit('A_9:30-9:35'))
    .when(pl.col('mod') < 585).then(pl.lit('B_9:35-9:45'))
    .when(pl.col('mod') < 600).then(pl.lit('C_9:45-10:00'))
    .when(pl.col('mod') < 615).then(pl.lit('D_10:00-10:15'))
    .otherwise(pl.lit('E_10:15+'))
    .alias('entry_bucket'),
])

# sl_dist quartiles
qs = df['sl_dist'].quantile(0.25), df['sl_dist'].quantile(0.5), df['sl_dist'].quantile(0.75)
df = df.with_columns(
    pl.when(pl.col('sl_dist') < qs[0]).then(pl.lit('Q1_small'))
    .when(pl.col('sl_dist') < qs[1]).then(pl.lit('Q2'))
    .when(pl.col('sl_dist') < qs[2]).then(pl.lit('Q3'))
    .otherwise(pl.lit('Q4_large'))
    .alias('sl_dist_bucket')
)

# Direction-match flags
df = df.with_columns([
    (((pl.col('direction') == 'long') & (pl.col('overnight_direction') == 'up'))
     | ((pl.col('direction') == 'short') & (pl.col('overnight_direction') == 'down'))).alias('match_on_dir'),

    (((pl.col('direction') == 'long') & (pl.col('candle_930_direction') == 'up'))
     | ((pl.col('direction') == 'short') & (pl.col('candle_930_direction') == 'down'))).alias('match_930_dir'),

    (((pl.col('direction') == 'long') & (pl.col('gap_from_prior_close') > 0))
     | ((pl.col('direction') == 'short') & (pl.col('gap_from_prior_close') < 0))).alias('match_gap_dir'),
])

# Gap bucket (pts)
df = df.with_columns(
    pl.when(pl.col('gap_from_prior_close').abs() < 5).then(pl.lit('flat'))
    .when((pl.col('gap_from_prior_close') >= 5) & (pl.col('gap_from_prior_close') < 25)).then(pl.lit('small_up'))
    .when(pl.col('gap_from_prior_close') >= 25).then(pl.lit('large_up'))
    .when((pl.col('gap_from_prior_close') <= -5) & (pl.col('gap_from_prior_close') > -25)).then(pl.lit('small_dn'))
    .when(pl.col('gap_from_prior_close') <= -25).then(pl.lit('large_dn'))
    .otherwise(pl.lit('flat'))
    .alias('gap_bucket')
)

# OR break states at entry: 5/15/45 min ORs
for tag in ('5min', '15min', '45min'):
    df = df.with_columns(
        pl.when(pl.col(f'or_{tag}_high').is_null()).then(pl.lit('na'))
        .when(pl.col('entry_price') > pl.col(f'or_{tag}_high')).then(pl.lit('above'))
        .when(pl.col('entry_price') < pl.col(f'or_{tag}_low')).then(pl.lit('below'))
        .otherwise(pl.lit('inside'))
        .alias(f'or_{tag}_state')
    )

# Distance from ATH (entry_price - ath_prior, in pts) and bucket
df = df.with_columns([
    (pl.col('entry_price') - pl.col('ath_prior')).alias('ath_dist_pts'),
])
df = df.with_columns(
    pl.when(pl.col('ath_dist_pts').is_null()).then(pl.lit('na'))
    .when(pl.col('ath_dist_pts').abs() < 50).then(pl.lit('lt_50'))
    .when(pl.col('ath_dist_pts').abs() < 100).then(pl.lit('50-100'))
    .when(pl.col('ath_dist_pts').abs() < 200).then(pl.lit('100-200'))
    .when(pl.col('ath_dist_pts').abs() < 500).then(pl.lit('200-500'))
    .otherwise(pl.lit('gt_500'))
    .alias('ath_dist_bucket')
)

# 5-day range expansion (current rth_range vs 5d_avg)
df = df.with_columns(
    (pl.col('rth_range_5d_avg').is_not_null()).alias('_has_5d'),
)
df = df.with_columns(
    pl.when(~pl.col('_has_5d')).then(pl.lit('na'))
    .when(pl.col('rth_range') > pl.col('rth_range_5d_avg') * 1.25).then(pl.lit('expansion'))
    .when(pl.col('rth_range') < pl.col('rth_range_5d_avg') * 0.75).then(pl.lit('contraction'))
    .otherwise(pl.lit('normal'))
    .alias('range_regime')
).drop('_has_5d')

# Position in prior day's range — use prev_day_high/prev_day_low from levels
df = df.with_columns(
    ((pl.col('entry_price') - pl.col('prev_day_low'))
     / (pl.col('prev_day_high') - pl.col('prev_day_low')).clip(0.1, None)).alias('pdr_pos_raw')
)
df = df.with_columns(
    pl.when(pl.col('pdr_pos_raw').is_null()).then(pl.lit('na'))
    .when(pl.col('pdr_pos_raw') < 0).then(pl.lit('below_pdl'))
    .when(pl.col('pdr_pos_raw') < 0.25).then(pl.lit('lower_q'))
    .when(pl.col('pdr_pos_raw') < 0.5).then(pl.lit('lower_mid'))
    .when(pl.col('pdr_pos_raw') < 0.75).then(pl.lit('upper_mid'))
    .when(pl.col('pdr_pos_raw') <= 1.0).then(pl.lit('upper_q'))
    .otherwise(pl.lit('above_pdh'))
    .alias('pdr_position')
)

# ============================================================
# Liquidity-level features
# Curated list of "core" session levels + daily volume profile points.
# OR_15min levels (or_high/or_low from levels file) only valid for entries >= 9:45.
# ============================================================
ALWAYS_ON = [
    'prev_day_high', 'prev_day_low',
    'asia_high', 'asia_low',
    'london_high', 'london_low',
    '6am_high', '6am_low',
    'overnight_high', 'overnight_low',
    'nwog_high', 'nwog_low',
    'bsl_level', 'ssl_level',
    'poc', 'vah', 'val',
]
AT_945 = ['or_high', 'or_low']

# Verify all columns are present
missing = [c for c in ALWAYS_ON + AT_945 if c not in df.columns]
if missing:
    raise RuntimeError(f'Missing level columns: {missing}')

# Compute level features in pandas-like fashion via polars expressions
entry = df['entry_price'].to_numpy()
sl_dist = df['sl_dist'].to_numpy()
direction = df['direction'].to_numpy()
mod = df['mod'].to_numpy()

# Gather level price columns into a (n_trades, n_levels) array
def col_arr(name: str) -> np.ndarray:
    return df[name].to_numpy()

lvl_names: list[str] = []
lvl_prices: list[np.ndarray] = []
for n in ALWAYS_ON:
    lvl_names.append(n)
    lvl_prices.append(col_arr(n))
for n in AT_945:
    arr = col_arr(n).astype(float)
    # Mask out levels for entries before 9:45 (mod < 585)
    arr = np.where(mod < 585, np.nan, arr)
    lvl_names.append(n)
    lvl_prices.append(arr)

L = np.column_stack(lvl_prices).astype(float)  # (n, n_levels)
diff = L - entry[:, None]                       # +ve = above entry
abs_diff = np.abs(diff)
# r-units (distance / sl_dist)
r_units = abs_diff / sl_dist[:, None]

# Min abs distance (R-units) -- ignore NaNs
nearest_r = np.nanmin(r_units, axis=1)
# Count levels within 1R
within_1R = np.nansum(r_units <= 1.0, axis=1)
# at-level: any level within 0.25R
at_level = (np.nanmin(r_units, axis=1) <= 0.25)
# target-level-in-direction: long & level above between 0.5R and 3R; short & level below between 0.5R and 3R
# diff > 0 means level is ABOVE entry
is_long = (direction == 'long')[:, None]
r_signed = np.where(is_long, diff, -diff) / sl_dist[:, None]   # +ve means level is in the trade direction
target_mask = (r_signed >= 0.5) & (r_signed <= 3.0)
has_target_in_dir = np.nansum(target_mask, axis=1) > 0
n_targets_in_dir = np.nansum(target_mask, axis=1)

df = df.with_columns([
    pl.Series('nearest_lvl_R', nearest_r),
    pl.Series('lvls_within_1R', within_1R.astype(np.int32)),
    pl.Series('at_level_quarter_R', at_level),
    pl.Series('has_target_in_dir', has_target_in_dir),
    pl.Series('n_targets_in_dir', n_targets_in_dir.astype(np.int32)),
])

# HTF FVG confluence -- count of HTF FVG mids within 1R of entry
htf_grouped = htf_per_day.group_by('date').agg(pl.col('price').alias('htf_prices'))
df = df.join(htf_grouped, on='date', how='left')
# Manual count
htf_count = np.zeros(df.height, dtype=np.int32)
htf_lists = df['htf_prices'].to_list()
for i, prices in enumerate(htf_lists):
    if prices is None:
        continue
    cnt = 0
    for p in prices:
        if p is None or math.isnan(p):
            continue
        if abs(p - entry[i]) <= sl_dist[i]:
            cnt += 1
    htf_count[i] = cnt
df = df.with_columns(pl.Series('htf_fvg_within_1R', htf_count)).drop('htf_prices')

# Buckets for numeric continuous features
df = df.with_columns([
    pl.when(pl.col('lvls_within_1R') == 0).then(pl.lit('0'))
    .when(pl.col('lvls_within_1R') <= 2).then(pl.lit('1-2'))
    .when(pl.col('lvls_within_1R') <= 4).then(pl.lit('3-4'))
    .when(pl.col('lvls_within_1R') <= 6).then(pl.lit('5-6'))
    .otherwise(pl.lit('7+'))
    .alias('lvls_within_1R_bucket'),

    pl.when(pl.col('htf_fvg_within_1R') == 0).then(pl.lit('0'))
    .when(pl.col('htf_fvg_within_1R') <= 2).then(pl.lit('1-2'))
    .when(pl.col('htf_fvg_within_1R') <= 5).then(pl.lit('3-5'))
    .otherwise(pl.lit('6+'))
    .alias('htf_within_1R_bucket'),

    pl.when(pl.col('n_targets_in_dir') == 0).then(pl.lit('0'))
    .when(pl.col('n_targets_in_dir') == 1).then(pl.lit('1'))
    .when(pl.col('n_targets_in_dir') == 2).then(pl.lit('2'))
    .otherwise(pl.lit('3+'))
    .alias('n_targets_in_dir_bucket'),
])

# day_of_week as string
df = df.with_columns(pl.col('day_of_week_name').alias('dow'))

# Save feature matrix snapshot for inspection
keep_cols = [
    'timestamp', 'date', 'year', 'is_oos', 'direction', 'variant', 'sl_dist', TARGET,
    'macro_window', 'entry_bucket', 'sl_dist_bucket',
    'match_on_dir', 'match_930_dir', 'match_gap_dir',
    'gap_bucket', 'or_5min_state', 'or_15min_state', 'or_45min_state',
    'ath_dist_bucket', 'range_regime', 'pdr_position',
    'prior_day_type', 'vixy_regime', 'dow',
    'is_fomc_week', 'is_opex_week', 'is_month_start', 'is_month_end',
    'has_red_folder_news', 'has_pre_rth_news',
    'lvls_within_1R_bucket', 'htf_within_1R_bucket', 'n_targets_in_dir_bucket',
    'has_target_in_dir', 'at_level_quarter_R',
]
fm = df.select(keep_cols)
fm.write_parquet(OUT / 'feature_matrix.parquet')
print(f'feature matrix written: {fm.shape}')

# ============================================================
# Single-feature scan
# ============================================================
FEATURES = [
    # setup
    'variant', 'direction', 'sl_dist_bucket',
    # time-of-day
    'macro_window', 'entry_bucket',
    # direction match
    'match_on_dir', 'match_930_dir', 'match_gap_dir',
    # gap / OR
    'gap_bucket', 'or_5min_state', 'or_15min_state', 'or_45min_state',
    # range / structure
    'ath_dist_bucket', 'range_regime', 'pdr_position',
    'prior_day_type',
    # vol regime
    'vixy_regime',
    # calendar
    'dow', 'is_fomc_week', 'is_opex_week', 'is_month_start', 'is_month_end',
    'has_red_folder_news', 'has_pre_rth_news',
    # level features
    'lvls_within_1R_bucket', 'htf_within_1R_bucket', 'n_targets_in_dir_bucket',
    'has_target_in_dir', 'at_level_quarter_R',
]

# Compute base rates per era
base_is = df.filter(~pl.col('is_oos'))[TARGET].mean()
base_oos = df.filter(pl.col('is_oos'))[TARGET].mean()
base_all = df[TARGET].mean()
print(f'\nBase rates:  IS={base_is:.4f}  OOS={base_oos:.4f}  ALL={base_all:.4f}')


def cell_stats(sub: pl.DataFrame) -> tuple[int, float]:
    n = sub.height
    if n == 0:
        return 0, float('nan')
    return n, float(sub[TARGET].mean())


def scan_feature(name: str) -> list[dict]:
    rows = []
    for val in df[name].unique().to_list():
        if val is None:
            continue
        sub = df.filter(pl.col(name) == val)
        is_sub = sub.filter(~pl.col('is_oos'))
        oos_sub = sub.filter(pl.col('is_oos'))
        n_is, r_is = cell_stats(is_sub)
        n_oos, r_oos = cell_stats(oos_sub)
        if n_is < 20 or n_oos < 20:
            continue
        lift_is = (r_is - base_is) * 100
        lift_oos = (r_oos - base_oos) * 100
        rows.append({
            'feature': name,
            'value': str(val),
            'n_is': n_is, 'r_is': r_is, 'lift_is_pp': lift_is,
            'n_oos': n_oos, 'r_oos': r_oos, 'lift_oos_pp': lift_oos,
            'n_total': n_is + n_oos,
            'score': lift_is * math.sqrt(min(n_is, n_oos)),
        })
    return rows


all_rows = []
for feat in FEATURES:
    all_rows.extend(scan_feature(feat))

ranked = pl.DataFrame(all_rows).sort('score', descending=True)
ranked.write_csv(OUT / 'single_feature_ranked.csv')
print(f'\nSingle-feature scan: {ranked.height} buckets')

# STRICT survivors: lift >= 3pp BOTH eras, n>=50 BOTH
strict_survivors = ranked.filter(
    (pl.col('lift_is_pp') >= 3) & (pl.col('lift_oos_pp') >= 3)
    & (pl.col('n_is') >= 50) & (pl.col('n_oos') >= 50)
).sort('score', descending=True)
strict_survivors.write_csv(OUT / 'survivors_strict.csv')
print(f'  STRICT survivors (lift>=3pp both, n>=50 both): {strict_survivors.height}')

# LOOSE pool for stacking: lift_is >= 1.5 AND lift_oos >= 0 AND n>=80 both
# (or anti-inversions: lift_is <= -3 AND lift_oos <= -3 -- we'll negate the mask)
loose_survivors = ranked.filter(
    (pl.col('lift_is_pp') >= 1.5) & (pl.col('lift_oos_pp') >= 0)
    & (pl.col('n_is') >= 80) & (pl.col('n_oos') >= 80)
).sort('score', descending=True)
loose_survivors.write_csv(OUT / 'survivors_loose.csv')
print(f'  LOOSE pool (lift_is>=1.5, lift_oos>=0, n>=80 both): {loose_survivors.height}')

survivors = strict_survivors  # used for yearly tables below

# Anti-survivors (filters that HURT both eras) — useful for negative filter rules
anti = ranked.filter(
    (pl.col('lift_is_pp') <= -3) & (pl.col('lift_oos_pp') <= -3)
    & (pl.col('n_is') >= 50) & (pl.col('n_oos') >= 50)
).sort('score')
anti.write_csv(OUT / 'anti_survivors.csv')
print(f'  anti-survivors (BOTH eras hurt >=3pp): {anti.height}')

# ============================================================
# Year-by-year stability for top 20 survivors
# ============================================================
top = survivors.head(20)
yearly_rows = []
for r in top.iter_rows(named=True):
    feat, val = r['feature'], r['value']
    sub = df.filter(pl.col(feat).cast(pl.Utf8) == val)
    for y in sorted(df['year'].unique().to_list()):
        ss = sub.filter(pl.col('year') == y)
        if ss.height == 0:
            yearly_rows.append({'feature': feat, 'value': val, 'year': y, 'n': 0, 'r': None})
        else:
            yearly_rows.append({'feature': feat, 'value': val, 'year': y, 'n': ss.height, 'r': ss[TARGET].mean()})
yearly_df = pl.DataFrame(yearly_rows)
yearly_pivot = yearly_df.pivot(values='r', index=['feature', 'value'], on='year')
yearly_pivot.write_csv(OUT / 'survivors_yearly.csv')

# Year-by-year n
yearly_n = yearly_df.pivot(values='n', index=['feature', 'value'], on='year')
yearly_n.write_csv(OUT / 'survivors_yearly_n.csv')

# Per-variant survivor scan (the brief asked for this)
variant_rows = []
for variant_val in ['bos', 'ifvg', 'no_fvg', 'protected_swing']:
    dv = df.filter(pl.col('variant') == variant_val)
    if dv.height < 200:
        continue
    base_v_is = dv.filter(~pl.col('is_oos'))[TARGET].mean()
    base_v_oos = dv.filter(pl.col('is_oos'))[TARGET].mean()
    for feat in FEATURES:
        if feat == 'variant':
            continue
        for val in dv[feat].unique().to_list():
            if val is None:
                continue
            sub = dv.filter(pl.col(feat) == val)
            is_sub = sub.filter(~pl.col('is_oos'))
            oos_sub = sub.filter(pl.col('is_oos'))
            if is_sub.height < 30 or oos_sub.height < 30:
                continue
            r_is = is_sub[TARGET].mean()
            r_oos = oos_sub[TARGET].mean()
            lift_is = (r_is - base_v_is) * 100
            lift_oos = (r_oos - base_v_oos) * 100
            if lift_is < 3 or lift_oos < 3:
                continue
            variant_rows.append({
                'variant': variant_val,
                'feature': feat, 'value': str(val),
                'n_is': is_sub.height, 'r_is': r_is, 'lift_is_pp': lift_is,
                'n_oos': oos_sub.height, 'r_oos': r_oos, 'lift_oos_pp': lift_oos,
                'score': lift_is * math.sqrt(min(is_sub.height, oos_sub.height)),
            })

variant_ranked = pl.DataFrame(variant_rows).sort('score', descending=True) if variant_rows else pl.DataFrame()
if variant_ranked.height:
    variant_ranked.write_csv(OUT / 'variant_survivors.csv')
    print(f'  variant survivors: {variant_ranked.height}')

# ============================================================
# Confluence stacks (2-feature and 3-feature)
# Restrict pool to survivor feature/value pairs to keep search tractable.
# ============================================================
print('\nConfluence stack search (2-feature)...')
# Stack pool = loose survivors UNION inverse-of-anti-survivors (filter rules)
pool = [(r['feature'], r['value'], 'pos') for r in loose_survivors.iter_rows(named=True)]
# Also include negative filters: rows where BOTH eras lift <= -3 -> we want to EXCLUDE that value
anti_pool = ranked.filter(
    (pl.col('lift_is_pp') <= -3) & (pl.col('lift_oos_pp') <= -3)
    & (pl.col('n_is') >= 80) & (pl.col('n_oos') >= 80)
)
for r in anti_pool.iter_rows(named=True):
    pool.append((r['feature'], r['value'], 'neg'))
# Dedup: only one entry per (feature, value, polarity)
seen = set()
pool_u = []
for fv in pool:
    if fv in seen:
        continue
    seen.add(fv)
    pool_u.append(fv)
print(f'  pool size: {len(pool_u)} (positives + negatives)')

# Build boolean masks once. Positives: feature==value. Negatives: feature!=value.
masks = {}
for f, v, pol in pool_u:
    base_m = (df[f].cast(pl.Utf8) == v).to_numpy()
    masks[(f, v, pol)] = base_m if pol == 'pos' else ~base_m

is_mask = (~df['is_oos']).to_numpy()
oos_mask = df['is_oos'].to_numpy()
hit = df[TARGET].to_numpy()


def eval_mask(m: np.ndarray) -> dict:
    m_is = m & is_mask
    m_oos = m & oos_mask
    n_is = int(m_is.sum())
    n_oos = int(m_oos.sum())
    r_is = float(hit[m_is].mean()) if n_is else float('nan')
    r_oos = float(hit[m_oos].mean()) if n_oos else float('nan')
    return {'n_is': n_is, 'n_oos': n_oos, 'r_is': r_is, 'r_oos': r_oos,
            'lift_is_pp': (r_is - base_is) * 100, 'lift_oos_pp': (r_oos - base_oos) * 100}


def fv_label(fv: tuple[str, str, str]) -> str:
    f, v, pol = fv
    op = '==' if pol == 'pos' else '!='
    return f'{f}{op}{v}'


stack_rows = []
n = len(pool_u)
for i in range(n):
    for j in range(i + 1, n):
        f1, v1, p1 = pool_u[i]
        f2, v2, p2 = pool_u[j]
        if f1 == f2:
            continue
        m = masks[pool_u[i]] & masks[pool_u[j]]
        st = eval_mask(m)
        if st['n_is'] < 50 or st['n_oos'] < 50:
            continue
        if st['lift_is_pp'] < 5 or st['lift_oos_pp'] < 5:
            continue
        stack_rows.append({
            'features': f'{fv_label(pool_u[i])} & {fv_label(pool_u[j])}',
            **st,
            'score': st['lift_is_pp'] * math.sqrt(min(st['n_is'], st['n_oos'])),
        })

# Dedup: a stack is the same regardless of order. Hash by frozenset of fv labels.
def stack_key(features_str: str) -> frozenset[str]:
    return frozenset(features_str.split(' & '))


if stack_rows:
    seen_keys: set = set()
    deduped: list = []
    for r in sorted(stack_rows, key=lambda x: -x['score']):
        k = stack_key(r['features'])
        if k in seen_keys:
            continue
        seen_keys.add(k)
        deduped.append(r)
    stack_df = pl.DataFrame(deduped)
else:
    stack_df = pl.DataFrame()
if stack_df.height:
    stack_df.write_csv(OUT / 'stack_2feat.csv')
print(f'  2-feature stacks (lift>=5pp both, n>=50 both): {stack_df.height}')

# 3-feature: only from top 30 2-feature stacks
print('Confluence stack search (3-feature)...')
# Find top 2-pair INDICES rather than parsing strings
pair_results = []
for i in range(n):
    for j in range(i + 1, n):
        if pool_u[i][0] == pool_u[j][0]:
            continue
        m = masks[pool_u[i]] & masks[pool_u[j]]
        st = eval_mask(m)
        if st['n_is'] < 50 or st['n_oos'] < 50:
            continue
        if st['lift_is_pp'] < 5 or st['lift_oos_pp'] < 5:
            continue
        pair_results.append((i, j, st['lift_is_pp'] * math.sqrt(min(st['n_is'], st['n_oos']))))
pair_results.sort(key=lambda x: -x[2])

stack3_rows = []
for (i, j, _) in pair_results[:30]:
    f1 = pool_u[i][0]
    f2 = pool_u[j][0]
    m_pair = masks[pool_u[i]] & masks[pool_u[j]]
    for k, fv3 in enumerate(pool_u):
        if k in (i, j):
            continue
        if fv3[0] in (f1, f2):
            continue
        m = m_pair & masks[fv3]
        st = eval_mask(m)
        if st['n_is'] < 50 or st['n_oos'] < 50:
            continue
        if st['lift_is_pp'] < 8 or st['lift_oos_pp'] < 8:
            continue
        stack3_rows.append({
            'features': f'{fv_label(pool_u[i])} & {fv_label(pool_u[j])} & {fv_label(fv3)}',
            **st,
            'score': st['lift_is_pp'] * math.sqrt(min(st['n_is'], st['n_oos'])),
        })
if stack3_rows:
    seen_keys = set()
    deduped3 = []
    for r in sorted(stack3_rows, key=lambda x: -x['score']):
        k = stack_key(r['features'])
        if k in seen_keys:
            continue
        seen_keys.add(k)
        deduped3.append(r)
    stack3_df = pl.DataFrame(deduped3)
else:
    stack3_df = pl.DataFrame()
if stack3_df.height:
    stack3_df.write_csv(OUT / 'stack_3feat.csv')
print(f'  3-feature stacks (lift>=8pp both, n>=50 both): {stack3_df.height}')

# ============================================================
# Year-by-year stability for top stacks (the deliverable check)
# ============================================================
def parse_features(s: str) -> list[tuple[str, str, str]]:
    out = []
    for part in s.split(' & '):
        if '==' in part:
            f, v = part.split('==', 1)
            out.append((f, v, 'pos'))
        else:
            f, v = part.split('!=', 1)
            out.append((f, v, 'neg'))
    return out


def stack_mask(s: str) -> np.ndarray:
    m = np.ones(df.height, dtype=bool)
    for (f, v, pol) in parse_features(s):
        col = (df[f].cast(pl.Utf8) == v).to_numpy()
        m &= col if pol == 'pos' else ~col
    return m


# Year-by-year for the headline single-feature survivor + top 5 deduped stacks
year_rows = []
year_arr = df['year'].to_numpy()
years_sorted = sorted(set(year_arr.tolist()))


def yearly_for(label: str, m: np.ndarray):
    for y in years_sorted:
        sub_m = m & (year_arr == y)
        n = int(sub_m.sum())
        r = float(hit[sub_m].mean()) if n else float('nan')
        year_rows.append({'filter': label, 'year': y, 'n': n, 'r': r})


# Headline single survivor: n_targets_in_dir_bucket == 2
yearly_for('n_targets_in_dir_bucket==2', (df['n_targets_in_dir_bucket'].cast(pl.Utf8) == '2').to_numpy())
# Anti-survivor (the negative filter): n_targets==0
yearly_for('n_targets_in_dir_bucket==0', (df['n_targets_in_dir_bucket'].cast(pl.Utf8) == '0').to_numpy())
# Top stacks
top_stacks = []
if stack_df.height:
    top_stacks.extend(stack_df.head(5)['features'].to_list())
if stack3_df.height:
    top_stacks.extend(stack3_df.head(5)['features'].to_list())
for s in top_stacks:
    yearly_for(s, stack_mask(s))

yearly_top_df = pl.DataFrame(year_rows)
yearly_pivot = yearly_top_df.pivot(values='r', index='filter', on='year')
yearly_pivot.write_csv(OUT / 'top_filters_yearly_rate.csv')
yearly_pivot_n = yearly_top_df.pivot(values='n', index='filter', on='year')
yearly_pivot_n.write_csv(OUT / 'top_filters_yearly_n.csv')

print('\n=== Top filters year-by-year hit_2R ===')
print(yearly_pivot.to_pandas().to_string(index=False))
print('\n=== Top filters year-by-year n ===')
print(yearly_pivot_n.to_pandas().to_string(index=False))

# Print top of each for quick inspection
print('\n=== Top 15 survivors ===')
print(survivors.head(15).to_pandas().to_string(index=False))

if stack_df.height:
    print('\n=== Top 10 2-feature stacks ===')
    print(stack_df.head(10).to_pandas().to_string(index=False))

if stack3_df.height:
    print('\n=== Top 10 3-feature stacks ===')
    print(stack3_df.head(10).to_pandas().to_string(index=False))

print('\nDone.')
