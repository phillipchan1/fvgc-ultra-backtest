"""
Naked Volume Profile Levels Study.

Hypothesis: a POC/VAH/VAL that hasn't been touched since it was set is a
stronger magnet than one already tapped. If true, the parent finding
n_vp_targets is a noisy proxy for n_NAKED_vp_targets.

Walk-forward design copied from studies/vp_targets/ Phase A:
  IS  = 2018-2022
  OOS = 2023-2026

Naked-threshold N tested at {1, 2, 3, 5} (days since last touch). N selected
on IS only; OOS report is frozen.

Outputs:
  results/touch_history.csv         — one row per (vp_date, level_type)
  results/naked_vs_touched_hit_2R.csv — bucket × era comparison
  results/walk_forward.csv          — n_naked_vp_targets walk-forward
  results/decomposition.csv         — all-naked vs all-touched vs mixed within n_vp>=1
  results/per_level_type.csv        — naked POC vs naked VAH vs naked VAL
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
NAKED_THRESHOLDS = [1, 2, 3, 5]
KILL_LIFT_FLOOR_PP = 5.0  # n_naked must lift hit_2R by >=5pp over n_vp_targets in OOS, else kill

# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------
print('=' * 72)
print('Naked VP Levels Study')
print('=' * 72)

trades = (
    pl.read_csv(ROOT / 'studies/baseline/results/trades.csv', try_parse_dates=True)
    .filter(pl.col('outcome') != 'skip')
)
trades = trades.with_columns([
    pl.col('timestamp').dt.date().alias('date'),
    pl.col('timestamp').dt.year().alias('year'),
])
trades = trades.with_columns([
    (pl.col('year') <= IS_MAX_YEAR).alias('is_in_is'),
    (pl.col('year') >= OOS_MIN_YEAR).alias('is_in_oos'),
])
print(f'trades (non-skip): n={trades.height}')

vp = pl.read_csv(ROOT / 'data/levels/daily_volume_profile.csv', try_parse_dates=True)
print(f'vp rows: n={vp.height}  ({vp["date"].min()} .. {vp["date"].max()})')

# ---------------------------------------------------------------------------
# Build daily ETH H/L from 15m parquet (calendar-date NY)
# ---------------------------------------------------------------------------
print('\nbuilding daily ETH H/L from 15m bars...')
bars = pl.read_parquet(ROOT / 'data/consolidated/nq-front-month.ohlcv-15m.parquet')
daily = (
    bars
    .with_columns(pl.col('timestamp_ny').dt.date().alias('date'))
    .group_by('date')
    .agg([
        pl.col('high').max().alias('day_high'),
        pl.col('low').min().alias('day_low'),
    ])
    .sort('date')
)
print(f'daily H/L rows: n={daily.height}  ({daily["date"].min()} .. {daily["date"].max()})')

# ---------------------------------------------------------------------------
# Touch history: for each (vp_date D, level_type, level_price X),
# find max d < D where day_low[d] <= X <= day_high[d].
# ---------------------------------------------------------------------------
print('\ncomputing touch history (last-touch dates for each VP level)...')

# Index daily H/L by date for fast lookup
daily_dates = daily['date'].to_numpy()
daily_high = daily['day_high'].to_numpy()
daily_low = daily['day_low'].to_numpy()

vp_pd = vp.to_pandas()
vp_dates = vp_pd['date'].values  # numpy datetime64[D]
n_vp = len(vp_pd)

# Per-VP-level last-touch and days-since-touch
LEVEL_TYPES = ['poc', 'vah', 'val']
history_rows = []

# Pre-compute day index map for fast trading-day delta
import pandas as pd
daily_dt = pd.to_datetime(daily_dates)
day_to_idx = {d: i for i, d in enumerate(daily_dt)}

vp_dt = pd.to_datetime(vp_dates)

for lt in LEVEL_TYPES:
    level_vals = vp_pd[lt].values.astype(float)
    for i in range(n_vp):
        D = vp_dt[i]
        X = level_vals[i]
        if np.isnan(X):
            history_rows.append({'vp_date': D.date(), 'level_type': lt, 'level_price': X,
                                 'last_touch_date': None, 'days_since_touched': None})
            continue

        D_idx = day_to_idx.get(D)
        if D_idx is None:
            # vp_date not in daily H/L index — fall back to first idx <= D
            # search using np.searchsorted
            j = np.searchsorted(daily_dt, D, side='left') - 1
            if j < 0:
                history_rows.append({'vp_date': D.date(), 'level_type': lt, 'level_price': X,
                                     'last_touch_date': None, 'days_since_touched': None})
                continue
            D_idx = j + 1  # treat as if D is just after position j; prior days are 0..j
        # scan strictly prior days
        prior_high = daily_high[:D_idx]
        prior_low = daily_low[:D_idx]
        mask = (prior_low <= X) & (X <= prior_high)
        if not mask.any():
            history_rows.append({'vp_date': D.date(), 'level_type': lt, 'level_price': X,
                                 'last_touch_date': None, 'days_since_touched': 999})
            continue
        last_idx = int(np.where(mask)[0].max())
        last_date = daily_dt[last_idx]
        # Trading-day delta = number of daily rows between last_idx and D_idx (exclusive of last_idx, inclusive of D_idx-1)
        # Simpler: D_idx - last_idx (number of trading days from last touch up to D)
        dsd = D_idx - last_idx
        history_rows.append({
            'vp_date': D.date(),
            'level_type': lt,
            'level_price': X,
            'last_touch_date': last_date.date(),
            'days_since_touched': dsd,
        })

hist = pl.DataFrame(history_rows)
hist.write_csv(OUT / 'touch_history.csv')

# Quick sanity stats on dsd distribution
print('\ndays_since_touched distribution (across all VP levels):')
dsd_all = hist.filter(pl.col('days_since_touched').is_not_null())['days_since_touched']
for q in [0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99]:
    print(f'  q{int(q*100):>2}: {dsd_all.quantile(q):.0f}')
inception = hist.filter(pl.col('days_since_touched') == 999).height
print(f'  naked-since-inception: n={inception}')
print(f'  median: {dsd_all.median():.0f}   max(non-inception): {dsd_all.filter(dsd_all<999).max()}')

# Pivot back so per-vp_date we have dsd_poc, dsd_vah, dsd_val
hist_wide = hist.pivot(values='days_since_touched', index='vp_date', on='level_type')
hist_wide = hist_wide.rename({'poc': 'dsd_poc', 'vah': 'dsd_vah', 'val': 'dsd_val'})
hist_wide = hist_wide.with_columns(pl.col('vp_date').cast(pl.Date))

# ---------------------------------------------------------------------------
# Join trades × VP × touch-history
# ---------------------------------------------------------------------------
df = trades.join(vp, on='date', how='left')
df = df.join(hist_wide, left_on='date', right_on='vp_date', how='left')

# Per-VP-level signed R-distance in trade direction (same as parent study)
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
    pl.Series('poc_in_dir', poc_in),
    pl.Series('vah_in_dir', vah_in),
    pl.Series('val_in_dir', val_in),
    pl.Series('n_vp_targets', poc_in.astype(np.int32) + vah_in.astype(np.int32) + val_in.astype(np.int32)),
])


# ---------------------------------------------------------------------------
# For each naked threshold N, compute n_naked_vp_targets
# ---------------------------------------------------------------------------
def naked_counts(N: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    dsd_poc = df['dsd_poc'].to_numpy().astype(float)
    dsd_vah = df['dsd_vah'].to_numpy().astype(float)
    dsd_val = df['dsd_val'].to_numpy().astype(float)
    with np.errstate(invalid='ignore'):
        naked_poc = poc_in & (dsd_poc >= N)
        naked_vah = vah_in & (dsd_vah >= N)
        naked_val = val_in & (dsd_val >= N)
    return naked_poc, naked_vah, naked_val


def n_naked_for_threshold(N: int) -> np.ndarray:
    np_, nv, nl = naked_counts(N)
    return np_.astype(np.int32) + nv.astype(np.int32) + nl.astype(np.int32)


# Add columns for each tested N
for N in NAKED_THRESHOLDS:
    df = df.with_columns(pl.Series(f'n_naked_vp_N{N}', n_naked_for_threshold(N)))


# ---------------------------------------------------------------------------
# Reporting helpers
# ---------------------------------------------------------------------------
is_base = df.filter(pl.col('is_in_is'))[TARGET].mean()
oos_base = df.filter(pl.col('is_in_oos'))[TARGET].mean()
pooled_base = df[TARGET].mean()
print(f'\nn_total={df.height}  pooled_hit_2R={pooled_base*100:.1f}%')
print(f'IS  (year<={IS_MAX_YEAR})  n={df.filter(pl.col("is_in_is")).height}  base={is_base*100:.1f}%')
print(f'OOS (year>={OOS_MIN_YEAR}) n={df.filter(pl.col("is_in_oos")).height}  base={oos_base*100:.1f}%')


def cell(frame: pl.DataFrame) -> tuple[int, float | None]:
    n = frame.height
    r = frame[TARGET].mean() if n else None
    return n, r


def is_oos_split(frame: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame]:
    return frame.filter(pl.col('is_in_is')), frame.filter(pl.col('is_in_oos'))


# ---------------------------------------------------------------------------
# Walk-forward: pick best N on IS, freeze OOS
# ---------------------------------------------------------------------------
print('\n--- Threshold selection (IS only) — pick N that maximizes lift while n_IS >=200 ---')
threshold_rows = []
for N in NAKED_THRESHOLDS:
    col = f'n_naked_vp_N{N}'
    for bucket in ['0', '1', '2', '3+']:
        if bucket == '3+':
            sub = df.filter(pl.col(col) >= 3)
        else:
            sub = df.filter(pl.col(col) == int(bucket))
        sub_is, sub_oos = is_oos_split(sub)
        n_is, r_is = cell(sub_is)
        n_oos, r_oos = cell(sub_oos)
        threshold_rows.append({
            'N': N, 'bucket': bucket,
            'n_IS': n_is, 'hit_2R_IS': r_is,
            'lift_IS_pp': (r_is - is_base) * 100 if r_is is not None else None,
            'n_OOS': n_oos, 'hit_2R_OOS': r_oos,
            'lift_OOS_pp': (r_oos - oos_base) * 100 if r_oos is not None else None,
        })

tbl = pl.DataFrame(threshold_rows)
tbl.write_csv(OUT / 'threshold_scan.csv')
print(tbl.to_pandas().to_string(index=False))

# Pick N that gives the largest IS lift at bucket >=2 with n_IS >=200
ge2_is_lift_by_N = {}
for N in NAKED_THRESHOLDS:
    col = f'n_naked_vp_N{N}'
    sub_is = df.filter((pl.col('is_in_is')) & (pl.col(col) >= 2))
    if sub_is.height < 200:
        continue
    lift = (sub_is[TARGET].mean() - is_base) * 100
    ge2_is_lift_by_N[N] = (lift, sub_is.height)

print('\n>=2 cohort IS lifts (n_IS >= 200):')
for N, (lift, nN) in ge2_is_lift_by_N.items():
    print(f'  N={N}: lift={lift:+.2f}pp  n_IS={nN}')

if not ge2_is_lift_by_N:
    print('\n!!  No naked threshold has n_IS >= 200 in the >=2 cohort.')
    print('    Falling back to N=1 (every non-zero counts) for reporting.')
    BEST_N = 1
else:
    BEST_N = max(ge2_is_lift_by_N, key=lambda n: ge2_is_lift_by_N[n][0])
print(f'\n*** Chosen naked threshold (IS-selected): N = {BEST_N} ***')

# Bind chosen N column to the rest of the analysis
df = df.with_columns(pl.col(f'n_naked_vp_N{BEST_N}').alias('n_naked_vp_targets'))


# ---------------------------------------------------------------------------
# A1 — walk-forward of n_naked_vp_targets (mirroring parent's table)
# ---------------------------------------------------------------------------
print(f'\n--- A1: n_naked_vp_targets walk-forward (N={BEST_N}) ---')
wf_rows = []
for label, expr in [
    ('0', pl.col('n_naked_vp_targets') == 0),
    ('1', pl.col('n_naked_vp_targets') == 1),
    ('2', pl.col('n_naked_vp_targets') == 2),
    ('3+', pl.col('n_naked_vp_targets') >= 3),
]:
    sub = df.filter(expr)
    sub_is, sub_oos = is_oos_split(sub)
    n_is, r_is = cell(sub_is)
    n_oos, r_oos = cell(sub_oos)
    wf_rows.append({
        'bucket': label,
        'n_pooled': sub.height,
        'hit_2R_pooled': sub[TARGET].mean() if sub.height else None,
        'n_IS': n_is, 'hit_2R_IS': r_is,
        'lift_IS_pp': (r_is - is_base) * 100 if r_is is not None else None,
        'n_OOS': n_oos, 'hit_2R_OOS': r_oos,
        'lift_OOS_pp': (r_oos - oos_base) * 100 if r_oos is not None else None,
    })
wf = pl.DataFrame(wf_rows)
wf.write_csv(OUT / 'walk_forward.csv')
print(wf.to_pandas().to_string(index=False))


# ---------------------------------------------------------------------------
# Head-to-head: n_vp_targets vs n_naked_vp_targets at matching cohort sizes
# Build cohort by cohort comparison so we can read the lift directly.
# ---------------------------------------------------------------------------
print('\n--- Head-to-head: n_vp_targets vs n_naked_vp_targets (chosen N) ---')
h2h_rows = []
for col_name in ['n_vp_targets', 'n_naked_vp_targets']:
    for label, expr in [
        ('==0', pl.col(col_name) == 0),
        ('==1', pl.col(col_name) == 1),
        ('==2', pl.col(col_name) == 2),
        ('>=2', pl.col(col_name) >= 2),
        ('>=1', pl.col(col_name) >= 1),
    ]:
        sub = df.filter(expr)
        sub_is, sub_oos = is_oos_split(sub)
        n_is, r_is = cell(sub_is)
        n_oos, r_oos = cell(sub_oos)
        h2h_rows.append({
            'feature': col_name,
            'bucket': label,
            'n_IS': n_is, 'hit_2R_IS': r_is,
            'lift_IS_pp': (r_is - is_base) * 100 if r_is is not None else None,
            'n_OOS': n_oos, 'hit_2R_OOS': r_oos,
            'lift_OOS_pp': (r_oos - oos_base) * 100 if r_oos is not None else None,
        })
h2h = pl.DataFrame(h2h_rows)
h2h.write_csv(OUT / 'naked_vs_touched_hit_2R.csv')
print(h2h.to_pandas().to_string(index=False))


# Kill criterion: n_naked >=2 OOS lift vs n_vp_targets >=2 OOS lift
def cohort_oos_lift(col_name: str, ge: int) -> tuple[float | None, int]:
    sub = df.filter((pl.col('is_in_oos')) & (pl.col(col_name) >= ge))
    if sub.height == 0:
        return None, 0
    return float((sub[TARGET].mean() - oos_base) * 100), sub.height


naked_ge2_oos_lift, naked_ge2_oos_n = cohort_oos_lift('n_naked_vp_targets', 2)
vp_ge2_oos_lift, vp_ge2_oos_n = cohort_oos_lift('n_vp_targets', 2)

print(f'\nn_vp_targets>=2    OOS lift = {vp_ge2_oos_lift:+.2f}pp  (n={vp_ge2_oos_n})')
print(f'n_naked_vp_targets>=2 OOS lift = {naked_ge2_oos_lift:+.2f}pp  (n={naked_ge2_oos_n})')
delta = (naked_ge2_oos_lift - vp_ge2_oos_lift) if (naked_ge2_oos_lift is not None and vp_ge2_oos_lift is not None) else None
print(f'  delta (naked − vp) = {delta:+.2f}pp')

kill = (delta is None) or (delta < KILL_LIFT_FLOOR_PP)
verdict_q3 = 'KILL: naked refinement does NOT lift OOS by >=+5pp' if kill else 'OK: naked refinement lifts OOS by >=+5pp'
print(f'  kill-criterion-1 ({KILL_LIFT_FLOOR_PP:+.1f}pp): {verdict_q3}')


# ---------------------------------------------------------------------------
# Q4 — decomposition within n_vp_targets >= 1
# Within trades that have at least one VP target ahead, compare cohorts:
#   - all_naked: every in-direction VP target is naked
#   - all_touched: every in-direction VP target is touched (dsd < N)
#   - mixed
# ---------------------------------------------------------------------------
print('\n--- Q4: decomposition within n_vp_targets >= 1 ---')

np_, nv, nl = naked_counts(BEST_N)
np_int = np_.astype(np.int32)
nv_int = nv.astype(np.int32)
nl_int = nl.astype(np.int32)
naked_count = np_int + nv_int + nl_int
n_vp_arr = df['n_vp_targets'].to_numpy()

cohort = np.full(df.height, 'none', dtype=object)
mask_anyvp = n_vp_arr >= 1
mask_allnaked = mask_anyvp & (naked_count == n_vp_arr)
mask_alltouched = mask_anyvp & (naked_count == 0)
mask_mixed = mask_anyvp & (~mask_allnaked) & (~mask_alltouched)
cohort[mask_allnaked] = 'all_naked'
cohort[mask_alltouched] = 'all_touched'
cohort[mask_mixed] = 'mixed'

df = df.with_columns(pl.Series('decomp_cohort', cohort))

decomp_rows = []
for c in ['all_naked', 'mixed', 'all_touched']:
    sub = df.filter(pl.col('decomp_cohort') == c)
    sub_is, sub_oos = is_oos_split(sub)
    n_is, r_is = cell(sub_is)
    n_oos, r_oos = cell(sub_oos)
    decomp_rows.append({
        'cohort': c,
        'n_IS': n_is, 'hit_2R_IS': r_is,
        'lift_IS_pp': (r_is - is_base) * 100 if r_is is not None else None,
        'n_OOS': n_oos, 'hit_2R_OOS': r_oos,
        'lift_OOS_pp': (r_oos - oos_base) * 100 if r_oos is not None else None,
    })
decomp = pl.DataFrame(decomp_rows)
decomp.write_csv(OUT / 'decomposition.csv')
print(decomp.to_pandas().to_string(index=False))


# ---------------------------------------------------------------------------
# Q5 — per-level type (naked POC vs naked VAH vs naked VAL)
# ---------------------------------------------------------------------------
print('\n--- Q5: per-level type (naked POC vs VAH vs VAL) ---')
df = df.with_columns([
    pl.Series('naked_poc', np_),
    pl.Series('naked_vah', nv),
    pl.Series('naked_val', nl),
])

per_level_rows = []
for lt in ['naked_poc', 'naked_vah', 'naked_val']:
    sub = df.filter(pl.col(lt))
    sub_is, sub_oos = is_oos_split(sub)
    n_is, r_is = cell(sub_is)
    n_oos, r_oos = cell(sub_oos)
    per_level_rows.append({
        'filter': lt, 'direction': 'all',
        'n_IS': n_is, 'hit_2R_IS': r_is,
        'lift_IS_pp': (r_is - is_base) * 100 if r_is is not None else None,
        'n_OOS': n_oos, 'hit_2R_OOS': r_oos,
        'lift_OOS_pp': (r_oos - oos_base) * 100 if r_oos is not None else None,
    })

# Per-direction breakouts (replicate parent's asymmetry test)
for dirn in ('long', 'short'):
    sub_dir = df.filter(pl.col('direction') == dirn)
    for lt in ['naked_poc', 'naked_vah', 'naked_val']:
        sub = sub_dir.filter(pl.col(lt))
        sub_is, sub_oos = is_oos_split(sub)
        n_is, r_is = cell(sub_is)
        n_oos, r_oos = cell(sub_oos)
        per_level_rows.append({
            'filter': lt, 'direction': dirn,
            'n_IS': n_is, 'hit_2R_IS': r_is,
            'lift_IS_pp': (r_is - is_base) * 100 if r_is is not None else None,
            'n_OOS': n_oos, 'hit_2R_OOS': r_oos,
            'lift_OOS_pp': (r_oos - oos_base) * 100 if r_oos is not None else None,
        })

per_level = pl.DataFrame(per_level_rows)
per_level.write_csv(OUT / 'per_level_type.csv')
print(per_level.to_pandas().to_string(index=False))


# ---------------------------------------------------------------------------
# Q6 — year-by-year for n_naked_vp_targets >= 2 cohort
# ---------------------------------------------------------------------------
print('\n--- Q6: yearly n_naked_vp_targets == 2 ---')
year_rows = []
cohort_n2 = df.filter(pl.col('n_naked_vp_targets') == 2)
for y in sorted(df['year'].unique().to_list()):
    sub = cohort_n2.filter(pl.col('year') == y)
    full_y = df.filter(pl.col('year') == y)
    yr_base = full_y[TARGET].mean() if full_y.height else None
    rate = sub[TARGET].mean() if sub.height else None
    year_rows.append({
        'year': y, 'cohort': 'n_naked_vp==2',
        'n': sub.height, 'hit_2R': rate,
        'year_base': yr_base,
        'lift_pp': (rate - yr_base) * 100 if (rate is not None and yr_base is not None) else None,
    })
yearly = pl.DataFrame(year_rows)
yearly.write_csv(OUT / 'yearly_n_naked_vp_2.csv')
print(yearly.to_pandas().to_string(index=False))
positive = sum(1 for r in year_rows if r['lift_pp'] is not None and r['lift_pp'] > 0)
print(f'positive-lift years: {positive} / {len(year_rows)}')


# ---------------------------------------------------------------------------
# Counter-evidence: are freshly-touched levels actually the stronger magnets?
# Take all in-direction VP levels and bucket by their dsd value, then look at
# hit_2R when at least one in-direction level has that dsd value.
#
# Per-trade: take MIN dsd among in-direction VP levels (i.e. the freshest one
# the trade is targeting). Lower min_dsd = "freshest target ahead."
# ---------------------------------------------------------------------------
print('\n--- Counter-evidence: freshness of targets vs hit_2R ---')
dsd_poc = df['dsd_poc'].to_numpy().astype(float)
dsd_vah = df['dsd_vah'].to_numpy().astype(float)
dsd_val = df['dsd_val'].to_numpy().astype(float)
# mask: only count levels that are in direction; otherwise set to nan
big = np.where(poc_in, dsd_poc, np.nan)
small_vah = np.where(vah_in, dsd_vah, np.nan)
small_val = np.where(val_in, dsd_val, np.nan)
stacked_dsd = np.stack([big, small_vah, small_val], axis=1)
has_any_in_dir = (~np.isnan(stacked_dsd)).any(axis=1)
with np.errstate(invalid='ignore'):
    min_dsd_in_dir = np.where(has_any_in_dir, np.nanmin(np.where(np.isnan(stacked_dsd), np.inf, stacked_dsd), axis=1), np.nan)
    max_dsd_in_dir = np.where(has_any_in_dir, np.nanmax(np.where(np.isnan(stacked_dsd), -np.inf, stacked_dsd), axis=1), np.nan)
df = df.with_columns([
    pl.Series('min_dsd_in_dir', min_dsd_in_dir),
    pl.Series('max_dsd_in_dir', max_dsd_in_dir),
    pl.Series('has_any_in_dir', has_any_in_dir),
])

# Bucket trades with >=1 in-dir target by freshness of the freshest target.
freshness_rows = []
df_anyvp = df.filter(pl.col('has_any_in_dir'))
print(f'   restricted to trades with >=1 in-dir VP target: n={df_anyvp.height}')
for lbl, expr in [
    ('fresh (min_dsd==1)', pl.col('min_dsd_in_dir') == 1),
    ('recent (min_dsd 2-4)', (pl.col('min_dsd_in_dir') >= 2) & (pl.col('min_dsd_in_dir') <= 4)),
    ('stale (min_dsd 5-30)', (pl.col('min_dsd_in_dir') >= 5) & (pl.col('min_dsd_in_dir') <= 30)),
    ('very stale (>30, incl inception)', pl.col('min_dsd_in_dir') > 30),
]:
    sub = df_anyvp.filter(expr)
    sub_is, sub_oos = is_oos_split(sub)
    n_is, r_is = cell(sub_is)
    n_oos, r_oos = cell(sub_oos)
    freshness_rows.append({
        'freshness': lbl,
        'n_IS': n_is, 'hit_2R_IS': r_is,
        'lift_IS_pp': (r_is - is_base) * 100 if r_is is not None else None,
        'n_OOS': n_oos, 'hit_2R_OOS': r_oos,
        'lift_OOS_pp': (r_oos - oos_base) * 100 if r_oos is not None else None,
    })

fresh = pl.DataFrame(freshness_rows)
fresh.write_csv(OUT / 'freshness_vs_hit_2R.csv')
print(fresh.to_pandas().to_string(index=False))


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------
print('\n' + '=' * 72)
print('VERDICT')
print('=' * 72)
print(f'Chosen naked threshold N = {BEST_N}')
print(f'n_vp_targets>=2 OOS lift   = {vp_ge2_oos_lift:+.2f}pp  (n={vp_ge2_oos_n})')
print(f'n_naked_vp>=2 OOS lift     = {naked_ge2_oos_lift:+.2f}pp  (n={naked_ge2_oos_n})')
print(f'delta                      = {delta:+.2f}pp (need >= +{KILL_LIFT_FLOOR_PP}pp to be a real refinement)')
if kill:
    print('\nVERDICT: KILL — naked refinement does NOT meaningfully lift OOS hit_2R.')
    print('         n_vp_targets remains the cleaner story.')
else:
    print('\nVERDICT: SURVIVE — naked refinement lifts OOS hit_2R by >=+5pp.')
    print('         Recommend adopting n_naked_vp_targets as the cleaner filter.')
print('=' * 72)
