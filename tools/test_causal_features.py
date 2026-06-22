"""
Unit tests for tools/causal_features.py.

Run with: python -m pytest tools/test_causal_features.py -v
Or:       python tools/test_causal_features.py
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import polars as pl
import pytest

from tools import causal_features as cf


# A real trading date that is present in all CSVs.
SAMPLE_DATE = dt.date(2024, 3, 15)


def _make_trades(times: list[tuple[int, int]]) -> pl.DataFrame:
    """Build a trades frame with timestamps at (HH, MM) on SAMPLE_DATE."""
    return pl.DataFrame({
        'timestamp': [
            dt.datetime(SAMPLE_DATE.year, SAMPLE_DATE.month, SAMPLE_DATE.day, hh, mm)
            for hh, mm in times
        ],
    })


# ---------------------------------------------------------------------------
# Static API surface
# ---------------------------------------------------------------------------
def test_contaminated_disjoint_from_loadable() -> None:
    """No loadable feature is also in the contaminated set."""
    assert cf.CONTAMINATED.isdisjoint(cf.FEATURE_AVAILABILITY)


def test_gates_in_rth_range() -> None:
    """Every gate is in the RTH (9:30 - 16:00) range."""
    for col, mod in cf.GATED_FEATURES.items():
        assert 570 <= mod <= 960, f'{col} gate={mod} out of RTH window'


def test_safe_at_open_all_mod_570() -> None:
    """All SAFE_AT_OPEN features are gated at 9:30 sharp."""
    for col, mod in cf.SAFE_AT_OPEN.items():
        assert mod == 570, f'{col} should be mod=570, got {mod}'


def test_refuses_contaminated_request() -> None:
    """load_causal_features raises if asked for a contaminated column."""
    trades = _make_trades([(10, 0)])
    with pytest.raises(ValueError, match='contaminated'):
        cf.load_causal_features(trades, include=['rth_close'])
    with pytest.raises(ValueError, match='contaminated'):
        cf.load_causal_features(trades, include=['max_drawup_from_open'])


def test_rejects_unknown_feature() -> None:
    trades = _make_trades([(10, 0)])
    with pytest.raises(ValueError, match='unknown'):
        cf.load_causal_features(trades, include=['definitely_not_real'])


# ---------------------------------------------------------------------------
# Causal masking
# ---------------------------------------------------------------------------
def test_pre_945_trade_gets_or_15min_nan() -> None:
    """A 9:32 trade must not see or_15min_* (gate=585=9:45)."""
    trades = _make_trades([(9, 32)])
    out = cf.load_causal_features(trades, include=['or_15min_high', 'or_15min_range'])
    assert out['or_15min_high'][0] is None
    assert out['or_15min_range'][0] is None


def test_post_945_trade_sees_or_15min() -> None:
    """A 10:00 trade should see or_15min_* (gate=585=9:45)."""
    trades = _make_trades([(10, 0)])
    out = cf.load_causal_features(trades, include=['or_15min_high'])
    val = out['or_15min_high'][0]
    assert val is not None and val > 0, f'expected non-null or_15min_high, got {val!r}'


def test_pre_1015_trade_gets_or_45min_nan() -> None:
    """A 10:00 trade must not see or_45min_* (gate=615=10:15)."""
    trades = _make_trades([(10, 0)])
    out = cf.load_causal_features(trades, include=['or_45min_range'])
    assert out['or_45min_range'][0] is None


def test_post_1015_trade_sees_or_45min() -> None:
    """A 10:30 trade should see or_45min_*."""
    trades = _make_trades([(10, 30)])
    out = cf.load_causal_features(trades, include=['or_45min_range'])
    val = out['or_45min_range'][0]
    assert val is not None and val > 0


def test_930_trade_blocks_candle_930() -> None:
    """A 9:30 trade must NOT see candle_930_* (gate=571=9:31)."""
    trades = _make_trades([(9, 30)])
    out = cf.load_causal_features(trades, include=['candle_930_range'])
    assert out['candle_930_range'][0] is None


def test_open_features_always_available() -> None:
    """At 9:30 sharp, all SAFE_AT_OPEN features are available."""
    trades = _make_trades([(9, 30)])
    safe_cols = ['gap_from_prior_close', 'is_fomc_week', 'overnight_high',
                 'vixy_prior_close', 'prior_day_close_position']
    out = cf.load_causal_features(trades, include=safe_cols)
    for c in safe_cols:
        assert out[c][0] is not None, f'{c} must be available at 9:30'


# ---------------------------------------------------------------------------
# Lagged VP
# ---------------------------------------------------------------------------
def test_lagged_vp_is_d_minus_1() -> None:
    """Lagged POC at date d must equal raw POC at date d-1."""
    trades = _make_trades([(10, 0)])
    lagged = cf.load_lagged_vp(trades)
    raw = pl.read_csv(cf.DAILY_VP_CSV, try_parse_dates=True).sort('date')

    # Find the previous trading day in raw VP (which may not be d-1 calendar)
    raw_dates = raw['date'].to_list()
    idx_today = raw_dates.index(SAMPLE_DATE)
    expected_prev_date = raw_dates[idx_today - 1]
    expected_poc = raw.filter(pl.col('date') == expected_prev_date)['poc'][0]

    assert lagged['poc_lag1'][0] == pytest.approx(expected_poc)


def test_lagged_vp_distinct_from_today() -> None:
    """Sanity: lagged POC should NOT equal today's POC (high prob on any single day)."""
    trades = _make_trades([(10, 0)])
    lagged = cf.load_lagged_vp(trades)
    raw = pl.read_csv(cf.DAILY_VP_CSV, try_parse_dates=True)
    today_poc = raw.filter(pl.col('date') == SAMPLE_DATE)['poc'][0]
    assert lagged['poc_lag1'][0] != today_poc


# ---------------------------------------------------------------------------
# Session levels
# ---------------------------------------------------------------------------
def test_session_levels_or_high_masked_pre_945() -> None:
    """or_high has available_time=09:45 → must be NaN for a 9:30 trade."""
    trades = _make_trades([(9, 30)])
    out = cf.load_session_levels(trades, names=['or_high', 'or_low', 'prev_day_high'])
    assert out['or_high'][0] is None
    assert out['or_low'][0] is None


def test_session_levels_or_high_passthrough_post_945() -> None:
    """After 9:45, or_high should equal the raw csv price (possibly None if stubbed)."""
    trades_pre = _make_trades([(9, 30)])
    trades_post = _make_trades([(10, 0)])
    pre = cf.load_session_levels(trades_pre, names=['or_high'])
    post = cf.load_session_levels(trades_post, names=['or_high'])

    raw = pl.read_csv(cf.SESSION_LEVELS_CSV, try_parse_dates=True)
    raw_val = (
        raw.filter((pl.col('date') == SAMPLE_DATE) & (pl.col('level_name') == 'or_high'))['price'][0]
    )
    # Pre-9:45 is always None; post-9:45 mirrors the raw value (including None for stubs).
    assert pre['or_high'][0] is None
    assert post['or_high'][0] == raw_val


def test_session_levels_open_features_at_open() -> None:
    trades = _make_trades([(9, 30)])
    out = cf.load_session_levels(trades, names=['prev_day_high', 'overnight_high'])
    # prev_day_high should be present for most dates (modulo first-trading-day edge)
    assert out['prev_day_high'][0] is not None


# ---------------------------------------------------------------------------
# Schema preservation
# ---------------------------------------------------------------------------
def test_row_count_preserved() -> None:
    trades = _make_trades([(9, 30), (9, 45), (10, 0), (10, 30)])
    out = cf.load_causal_features(trades, include=['or_15min_range', 'or_45min_range'])
    assert out.height == 4


def test_input_columns_preserved() -> None:
    trades = _make_trades([(10, 0)]).with_columns(pl.lit('long').alias('direction'))
    out = cf.load_causal_features(trades, include=['gap_from_prior_close'])
    assert 'direction' in out.columns
    assert out['direction'][0] == 'long'


# ---------------------------------------------------------------------------
# Trade-level derived features (add_trade_level_features)
# ---------------------------------------------------------------------------
def _make_full_trades(rows: list[dict]) -> pl.DataFrame:
    """Build a richer trades frame for trade-level feature tests."""
    return pl.DataFrame(rows, schema={
        'timestamp': pl.Datetime,
        'entry_price': pl.Float64,
        'fvg_top': pl.Float64,
        'fvg_bottom': pl.Float64,
        'fvg_created_at': pl.Datetime,
        'outcome': pl.Utf8,
    })


def test_trade_level_signal_seq_first_is_1() -> None:
    """signal_seq_today is 1 for the first trade of a date."""
    trades = _make_full_trades([
        {'timestamp': dt.datetime(2024, 3, 15, 9, 35),
         'entry_price': 100.0, 'fvg_top': 101.0, 'fvg_bottom': 99.0,
         'fvg_created_at': dt.datetime(2024, 3, 15, 9, 33), 'outcome': 'win'},
        {'timestamp': dt.datetime(2024, 3, 15, 10, 0),
         'entry_price': 102.0, 'fvg_top': 103.0, 'fvg_bottom': 101.0,
         'fvg_created_at': dt.datetime(2024, 3, 15, 9, 58), 'outcome': 'loss'},
        {'timestamp': dt.datetime(2024, 3, 16, 9, 32),
         'entry_price': 99.5, 'fvg_top': 100.0, 'fvg_bottom': 99.0,
         'fvg_created_at': dt.datetime(2024, 3, 16, 9, 30), 'outcome': 'win'},
    ])
    out = cf.add_trade_level_features(trades).sort('timestamp')
    seqs = out['signal_seq_today'].to_list()
    assert seqs == [1, 2, 1], f'expected [1,2,1] got {seqs}'


def test_trade_level_has_prior_win_false_on_first() -> None:
    """has_prior_win is False on the day's first trade, True after a prior win."""
    trades = _make_full_trades([
        {'timestamp': dt.datetime(2024, 3, 15, 9, 35),
         'entry_price': 100.0, 'fvg_top': 101.0, 'fvg_bottom': 99.0,
         'fvg_created_at': dt.datetime(2024, 3, 15, 9, 33), 'outcome': 'win'},
        {'timestamp': dt.datetime(2024, 3, 15, 10, 0),
         'entry_price': 102.0, 'fvg_top': 103.0, 'fvg_bottom': 101.0,
         'fvg_created_at': dt.datetime(2024, 3, 15, 9, 58), 'outcome': 'loss'},
        {'timestamp': dt.datetime(2024, 3, 15, 10, 30),
         'entry_price': 104.0, 'fvg_top': 105.0, 'fvg_bottom': 103.0,
         'fvg_created_at': dt.datetime(2024, 3, 15, 10, 28), 'outcome': 'loss'},
    ])
    out = cf.add_trade_level_features(trades).sort('timestamp')
    assert out['has_prior_win'].to_list() == [False, True, True]
    assert out['has_prior_loss'].to_list() == [False, False, True]


def test_trade_level_entry_pos_in_fvg_in_unit_range() -> None:
    """entry_pos_in_fvg in [0,1] when entry is strictly between top and bottom."""
    trades = _make_full_trades([
        {'timestamp': dt.datetime(2024, 3, 15, 9, 35),
         'entry_price': 100.0, 'fvg_top': 101.0, 'fvg_bottom': 99.0,
         'fvg_created_at': dt.datetime(2024, 3, 15, 9, 33), 'outcome': 'win'},
    ])
    out = cf.add_trade_level_features(trades)
    pos = out['entry_pos_in_fvg'][0]
    assert pos == pytest.approx(0.5)


def test_trade_level_mod_matches_timestamp() -> None:
    """mod = hour*60 + minute."""
    trades = _make_full_trades([
        {'timestamp': dt.datetime(2024, 3, 15, 9, 32),
         'entry_price': 100.0, 'fvg_top': 101.0, 'fvg_bottom': 99.0,
         'fvg_created_at': dt.datetime(2024, 3, 15, 9, 30), 'outcome': 'win'},
        {'timestamp': dt.datetime(2024, 3, 15, 10, 15),
         'entry_price': 100.0, 'fvg_top': 101.0, 'fvg_bottom': 99.0,
         'fvg_created_at': dt.datetime(2024, 3, 15, 10, 13), 'outcome': 'loss'},
    ])
    out = cf.add_trade_level_features(trades).sort('timestamp')
    assert out['mod'].to_list() == [9 * 60 + 32, 10 * 60 + 15]


def test_trade_level_fvg_age_min() -> None:
    """fvg_age_min = (timestamp - fvg_created_at) in minutes."""
    trades = _make_full_trades([
        {'timestamp': dt.datetime(2024, 3, 15, 9, 35),
         'entry_price': 100.0, 'fvg_top': 101.0, 'fvg_bottom': 99.0,
         'fvg_created_at': dt.datetime(2024, 3, 15, 9, 30), 'outcome': 'win'},
    ])
    out = cf.add_trade_level_features(trades)
    assert out['fvg_age_min'][0] == pytest.approx(5.0)


def test_trade_level_fvg_size() -> None:
    """fvg_size = fvg_top - fvg_bottom."""
    trades = _make_full_trades([
        {'timestamp': dt.datetime(2024, 3, 15, 9, 35),
         'entry_price': 100.0, 'fvg_top': 102.5, 'fvg_bottom': 99.0,
         'fvg_created_at': dt.datetime(2024, 3, 15, 9, 33), 'outcome': 'win'},
    ])
    out = cf.add_trade_level_features(trades)
    assert out['fvg_size'][0] == pytest.approx(3.5)


def test_trade_level_missing_required_raises() -> None:
    """Missing required input column raises ValueError."""
    trades = pl.DataFrame({
        'timestamp': [dt.datetime(2024, 3, 15, 9, 35)],
        # missing entry_price, fvg_top, fvg_bottom, fvg_created_at, outcome
    })
    with pytest.raises(ValueError, match='missing columns'):
        cf.add_trade_level_features(trades)


if __name__ == '__main__':
    import sys
    sys.exit(pytest.main([__file__, '-v']))
