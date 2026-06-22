"""
Canonical causal feature loader for trade-level studies.

Background
----------
A lookahead bug was discovered in `studies/discovery_2R_hits/` and
`studies/vp_targets/` (Phase A): `daily_volume_profile.csv` was joined on
`date`, giving 9:30-10:15 trades access to features computed from the full
RTH session (9:30-16:00) that hadn't happened yet at trade time. Under
strictly causal lag-1 VP, the headline +18pp OOS lift collapsed to -1.10pp.

This module is the canonical fix. Every feature it loads is tagged with
its time-of-availability (in NY local minutes-of-day). For trades that
occur BEFORE the feature is available, the value is masked to NaN.

Use it everywhere. Hand-rolled joins on `date` are the bug surface.

Public API
----------
- load_causal_features(trades, include=None) -> pl.DataFrame
- load_lagged_vp(trades) -> pl.DataFrame                    # POC/VAH/VAL of d-1
- load_session_levels(trades, names=None) -> pl.DataFrame   # from session_levels.csv
- add_trade_level_features(trades) -> pl.DataFrame          # row-level derived cols
- FEATURE_AVAILABILITY: dict[str, int]                      # column -> mod
- TRADE_LEVEL_FEATURES: dict[str, int]                      # row-level cols -> mod
- CONTAMINATED: set[str]                                    # full-session aggregates

Schema
------
trades_df must contain at minimum:
  - 'timestamp' : pl.Datetime (NY local, the trade entry time)

The returned frame has the same row order as the input, with extra columns
appended. Existing column names in trades_df are not overwritten.

Time conventions
----------------
"minute-of-day" (mod) is hour*60 + minute in NY local time.
  9:30 = 570, 9:31 = 571, 9:35 = 575, 9:45 = 585,
  10:00 = 600, 10:15 = 615, 11:10 = 670, 13:50 = 830.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
TRADING_DAYS_CSV = ROOT / 'data' / 'trading_days' / 'trading_days.csv'
DAILY_VP_CSV = ROOT / 'data' / 'levels' / 'daily_volume_profile.csv'
SESSION_LEVELS_CSV = ROOT / 'data' / 'levels' / 'session_levels.csv'


# -- Feature classification ---------------------------------------------------

# Features known at 9:30 sharp (mod=570).  Anything date-keyed from prior-day
# state or pre-RTH overseas sessions belongs here.
SAFE_AT_OPEN: dict[str, int] = {
    # 9:30 open price is set by the open; safe at mod=570.
    'rth_open': 570,
    # Calendar / news
    'day_of_week': 570, 'day_of_week_name': 570,
    'month': 570, 'month_name': 570, 'day_of_month': 570,
    'is_month_start': 570, 'is_month_end': 570,
    'is_fomc_week': 570, 'is_opex_week': 570, 'is_quad_witching': 570,
    'has_red_folder_news': 570, 'has_pre_rth_news': 570,
    'has_during_session_news': 570,  # scheduled events are known at 9:30
    'red_folder_event_names': 570,
    # Overnight session
    'overnight_high': 570, 'overnight_low': 570,
    'overnight_range': 570, 'overnight_direction': 570,
    # Gap (vs prior RTH close, known at 9:30)
    'gap_from_prior_close': 570, 'gap_from_prior_close_pct': 570,
    # Prior-day stats
    'prior_day_range': 570, 'prior_day_close_position': 570,
    'prior_day_range_atr_ratio': 570, 'prior_day_directional_changes': 570,
    'prior_day_close_vs_open_pct': 570, 'prior_day_type': 570,
    # VIX (prior close)
    'vixy_prior_close': 570, 'vixy_regime': 570,
}

# Time-gated features (column -> mod-of-availability).
# A trade at mod=t gets the feature iff t >= gate; otherwise NaN.
GATED_FEATURES: dict[str, int] = {
    # 9:31 — after first 1-min RTH candle closes
    'candle_930_range': 571, 'candle_930_body': 571, 'candle_930_direction': 571,
    # 9:35 — after first 5min of RTH
    'or_5min_high': 575, 'or_5min_low': 575, 'or_5min_range': 575,
    'fvgs_first_5min': 575,
    'fvgs_first_5min_bullish': 575, 'fvgs_first_5min_bearish': 575,
    # 9:45 — after first 15min of RTH; macro_1 window also closes here
    'or_15min_high': 585, 'or_15min_low': 585, 'or_15min_range': 585,
    'fvgs_first_15min': 585,
    'fvgs_first_15min_bullish': 585, 'fvgs_first_15min_bearish': 585,
    'macro_1_range': 585, 'macro_1_num_fvgs': 585,
    # 10:00 — macro_2 closes
    'macro_2_range': 600, 'macro_2_num_fvgs': 600,
    # 10:15 — after first 45min of RTH
    'or_45min_high': 615, 'or_45min_low': 615, 'or_45min_range': 615,
    # 11:10 — macro_3 closes
    'macro_3_range': 670, 'macro_3_num_fvgs': 670,
    # 13:50 — macro_4 closes
    'macro_4_range': 830, 'macro_4_num_fvgs': 830,
}

# Refuse to load — these are full-session aggregates (only known at 16:00).
# If a study needs anything in this set, it must reconstruct from causal bars.
CONTAMINATED: set[str] = {
    'rth_close', 'rth_high', 'rth_low', 'rth_range',
    'directional_changes_30m',
    'max_drawdown_from_open', 'max_drawup_from_open',
}

FEATURE_AVAILABILITY: dict[str, int] = {**SAFE_AT_OPEN, **GATED_FEATURES}

# Row-level features derived from trade-row columns already known at entry.
# All gated at mod=570 (the trade's own entry time is, by construction, >= 570
# for RTH trades; these features are functions of fields known at that instant).
TRADE_LEVEL_FEATURES: dict[str, int] = {
    'fvg_size': 570,
    'fvg_age_min': 570,
    'entry_pos_in_fvg': 570,
    'signal_seq_today': 570,
    'has_prior_win': 570,
    'has_prior_loss': 570,
}


# -- Helpers ------------------------------------------------------------------

def _ensure_trade_keys(trades: pl.DataFrame) -> pl.DataFrame:
    """Add `date` (NY date) and `mod` (NY mins-of-day) columns to trades."""
    if 'timestamp' not in trades.columns:
        raise ValueError("trades_df must contain a 'timestamp' column")
    out = trades
    if 'date' not in out.columns:
        out = out.with_columns(pl.col('timestamp').dt.date().alias('date'))
    if 'mod' not in out.columns:
        out = out.with_columns(
            (pl.col('timestamp').dt.hour().cast(pl.Int32) * 60
             + pl.col('timestamp').dt.minute().cast(pl.Int32)).alias('mod')
        )
    return out


def _mask_gated(joined: pl.DataFrame, columns: Iterable[str]) -> pl.DataFrame:
    """For each gated column, NaN out values where trade.mod < gate."""
    expressions = []
    for col in columns:
        if col not in joined.columns or col not in GATED_FEATURES:
            continue
        gate = GATED_FEATURES[col]
        # NaN out non-numeric columns by setting to null
        expressions.append(
            pl.when(pl.col('mod') >= gate)
            .then(pl.col(col))
            .otherwise(None)
            .alias(col)
        )
    if expressions:
        joined = joined.with_columns(expressions)
    return joined


# -- Public API ---------------------------------------------------------------

def load_causal_features(
    trades: pl.DataFrame,
    include: Iterable[str] | None = None,
) -> pl.DataFrame:
    """
    Join causal features from trading_days.csv onto trades.

    Parameters
    ----------
    trades : pl.DataFrame
        Must contain 'timestamp'. Other columns are passed through.
    include : optional iterable[str]
        Subset of feature names. Default = all SAFE_AT_OPEN + all GATED_FEATURES.
        Requesting a column in CONTAMINATED raises ValueError.

    Returns
    -------
    pl.DataFrame
        trades with extra columns. Gated features are NaN'd for trades whose
        mod < gate. Adds 'date' and 'mod' if not present.

    Raises
    ------
    ValueError if `include` references a CONTAMINATED feature or an unknown name.
    """
    if include is None:
        wanted = list(SAFE_AT_OPEN.keys()) + list(GATED_FEATURES.keys())
    else:
        wanted = list(include)

    bad = [c for c in wanted if c in CONTAMINATED]
    if bad:
        raise ValueError(
            f"refusing to load contaminated full-session features: {bad}. "
            "These are only known at 16:00 — reconstruct from causal bars."
        )
    unknown = [c for c in wanted if c not in FEATURE_AVAILABILITY]
    if unknown:
        raise ValueError(
            f"unknown feature names: {unknown}. "
            f"Known: {sorted(FEATURE_AVAILABILITY)}"
        )

    trades = _ensure_trade_keys(trades)

    td = pl.read_csv(TRADING_DAYS_CSV, try_parse_dates=True)
    keep_cols = ['date'] + [c for c in wanted if c in td.columns]
    missing = [c for c in wanted if c not in td.columns]
    if missing:
        raise ValueError(
            f"trading_days.csv is missing requested columns: {missing}. "
            "Rebuild it via data/trading_days/build_trading_days.py."
        )
    td = td.select(keep_cols)

    out = trades.join(td, on='date', how='left')
    gated_in_request = [c for c in wanted if c in GATED_FEATURES]
    out = _mask_gated(out, gated_in_request)
    return out


def load_lagged_vp(trades: pl.DataFrame) -> pl.DataFrame:
    """
    Join yesterday's (d-1) volume profile onto trades.

    `daily_volume_profile.csv` stores TODAY's POC/VAH/VAL/va_width/rth_volume —
    a 9:30-16:00 aggregate. Joining on the trade date gives the model access
    to data that doesn't exist at trade time. This helper shifts the profile
    forward one trading day so the row joined to date d carries d-1's VP.

    Adds columns: poc_lag1, vah_lag1, val_lag1, va_width_lag1, vol_lag1.
    """
    trades = _ensure_trade_keys(trades)
    vp = pl.read_csv(DAILY_VP_CSV, try_parse_dates=True).sort('date')
    vp_lag = (
        vp.with_columns(pl.col('date').shift(-1).alias('date_for'))
        .filter(pl.col('date_for').is_not_null())
        .drop('date')
        .rename({
            'date_for': 'date',
            'poc': 'poc_lag1', 'vah': 'vah_lag1', 'val': 'val_lag1',
            'va_width': 'va_width_lag1', 'rth_volume': 'vol_lag1',
        })
    )
    return trades.join(vp_lag, on='date', how='left')


def load_session_levels(
    trades: pl.DataFrame,
    names: Iterable[str] | None = None,
) -> pl.DataFrame:
    """
    Join session liquidity levels (prev_day, asia, london, 6am, overnight,
    nwog, bsl/ssl, or_high/low) onto trades.

    `session_levels.csv` provides an `available_time` column ('open' or
    'HH:MM'). Levels with available_time='HH:MM' are masked to NaN for
    trades that occur before that time. 'open' = 9:30 = mod 570.

    Adds one numeric column per level price (column name = level_name).
    If `names` is None, all level_names in session_levels.csv are loaded.
    """
    trades = _ensure_trade_keys(trades)
    levels = pl.read_csv(SESSION_LEVELS_CSV, try_parse_dates=True)

    if names is not None:
        levels = levels.filter(pl.col('level_name').is_in(list(names)))

    # Build availability-mod from the textual column.
    def _parse_avail(s: str | None) -> int | None:
        if s is None or s == '':
            return None
        if s == 'open':
            return 570
        try:
            hh, mm = s.split(':')
            return int(hh) * 60 + int(mm)
        except Exception:
            return None

    avail_mod = [
        _parse_avail(x) for x in levels['available_time'].to_list()
    ]
    levels = levels.with_columns(pl.Series('avail_mod', avail_mod, dtype=pl.Int32))

    wide = (
        levels.select(['date', 'level_name', 'price', 'avail_mod'])
        .pivot(values='price', index='date', on='level_name', aggregate_function='first')
    )
    avail = (
        levels.select(['date', 'level_name', 'avail_mod'])
        .pivot(values='avail_mod', index='date', on='level_name', aggregate_function='first')
    )

    out = trades.join(wide, on='date', how='left')

    # For each level column, mask values where mod < avail_mod.
    level_cols = [c for c in wide.columns if c != 'date']
    avail_by_level: dict[str, int | None] = {}
    for c in level_cols:
        # availability is the same per (date, level) but for simplicity grab
        # the first non-null value across all dates.
        col = avail.get_column(c)
        non_null = col.drop_nulls()
        avail_by_level[c] = int(non_null[0]) if non_null.len() else None

    masks = []
    for c, gate in avail_by_level.items():
        if gate is None or gate <= 570:
            continue  # safe at open, no masking needed
        masks.append(
            pl.when(pl.col('mod') >= gate).then(pl.col(c)).otherwise(None).alias(c)
        )
    if masks:
        out = out.with_columns(masks)
    return out


def add_trade_level_features(trades: pl.DataFrame) -> pl.DataFrame:
    """
    Add row-level features derived from trade-row columns known at entry.

    Required input columns: timestamp, entry_price, fvg_top, fvg_bottom,
    fvg_created_at, outcome. Returns the input with the columns in
    TRADE_LEVEL_FEATURES added (plus `date` and `mod` via _ensure_trade_keys).

    All outputs are causally observable at the trade's entry time:
      - fvg_size, fvg_age_min, entry_pos_in_fvg are pure functions of the
        trade row's own already-known fields.
      - signal_seq_today, has_prior_win, has_prior_loss depend only on
        STRICTLY EARLIER same-day trade outcomes (not this trade's own).

    Note: the input frame must contain ALL trades for a given date if you want
    correct signal_seq_today / has_prior_* on a filtered subset. Apply this
    BEFORE filtering by outcome.
    """
    required = {'timestamp', 'entry_price', 'fvg_top', 'fvg_bottom',
                'fvg_created_at', 'outcome'}
    missing = required - set(trades.columns)
    if missing:
        raise ValueError(
            f"add_trade_level_features: trades is missing columns: {sorted(missing)}"
        )

    out = _ensure_trade_keys(trades).sort(['date', 'timestamp'])

    fvg_size = pl.col('fvg_top') - pl.col('fvg_bottom')
    fvg_age_sec = (pl.col('timestamp') - pl.col('fvg_created_at')).dt.total_seconds()

    out = out.with_columns([
        fvg_size.alias('fvg_size'),
        (fvg_age_sec / 60.0).alias('fvg_age_min'),
        pl.when(fvg_size != 0)
            .then((pl.col('entry_price') - pl.col('fvg_bottom')) / fvg_size)
            .otherwise(None)
            .alias('entry_pos_in_fvg'),
    ])

    # Per-date sequence (1-indexed) and prior win/loss flags using cum_sum
    # over the date partition. `cum_sum - this_row_indicator > 0` =
    # "any STRICTLY earlier row on this date had the outcome".
    is_win = pl.col('outcome').eq('win').cast(pl.Int32)
    is_loss = pl.col('outcome').eq('loss').cast(pl.Int32)
    out = out.with_columns([
        pl.col('timestamp').cum_count().over('date').cast(pl.Int32)
            .alias('signal_seq_today'),
        (is_win.cum_sum().over('date') - is_win).gt(0).alias('has_prior_win'),
        (is_loss.cum_sum().over('date') - is_loss).gt(0).alias('has_prior_loss'),
    ])
    return out


# -- Diagnostics --------------------------------------------------------------

def feature_report() -> str:
    """Human-readable summary of what this module loads."""
    lines = ['== Safe at open (mod=570) ==']
    for k in sorted(SAFE_AT_OPEN):
        lines.append(f'  {k}')
    lines.append('')
    lines.append('== Time-gated ==')
    for k in sorted(GATED_FEATURES, key=lambda x: (GATED_FEATURES[x], x)):
        m = GATED_FEATURES[k]
        hh, mm = divmod(m, 60)
        lines.append(f'  {hh:02d}:{mm:02d}  {k}')
    lines.append('')
    lines.append('== Trade-level (derived at entry) ==')
    for k in sorted(TRADE_LEVEL_FEATURES):
        lines.append(f'  {k}')
    lines.append('')
    lines.append('== Refused (full-session aggregates) ==')
    for k in sorted(CONTAMINATED):
        lines.append(f'  {k}')
    return '\n'.join(lines)


if __name__ == '__main__':
    print(feature_report())
