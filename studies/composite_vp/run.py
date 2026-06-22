"""
Multi-Day Composite Volume Profile Study.

Tests whether a rolling 5-/10-/20-day composite POC/VAH/VAL is a stronger
hit_2R signal than yesterday's single-day VP (Phase A's n_vp_targets).

Splits:
  IS  = year <= 2022
  OOS = year >= 2023

Buckets are STRUCTURAL (0 / 1 / 2 / 3+) — no threshold tuning touches OOS.

Outputs:
  results/hit_2R_by_window.csv     — bucket × window walk-forward table
  results/vs_yesterday.csv         — side-by-side rank summary
  results/additivity.csv           — composite × yesterday cells
  results/dow_stability.csv        — bucket lift by day-of-week
  results/year_by_year.csv         — best window: top bucket yearly hit_2R
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
TARGET_R_LO = 0.5
TARGET_R_HI = 3.0
WINDOWS = ('1d', '5d', '10d', '20d')  # '1d' = yesterday's VP (canonical Phase A)
KILL_LIFT_FLOOR_PP = 3.0  # composite must beat yesterday by >= +3pp on hit_2R OOS top bucket

# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------
trades = (
    pl.read_csv(ROOT / 'studies/baseline/results/trades.csv', try_parse_dates=True)
    .filter(pl.col('outcome') != 'skip')
)

vp1 = pl.read_csv(ROOT / 'data/levels/daily_volume_profile.csv', try_parse_dates=True)
vp1 = vp1.rename({'poc': 'poc_1d', 'vah': 'vah_1d', 'val': 'val_1d',
                  'rth_volume': 'vol_1d', 'va_width': 'va_width_1d'})

vpC = pl.read_csv(OUT / 'composite_vp_levels.csv', try_parse_dates=True)

trades = trades.with_columns([
    pl.col('timestamp').dt.date().alias('date'),
    pl.col('timestamp').dt.year().alias('year'),
    pl.col('timestamp').dt.weekday().alias('dow'),  # 1=Mon
])
trades = trades.with_columns([
    (pl.col('year') <= IS_MAX_YEAR).alias('is_in_is'),
    (pl.col('year') >= OOS_MIN_YEAR).alias('is_in_oos'),
])

# Phase A uses yesterday's VP — but daily_volume_profile.csv stores TODAY's VP per row.
# To stay strictly causal we shift the level CSV forward by one trading day so
# the row joined to date d carries the VP of d-1.
vp1_sorted = vp1.sort('date')
vp1_lag = vp1_sorted.with_columns(pl.col('date').shift(-1).alias('date_for'))
vp1_lag = vp1_lag.filter(pl.col('date_for').is_not_null()).drop('date').rename({'date_for': 'date'})

df = trades.join(vp1_lag, on='date', how='left').join(vpC, on='date', how='left')

# Phase A's run.py joined directly on date (TODAY's POC). That's a mild
# look-ahead. We replicate BOTH formulations and report each so the headline
# comparison is apples-to-apples with the published Phase A result.
df_todayVP = trades.join(
    vp1.rename({'poc_1d': 'poc_today', 'vah_1d': 'vah_today', 'val_1d': 'val_today',
                'vol_1d': 'vol_today', 'va_width_1d': 'va_width_today'}),
    on='date', how='left',
).join(vpC, on='date', how='left')

# ---------------------------------------------------------------------------
# Build n_targets columns for each window
# ---------------------------------------------------------------------------

def compute_n_targets(frame: pl.DataFrame, suffix: str, poc_c: str, vah_c: str, val_c: str) -> pl.DataFrame:
    sl = frame['sl_dist'].to_numpy().astype(float)
    is_long = (frame['direction'].to_numpy() == 'long')
    ep = frame['entry_price'].to_numpy().astype(float)

    def r_signed(col):
        lvl = frame[col].to_numpy().astype(float)
        diff = lvl - ep
        return np.where(is_long, diff, -diff) / sl

    def in_zone(rs):
        with np.errstate(invalid='ignore'):
            return (rs >= TARGET_R_LO) & (rs <= TARGET_R_HI)

    r_poc = r_signed(poc_c)
    r_vah = r_signed(vah_c)
    r_val = r_signed(val_c)
    poc_in = in_zone(r_poc)
    vah_in = in_zone(r_vah)
    val_in = in_zone(r_val)
    n = poc_in.astype(np.int32) + vah_in.astype(np.int32) + val_in.astype(np.int32)
    return frame.with_columns([
        pl.Series(f'poc_in_{suffix}', poc_in),
        pl.Series(f'vah_in_{suffix}', vah_in),
        pl.Series(f'val_in_{suffix}', val_in),
        pl.Series(f'n_vp_{suffix}', n),
    ])


# Causal (lagged) variant — every formulation uses yesterday or earlier VP.
df = compute_n_targets(df, '1d', 'poc_1d', 'vah_1d', 'val_1d')
df = compute_n_targets(df, '5d', 'poc_5d', 'vah_5d', 'val_5d')
df = compute_n_targets(df, '10d', 'poc_10d', 'vah_10d', 'val_10d')
df = compute_n_targets(df, '20d', 'poc_20d', 'vah_20d', 'val_20d')

# Phase-A-style variant where the headline 1d feature uses TODAY's VP
# (this is what the parent Phase A study reported).
df_todayVP = compute_n_targets(df_todayVP, 'today', 'poc_today', 'vah_today', 'val_today')

# ---------------------------------------------------------------------------
# Base rates
# ---------------------------------------------------------------------------
is_base = float(df.filter(pl.col('is_in_is'))[TARGET].mean())
oos_base = float(df.filter(pl.col('is_in_oos'))[TARGET].mean())
pooled_base = float(df[TARGET].mean())

print('=' * 78)
print('Composite VP Study — n_vp by rolling window')
print('=' * 78)
print(f'n_total={df.height}  pooled hit_2R={pooled_base*100:.1f}%')
print(f'IS  (year<={IS_MAX_YEAR})  n={df.filter(pl.col("is_in_is")).height}  base={is_base*100:.2f}%')
print(f'OOS (year>={OOS_MIN_YEAR}) n={df.filter(pl.col("is_in_oos")).height}  base={oos_base*100:.2f}%')
print()


def cell_summary(frame: pl.DataFrame) -> tuple[int, float | None]:
    n = frame.height
    if n == 0:
        return 0, None
    return n, float(frame[TARGET].mean())


# ---------------------------------------------------------------------------
# Bucket lift per window (walk-forward)
# ---------------------------------------------------------------------------
print('--- hit_2R lift by composite-VP bucket (walk-forward) ---')
hbw_rows = []
for w in WINDOWS:
    col = f'n_vp_{w}'
    # Drop rows with missing composite (early dates lack 5/10/20d history)
    sub = df.filter(pl.col(col).is_not_null())
    sub_is = sub.filter(pl.col('is_in_is'))
    sub_oos = sub.filter(pl.col('is_in_oos'))
    is_base_w = float(sub_is[TARGET].mean()) if sub_is.height else float('nan')
    oos_base_w = float(sub_oos[TARGET].mean()) if sub_oos.height else float('nan')

    for label, expr in [
        ('0', pl.col(col) == 0),
        ('1', pl.col(col) == 1),
        ('2', pl.col(col) == 2),
        ('3+', pl.col(col) >= 3),
    ]:
        cell_is = sub_is.filter(expr)
        cell_oos = sub_oos.filter(expr)
        n_is, r_is = cell_summary(cell_is)
        n_oos, r_oos = cell_summary(cell_oos)
        hbw_rows.append({
            'window': w,
            'bucket': label,
            'n_IS': n_is,
            'hit_2R_IS': r_is,
            'lift_IS_pp': (r_is - is_base_w) * 100 if r_is is not None else None,
            'n_OOS': n_oos,
            'hit_2R_OOS': r_oos,
            'lift_OOS_pp': (r_oos - oos_base_w) * 100 if r_oos is not None else None,
        })

hbw = pl.DataFrame(hbw_rows)
hbw.write_csv(OUT / 'hit_2R_by_window.csv')
print(hbw.to_pandas().to_string(index=False, float_format=lambda x: f'{x:.4f}' if isinstance(x, float) else str(x)))
print()

# Also include Phase A's headline 1d=TODAY-VP cell (for reference vs published number).
print('--- Phase A reference (1d = TODAY VP — same join as parent study) ---')
phaseA_rows = []
for label, expr in [
    ('0', pl.col('n_vp_today') == 0),
    ('1', pl.col('n_vp_today') == 1),
    ('2', pl.col('n_vp_today') == 2),
    ('3+', pl.col('n_vp_today') >= 3),
]:
    sub_is = df_todayVP.filter(pl.col('is_in_is') & expr)
    sub_oos = df_todayVP.filter(pl.col('is_in_oos') & expr)
    n_is, r_is = cell_summary(sub_is)
    n_oos, r_oos = cell_summary(sub_oos)
    phaseA_rows.append({
        'window': '1d_today',
        'bucket': label,
        'n_IS': n_is, 'hit_2R_IS': r_is,
        'lift_IS_pp': (r_is - is_base) * 100 if r_is is not None else None,
        'n_OOS': n_oos, 'hit_2R_OOS': r_oos,
        'lift_OOS_pp': (r_oos - oos_base) * 100 if r_oos is not None else None,
    })
phaseA = pl.DataFrame(phaseA_rows)
print(phaseA.to_pandas().to_string(index=False, float_format=lambda x: f'{x:.4f}' if isinstance(x, float) else str(x)))
print()


# ---------------------------------------------------------------------------
# Side-by-side rank summary: max hit_2R bucket per window, monotonicity, year-consistency
# ---------------------------------------------------------------------------
print('--- vs_yesterday: top-bucket comparison ---')
vy_rows = []
for w in WINDOWS:
    col = f'n_vp_{w}'
    sub = df.filter(pl.col(col).is_not_null())
    sub_is_all = sub.filter(pl.col('is_in_is'))
    sub_oos_all = sub.filter(pl.col('is_in_oos'))
    is_base_w = float(sub_is_all[TARGET].mean()) if sub_is_all.height else float('nan')
    oos_base_w = float(sub_oos_all[TARGET].mean()) if sub_oos_all.height else float('nan')

    # Top-bucket (n>=2) cohort — Phase A's "magnet" trade.
    top_is = sub_is_all.filter(pl.col(col) >= 2)
    top_oos = sub_oos_all.filter(pl.col(col) >= 2)
    n_is, r_is = cell_summary(top_is)
    n_oos, r_oos = cell_summary(top_oos)

    # Monotonicity check on IS only (no peeking at OOS).
    is_rates = []
    for k in (0, 1, 2, 3):
        c = sub_is_all.filter(pl.col(col) == k) if k < 3 else sub_is_all.filter(pl.col(col) >= 3)
        if c.height:
            is_rates.append(float(c[TARGET].mean()))
        else:
            is_rates.append(float('nan'))
    # Strict monotone-increasing?  (ignore nan buckets)
    mono = all(
        (np.isnan(is_rates[i]) or np.isnan(is_rates[i + 1]) or is_rates[i + 1] >= is_rates[i])
        for i in range(len(is_rates) - 1)
    )

    # Year-by-year IS positive lift count for top bucket
    top_is_pd = top_is.with_columns(pl.col('timestamp').dt.year().alias('y'))
    if top_is_pd.height:
        ann = (
            top_is_pd.group_by('y')
            .agg([pl.len().alias('n'), pl.col(TARGET).mean().alias('hr')])
            .sort('y')
        )
        years_total = ann.height
        # Need year-base from full IS frame
        base_ann = sub_is_all.with_columns(pl.col('timestamp').dt.year().alias('y')).group_by('y').agg(pl.col(TARGET).mean().alias('base_hr')).sort('y')
        ann = ann.join(base_ann, on='y', how='left')
        years_pos = int((ann['hr'] > ann['base_hr']).sum())
    else:
        years_total = 0
        years_pos = 0

    vy_rows.append({
        'window': w,
        'IS_base_pct': is_base_w * 100,
        'top_bucket': '>=2',
        'IS_n': n_is,
        'IS_hit_2R_pct': r_is * 100 if r_is is not None else None,
        'IS_lift_pp': (r_is - is_base_w) * 100 if r_is is not None else None,
        'IS_mono_increasing': mono,
        'IS_years_pos': f'{years_pos}/{years_total}',
        'OOS_base_pct': oos_base_w * 100,
        'OOS_n': n_oos,
        'OOS_hit_2R_pct': r_oos * 100 if r_oos is not None else None,
        'OOS_lift_pp': (r_oos - oos_base_w) * 100 if r_oos is not None else None,
    })
vy = pl.DataFrame(vy_rows)
vy.write_csv(OUT / 'vs_yesterday.csv')
print(vy.to_pandas().to_string(index=False, float_format=lambda x: f'{x:.2f}' if isinstance(x, float) else str(x)))
print()


# ---------------------------------------------------------------------------
# Pick best composite window from IS only, then OOS test
# ---------------------------------------------------------------------------
print('--- IS window selection → OOS validation ---')
# Composite candidates: 5d / 10d / 20d. Selection metric: IS top-bucket lift_pp.
comp_candidates = ('5d', '10d', '20d')
is_scores = {
    w: float(vy.filter(pl.col('window') == w)['IS_lift_pp'][0])
    for w in comp_candidates
}
best_w = max(is_scores, key=is_scores.get)
yest_is_lift = float(vy.filter(pl.col('window') == '1d')['IS_lift_pp'][0])
yest_oos_lift = float(vy.filter(pl.col('window') == '1d')['OOS_lift_pp'][0])
best_oos_lift = float(vy.filter(pl.col('window') == best_w)['OOS_lift_pp'][0])

print(f'IS top-bucket lifts: {is_scores}')
print(f'best-IS-window: {best_w}  (IS lift {is_scores[best_w]:+.2f}pp)')
print(f'yesterday-VP (causal lag) IS lift {yest_is_lift:+.2f}pp, OOS lift {yest_oos_lift:+.2f}pp')
print(f'{best_w} OOS lift {best_oos_lift:+.2f}pp')
delta_vs_yest_oos = best_oos_lift - yest_oos_lift
print(f'\nΔ(best_composite − yesterday) OOS lift = {delta_vs_yest_oos:+.2f}pp')
print(f'Kill criterion: delta < +{KILL_LIFT_FLOOR_PP:.1f}pp → composite NOT canonical')
verdict = 'PASS — composite beats yesterday' if delta_vs_yest_oos >= KILL_LIFT_FLOOR_PP else 'FAIL — single-day VP remains canonical'
print(f'Verdict: {verdict}')
print()


# ---------------------------------------------------------------------------
# Additivity: composite-AND-yesterday cells
# ---------------------------------------------------------------------------
print(f'--- Additivity (best window = {best_w}) ---')
col_yest = 'n_vp_1d'
col_comp = f'n_vp_{best_w}'
df_ay = df.filter(pl.col(col_yest).is_not_null() & pl.col(col_comp).is_not_null())

add_rows = []
for yest_label, yest_expr in [('y_lo (0-1)', pl.col(col_yest) <= 1), ('y_hi (>=2)', pl.col(col_yest) >= 2)]:
    for comp_label, comp_expr in [('c_lo (0-1)', pl.col(col_comp) <= 1), ('c_hi (>=2)', pl.col(col_comp) >= 2)]:
        cell = df_ay.filter(yest_expr & comp_expr)
        c_is = cell.filter(pl.col('is_in_is'))
        c_oos = cell.filter(pl.col('is_in_oos'))
        n_is, r_is = cell_summary(c_is)
        n_oos, r_oos = cell_summary(c_oos)
        add_rows.append({
            'cell': f'{yest_label} × {comp_label}',
            'n_IS': n_is,
            'hit_2R_IS': r_is,
            'lift_IS_pp': (r_is - is_base) * 100 if r_is is not None else None,
            'n_OOS': n_oos,
            'hit_2R_OOS': r_oos,
            'lift_OOS_pp': (r_oos - oos_base) * 100 if r_oos is not None else None,
        })
add = pl.DataFrame(add_rows)
add.write_csv(OUT / 'additivity.csv')
print(add.to_pandas().to_string(index=False, float_format=lambda x: f'{x:.4f}' if isinstance(x, float) else str(x)))
print()


# ---------------------------------------------------------------------------
# Day-of-week stability (best window)
# ---------------------------------------------------------------------------
print(f'--- DoW stability (top-bucket n_vp_{best_w} >= 2) ---')
top = df.filter(pl.col(col_comp) >= 2)
dow_rows = []
dow_names = {1: 'Mon', 2: 'Tue', 3: 'Wed', 4: 'Thu', 5: 'Fri'}
for d in (1, 2, 3, 4, 5):
    cell = top.filter(pl.col('dow') == d)
    base_cell = df.filter(pl.col('dow') == d)
    base_rate = float(base_cell[TARGET].mean()) if base_cell.height else float('nan')
    n_cell = cell.height
    r_cell = float(cell[TARGET].mean()) if n_cell else float('nan')
    dow_rows.append({
        'dow': dow_names[d],
        'n_all_dow': base_cell.height,
        'base_hit_2R_pct': base_rate * 100,
        'n_top_dow': n_cell,
        'top_hit_2R_pct': r_cell * 100,
        'lift_pp': (r_cell - base_rate) * 100,
    })
dow = pl.DataFrame(dow_rows)
dow.write_csv(OUT / 'dow_stability.csv')
print(dow.to_pandas().to_string(index=False, float_format=lambda x: f'{x:.2f}' if isinstance(x, float) else str(x)))
print()


# ---------------------------------------------------------------------------
# Year-by-year for top bucket (best window)
# ---------------------------------------------------------------------------
print(f'--- Year-by-year hit_2R for top bucket (n_vp_{best_w} >= 2) ---')
top_year = (
    df.filter(pl.col(col_comp) >= 2)
    .with_columns(pl.col('timestamp').dt.year().alias('year'))
    .group_by('year').agg([
        pl.len().alias('n'),
        pl.col(TARGET).mean().alias('hit_2R'),
    ])
    .sort('year')
)
base_year = (
    df.with_columns(pl.col('timestamp').dt.year().alias('year'))
    .group_by('year').agg(pl.col(TARGET).mean().alias('base_hit_2R'))
    .sort('year')
)
yr = top_year.join(base_year, on='year', how='left').with_columns(
    ((pl.col('hit_2R') - pl.col('base_hit_2R')) * 100).alias('lift_pp')
)
yr.write_csv(OUT / 'year_by_year.csv')
print(yr.to_pandas().to_string(index=False, float_format=lambda x: f'{x:.4f}' if isinstance(x, float) else str(x)))
print()

print('Done. Wrote results/ {hit_2R_by_window, vs_yesterday, additivity, dow_stability, year_by_year}.csv')
