# config.py
# ---------------------------------------------------------------------------
# Configuration settings for FVG Backtest
# ---------------------------------------------------------------------------

from typing import List

# =============================
# CONFIGURATION
# =============================
CONFIG = {
    "data_path": "glbx-mdp3-20250911-20251010.ohlcv-1s.csv",
    "symbol": None,
    "start_date": None,
    "end_date": None,

    "session_tz": "America/New_York",
    "session_start": "09:30:00",
    "session_end": "10:15:00",

    "points_tp": 20.0,
    "points_sl": 20.0,
    "assume_tp_first": False,

    # priority order; first match wins for a given FVG on a given bar
    "models_to_eval": ["fvg_ifvg", "fvg_bos", "fvg_no_fvg"],
    "max_trades_per_session_per_model": 3,

    "min_gap_pts": 0.75,
    "min_middle_body_pts": 1.0,
    "fvg_max_age_bars": 20,
    "max_active_per_side": 3,
    "invalidate_on_wick_through": False,

    # conflict handling & baseline guards
    "skip_conflicting_fvgs": True,
    "require_prev_extreme_break_no_fvg": True,
    "block_if_opposite_ifvg_same_bar": True,

    # baseline shape (used by all models as the base continuation filter)
    "disallow_same_bar_entry": True,
    "min_bars_since_creation": 1,
    "require_pullback_from_outside": True,
    "require_directional_close": True,
    "require_prev_close_break": True,
    "require_close_outside_gap": False,

    # iFVG knobs
    "ifvg_same_bar": True,
    "ifvg_lookback_bars": 6,
    "ifvg_require_prev_high_low_break": True,
    "ifvg_respect_IEL": False,

    # BOS knobs
    "bos_left": 2,
    "bos_right": 2,
    "bos_lookback_bars": 12,
    "bos_require_close_through": True,

    "trades_csv": "trades.csv"
}

# Required columns for data loading
REQUIRED_COLS = [
    "ts_event", "open", "high", "low", "close", "volume", "symbol"
]
