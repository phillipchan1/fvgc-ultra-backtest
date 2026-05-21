"""
v4 — characterise the discovery from v3:
  The signal is "the only target levels ahead are from the daily volume profile
  (POC/VAH/VAL), with no session levels in the path."

Compute two separate counts:
  - n_session_targets_in_dir: count of session levels (non-VP, non-HTF) in 0.5-3R ahead
  - n_vp_targets_in_dir:      count of POC/VAH/VAL in 0.5-3R ahead

Then test all combinations and report year-by-year stability.
"""

from __future__ import annotations
import math
from pathlib import Path
import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / 'results_v4'
OUT.mkdir(exist_ok=True)

trades = pl.read_csv(ROOT / 'studies/baseline/results/trades.csv', try_parse_dates=True).filter(pl.col('outcome') != 'skip')
levels = pl.read_csv(ROOT / 'data/levels/liquidity_levels.csv', try_parse_dates=True)
vp = pl.read_csv(ROOT / 'data/levels/daily_volume_profile.csv', try_parse_dates=True)

trades = trades.with_columns([
    pl.col('timestamp').dt.date().alias('date'),
    pl.col('timestamp').dt.year().alias('year'),
    (pl.col('timestamp').dt.year() >= 2024).alias('is_oos'),
    (pl.col('timestamp').dt.hour().cast(pl.Int32) * 60
     + pl.col('timestamp').dt.minute().cast(pl.Int32)).alias('mod'),
])

# Pivot session levels (non-HTF) wide
core = levels.filter(~pl.col('group').str.starts_with('htf_'))
core_wide = core.select(['date', 'level_name', 'price']).pivot(
    values='price', index='date', on='level_name', aggregate_function='first'
)
df = trades.join(core_wide, on='date', how='left').join(vp, on='date', how='left')

SESSION_LEVELS = ['prev_day_high', 'prev_day_low', 'asia_high', 'asia_low',
                  'london_high', 'london_low', '6am_high', '6am_low',
                  'overnight_high', 'overnight_low', 'nwog_high', 'nwog_low',
                  'bsl_level', 'ssl_level']
OR_LEVELS = ['or_high', 'or_low']
VP_LEVELS = ['poc', 'vah', 'val']

sl = df['sl_dist'].to_numpy()
is_long = (df['direction'].to_numpy() == 'long')
ep = df['entry_price'].to_numpy()
mod = df['mod'].to_numpy()


def count_targets(level_names, mask_pre_945: bool = False) -> np.ndarray:
    """count levels with r_signed in [0.5, 3.0] (ahead in trade direction)"""
    n = np.zeros(df.height, dtype=np.int32)
    for name in level_names:
        if name not in df.columns:
            continue
        lvl = df[name].to_numpy().astype(float)
        if mask_pre_945:
            lvl = np.where(mod < 585, np.nan, lvl)
        diff = lvl - ep
        r_signed = np.where(is_long, diff, -diff) / sl
        with np.errstate(invalid='ignore'):
            m = (r_signed >= 0.5) & (r_signed <= 3.0)
        n += m.astype(np.int32)
    return n


def count_behind(level_names) -> np.ndarray:
    """count levels with r_signed < 0 (behind entry — supports for longs, resistances for shorts)"""
    n = np.zeros(df.height, dtype=np.int32)
    for name in level_names:
        if name not in df.columns:
            continue
        lvl = df[name].to_numpy().astype(float)
        diff = lvl - ep
        r_signed = np.where(is_long, diff, -diff) / sl
        with np.errstate(invalid='ignore'):
            m = r_signed < 0
        n += m.astype(np.int32)
    return n


df = df.with_columns([
    pl.Series('n_session_targets', count_targets(SESSION_LEVELS)),
    pl.Series('n_or_targets', count_targets(OR_LEVELS, mask_pre_945=True)),
    pl.Series('n_vp_targets', count_targets(VP_LEVELS)),
    pl.Series('n_session_behind', count_behind(SESSION_LEVELS)),
])
df = df.with_columns(
    (pl.col('n_session_targets') + pl.col('n_or_targets') + pl.col('n_vp_targets')).alias('n_all_targets')
)

# Define the candidate composite: "VP-only target zone"
df = df.with_columns(
    ((pl.col('n_session_targets') == 0) & (pl.col('n_or_targets') == 0) & (pl.col('n_vp_targets') >= 1)).alias('vp_only_target'),
)

print('=== Baseline ===')
TARGET = 'hit_2_0R'
base = df[TARGET].mean()
base_is = df.filter(~pl.col('is_oos'))[TARGET].mean()
base_oos = df.filter(pl.col('is_oos'))[TARGET].mean()
print(f'all n={df.height}  hit_2R={base*100:.1f}%  (IS={base_is*100:.1f}%, OOS={base_oos*100:.1f}%)')


def cell(label, mask_expr, frame=df):
    sub = frame.filter(mask_expr)
    is_sub = sub.filter(~pl.col('is_oos'))
    oos_sub = sub.filter(pl.col('is_oos'))
    n = sub.height
    r = sub[TARGET].mean() if n else float('nan')
    n_i = is_sub.height
    r_i = is_sub[TARGET].mean() if n_i else float('nan')
    n_o = oos_sub.height
    r_o = oos_sub[TARGET].mean() if n_o else float('nan')
    print(f'  {label:55s}  n={n:5d}  hit_2R={r*100:5.1f}%   IS:{n_i:5d}/{r_i*100:5.1f}%   OOS:{n_o:5d}/{r_o*100:5.1f}%')


print('\n=== Single-feature ===')
cell('vp_only_target=True (VP is the ONLY target ahead)', pl.col('vp_only_target') == True)
cell('vp_only_target=False (some session/OR also ahead)', pl.col('vp_only_target') == False)
cell('n_vp_targets >= 2 (multi-VP magnet)', pl.col('n_vp_targets') >= 2)
cell('n_vp_targets == 1', pl.col('n_vp_targets') == 1)
cell('n_vp_targets == 0', pl.col('n_vp_targets') == 0)
cell('n_session_targets == 0 (no session ahead)', pl.col('n_session_targets') == 0)
cell('n_session_targets >= 1', pl.col('n_session_targets') >= 1)
cell('n_all_targets == 0 (NOTHING ahead)', pl.col('n_all_targets') == 0)

print('\n=== Stacks ===')
cell('vp_only_target=True AND variant==bos', (pl.col('vp_only_target') == True) & (pl.col('variant') == 'bos'))
cell('vp_only_target=True AND variant==no_fvg', (pl.col('vp_only_target') == True) & (pl.col('variant') == 'no_fvg'))
cell('vp_only_target=True AND direction==long', (pl.col('vp_only_target') == True) & (pl.col('direction') == 'long'))
cell('vp_only_target=True AND direction==short', (pl.col('vp_only_target') == True) & (pl.col('direction') == 'short'))
cell('vp_only_target=True AND n_vp_targets>=2', (pl.col('vp_only_target') == True) & (pl.col('n_vp_targets') >= 2))
cell('vp_only_target=True AND n_session_behind>=5', (pl.col('vp_only_target') == True) & (pl.col('n_session_behind') >= 5))

print('\n=== Year-by-year for vp_only_target=True ===')
sub = df.filter(pl.col('vp_only_target') == True)
print(sub.group_by('year').agg(pl.len().alias('n'), pl.col(TARGET).mean().alias('hit_2R')).sort('year').to_pandas().to_string(index=False))

# Compare vs the n_targets==2 cohort
print('\n=== Cross with v1\'s n_targets==2 ===')
fm_v1 = pl.read_parquet(ROOT / 'studies/discovery_2R_hits/results/feature_matrix.parquet')
dfx = df.join(fm_v1.select(['timestamp', 'n_targets_in_dir_bucket']), on='timestamp', how='left')
cell('n_targets==2', pl.col('n_targets_in_dir_bucket').cast(pl.Utf8) == '2', frame=dfx)
cell('n_targets==2 AND vp_only_target', (pl.col('n_targets_in_dir_bucket').cast(pl.Utf8) == '2') & (pl.col('vp_only_target') == True), frame=dfx)
cell('n_targets==2 AND NOT vp_only_target', (pl.col('n_targets_in_dir_bucket').cast(pl.Utf8) == '2') & (pl.col('vp_only_target') == False), frame=dfx)

# Save feature-matrix
keep = ['timestamp', 'date', 'year', 'is_oos', 'direction', 'variant', 'sl_dist', TARGET,
        'n_session_targets', 'n_or_targets', 'n_vp_targets', 'n_all_targets',
        'n_session_behind', 'vp_only_target']
df.select(keep).write_parquet(OUT / 'feature_matrix_v4.parquet')
print('\nDone.')
