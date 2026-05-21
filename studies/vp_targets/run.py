"""
Phase A — adversarial walk-forward of the n_vp_targets discovery.

Stricter split than the parent discovery study:
  IS  = 2018-2022 (~2,200 trades)
  OOS = 2023-2026 (~2,350 trades)

The bucket boundaries (0/1/2/>=3) are STRUCTURAL, not tuned. No threshold
selection touches OOS.

Outputs CSVs to studies/vp_targets/results/ and prints a verdict.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / 'results'
OUT.mkdir(parents=True, exist_ok=True)

IS_MAX_YEAR = 2022
OOS_MIN_YEAR = 2023
TARGET = 'hit_2_0R'
KILL_VP0_LIFT_FLOOR = 0.0   # n_vp==0 OOS hit_2R must stay BELOW OOS base by some margin
KILL_VP2P_LIFT_FLOOR = 10.0  # n_vp>=2 OOS lift must be >= +10pp
STALL_WINDOW_BARS = 240      # 30s bars — 2 hr forward walk for A3

# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------
trades = (
    pl.read_csv(ROOT / 'studies/baseline/results/trades.csv', try_parse_dates=True)
    .filter(pl.col('outcome') != 'skip')
)
vp = pl.read_csv(ROOT / 'data/levels/daily_volume_profile.csv', try_parse_dates=True)
fm_v1 = pl.read_parquet(ROOT / 'studies/discovery_2R_hits/results/feature_matrix.parquet')

trades = trades.with_columns([
    pl.col('timestamp').dt.date().alias('date'),
    pl.col('timestamp').dt.year().alias('year'),
])
trades = trades.with_columns([
    (pl.col('year') <= IS_MAX_YEAR).alias('is_in_is'),
    (pl.col('year') >= OOS_MIN_YEAR).alias('is_in_oos'),
])

df = trades.join(vp, on='date', how='left')

# ---------------------------------------------------------------------------
# Per-VP-level signed R-distance and the bucket variable
# ---------------------------------------------------------------------------
sl = df['sl_dist'].to_numpy()
is_long = (df['direction'].to_numpy() == 'long')
ep = df['entry_price'].to_numpy()


def r_signed(level_col: str) -> np.ndarray:
    lvl = df[level_col].to_numpy().astype(float)
    diff = lvl - ep
    return np.where(is_long, diff, -diff) / sl


r_poc = r_signed('poc')
r_vah = r_signed('vah')
r_val = r_signed('val')


def in_target_zone(rs: np.ndarray) -> np.ndarray:
    with np.errstate(invalid='ignore'):
        return (rs >= 0.5) & (rs <= 3.0)


poc_in = in_target_zone(r_poc)
vah_in = in_target_zone(r_vah)
val_in = in_target_zone(r_val)

df = df.with_columns([
    pl.Series('r_poc', r_poc),
    pl.Series('r_vah', r_vah),
    pl.Series('r_val', r_val),
    pl.Series('poc_in_dir', poc_in),
    pl.Series('vah_in_dir', vah_in),
    pl.Series('val_in_dir', val_in),
    pl.Series('n_vp_targets', poc_in.astype(np.int32) + vah_in.astype(np.int32) + val_in.astype(np.int32)),
])
df = df.with_columns(
    pl.when(pl.col('n_vp_targets') >= 3).then(pl.lit('3+'))
    .when(pl.col('n_vp_targets') == 2).then(pl.lit('2'))
    .when(pl.col('n_vp_targets') == 1).then(pl.lit('1'))
    .otherwise(pl.lit('0'))
    .alias('vp_bucket')
)

# Pull macro_window + vixy_regime from v1 feature matrix
df = df.join(
    fm_v1.select(['timestamp', 'macro_window', 'vixy_regime']),
    on='timestamp', how='left',
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def cell_rate(frame: pl.DataFrame) -> tuple[int, float | None]:
    n = frame.height
    r = frame[TARGET].mean() if n else None
    return n, r


def is_oos_split(frame: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame]:
    return frame.filter(pl.col('is_in_is')), frame.filter(pl.col('is_in_oos'))


is_base = df.filter(pl.col('is_in_is'))[TARGET].mean()
oos_base = df.filter(pl.col('is_in_oos'))[TARGET].mean()
pooled_base = df[TARGET].mean()

print('=' * 70)
print('Phase A — n_vp_targets walk-forward')
print('=' * 70)
print(f'n_total={df.height}  pooled_hit_2R={pooled_base*100:.1f}%')
print(f'IS  (year<={IS_MAX_YEAR})  n={df.filter(pl.col("is_in_is")).height}  base={is_base*100:.1f}%')
print(f'OOS (year>={OOS_MIN_YEAR}) n={df.filter(pl.col("is_in_oos")).height}  base={oos_base*100:.1f}%')
print()


# ---------------------------------------------------------------------------
# A1 — Walk-forward
# ---------------------------------------------------------------------------
rows = []
for label, expr in [
    ('0', pl.col('n_vp_targets') == 0),
    ('1', pl.col('n_vp_targets') == 1),
    ('2', pl.col('n_vp_targets') == 2),
    ('3+', pl.col('n_vp_targets') >= 3),
]:
    sub = df.filter(expr)
    sub_is, sub_oos = is_oos_split(sub)
    n_is, r_is = cell_rate(sub_is)
    n_oos, r_oos = cell_rate(sub_oos)
    rows.append({
        'bucket': label,
        'n_pooled': sub.height,
        'hit_2R_pooled': sub[TARGET].mean() if sub.height else None,
        'n_IS': n_is, 'hit_2R_IS': r_is,
        'lift_IS_pp': (r_is - is_base) * 100 if r_is is not None else None,
        'n_OOS': n_oos, 'hit_2R_OOS': r_oos,
        'lift_OOS_pp': (r_oos - oos_base) * 100 if r_oos is not None else None,
    })
wf = pl.DataFrame(rows)
wf.write_csv(OUT / 'walk_forward.csv')

print('--- A1: walk-forward ---')
print(wf.to_pandas().to_string(index=False))
print()

# Kill criteria
vp0 = wf.filter(pl.col('bucket') == '0').to_dicts()[0]
vp2p = wf.row(by_predicate=pl.col('bucket') == '3+', named=True)  # tail
vp2 = wf.filter(pl.col('bucket') == '2').to_dicts()[0]

# Combine n_vp >= 2 cohort (the "magnet" trade) for OOS lift
vp_ge2 = df.filter(pl.col('n_vp_targets') >= 2)
vp_ge2_is, vp_ge2_oos = is_oos_split(vp_ge2)
vp_ge2_oos_lift_pp = (vp_ge2_oos[TARGET].mean() - oos_base) * 100 if vp_ge2_oos.height else None
vp_ge2_is_lift_pp = (vp_ge2_is[TARGET].mean() - is_base) * 100 if vp_ge2_is.height else None
print(f'n_vp>=2 cohort  IS n={vp_ge2_is.height} lift={vp_ge2_is_lift_pp:+.2f}pp  OOS n={vp_ge2_oos.height} lift={vp_ge2_oos_lift_pp:+.2f}pp')

vp0_oos_hit = vp0['hit_2R_OOS']
vp0_oos_lift = vp0['lift_OOS_pp']

kill1 = vp0_oos_hit >= oos_base  # n_vp==0 reached/exceeded OOS base rate
kill2 = vp_ge2_oos_lift_pp < KILL_VP2P_LIFT_FLOOR

print()
print(f'Kill criterion 1 — n_vp==0 OOS hit_2R >= OOS base ({oos_base*100:.1f}%)?')
print(f'  n_vp==0 OOS hit_2R = {vp0_oos_hit*100:.1f}% (lift {vp0_oos_lift:+.2f}pp)  ->  {"TRIPPED" if kill1 else "OK"}')
print(f'Kill criterion 2 — n_vp>=2 OOS lift < +{KILL_VP2P_LIFT_FLOOR:.0f}pp?')
print(f'  n_vp>=2 OOS lift = {vp_ge2_oos_lift_pp:+.2f}pp  ->  {"TRIPPED" if kill2 else "OK"}')

walk_forward_verdict = 'PASS' if not (kill1 or kill2) else 'FAIL'
print(f'\nA1 verdict: {walk_forward_verdict}')
print()


# ---------------------------------------------------------------------------
# A2 — Per-VP-level decomposition
# ---------------------------------------------------------------------------
print('--- A2: per-VP-level decomposition ---')

a2_rows = []


def add_a2_row(label: str, frame: pl.DataFrame, direction: str = 'all') -> None:
    sub_is, sub_oos = is_oos_split(frame)
    n_is, r_is = cell_rate(sub_is)
    n_oos, r_oos = cell_rate(sub_oos)
    a2_rows.append({
        'filter': label,
        'direction': direction,
        'n_IS': n_is, 'hit_2R_IS': r_is,
        'lift_IS_pp': (r_is - is_base) * 100 if r_is is not None else None,
        'n_OOS': n_oos, 'hit_2R_OOS': r_oos,
        'lift_OOS_pp': (r_oos - oos_base) * 100 if r_oos is not None else None,
    })


# All trades
add_a2_row('poc_in_dir', df.filter(pl.col('poc_in_dir')))
add_a2_row('vah_in_dir', df.filter(pl.col('vah_in_dir')))
add_a2_row('val_in_dir', df.filter(pl.col('val_in_dir')))
add_a2_row('any_vp_in_dir', df.filter(pl.col('n_vp_targets') >= 1))
add_a2_row('no_vp_in_dir', df.filter(pl.col('n_vp_targets') == 0))

# By direction (long/short separately)
for dirn in ('long', 'short'):
    sub = df.filter(pl.col('direction') == dirn)
    add_a2_row('poc_in_dir', sub.filter(pl.col('poc_in_dir')), direction=dirn)
    add_a2_row('vah_in_dir', sub.filter(pl.col('vah_in_dir')), direction=dirn)
    add_a2_row('val_in_dir', sub.filter(pl.col('val_in_dir')), direction=dirn)

a2 = pl.DataFrame(a2_rows)
a2.write_csv(OUT / 'per_vp_level.csv')
print(a2.to_pandas().to_string(index=False))
print()


# ---------------------------------------------------------------------------
# A3 — Stall at VP (MFE peak proximity)
# ---------------------------------------------------------------------------
print('--- A3: stall-at-VP MFE peak analysis ---')

bars = pl.read_parquet(ROOT / 'data/consolidated/nq-front-month.ohlcv-30s.parquet')
bar_high = bars['high'].to_numpy()
bar_low = bars['low'].to_numpy()
n_bars = len(bar_high)

# Restrict to hit_2R winners only
winners = df.filter(pl.col(TARGET))
print(f'winners: n={winners.height}')

w_entry_idx = winners['entry_idx'].to_numpy()
w_entry_px = winners['entry_price'].to_numpy()
w_sl = winners['sl_dist'].to_numpy()
w_long = (winners['direction'].to_numpy() == 'long')
w_poc = winners['poc'].to_numpy()
w_vah = winners['vah'].to_numpy()
w_val = winners['val'].to_numpy()
w_r_poc = winners['r_poc'].to_numpy()
w_r_vah = winners['r_vah'].to_numpy()
w_r_val = winners['r_val'].to_numpy()
w_year = winners['year'].to_numpy()

peak_r = np.full(winners.height, np.nan)
peak_offset_bars = np.full(winners.height, -1, dtype=np.int32)
peak_price = np.full(winners.height, np.nan)

for i in range(winners.height):
    ei = int(w_entry_idx[i])
    end = min(ei + STALL_WINDOW_BARS, n_bars)
    if ei >= n_bars:
        continue
    window_high = bar_high[ei:end]
    window_low = bar_low[ei:end]
    if w_long[i]:
        mfe_pts = window_high - w_entry_px[i]
    else:
        mfe_pts = w_entry_px[i] - window_low
    mfe_r_window = mfe_pts / w_sl[i]
    j = int(np.argmax(mfe_r_window))
    peak_r[i] = mfe_r_window[j]
    peak_offset_bars[i] = j
    peak_price[i] = window_high[j] if w_long[i] else window_low[j]

# Distance from peak price to each VP level, in R, signed (positive = peak past the level in trade dir)
def peak_dist_r(level_price: np.ndarray) -> np.ndarray:
    diff = peak_price - level_price
    return np.where(w_long, diff, -diff) / w_sl


# Distance from peak BACK to the nearest VP level *in trade direction* and within 0-3R region
# For "stall" we want: how close did peak come to a VP level? Signed by trade direction.
# Use absolute R-distance to capture proximity regardless of overshoot/undershoot.
abs_d_poc = np.abs(peak_dist_r(w_poc))
abs_d_vah = np.abs(peak_dist_r(w_vah))
abs_d_val = np.abs(peak_dist_r(w_val))
abs_d_min = np.minimum.reduce([abs_d_poc, abs_d_vah, abs_d_val])

# Identify which level was nearest
nearest_label = np.array(['poc'] * winners.height, dtype=object)
nearest_label[abs_d_vah < abs_d_poc] = 'vah'
near_val_mask = (abs_d_val < abs_d_min) | ((abs_d_val == abs_d_min) & (~np.isin(nearest_label, ['poc', 'vah'])))
# simpler: pick argmin per row
stacked = np.stack([abs_d_poc, abs_d_vah, abs_d_val], axis=1)
argmin = np.argmin(stacked, axis=1)
labels = np.array(['poc', 'vah', 'val'])
nearest_label = labels[argmin]
nearest_dist = stacked[np.arange(winners.height), argmin]

# Bands
def band(d):
    if np.isnan(d):
        return 'na'
    if d < 0.25:
        return '<0.25R'
    if d < 0.5:
        return '0.25-0.5R'
    if d < 1.0:
        return '0.5-1.0R'
    return '>=1.0R'


bands = np.array([band(d) for d in nearest_dist])

# Restrict to winners that have a valid VP target ahead (n_vp_targets >= 1) — these are the cases where stall is meaningful
w_n_vp = winners['n_vp_targets'].to_numpy()
mask_has_vp = w_n_vp >= 1

stall_rows = []
for band_label in ['<0.25R', '0.25-0.5R', '0.5-1.0R', '>=1.0R']:
    # restricted to has-VP winners (relevant cohort)
    m = mask_has_vp & (bands == band_label)
    stall_rows.append({
        'band': band_label,
        'cohort': 'winners_with_vp_target',
        'n': int(m.sum()),
        'share': float(m.sum() / mask_has_vp.sum()) if mask_has_vp.sum() else None,
        'nearest_poc_share': float(((nearest_label == 'poc') & m).sum() / m.sum()) if m.sum() else None,
        'nearest_vah_share': float(((nearest_label == 'vah') & m).sum() / m.sum()) if m.sum() else None,
        'nearest_val_share': float(((nearest_label == 'val') & m).sum() / m.sum()) if m.sum() else None,
    })

# Per-level share (which VP is the magnet most often, among <0.5R peaks)
close_mask = mask_has_vp & (nearest_dist < 0.5)
stall_rows.append({
    'band': 'all_winners_with_vp',
    'cohort': 'denominator',
    'n': int(mask_has_vp.sum()),
    'share': 1.0,
    'nearest_poc_share': float((nearest_label == 'poc')[mask_has_vp].mean()),
    'nearest_vah_share': float((nearest_label == 'vah')[mask_has_vp].mean()),
    'nearest_val_share': float((nearest_label == 'val')[mask_has_vp].mean()),
})

stall_df = pl.DataFrame(stall_rows)
stall_df.write_csv(OUT / 'stall_analysis.csv')
print(stall_df.to_pandas().to_string(index=False))

# Headline metric
share_close = float((mask_has_vp & (nearest_dist < 0.5)).sum() / mask_has_vp.sum()) if mask_has_vp.sum() else None
print(f'\nWinners (with VP target) peaking within 0.5R of a VP level: {share_close*100:.1f}%')
print()


# ---------------------------------------------------------------------------
# A4 — Variant × n_vp_targets
# ---------------------------------------------------------------------------
print('--- A4: variant × n_vp_targets ---')
a4_rows = []
for variant in sorted(df['variant'].unique().to_list()):
    for bucket in ['0', '1', '2', '3+']:
        if bucket == '3+':
            sub = df.filter((pl.col('variant') == variant) & (pl.col('n_vp_targets') >= 3))
        else:
            sub = df.filter((pl.col('variant') == variant) & (pl.col('n_vp_targets') == int(bucket)))
        sub_is, sub_oos = is_oos_split(sub)
        n_is, r_is = cell_rate(sub_is)
        n_oos, r_oos = cell_rate(sub_oos)
        a4_rows.append({
            'variant': variant, 'bucket': bucket,
            'n_IS': n_is, 'hit_2R_IS': r_is,
            'lift_IS_pp': (r_is - is_base) * 100 if r_is is not None else None,
            'n_OOS': n_oos, 'hit_2R_OOS': r_oos,
            'lift_OOS_pp': (r_oos - oos_base) * 100 if r_oos is not None else None,
        })
a4 = pl.DataFrame(a4_rows)
a4.write_csv(OUT / 'variant_x_vp.csv')
print(a4.to_pandas().to_string(index=False))
print()


# ---------------------------------------------------------------------------
# A5 — Robustness
# ---------------------------------------------------------------------------
print('--- A5: robustness ---')

# Yearly for n_vp == 2 cohort
year_rows = []
cohort_vp2 = df.filter(pl.col('n_vp_targets') == 2)
for y in sorted(df['year'].unique().to_list()):
    sub = cohort_vp2.filter(pl.col('year') == y)
    full_year = df.filter(pl.col('year') == y)
    year_base = full_year[TARGET].mean() if full_year.height else None
    rate = sub[TARGET].mean() if sub.height else None
    year_rows.append({
        'year': y,
        'cohort': 'n_vp==2',
        'n': sub.height,
        'hit_2R': rate,
        'year_base_rate': year_base,
        'lift_pp': (rate - year_base) * 100 if (rate is not None and year_base is not None) else None,
    })
yearly = pl.DataFrame(year_rows)
yearly.write_csv(OUT / 'yearly_n_vp_2.csv')
print('Yearly n_vp==2:')
print(yearly.to_pandas().to_string(index=False))
positive_years = sum(1 for r in year_rows if r['lift_pp'] is not None and r['lift_pp'] > 0)
print(f'Positive-lift years: {positive_years} / {len(year_rows)}')
print()

# Long/short × bucket × era
print('Direction × bucket:')
ds_rows = []
for dirn in ('long', 'short'):
    for bucket in ['0', '1', '2', '3+']:
        if bucket == '3+':
            sub = df.filter((pl.col('direction') == dirn) & (pl.col('n_vp_targets') >= 3))
        else:
            sub = df.filter((pl.col('direction') == dirn) & (pl.col('n_vp_targets') == int(bucket)))
        sub_is, sub_oos = is_oos_split(sub)
        n_is, r_is = cell_rate(sub_is)
        n_oos, r_oos = cell_rate(sub_oos)
        ds_rows.append({
            'direction': dirn, 'bucket': bucket,
            'n_IS': n_is, 'hit_2R_IS': r_is,
            'lift_IS_pp': (r_is - is_base) * 100 if r_is is not None else None,
            'n_OOS': n_oos, 'hit_2R_OOS': r_oos,
            'lift_OOS_pp': (r_oos - oos_base) * 100 if r_oos is not None else None,
        })
ds = pl.DataFrame(ds_rows)
print(ds.to_pandas().to_string(index=False))
print()

# Macro window × bucket
print('Macro window × bucket:')
mw_rows = []
macro_windows = [m for m in df['macro_window'].unique().to_list() if m is not None]
for mw in sorted(macro_windows):
    for bucket in ['0', '1', '2', '3+']:
        if bucket == '3+':
            sub = df.filter((pl.col('macro_window') == mw) & (pl.col('n_vp_targets') >= 3))
        else:
            sub = df.filter((pl.col('macro_window') == mw) & (pl.col('n_vp_targets') == int(bucket)))
        sub_is, sub_oos = is_oos_split(sub)
        n_is, r_is = cell_rate(sub_is)
        n_oos, r_oos = cell_rate(sub_oos)
        mw_rows.append({
            'macro_window': mw, 'bucket': bucket,
            'n_IS': n_is, 'hit_2R_IS': r_is,
            'lift_IS_pp': (r_is - is_base) * 100 if r_is is not None else None,
            'n_OOS': n_oos, 'hit_2R_OOS': r_oos,
            'lift_OOS_pp': (r_oos - oos_base) * 100 if r_oos is not None else None,
        })
mw = pl.DataFrame(mw_rows)
print(mw.to_pandas().to_string(index=False))
print()

# VIXY regime × bucket
print('VIXY regime × bucket:')
vx_rows = []
vixy_regimes = [v for v in df['vixy_regime'].unique().to_list() if v is not None]
for vr in sorted(vixy_regimes):
    for bucket in ['0', '1', '2', '3+']:
        if bucket == '3+':
            sub = df.filter((pl.col('vixy_regime') == vr) & (pl.col('n_vp_targets') >= 3))
        else:
            sub = df.filter((pl.col('vixy_regime') == vr) & (pl.col('n_vp_targets') == int(bucket)))
        sub_is, sub_oos = is_oos_split(sub)
        n_is, r_is = cell_rate(sub_is)
        n_oos, r_oos = cell_rate(sub_oos)
        vx_rows.append({
            'vixy_regime': vr, 'bucket': bucket,
            'n_IS': n_is, 'hit_2R_IS': r_is,
            'lift_IS_pp': (r_is - is_base) * 100 if r_is is not None else None,
            'n_OOS': n_oos, 'hit_2R_OOS': r_oos,
            'lift_OOS_pp': (r_oos - oos_base) * 100 if r_oos is not None else None,
        })
vx = pl.DataFrame(vx_rows)
print(vx.to_pandas().to_string(index=False))

# Save combined robustness frame too
robustness = pl.concat([
    ds.with_columns(pl.lit('direction').alias('slice')).rename({'direction': 'value'}),
    mw.with_columns(pl.lit('macro_window').alias('slice')).rename({'macro_window': 'value'}),
    vx.with_columns(pl.lit('vixy_regime').alias('slice')).rename({'vixy_regime': 'value'}),
], how='diagonal')
robustness.write_csv(OUT / 'robustness.csv')

print()
print('=' * 70)
print(f'A1 verdict: {walk_forward_verdict}')
if walk_forward_verdict == 'PASS':
    print('  -> signal survived stricter walk-forward; proceed to write analysis.md PASS verdict')
else:
    print('  -> signal failed; write analysis.md with negative result')
print('=' * 70)
