"""
v3 — focused checks on:
  1. HTF FVG nesting: does the trade entry sit inside a same-direction HTF FVG (15m/1H/4H/Daily)?
  2. Distance to nearest target-in-direction in R-units (continuous)
  3. Trade direction × momentum (longs on up-momentum days, shorts on down)
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / 'results_v3'
OUT.mkdir(exist_ok=True)

trades = pl.read_csv(ROOT / 'studies/baseline/results/trades.csv', try_parse_dates=True).filter(pl.col('outcome') != 'skip')
levels = pl.read_csv(ROOT / 'data/levels/liquidity_levels.csv', try_parse_dates=True)
days = pl.read_csv(ROOT / 'data/trading_days/trading_days.csv', try_parse_dates=True).sort('date')

# Day-level momentum
days = days.with_columns([
    pl.col('rth_close').shift(1).alias('prev_close'),
    pl.col('rth_close').shift(5).alias('close_5d_ago'),
])
days = days.with_columns(
    ((pl.col('prev_close') - pl.col('close_5d_ago')) / pl.col('close_5d_ago') * 100).alias('mom_5d_pct')
)

trades = trades.with_columns([
    pl.col('timestamp').dt.date().alias('date'),
    (pl.col('timestamp').dt.year() >= 2024).alias('is_oos'),
    pl.col('timestamp').dt.year().alias('year'),
])
df = trades.join(days.select(['date', 'mom_5d_pct']), on='date', how='left')

# ---- 1. HTF FVG nesting ----
# For each trade, check if entry_price is INSIDE a same-direction HTF FVG (for any TF).
# An HTF FVG has fvg_top/fvg_bottom in the levels file. Filter HTF entries:
htf = levels.filter(pl.col('group').str.starts_with('htf_'))
# Each row has timeframe (15m/1H/4H/Daily), fvg_direction, fvg_top, fvg_bottom, date
htf = htf.select(['date', 'timeframe', 'fvg_direction', 'fvg_top', 'fvg_bottom']).filter(
    pl.col('fvg_top').is_not_null() & pl.col('fvg_bottom').is_not_null()
)

# For each trade, look up HTF FVGs for that date. Check inside-ness vs direction.
# Build a grouped dict for speed
print('Building HTF lookup...')
htf_by_date: dict = {}
for r in htf.iter_rows(named=True):
    d = r['date']
    htf_by_date.setdefault(d, []).append((r['timeframe'], r['fvg_direction'], r['fvg_top'], r['fvg_bottom']))

# direction match: long entry inside a 'bullish' HTF FVG, short inside a 'bearish' HTF FVG
print('Computing nesting features...')
entry = df['entry_price'].to_numpy()
direction = df['direction'].to_numpy()
dates = df['date'].to_numpy()

nesting_flags: dict[str, np.ndarray] = {
    'nested_15m': np.zeros(df.height, dtype=bool),
    'nested_1H': np.zeros(df.height, dtype=bool),
    'nested_4H': np.zeros(df.height, dtype=bool),
    'nested_Daily': np.zeros(df.height, dtype=bool),
    'nested_any_htf': np.zeros(df.height, dtype=bool),
    'nested_count': np.zeros(df.height, dtype=np.int32),
}

for i in range(df.height):
    fvgs = htf_by_date.get(dates[i], [])
    if not fvgs:
        continue
    want_dir = 'bullish' if direction[i] == 'long' else 'bearish'
    cnt = 0
    for (tf, fd, top, bottom) in fvgs:
        if fd != want_dir:
            continue
        if bottom <= entry[i] <= top:
            nesting_flags[f'nested_{tf}'][i] = True
            nesting_flags['nested_any_htf'][i] = True
            cnt += 1
    nesting_flags['nested_count'][i] = cnt

for k, v in nesting_flags.items():
    df = df.with_columns(pl.Series(k, v))

df = df.with_columns([
    pl.when(pl.col('nested_count') == 0).then(pl.lit('0'))
    .when(pl.col('nested_count') == 1).then(pl.lit('1'))
    .when(pl.col('nested_count') == 2).then(pl.lit('2'))
    .otherwise(pl.lit('3+'))
    .alias('nested_count_bucket')
])

# ---- 2. Nearest target in R ----
# Reload v1 feature matrix to get n_targets_in_dir_bucket as cross-ref
fm_v1 = pl.read_parquet(ROOT / 'studies/discovery_2R_hits/results/feature_matrix.parquet')

# Compute nearest target distance in R for each trade
ALWAYS_ON = [
    'prev_day_high', 'prev_day_low', 'asia_high', 'asia_low',
    'london_high', 'london_low', '6am_high', '6am_low',
    'overnight_high', 'overnight_low', 'nwog_high', 'nwog_low',
    'bsl_level', 'ssl_level', 'poc', 'vah', 'val',
]
# Pivot non-HTF levels wide
core = levels.filter(~pl.col('group').str.starts_with('htf_'))
core_wide = core.select(['date', 'level_name', 'price']).pivot(
    values='price', index='date', on='level_name', aggregate_function='first'
)
df = df.join(core_wide, on='date', how='left')

# Compute signed R-distance to each level for trade-direction "ahead" of entry
sl_arr = df['sl_dist'].to_numpy()
is_long = (df['direction'].to_numpy() == 'long')
nearest_R_ahead = np.full(df.height, np.nan)
for name in ALWAYS_ON:
    if name not in df.columns:
        continue
    lvl = df[name].to_numpy(allow_copy=True).astype(float)
    diff = lvl - df['entry_price'].to_numpy()
    r_signed = np.where(is_long, diff, -diff) / sl_arr
    # Only consider levels at least 0.25R ahead (positive r_signed)
    cand = np.where(r_signed >= 0.25, r_signed, np.nan)
    nearest_R_ahead = np.nanmin(np.stack([nearest_R_ahead, cand]), axis=0)

df = df.with_columns(pl.Series('nearest_target_R_ahead', nearest_R_ahead))
df = df.with_columns(
    pl.when(pl.col('nearest_target_R_ahead').is_null()).then(pl.lit('none_ahead'))
    .when(pl.col('nearest_target_R_ahead') < 0.75).then(pl.lit('lt_0.75R'))
    .when(pl.col('nearest_target_R_ahead') < 1.25).then(pl.lit('0.75-1.25R'))
    .when(pl.col('nearest_target_R_ahead') < 2.0).then(pl.lit('1.25-2R'))
    .when(pl.col('nearest_target_R_ahead') < 3.0).then(pl.lit('2-3R'))
    .otherwise(pl.lit('gt_3R'))
    .alias('nearest_R_bucket')
)

# ---- 3. direction × 5d momentum ----
df = df.with_columns([
    (((pl.col('direction') == 'long') & (pl.col('mom_5d_pct') > 1))
     | ((pl.col('direction') == 'short') & (pl.col('mom_5d_pct') < -1))).alias('match_5d_momentum'),
    pl.when((pl.col('direction') == 'long') & (pl.col('mom_5d_pct') > 3)).then(pl.lit('long_strong_up'))
    .when((pl.col('direction') == 'short') & (pl.col('mom_5d_pct') < -3)).then(pl.lit('short_strong_down'))
    .when((pl.col('direction') == 'long') & (pl.col('mom_5d_pct') < -3)).then(pl.lit('long_strong_dn'))
    .when((pl.col('direction') == 'short') & (pl.col('mom_5d_pct') > 3)).then(pl.lit('short_strong_up'))
    .otherwise(pl.lit('other'))
    .alias('dir_x_5d_mom')
])

# ---- Scan ----
TARGET = 'hit_2_0R'
base_is = df.filter(~pl.col('is_oos'))[TARGET].mean()
base_oos = df.filter(pl.col('is_oos'))[TARGET].mean()
print(f'Base rates IS={base_is:.4f} OOS={base_oos:.4f}')

FEATURES = ['nested_15m', 'nested_1H', 'nested_4H', 'nested_Daily',
            'nested_any_htf', 'nested_count_bucket',
            'nearest_R_bucket', 'match_5d_momentum', 'dir_x_5d_mom']


def scan(name: str) -> list[dict]:
    rows = []
    for val in df[name].unique().to_list():
        if val is None:
            continue
        sub = df.filter(pl.col(name) == val)
        is_sub = sub.filter(~pl.col('is_oos'))
        oos_sub = sub.filter(pl.col('is_oos'))
        if is_sub.height < 30 or oos_sub.height < 30:
            continue
        r_is = is_sub[TARGET].mean()
        r_oos = oos_sub[TARGET].mean()
        rows.append({
            'feature': name, 'value': str(val),
            'n_is': is_sub.height, 'r_is': r_is, 'lift_is_pp': (r_is - base_is) * 100,
            'n_oos': oos_sub.height, 'r_oos': r_oos, 'lift_oos_pp': (r_oos - base_oos) * 100,
            'n_total': is_sub.height + oos_sub.height,
            'score': (r_is - base_is) * 100 * math.sqrt(min(is_sub.height, oos_sub.height)),
        })
    return rows


all_rows = []
for f in FEATURES:
    all_rows.extend(scan(f))

ranked = pl.DataFrame(all_rows).sort('score', descending=True)
ranked.write_csv(OUT / 'single_feature_ranked.csv')

print('\nFull ranked (n>=30 each era):')
print(ranked.to_pandas().to_string(index=False))

# ---- Stack each finding with v1's n_targets==2 ----
fm_v1 = fm_v1.select(['timestamp', 'n_targets_in_dir_bucket'])
dfx = df.join(fm_v1, on='timestamp', how='left')
hit = dfx[TARGET].to_numpy()
is_arr = (~dfx['is_oos']).to_numpy()
oos_arr = dfx['is_oos'].to_numpy()
n2 = (dfx['n_targets_in_dir_bucket'].cast(pl.Utf8) == '2').to_numpy()

stack_rows = []
for f in FEATURES:
    for val in dfx[f].unique().to_list():
        if val is None:
            continue
        m_feat = (dfx[f].cast(pl.Utf8) == str(val)).to_numpy()
        m = m_feat & n2
        n_is = int((m & is_arr).sum())
        n_oos = int((m & oos_arr).sum())
        if n_is < 30 or n_oos < 30:
            continue
        r_is = float(hit[m & is_arr].mean())
        r_oos = float(hit[m & oos_arr].mean())
        stack_rows.append({
            'stack': f'n_targets==2 & {f}=={val}',
            'n_is': n_is, 'r_is': r_is, 'lift_is_pp': (r_is - base_is) * 100,
            'n_oos': n_oos, 'r_oos': r_oos, 'lift_oos_pp': (r_oos - base_oos) * 100,
            'score': (r_is - base_is) * 100 * math.sqrt(min(n_is, n_oos)),
        })

if stack_rows:
    sdf = pl.DataFrame(stack_rows).sort('score', descending=True)
    sdf.write_csv(OUT / 'stack_with_n_targets_2.csv')
    print('\nStacks with n_targets==2 (sorted):')
    print(sdf.to_pandas().to_string(index=False))

# Save dfx for downstream inspection
dfx.write_parquet(OUT / 'dfx.parquet')
# Inspect the magic cohort
cohort = dfx.filter((pl.col('n_targets_in_dir_bucket').cast(pl.Utf8) == '2') & (pl.col('nearest_target_R_ahead') > 3))
print(f'\n=== MAGIC COHORT: n_targets==2 & nearest_R > 3R ===')
print(f'n={cohort.height}  hit_2R={cohort[TARGET].mean()*100:.1f}%')
print('\nVariant distribution:')
print(cohort['variant'].value_counts().sort('count', descending=True))
print('\nDirection:')
print(cohort['direction'].value_counts())
# Re-derive macro_window from the timestamp column
cohort = cohort.with_columns(
    (pl.col('timestamp').dt.hour().cast(pl.Int32) * 60 + pl.col('timestamp').dt.minute().cast(pl.Int32)).alias('mod')
)
cohort = cohort.with_columns(
    pl.when(pl.col('mod') < 585).then(pl.lit('M1'))
    .when(pl.col('mod') < 600).then(pl.lit('M2'))
    .when(pl.col('mod') < 615).then(pl.lit('M3'))
    .otherwise(pl.lit('M4')).alias('macro_window')
)
print('\nMacro window:')
print(cohort['macro_window'].value_counts().sort('count', descending=True))
print('\nYear-by-year:')
print(cohort.group_by('year').agg(pl.len().alias('n'), pl.col(TARGET).mean().alias('rate')).sort('year'))
cohort.write_csv(OUT / 'magic_cohort.csv')
print('\nDone.')
