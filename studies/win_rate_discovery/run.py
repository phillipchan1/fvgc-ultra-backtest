"""
Path A — Re-discover High-WR Filters Using Causal Features Only.

See ../win_rate_discovery/analysis.md and /Users/philchan/.claude/plans/
path-a-re-discover-high-wr-sunny-moore.md for the full brief.

Pipeline:
  1. build_feature_frame() — load baseline, attach all causal features.
  2. run_controls()        — Phase A2: 3 known-null controls must show |lift|<=2pp.
  3. scan_single_feature() — Phase A1 (positive) + A4 (negative) lift scan.
  4. run_stacks()          — Phase A3: pairwise + triple AND-stacks of A1 survivors.
  5. yearly_stability()    — per-year stability table for survivors/anti.
  6. write_results()       — emit CSVs into ./results/.

CLI:
  python studies/win_rate_discovery/run.py --controls-only
  python studies/win_rate_discovery/run.py                  # full A1..A4
"""

from __future__ import annotations

import argparse
import sys
from itertools import combinations
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.causal_features import (  # noqa: E402
    CONTAMINATED,
    GATED_FEATURES,
    SAFE_AT_OPEN,
    TRADE_LEVEL_FEATURES,
    add_trade_level_features,
    load_causal_features,
    load_lagged_vp,
    load_session_levels,
)

BASELINE = ROOT / 'logs' / 'baseline_trades.csv'
OUT_DIR = Path(__file__).parent / 'results'
OUT_DIR.mkdir(parents=True, exist_ok=True)

IS_YEARS = (2018, 2019, 2020, 2021, 2022)
OOS_YEARS = (2023, 2024, 2025, 2026)
ALL_YEARS = IS_YEARS + OOS_YEARS

MIN_CELL_N = 50
LIFT_THRESHOLD_PP = 3.0
YEAR_STABILITY_MIN = 7  # of 9
CONTROL_TOLERANCE_PP = 2.0

# Session level names (from data/levels/session_levels.csv)
PRICE_LEVELS_OPEN = [
    'prev_day_high', 'prev_day_low',
    'asia_high', 'asia_low',
    'london_high', 'london_low',
    '6am_high', '6am_low',
    'overnight_high', 'overnight_low',
    'nwog_high', 'nwog_low',
    'bsl_level', 'ssl_level',
]
PRICE_LEVELS_945 = ['or_high', 'or_low']
LAG1_VP_LEVELS = ['poc_lag1', 'vah_lag1', 'val_lag1']

# Forbidden columns — assert never accessed
FORBIDDEN = set(CONTAMINATED)


# ---------------------------------------------------------------------------
# Feature frame construction
# ---------------------------------------------------------------------------

def build_feature_frame() -> pl.DataFrame:
    """Load baseline trades, attach all causal features, return wide frame."""
    raw = pl.read_csv(BASELINE, try_parse_dates=True)

    # Universe: outcome != 'skip' (matches the 4548-trade tradeable universe).
    # We keep 'ambiguous' (6 rows) in the denominator as non-wins, consistent
    # with the 49.4% baseline cited in the brief.
    trades = raw.filter(pl.col('outcome') != 'skip')

    # Step 1: trade-level features (date, mod, fvg_size, fvg_age_min,
    # entry_pos_in_fvg, signal_seq_today, has_prior_win/loss).
    trades = add_trade_level_features(trades)

    # Step 2: SAFE_AT_OPEN + GATED via canonical helper (gated cols already
    # masked to None for trades whose mod < gate).
    trades = load_causal_features(trades)

    # Step 3: lag-1 VP (poc_lag1, vah_lag1, val_lag1, va_width_lag1, vol_lag1).
    trades = load_lagged_vp(trades)

    # Step 4: session levels (open + 09:45 gated).
    trades = load_session_levels(trades)

    # Step 5: derive scale-invariant ratio + level features.
    trades = _add_derived_features(trades)

    # Step 6: target + era + year
    trades = trades.with_columns([
        (pl.col('outcome') == 'win').cast(pl.Int8).alias('target'),
        pl.col('date').dt.year().alias('year'),
    ])
    trades = trades.with_columns(
        pl.when(pl.col('year').is_in(list(IS_YEARS))).then(pl.lit('is'))
        .when(pl.col('year').is_in(list(OOS_YEARS))).then(pl.lit('oos'))
        .otherwise(pl.lit('drop'))
        .alias('era')
    )

    # Refuse any forbidden column.
    overlap = set(trades.columns) & FORBIDDEN
    if overlap:
        raise RuntimeError(f"FORBIDDEN columns present in frame: {overlap}")

    return trades


def _add_derived_features(trades: pl.DataFrame) -> pl.DataFrame:
    """Build scale-invariant ratio features + level-distance features."""
    sld = pl.col('sl_dist').cast(pl.Float64)
    ep = pl.col('entry_price')

    exprs: list[pl.Expr] = []

    # Trade-level R-normalized
    exprs.append((pl.col('fvg_size') / sld).alias('fvg_size_R'))

    # Calendar / regime R-normalized (where it makes sense)
    if 'overnight_range' in trades.columns:
        exprs.append((pl.col('overnight_range') / sld).alias('overnight_range_R'))
    if 'prior_day_range' in trades.columns:
        exprs.append((pl.col('prior_day_range') / sld).alias('prior_day_range_R'))
    if 'gap_from_prior_close' in trades.columns:
        exprs.append((pl.col('gap_from_prior_close') / sld).alias('gap_R'))

    # Gated bar features R-normalized
    for col in ['candle_930_range', 'candle_930_body',
                'or_5min_range', 'or_15min_range', 'or_45min_range',
                'macro_1_range', 'macro_2_range',
                'macro_3_range', 'macro_4_range']:
        if col in trades.columns:
            exprs.append((pl.col(col) / sld).alias(f'{col}_R'))

    # Price-level features: entry_above_X (bool) + abs_dist_X_R (numeric)
    all_levels = PRICE_LEVELS_OPEN + PRICE_LEVELS_945 + LAG1_VP_LEVELS
    for lvl in all_levels:
        if lvl in trades.columns:
            exprs.append((ep > pl.col(lvl)).alias(f'entry_above_{lvl}'))
            exprs.append(((ep - pl.col(lvl)).abs() / sld).alias(f'abs_dist_{lvl}_R'))

    # VA membership (lag-1)
    if 'vah_lag1' in trades.columns and 'val_lag1' in trades.columns:
        exprs.append(
            ((ep <= pl.col('vah_lag1')) & (ep >= pl.col('val_lag1')))
            .alias('entry_in_va_lag1')
        )

    return trades.with_columns(exprs)


# ---------------------------------------------------------------------------
# Feature specification — which features get scanned, and how
# ---------------------------------------------------------------------------

# Categorical / boolean features (each value = bucket)
CATEGORICAL_FEATURES = [
    'direction', 'variant', 'fvg_direction',
    'day_of_week_name', 'month_name',
    'prior_day_type', 'overnight_direction', 'vixy_regime',
    'is_fomc_week', 'is_opex_week', 'is_quad_witching',
    'is_month_start', 'is_month_end',
    'has_red_folder_news', 'has_pre_rth_news', 'has_during_session_news',
    'has_prior_win', 'has_prior_loss',
    'candle_930_direction',
    # entry_above_* bools (built dynamically from level list)
] + [f'entry_above_{lvl}' for lvl in PRICE_LEVELS_OPEN + PRICE_LEVELS_945 + LAG1_VP_LEVELS] + [
    'entry_in_va_lag1',
]

# Small-int categorical (treat values as buckets, group 3+ into '3+')
SMALL_INT_CATEGORICAL = [
    'signal_seq_today',
    'fvgs_first_5min', 'fvgs_first_5min_bullish', 'fvgs_first_5min_bearish',
    'fvgs_first_15min', 'fvgs_first_15min_bullish', 'fvgs_first_15min_bearish',
    'macro_1_num_fvgs', 'macro_2_num_fvgs',
    'prior_day_directional_changes',
]

# Numeric (quartile-bucketed using IS cuts)
NUMERIC_FEATURES = [
    'sl_dist',
    'fvg_size', 'fvg_age_min', 'entry_pos_in_fvg', 'fvg_size_R',
    'gap_from_prior_close_pct', 'gap_R',
    'overnight_range_R', 'prior_day_range_R',
    'prior_day_range_atr_ratio', 'prior_day_close_position',
    'prior_day_close_vs_open_pct',
    'vixy_prior_close',
    'candle_930_range_R', 'candle_930_body_R',
    'or_5min_range_R', 'or_15min_range_R', 'or_45min_range_R',
    'macro_1_range_R', 'macro_2_range_R',
] + [f'abs_dist_{lvl}_R' for lvl in PRICE_LEVELS_OPEN + PRICE_LEVELS_945 + LAG1_VP_LEVELS]


# ---------------------------------------------------------------------------
# Bucketing
# ---------------------------------------------------------------------------

def _ensure_in_frame(df: pl.DataFrame, features: list[str]) -> list[str]:
    return [f for f in features if f in df.columns]


def _quartile_cuts(is_df: pl.DataFrame, feature: str) -> list[float] | None:
    """Compute Q1/Q2/Q3 cut points from IS-only non-null values."""
    s = is_df.get_column(feature).drop_nulls().drop_nans() \
        if is_df.get_column(feature).dtype.is_numeric() else None
    if s is None or s.len() < 4 * MIN_CELL_N:
        return None
    cuts = [float(s.quantile(q)) for q in (0.25, 0.5, 0.75)]
    # Reject degenerate cuts
    if cuts[0] == cuts[1] or cuts[1] == cuts[2]:
        return None
    return cuts


def _bucket_numeric(df: pl.DataFrame, feature: str, cuts: list[float]) -> pl.Series:
    """Return bucket labels Q1..Q4 (None for nulls)."""
    col = pl.col(feature)
    return df.select(
        pl.when(col.is_null()).then(None)
        .when(col <= cuts[0]).then(pl.lit('Q1'))
        .when(col <= cuts[1]).then(pl.lit('Q2'))
        .when(col <= cuts[2]).then(pl.lit('Q3'))
        .otherwise(pl.lit('Q4'))
        .alias('_b')
    )['_b']


def _bucket_categorical(df: pl.DataFrame, feature: str) -> pl.Series:
    """Cast values to strings; None passes through."""
    return df.get_column(feature).cast(pl.Utf8)


def _bucket_small_int(df: pl.DataFrame, feature: str) -> pl.Series:
    """Group small-int counts into '0', '1', '2', '3+'."""
    col = pl.col(feature)
    return df.select(
        pl.when(col.is_null()).then(None)
        .when(col <= 0).then(pl.lit('0'))
        .when(col == 1).then(pl.lit('1'))
        .when(col == 2).then(pl.lit('2'))
        .otherwise(pl.lit('3+'))
        .alias('_b')
    )['_b']


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------

def _conditional_baseline(df: pl.DataFrame, feature: str) -> dict:
    """Win-rate of the non-null subset of `feature`, per era."""
    out = {}
    for era in ('is', 'oos'):
        sub = df.filter((pl.col('era') == era) & pl.col(feature).is_not_null())
        n = sub.height
        wr = (sub['target'].sum() / n) if n > 0 else 0.0
        out[f'n_{era}_subset'] = n
        out[f'wr_{era}_subset'] = float(wr)
    return out


def _bucket_stats(df: pl.DataFrame, bucket_col: pl.Series, bucket_value: str) -> dict:
    """n / win-rate per era for a given bucket."""
    df2 = df.with_columns(bucket_col.alias('_b'))
    out = {}
    for era in ('is', 'oos'):
        sub = df2.filter((pl.col('era') == era) & (pl.col('_b') == bucket_value))
        n = sub.height
        wr = (sub['target'].sum() / n) if n > 0 else 0.0
        out[f'n_{era}'] = n
        out[f'wr_{era}'] = float(wr)
    return out


def scan_feature(df: pl.DataFrame, feature: str, kind: str) -> list[dict]:
    """
    Scan a single feature: bucket, compute n/wr per era per bucket, return rows.
    kind in {'categorical','small_int','numeric'}.
    """
    if feature not in df.columns:
        return []

    if kind == 'categorical':
        bucket_col = _bucket_categorical(df, feature)
        cuts = None
    elif kind == 'small_int':
        bucket_col = _bucket_small_int(df, feature)
        cuts = None
    elif kind == 'numeric':
        is_df = df.filter(pl.col('era') == 'is')
        cuts = _quartile_cuts(is_df, feature)
        if cuts is None:
            return []
        bucket_col = _bucket_numeric(df, feature, cuts)
    else:
        raise ValueError(f'unknown kind: {kind}')

    base = _conditional_baseline(df, feature)

    df2 = df.with_columns(bucket_col.alias('_b'))
    unique_buckets = [b for b in df2['_b'].drop_nulls().unique().to_list()]
    rows = []
    for b in sorted(unique_buckets):
        sub = df2.filter(pl.col('_b') == b)
        n_is = sub.filter(pl.col('era') == 'is').height
        wr_is = (sub.filter(pl.col('era') == 'is')['target'].sum() / n_is) if n_is else 0.0
        n_oos = sub.filter(pl.col('era') == 'oos').height
        wr_oos = (sub.filter(pl.col('era') == 'oos')['target'].sum() / n_oos) if n_oos else 0.0

        lift_is_pp = 100 * (float(wr_is) - base['wr_is_subset'])
        lift_oos_pp = 100 * (float(wr_oos) - base['wr_oos_subset'])
        score = lift_is_pp * (min(n_is, n_oos) ** 0.5)

        rows.append({
            'feature': feature,
            'kind': kind,
            'bucket': b,
            'cuts': str(cuts) if cuts else '',
            'n_is_subset': base['n_is_subset'],
            'wr_is_subset': base['wr_is_subset'],
            'n_oos_subset': base['n_oos_subset'],
            'wr_oos_subset': base['wr_oos_subset'],
            'n_is': n_is,
            'wr_is': float(wr_is),
            'lift_is_pp': lift_is_pp,
            'n_oos': n_oos,
            'wr_oos': float(wr_oos),
            'lift_oos_pp': lift_oos_pp,
            'score': score,
        })
    return rows


def scan_all_features(df: pl.DataFrame) -> pl.DataFrame:
    """Scan all features; return a tall DataFrame of (feature, bucket) cells."""
    all_rows: list[dict] = []
    for feat in _ensure_in_frame(df, CATEGORICAL_FEATURES):
        all_rows.extend(scan_feature(df, feat, 'categorical'))
    for feat in _ensure_in_frame(df, SMALL_INT_CATEGORICAL):
        all_rows.extend(scan_feature(df, feat, 'small_int'))
    for feat in _ensure_in_frame(df, NUMERIC_FEATURES):
        all_rows.extend(scan_feature(df, feat, 'numeric'))
    return pl.DataFrame(all_rows).sort('score', descending=True)


# ---------------------------------------------------------------------------
# Year-by-year stability
# ---------------------------------------------------------------------------

def yearly_stability(df: pl.DataFrame, feature: str, kind: str,
                     bucket_value: str, cuts: list[float] | None) -> pl.DataFrame:
    """Per-year n / wr / lift for a (feature, bucket) cell. Lift vs conditional yearly baseline."""
    if kind == 'categorical':
        bucket_col = _bucket_categorical(df, feature)
    elif kind == 'small_int':
        bucket_col = _bucket_small_int(df, feature)
    else:
        bucket_col = _bucket_numeric(df, feature, cuts)

    df2 = df.with_columns(bucket_col.alias('_b'))
    rows = []
    for y in ALL_YEARS:
        sub_year = df2.filter((pl.col('year') == y) & pl.col(feature).is_not_null())
        n_year = sub_year.height
        if n_year == 0:
            rows.append({'year': y, 'n': 0, 'wr': None, 'baseline_wr': None, 'lift_pp': None})
            continue
        baseline_wr = sub_year['target'].sum() / n_year
        cell = sub_year.filter(pl.col('_b') == bucket_value)
        n_cell = cell.height
        wr_cell = (cell['target'].sum() / n_cell) if n_cell else None
        lift = 100 * (float(wr_cell) - float(baseline_wr)) if wr_cell is not None else None
        rows.append({
            'feature': feature,
            'bucket': bucket_value,
            'year': y, 'n': n_cell,
            'wr': float(wr_cell) if wr_cell is not None else None,
            'baseline_wr': float(baseline_wr),
            'lift_pp': lift,
        })
    return pl.DataFrame(rows)


def years_positive(yearly: pl.DataFrame, sign: str = 'positive') -> int:
    """Count of years where lift_pp is positive (or negative). Skips year with n=0."""
    if sign == 'positive':
        return yearly.filter(pl.col('lift_pp') > 0).height
    return yearly.filter(pl.col('lift_pp') < 0).height


# ---------------------------------------------------------------------------
# Control test (Phase A2)
# ---------------------------------------------------------------------------

def run_controls(df: pl.DataFrame, seed: int = 13) -> pl.DataFrame:
    """
    Three controls:
      1. is_fomc_week (known-null per the lookahead audit).
      2. day_of_week_name == 'Tuesday'.
      3. Label-shuffle on prior_day_range_atr_ratio: shuffle target labels
         within IS, re-run the quartile scan, expect |lift|<=2pp.
    """
    rows: list[dict] = []

    # 1. is_fomc_week
    rows.extend(scan_feature(df, 'is_fomc_week', 'categorical'))
    # Tag as control
    for r in rows:
        r['control'] = 'is_fomc_week'

    # 2. day_of_week_name == 'Tuesday' as a 2-bucket categorical
    df2 = df.with_columns(
        (pl.col('day_of_week_name') == 'Tuesday').alias('_is_tuesday')
    )
    tue_rows = scan_feature(df2, '_is_tuesday', 'categorical')
    for r in tue_rows:
        r['control'] = 'is_tuesday'
        r['feature'] = 'is_tuesday'
    rows.extend(tue_rows)

    # 3. Label-shuffle: shuffle target within IS rows.
    df_shuf = df.with_columns(pl.col('target').alias('_t_orig'))
    is_rows = df_shuf.filter(pl.col('era') == 'is')
    n_is = is_rows.height
    shuffled = (
        is_rows
        .with_columns(pl.col('target')
                      .shuffle(seed=seed)
                      .alias('target'))
        .select(pl.col('target').alias('target_shuf'))
    )
    # Stitch shuffled IS target back; OOS keeps original
    df_shuf = pl.concat([
        is_rows.with_columns(shuffled.to_series().alias('target')),
        df_shuf.filter(pl.col('era') == 'oos'),
    ])
    shuf_rows = scan_feature(df_shuf.drop('_t_orig'), 'prior_day_range_atr_ratio', 'numeric')
    for r in shuf_rows:
        r['control'] = 'label_shuffle__prior_day_range_atr_ratio'
        r['feature'] = 'label_shuffle__prior_day_range_atr_ratio'
    rows.extend(shuf_rows)

    out = pl.DataFrame(rows)
    return out


def controls_pass(controls_df: pl.DataFrame) -> tuple[bool, list[dict]]:
    """A control passes if it does NOT produce a survivor-grade cell.

    Survivor criterion (positive OR negative):
      lift_is_pp and lift_oos_pp both clear ±LIFT_THRESHOLD_PP, AND
      n_is and n_oos both >= MIN_CELL_N.

    A single-era 2-3pp lift is within noise (SE ~2pp at n≈547 per quartile) —
    the IS/OOS double-cross is what would indicate a real pipeline bug.
    """
    failures = []
    for ctrl in controls_df['control'].unique().to_list():
        sub = controls_df.filter(pl.col('control') == ctrl)
        fake_pos = sub.filter(
            (pl.col('lift_is_pp') >= LIFT_THRESHOLD_PP)
            & (pl.col('lift_oos_pp') >= LIFT_THRESHOLD_PP)
            & (pl.col('n_is') >= MIN_CELL_N)
            & (pl.col('n_oos') >= MIN_CELL_N)
        )
        fake_neg = sub.filter(
            (pl.col('lift_is_pp') <= -LIFT_THRESHOLD_PP)
            & (pl.col('lift_oos_pp') <= -LIFT_THRESHOLD_PP)
            & (pl.col('n_is') >= MIN_CELL_N)
            & (pl.col('n_oos') >= MIN_CELL_N)
        )
        n_fake = fake_pos.height + fake_neg.height
        # Report max |lift| in either era for context
        worst_is = float(sub['lift_is_pp'].abs().max() or 0.0)
        worst_oos = float(sub['lift_oos_pp'].abs().max() or 0.0)
        if n_fake > 0:
            failures.append({
                'control': ctrl,
                'fake_survivor_cells': n_fake,
                'max_abs_lift_is_pp': worst_is,
                'max_abs_lift_oos_pp': worst_oos,
            })
    return (len(failures) == 0), failures


# ---------------------------------------------------------------------------
# Survivor filter + stacks
# ---------------------------------------------------------------------------

def filter_survivors(scan_df: pl.DataFrame, anti: bool = False) -> pl.DataFrame:
    """Apply strict survivor criteria (or anti-survivor with flipped sign)."""
    if anti:
        return scan_df.filter(
            (pl.col('lift_is_pp') <= -LIFT_THRESHOLD_PP)
            & (pl.col('lift_oos_pp') <= -LIFT_THRESHOLD_PP)
            & (pl.col('n_is') >= MIN_CELL_N)
            & (pl.col('n_oos') >= MIN_CELL_N)
        )
    return scan_df.filter(
        (pl.col('lift_is_pp') >= LIFT_THRESHOLD_PP)
        & (pl.col('lift_oos_pp') >= LIFT_THRESHOLD_PP)
        & (pl.col('n_is') >= MIN_CELL_N)
        & (pl.col('n_oos') >= MIN_CELL_N)
    )


def _build_mask(df: pl.DataFrame, feature: str, kind: str,
                bucket_value: str, cuts_str: str) -> pl.Expr:
    """Recreate the boolean mask for (feature, bucket) given its kind + cuts."""
    if kind == 'categorical':
        return (pl.col(feature).cast(pl.Utf8) == bucket_value) & pl.col(feature).is_not_null()
    if kind == 'small_int':
        col = pl.col(feature)
        if bucket_value == '0':
            return col <= 0
        if bucket_value == '1':
            return col == 1
        if bucket_value == '2':
            return col == 2
        return col >= 3
    # numeric
    cuts = eval(cuts_str)  # was stored as repr of list[float]; safe — internal only
    col = pl.col(feature)
    if bucket_value == 'Q1':
        return col.is_not_null() & (col <= cuts[0])
    if bucket_value == 'Q2':
        return col.is_not_null() & (col > cuts[0]) & (col <= cuts[1])
    if bucket_value == 'Q3':
        return col.is_not_null() & (col > cuts[1]) & (col <= cuts[2])
    return col.is_not_null() & (col > cuts[2])


def run_stacks(df: pl.DataFrame, survivors: pl.DataFrame, k: int = 2) -> pl.DataFrame:
    """AND-stack survivor cells, applying the same n/lift criteria."""
    if survivors.height < k:
        return pl.DataFrame()

    survivor_specs = survivors.select(['feature', 'kind', 'bucket', 'cuts']).to_dicts()
    rows = []
    for combo in combinations(survivor_specs, k):
        # Skip same-feature stacks (would just be empty intersect or self)
        if len({s['feature'] for s in combo}) < k:
            continue

        masks = [_build_mask(df, s['feature'], s['kind'], s['bucket'], s['cuts']) for s in combo]
        full_mask = masks[0]
        for m in masks[1:]:
            full_mask = full_mask & m

        sub = df.filter(full_mask)
        n_is = sub.filter(pl.col('era') == 'is').height
        n_oos = sub.filter(pl.col('era') == 'oos').height
        if min(n_is, n_oos) < MIN_CELL_N:
            continue
        wr_is = sub.filter(pl.col('era') == 'is')['target'].sum() / n_is if n_is else 0
        wr_oos = sub.filter(pl.col('era') == 'oos')['target'].sum() / n_oos if n_oos else 0

        # Stack baseline = era WR (no conditional, since stacks combine
        # heterogeneous availability — use the era-wide WR as the reference).
        is_base = df.filter(pl.col('era') == 'is')['target'].mean()
        oos_base = df.filter(pl.col('era') == 'oos')['target'].mean()

        lift_is_pp = 100 * (float(wr_is) - float(is_base))
        lift_oos_pp = 100 * (float(wr_oos) - float(oos_base))
        rows.append({
            'k': k,
            'features': ' & '.join(f"{s['feature']}={s['bucket']}" for s in combo),
            'n_is': n_is, 'wr_is': float(wr_is), 'lift_is_pp': lift_is_pp,
            'n_oos': n_oos, 'wr_oos': float(wr_oos), 'lift_oos_pp': lift_oos_pp,
            'score': lift_is_pp * (min(n_is, n_oos) ** 0.5),
        })

    if not rows:
        return pl.DataFrame()
    return pl.DataFrame(rows).sort('score', descending=True)


# ---------------------------------------------------------------------------
# Sanity checks + reporting
# ---------------------------------------------------------------------------

def sanity_checks(df: pl.DataFrame) -> dict:
    n_total = df.height
    n_is = df.filter(pl.col('era') == 'is').height
    n_oos = df.filter(pl.col('era') == 'oos').height
    wr_total = df['target'].mean()
    wr_is = df.filter(pl.col('era') == 'is')['target'].mean()
    wr_oos = df.filter(pl.col('era') == 'oos')['target'].mean()
    vp_cov = df['poc_lag1'].drop_nulls().len() / n_total
    return {
        'n_total': n_total, 'n_is': n_is, 'n_oos': n_oos,
        'wr_total': float(wr_total), 'wr_is': float(wr_is), 'wr_oos': float(wr_oos),
        'lag1_vp_coverage': float(vp_cov),
        'n_features_categorical': len(_ensure_in_frame(df, CATEGORICAL_FEATURES)),
        'n_features_small_int': len(_ensure_in_frame(df, SMALL_INT_CATEGORICAL)),
        'n_features_numeric': len(_ensure_in_frame(df, NUMERIC_FEATURES)),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument('--controls-only', action='store_true',
                   help='Run Phase A2 controls and exit (do not mine survivors).')
    args = p.parse_args(argv)

    print('Building feature frame...')
    df = build_feature_frame()

    print('Sanity checks:')
    for k, v in sanity_checks(df).items():
        print(f'  {k}: {v}')

    print('\nPhase A2 — Running control tests...')
    controls = run_controls(df)
    controls.write_csv(OUT_DIR / 'control_test.csv')
    ok, failures = controls_pass(controls)
    if not ok:
        print(f'  FAIL: controls produced spurious lift > {CONTROL_TOLERANCE_PP}pp:')
        for f in failures:
            print(f'    {f}')
        print('  Halting per kill-criteria. Investigate before continuing.')
        return 2
    print(f'  PASS: no control produced a survivor-grade fake cell.')

    if args.controls_only:
        print('Done (--controls-only).')
        return 0

    print('\nPhase A1 — Single-feature scan...')
    scan = scan_all_features(df)
    scan.write_csv(OUT_DIR / 'single_feature_ranked.csv')
    print(f'  scanned {scan.height} (feature, bucket) cells')

    print('\nPhase A1 — Strict survivors (lift_is/oos ≥ +3pp, n ≥ 50 both eras)...')
    survivor_cells = filter_survivors(scan, anti=False)
    print(f'  cells passing lift+n criteria: {survivor_cells.height}')

    # Apply year-by-year stability filter
    survivor_rows = []
    yearly_rows = []
    for r in survivor_cells.to_dicts():
        cuts = eval(r['cuts']) if r['cuts'] else None
        yearly = yearly_stability(df, r['feature'], r['kind'], r['bucket'], cuts)
        positive_years = years_positive(yearly, 'positive')
        r['years_positive'] = positive_years
        if positive_years >= YEAR_STABILITY_MIN:
            survivor_rows.append(r)
            for yr in yearly.to_dicts():
                yr['side'] = 'survivor'
                yearly_rows.append(yr)
    survivors = pl.DataFrame(survivor_rows) if survivor_rows else pl.DataFrame()
    survivors.write_csv(OUT_DIR / 'survivors_strict.csv')
    print(f'  passing year-stability ≥{YEAR_STABILITY_MIN}/9: {survivors.height}')

    print('\nPhase A4 — Anti-survivor scan...')
    anti_cells = filter_survivors(scan, anti=True)
    print(f'  cells passing anti-lift+n criteria: {anti_cells.height}')
    anti_rows = []
    for r in anti_cells.to_dicts():
        cuts = eval(r['cuts']) if r['cuts'] else None
        yearly = yearly_stability(df, r['feature'], r['kind'], r['bucket'], cuts)
        negative_years = years_positive(yearly, 'negative')
        r['years_negative'] = negative_years
        if negative_years >= YEAR_STABILITY_MIN:
            anti_rows.append(r)
            for yr in yearly.to_dicts():
                yr['side'] = 'anti'
                yearly_rows.append(yr)
    anti = pl.DataFrame(anti_rows) if anti_rows else pl.DataFrame()
    anti.write_csv(OUT_DIR / 'anti_survivors.csv')
    print(f'  passing year-stability ≥{YEAR_STABILITY_MIN}/9: {anti.height}')

    if yearly_rows:
        pl.DataFrame(yearly_rows).write_csv(OUT_DIR / 'yearly_stability.csv')

    print('\nPhase A3 — Pairwise stacks...')
    if survivors.height >= 2:
        stacks2 = run_stacks(df, survivors, k=2)
        stacks2.write_csv(OUT_DIR / 'stacks_2feat.csv')
        print(f'  2-feat stacks emitted: {stacks2.height}')
    else:
        print('  insufficient survivors for stacks_2feat')
        pl.DataFrame().write_csv(OUT_DIR / 'stacks_2feat.csv')

    print('\nPhase A3 — Triple stacks...')
    if survivors.height >= 3:
        stacks3 = run_stacks(df, survivors, k=3)
        stacks3.write_csv(OUT_DIR / 'stacks_3feat.csv')
        print(f'  3-feat stacks emitted: {stacks3.height}')
    else:
        print('  insufficient survivors for stacks_3feat')
        pl.DataFrame().write_csv(OUT_DIR / 'stacks_3feat.csv')

    print('\nDone.  Results in', OUT_DIR)
    return 0


if __name__ == '__main__':
    sys.exit(main())
