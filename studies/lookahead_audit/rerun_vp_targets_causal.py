"""
Re-run studies/vp_targets/run.py + studies/discovery_2R_hits/explore_v4.py
using STRICTLY CAUSAL VP (yesterday's POC/VAH/VAL).

The originals joined on `date`, which gave 9:30-10:15 trades access to today's
9:30-16:00 POC/VAH/VAL. This script substitutes lag-1 VP via
tools.causal_features.load_lagged_vp() and rebuilds n_vp_targets the same way.

Output: results/vp_causal_walk_forward.csv
        results/vp_causal_v4_buckets.csv
        results/headline_compare.csv     # before vs after numbers
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.causal_features import load_lagged_vp  # noqa: E402

OUT = Path(__file__).resolve().parent / 'results'
OUT.mkdir(parents=True, exist_ok=True)

TARGET = 'hit_2_0R'
IS_MAX_YEAR = 2022
OOS_MIN_YEAR = 2023
TARGET_R_LO = 0.5
TARGET_R_HI = 3.0


# ---------------------------------------------------------------------------
# Load trades
# ---------------------------------------------------------------------------
trades = (
    pl.read_csv(ROOT / 'studies/baseline/results/trades.csv', try_parse_dates=True)
    .filter(pl.col('outcome') != 'skip')
)
trades = trades.with_columns([
    pl.col('timestamp').dt.year().alias('year'),
])
trades = trades.with_columns([
    (pl.col('year') <= IS_MAX_YEAR).alias('is_in_is'),
    (pl.col('year') >= OOS_MIN_YEAR).alias('is_in_oos'),
])


def compute_n_vp(df: pl.DataFrame, poc_c: str, vah_c: str, val_c: str) -> pl.DataFrame:
    sl = df['sl_dist'].to_numpy().astype(float)
    is_long = (df['direction'].to_numpy() == 'long')
    ep = df['entry_price'].to_numpy().astype(float)

    def r_signed(col):
        lvl = df[col].to_numpy().astype(float)
        diff = lvl - ep
        return np.where(is_long, diff, -diff) / sl

    def in_zone(rs):
        with np.errstate(invalid='ignore'):
            return (rs >= TARGET_R_LO) & (rs <= TARGET_R_HI)

    r_poc, r_vah, r_val = r_signed(poc_c), r_signed(vah_c), r_signed(val_c)
    p_in, h_in, l_in = in_zone(r_poc), in_zone(r_vah), in_zone(r_val)
    n = p_in.astype(np.int32) + h_in.astype(np.int32) + l_in.astype(np.int32)
    return df.with_columns([
        pl.Series('poc_in', p_in),
        pl.Series('vah_in', h_in),
        pl.Series('val_in', l_in),
        pl.Series('n_vp_targets', n),
    ])


# ---------------------------------------------------------------------------
# (1) TODAY's VP join (lookahead — reproduces original buggy result)
# ---------------------------------------------------------------------------
vp = pl.read_csv(ROOT / 'data/levels/daily_volume_profile.csv', try_parse_dates=True)
df_today = trades.with_columns(pl.col('timestamp').dt.date().alias('date')).join(
    vp, on='date', how='left'
)
df_today = compute_n_vp(df_today, 'poc', 'vah', 'val')

# ---------------------------------------------------------------------------
# (2) Lagged VP join (CAUSAL — the right way)
# ---------------------------------------------------------------------------
df_lag = load_lagged_vp(trades)
df_lag = compute_n_vp(df_lag, 'poc_lag1', 'vah_lag1', 'val_lag1')


# ---------------------------------------------------------------------------
# Walk-forward bucket tables
# ---------------------------------------------------------------------------
def walk_forward(df: pl.DataFrame, label: str) -> pl.DataFrame:
    is_base = float(df.filter(pl.col('is_in_is'))[TARGET].mean())
    oos_base = float(df.filter(pl.col('is_in_oos'))[TARGET].mean())
    rows = []
    for bucket, expr in [
        ('0', pl.col('n_vp_targets') == 0),
        ('1', pl.col('n_vp_targets') == 1),
        ('2', pl.col('n_vp_targets') == 2),
        ('3+', pl.col('n_vp_targets') >= 3),
    ]:
        sub = df.filter(expr)
        sub_is = sub.filter(pl.col('is_in_is'))
        sub_oos = sub.filter(pl.col('is_in_oos'))
        r_is = float(sub_is[TARGET].mean()) if sub_is.height else None
        r_oos = float(sub_oos[TARGET].mean()) if sub_oos.height else None
        rows.append({
            'variant': label,
            'bucket': bucket,
            'n_IS': sub_is.height,
            'hit_2R_IS': r_is,
            'lift_IS_pp': (r_is - is_base) * 100 if r_is is not None else None,
            'n_OOS': sub_oos.height,
            'hit_2R_OOS': r_oos,
            'lift_OOS_pp': (r_oos - oos_base) * 100 if r_oos is not None else None,
        })
    return pl.DataFrame(rows)


wf_today = walk_forward(df_today, 'today_vp_LOOKAHEAD')
wf_lag = walk_forward(df_lag, 'lag1_vp_CAUSAL')
combined = pl.concat([wf_today, wf_lag])
combined.write_csv(OUT / 'vp_causal_walk_forward.csv')

print('=' * 78)
print('vp_targets re-run: today VP (lookahead) vs lag-1 VP (causal)')
print('=' * 78)
print(combined.to_pandas().to_string(index=False, float_format=lambda x: f'{x:.4f}' if isinstance(x, float) else str(x)))


# ---------------------------------------------------------------------------
# n_vp>=2 cohort headline (the published Phase A magnet)
# ---------------------------------------------------------------------------
def headline(df: pl.DataFrame) -> dict:
    is_base = float(df.filter(pl.col('is_in_is'))[TARGET].mean())
    oos_base = float(df.filter(pl.col('is_in_oos'))[TARGET].mean())
    is_cohort = df.filter(pl.col('is_in_is') & (pl.col('n_vp_targets') >= 2))
    oos_cohort = df.filter(pl.col('is_in_oos') & (pl.col('n_vp_targets') >= 2))
    r_is = float(is_cohort[TARGET].mean()) if is_cohort.height else None
    r_oos = float(oos_cohort[TARGET].mean()) if oos_cohort.height else None
    return {
        'is_base_pct': is_base * 100,
        'oos_base_pct': oos_base * 100,
        'n_is_top': is_cohort.height,
        'n_oos_top': oos_cohort.height,
        'hit_2R_IS_top_pct': r_is * 100 if r_is is not None else None,
        'hit_2R_OOS_top_pct': r_oos * 100 if r_oos is not None else None,
        'IS_lift_pp': (r_is - is_base) * 100 if r_is is not None else None,
        'OOS_lift_pp': (r_oos - oos_base) * 100 if r_oos is not None else None,
    }


head_today = headline(df_today)
head_lag = headline(df_lag)
pl.DataFrame([
    {'variant': 'today_vp_LOOKAHEAD', **head_today},
    {'variant': 'lag1_vp_CAUSAL', **head_lag},
]).write_csv(OUT / 'headline_compare.csv')

print()
print(f"Published headline (today-VP)  IS lift {head_today['IS_lift_pp']:+.2f}pp  OOS lift {head_today['OOS_lift_pp']:+.2f}pp  (n_oos_top={head_today['n_oos_top']})")
print(f"Causal (lag-1 VP)              IS lift {head_lag['IS_lift_pp']:+.2f}pp  OOS lift {head_lag['OOS_lift_pp']:+.2f}pp  (n_oos_top={head_lag['n_oos_top']})")
print()


# ---------------------------------------------------------------------------
# explore_v4.py-style 4-bucket: also include 0-target distinction
# ---------------------------------------------------------------------------
def v4_summary(df: pl.DataFrame, label: str) -> pl.DataFrame:
    base = float(df[TARGET].mean())
    is_base = float(df.filter(pl.col('is_in_is'))[TARGET].mean())
    oos_base = float(df.filter(pl.col('is_in_oos'))[TARGET].mean())

    rows = [{
        'variant': label, 'cell': 'all',
        'n': df.height, 'hit_2R_pct': base * 100,
        'n_is': df.filter(pl.col('is_in_is')).height,
        'hit_2R_IS_pct': is_base * 100,
        'n_oos': df.filter(pl.col('is_in_oos')).height,
        'hit_2R_OOS_pct': oos_base * 100,
    }]
    for cell_label, expr in [
        ('n_vp==0', pl.col('n_vp_targets') == 0),
        ('n_vp==1', pl.col('n_vp_targets') == 1),
        ('n_vp==2', pl.col('n_vp_targets') == 2),
        ('n_vp>=3', pl.col('n_vp_targets') >= 3),
        ('n_vp>=1', pl.col('n_vp_targets') >= 1),
        ('n_vp>=2', pl.col('n_vp_targets') >= 2),
    ]:
        sub = df.filter(expr)
        sub_is = sub.filter(pl.col('is_in_is'))
        sub_oos = sub.filter(pl.col('is_in_oos'))
        r = float(sub[TARGET].mean()) if sub.height else None
        r_is = float(sub_is[TARGET].mean()) if sub_is.height else None
        r_oos = float(sub_oos[TARGET].mean()) if sub_oos.height else None
        rows.append({
            'variant': label, 'cell': cell_label,
            'n': sub.height, 'hit_2R_pct': r * 100 if r is not None else None,
            'n_is': sub_is.height, 'hit_2R_IS_pct': r_is * 100 if r_is is not None else None,
            'n_oos': sub_oos.height, 'hit_2R_OOS_pct': r_oos * 100 if r_oos is not None else None,
        })
    return pl.DataFrame(rows)


v4_combined = pl.concat([
    v4_summary(df_today, 'today_vp_LOOKAHEAD'),
    v4_summary(df_lag, 'lag1_vp_CAUSAL'),
])
v4_combined.write_csv(OUT / 'vp_causal_v4_buckets.csv')

print('--- 4-bucket discovery_v4-style breakdown ---')
print(v4_combined.to_pandas().to_string(index=False, float_format=lambda x: f'{x:.2f}' if isinstance(x, float) else str(x)))
print()
print('Wrote results/{vp_causal_walk_forward, headline_compare, vp_causal_v4_buckets}.csv')
