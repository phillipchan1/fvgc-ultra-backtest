"""
VA-width as a day-type filter for FVGC trades.

Hypothesis: tight value area = balance day favoring mean-reversion to POC;
wide value area = trend day favoring breakouts beyond VAH/VAL.

Strict IS/OOS:
  IS  = 2018-2022
  OOS = 2023-2026
Quartile cuts and z-score parameters are derived from IS-only and frozen.

Kill criteria
-------------
K1: no va_width regime shows >= +5pp OOS hit_2R lift over OOS base.
K2: among trades with n_vp_targets >= 1, va_width × n_vp interaction is flat
    (every va regime within ~2pp of the n_vp>=1 OOS rate) -> va_width
    is redundant to the trade-level VP filter.
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
KILL_K1_LIFT_PP = 5.0
KILL_K2_SPREAD_PP = 2.0  # range across va-regimes inside n_vp>=1 cohort, OOS

# ----------------------------------------------------------------------------
# Load
# ----------------------------------------------------------------------------
trades = (
    pl.read_csv(ROOT / 'studies/baseline/results/trades.csv', try_parse_dates=True)
    .filter(pl.col('outcome') != 'skip')
)
vp = pl.read_csv(ROOT / 'data/levels/daily_volume_profile.csv', try_parse_dates=True)

trades = trades.with_columns([
    pl.col('timestamp').dt.date().alias('date'),
    pl.col('timestamp').dt.year().alias('year'),
])
trades = trades.with_columns([
    (pl.col('year') <= IS_MAX_YEAR).alias('is_in_is'),
    (pl.col('year') >= OOS_MIN_YEAR).alias('is_in_oos'),
])

# va_width is in raw NQ points; NQ ~tripled over the sample so absolute width
# scales with price. Use va_width_pct = va_width / poc as the main proxy and
# also report absolute and rolling-z forms.
vp = vp.sort('date').with_columns(
    (pl.col('va_width') / pl.col('poc') * 100.0).alias('va_width_pct'),
)
# 20-day trailing (prior 20 days, excluding today) z-score per task spec.
vp = vp.with_columns([
    pl.col('va_width').shift(1).rolling_mean(window_size=20).alias('_vw_mu'),
    pl.col('va_width').shift(1).rolling_std(window_size=20).alias('_vw_sd'),
])
vp = vp.with_columns(
    ((pl.col('va_width') - pl.col('_vw_mu')) / pl.col('_vw_sd')).alias('va_width_z')
)
vp = vp.drop(['_vw_mu', '_vw_sd'])

df = trades.join(vp, on='date', how='left')

# Per-trade VP target distance (mirrors vp_targets study) so we can stack
# va_width regime on top of the n_vp_targets filter.
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
    pl.Series('poc_in_dir', poc_in),
    pl.Series('vah_in_dir', vah_in),
    pl.Series('val_in_dir', val_in),
    pl.Series('n_vp_targets', poc_in.astype(np.int32) + vah_in.astype(np.int32) + val_in.astype(np.int32)),
])


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
def cell_rate(frame: pl.DataFrame) -> tuple[int, float | None]:
    n = frame.height
    r = frame[TARGET].mean() if n else None
    return n, r


def split(frame: pl.DataFrame):
    return frame.filter(pl.col('is_in_is')), frame.filter(pl.col('is_in_oos'))


is_base = df.filter(pl.col('is_in_is'))[TARGET].mean()
oos_base = df.filter(pl.col('is_in_oos'))[TARGET].mean()
print('=' * 70)
print('VA-width regime study')
print('=' * 70)
print(f'n_total={df.height}  pooled hit_2R={df[TARGET].mean()*100:.1f}%')
print(f'IS  (year<={IS_MAX_YEAR})  n={df.filter(pl.col("is_in_is")).height}  base={is_base*100:.1f}%')
print(f'OOS (year>={OOS_MIN_YEAR}) n={df.filter(pl.col("is_in_oos")).height}  base={oos_base*100:.1f}%')
print()


# ----------------------------------------------------------------------------
# Q1 — distribution of va_width / va_width_pct / va_width_z
# ----------------------------------------------------------------------------
print('--- Q1: va_width distribution ---')
hist_rows = []
for col in ['va_width', 'va_width_pct', 'va_width_z']:
    s = vp[col].drop_nulls()
    s_is = vp.filter(pl.col('date').dt.year() <= IS_MAX_YEAR)[col].drop_nulls()
    hist_rows.append({
        'col': col,
        'n_days_pooled': s.len(),
        'n_days_IS': s_is.len(),
        'min': float(s.min()),
        'p10': float(s.quantile(0.10)),
        'p25_IS': float(s_is.quantile(0.25)),
        'p50_IS': float(s_is.quantile(0.50)),
        'p75_IS': float(s_is.quantile(0.75)),
        'p90': float(s.quantile(0.90)),
        'max': float(s.max()),
        'mean': float(s.mean()),
        'std': float(s.std()),
    })
hist_df = pl.DataFrame(hist_rows)
hist_df.write_csv(OUT / 'va_width_hist.csv')
print(hist_df.to_pandas().to_string(index=False))

# Freeze IS-derived quartile cuts. Apply to OOS as a held-out test.
vp_is = vp.filter(pl.col('date').dt.year() <= IS_MAX_YEAR)
cuts_pct = [float(vp_is['va_width_pct'].quantile(q)) for q in (0.25, 0.50, 0.75)]
cuts_abs = [float(vp_is['va_width'].quantile(q)) for q in (0.25, 0.50, 0.75)]
print(f'\nIS quartile cuts (va_width_pct, %): {cuts_pct}')
print(f'IS quartile cuts (va_width abs, pts): {cuts_abs}')


def to_quartile(s: pl.Series, cuts: list[float]) -> pl.Series:
    a = s.to_numpy()
    out = np.full(a.shape, 'NA', dtype=object)
    out[a <= cuts[0]] = 'Q1_tight'
    out[(a > cuts[0]) & (a <= cuts[1])] = 'Q2'
    out[(a > cuts[1]) & (a <= cuts[2])] = 'Q3'
    out[a > cuts[2]] = 'Q4_wide'
    return pl.Series(out)


df = df.with_columns([
    to_quartile(df['va_width_pct'], cuts_pct).alias('va_pct_q'),
    to_quartile(df['va_width'], cuts_abs).alias('va_abs_q'),
])
# z-score binning (relative to own-history). Use fixed cuts.
def z_bin(z: float | None) -> str:
    if z is None or np.isnan(z):
        return 'NA'
    if z <= -0.75:
        return 'tight_z(<=-0.75)'
    if z < 0.75:
        return 'mid_z'
    return 'wide_z(>=0.75)'


df = df.with_columns(
    pl.col('va_width_z').map_elements(z_bin, return_dtype=pl.Utf8).alias('va_z_bin')
)
print()


# ----------------------------------------------------------------------------
# Q2 — per-quartile hit_2R (kill check)
# ----------------------------------------------------------------------------
def per_bucket_table(col: str, order: list[str]) -> pl.DataFrame:
    rows = []
    for b in order:
        sub = df.filter(pl.col(col) == b)
        sub_is, sub_oos = split(sub)
        n_is, r_is = cell_rate(sub_is)
        n_oos, r_oos = cell_rate(sub_oos)
        rows.append({
            'bucket': b,
            'n_pooled': sub.height,
            'n_IS': n_is, 'hit_2R_IS': r_is,
            'lift_IS_pp': (r_is - is_base) * 100 if r_is is not None else None,
            'n_OOS': n_oos, 'hit_2R_OOS': r_oos,
            'lift_OOS_pp': (r_oos - oos_base) * 100 if r_oos is not None else None,
        })
    return pl.DataFrame(rows)


print('--- Q2: hit_2R by va_width_pct quartile (IS-cut) ---')
q2_pct = per_bucket_table('va_pct_q', ['Q1_tight', 'Q2', 'Q3', 'Q4_wide'])
q2_pct.write_csv(OUT / 'hit_2R_by_va_quartile.csv')
print(q2_pct.to_pandas().to_string(index=False))

print('\n--- Q2b: hit_2R by va_width absolute quartile (IS-cut) ---')
q2_abs = per_bucket_table('va_abs_q', ['Q1_tight', 'Q2', 'Q3', 'Q4_wide'])
q2_abs.write_csv(OUT / 'hit_2R_by_va_width_abs.csv')
print(q2_abs.to_pandas().to_string(index=False))

# Kill K1: any bucket OOS lift >= +5pp?
max_oos_lift = max(
    (r['lift_OOS_pp'] for r in q2_pct.to_dicts() if r['lift_OOS_pp'] is not None),
    default=-99.0,
)
max_oos_lift_abs = max(
    (r['lift_OOS_pp'] for r in q2_abs.to_dicts() if r['lift_OOS_pp'] is not None),
    default=-99.0,
)
k1_tripped = max(max_oos_lift, max_oos_lift_abs) < KILL_K1_LIFT_PP
print(f'\nK1: max OOS lift across va quartiles = {max(max_oos_lift, max_oos_lift_abs):+.2f}pp'
      f' (threshold +{KILL_K1_LIFT_PP:.1f}pp) -> {"TRIPPED" if k1_tripped else "OK"}')

# Year-by-year stability for the strongest IS bucket
best_bucket = max(q2_pct.to_dicts(), key=lambda r: (r['lift_IS_pp'] or -99))['bucket']
print(f"\nYear-by-year stability for IS-best bucket {best_bucket} (va_pct_q):")
year_rows = []
for y in sorted(df['year'].unique().to_list()):
    sub = df.filter((pl.col('year') == y) & (pl.col('va_pct_q') == best_bucket))
    full = df.filter(pl.col('year') == y)
    yb = full[TARGET].mean() if full.height else None
    r = sub[TARGET].mean() if sub.height else None
    year_rows.append({
        'year': y, 'bucket': best_bucket,
        'n': sub.height, 'hit_2R': r,
        'year_base': yb,
        'lift_pp': (r - yb) * 100 if (r is not None and yb is not None) else None,
    })
yr = pl.DataFrame(year_rows)
yr.write_csv(OUT / 'yearly_best_bucket.csv')
print(yr.to_pandas().to_string(index=False))
print()


# ----------------------------------------------------------------------------
# Q3 — va_width × direction
# ----------------------------------------------------------------------------
print('--- Q3: va_width × direction ---')
q3_rows = []
for dirn in ('long', 'short'):
    for b in ['Q1_tight', 'Q2', 'Q3', 'Q4_wide']:
        sub = df.filter((pl.col('direction') == dirn) & (pl.col('va_pct_q') == b))
        sub_is, sub_oos = split(sub)
        n_is, r_is = cell_rate(sub_is)
        n_oos, r_oos = cell_rate(sub_oos)
        # base = same direction overall
        is_dir_base = df.filter(
            pl.col('direction') == dirn).filter(pl.col('is_in_is'))[TARGET].mean()
        oos_dir_base = df.filter(
            pl.col('direction') == dirn).filter(pl.col('is_in_oos'))[TARGET].mean()
        q3_rows.append({
            'direction': dirn, 'va_pct_q': b,
            'n_IS': n_is, 'hit_2R_IS': r_is,
            'lift_IS_pp': (r_is - is_dir_base) * 100 if r_is is not None else None,
            'n_OOS': n_oos, 'hit_2R_OOS': r_oos,
            'lift_OOS_pp': (r_oos - oos_dir_base) * 100 if r_oos is not None else None,
        })
q3 = pl.DataFrame(q3_rows)
q3.write_csv(OUT / 'va_x_direction.csv')
print(q3.to_pandas().to_string(index=False))
print()


# ----------------------------------------------------------------------------
# Q4 — va_width × n_vp_targets (the redundancy check)
# ----------------------------------------------------------------------------
print('--- Q4: va_width × n_vp_targets ---')
q4_rows = []
for vp_bucket_label, vp_filter in [
    ('n_vp==0', pl.col('n_vp_targets') == 0),
    ('n_vp>=1', pl.col('n_vp_targets') >= 1),
    ('n_vp>=2', pl.col('n_vp_targets') >= 2),
]:
    base_oos = df.filter(vp_filter & pl.col('is_in_oos'))[TARGET].mean()
    base_is = df.filter(vp_filter & pl.col('is_in_is'))[TARGET].mean()
    for b in ['Q1_tight', 'Q2', 'Q3', 'Q4_wide']:
        sub = df.filter(vp_filter & (pl.col('va_pct_q') == b))
        sub_is, sub_oos = split(sub)
        n_is, r_is = cell_rate(sub_is)
        n_oos, r_oos = cell_rate(sub_oos)
        q4_rows.append({
            'vp_cohort': vp_bucket_label,
            'cohort_OOS_base': (base_oos or 0) * 100,
            'va_pct_q': b,
            'n_IS': n_is, 'hit_2R_IS': r_is,
            'lift_vs_cohort_IS_pp': (r_is - base_is) * 100 if (r_is is not None and base_is is not None) else None,
            'n_OOS': n_oos, 'hit_2R_OOS': r_oos,
            'lift_vs_cohort_OOS_pp': (r_oos - base_oos) * 100 if (r_oos is not None and base_oos is not None) else None,
        })
q4 = pl.DataFrame(q4_rows)
q4.write_csv(OUT / 'va_x_vp_filter.csv')
print(q4.to_pandas().to_string(index=False))

# Kill K2: among n_vp>=1, OOS spread across va regimes
spread = (
    q4.filter(pl.col('vp_cohort') == 'n_vp>=1')
    .drop_nulls('lift_vs_cohort_OOS_pp')['lift_vs_cohort_OOS_pp']
)
oos_spread = float(spread.max() - spread.min()) if spread.len() else 0.0
k2_tripped = oos_spread < KILL_K2_SPREAD_PP
print(f'\nK2: OOS lift spread inside n_vp>=1 = {oos_spread:.2f}pp '
      f'(threshold {KILL_K2_SPREAD_PP}pp) -> {"TRIPPED (va is redundant)" if k2_tripped else "OK"}')
print()


# ----------------------------------------------------------------------------
# Q5 — va_width_z (rolling-relative)
# ----------------------------------------------------------------------------
print('--- Q5: rolling-20d z-score regime ---')
q5 = per_bucket_table('va_z_bin', ['tight_z(<=-0.75)', 'mid_z', 'wide_z(>=0.75)', 'NA'])
q5.write_csv(OUT / 'hit_2R_by_va_z.csv')
print(q5.to_pandas().to_string(index=False))
max_z_lift = max(
    (r['lift_OOS_pp'] for r in q5.to_dicts() if r['lift_OOS_pp'] is not None and r['bucket'] != 'NA'),
    default=-99.0,
)
print(f'\nMax OOS lift across z bins (ex NA) = {max_z_lift:+.2f}pp')
print()


# ----------------------------------------------------------------------------
# Q6 — mean-reversion vs trend by VA regime
# ----------------------------------------------------------------------------
# Note: studies/prior_day_type/results/trades_by_prior_day_type.csv covers only
# 127/4548 trades (it was filtered to a specific playbook cohort), so we define
# play_type structurally from entry vs today's POC:
#   reversion    = trade direction points back toward POC
#                  (long entry below POC, short entry above POC)
#   continuation = trade direction moves away from POC
# This is what "tight-VA favors reversion / wide-VA favors trend" actually
# predicts at the trade level.
print('--- Q6: reversion vs continuation by VA regime ---')
df = df.with_columns(
    pl.when(
        ((pl.col('direction') == 'long') & (pl.col('entry_price') < pl.col('poc')))
        | ((pl.col('direction') == 'short') & (pl.col('entry_price') > pl.col('poc')))
    ).then(pl.lit('reversion'))
    .otherwise(pl.lit('continuation'))
    .alias('play_type')
)

q6_rows = []
for b in ['Q1_tight', 'Q2', 'Q3', 'Q4_wide']:
    for play in ('reversion', 'continuation'):
        sub = df.filter((pl.col('va_pct_q') == b) & (pl.col('play_type') == play))
        sub_is, sub_oos = split(sub)
        n_is, r_is = cell_rate(sub_is)
        n_oos, r_oos = cell_rate(sub_oos)
        q6_rows.append({
            'va_pct_q': b, 'play_type': play,
            'n_IS': n_is, 'hit_2R_IS': r_is,
            'lift_IS_pp': (r_is - is_base) * 100 if r_is is not None else None,
            'n_OOS': n_oos, 'hit_2R_OOS': r_oos,
            'lift_OOS_pp': (r_oos - oos_base) * 100 if r_oos is not None else None,
        })
q6 = pl.DataFrame(q6_rows)
q6.write_csv(OUT / 'reversion_vs_trend.csv')
print(q6.to_pandas().to_string(index=False))
print()


# ----------------------------------------------------------------------------
# Verdict
# ----------------------------------------------------------------------------
print('=' * 70)
print('Verdict')
print('=' * 70)
verdict = 'KILL' if (k1_tripped and k2_tripped) else ('WEAK' if k1_tripped or k2_tripped else 'PASS')
print(f'K1 (any va-quartile OOS lift >= +{KILL_K1_LIFT_PP}pp): '
      f'{"TRIPPED" if k1_tripped else "OK"}')
print(f'K2 (va spread inside n_vp>=1 OOS < {KILL_K2_SPREAD_PP}pp): '
      f'{"TRIPPED — va is redundant to n_vp_targets" if k2_tripped else "OK"}')
print(f'Overall: {verdict}')
print('=' * 70)
