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
    # If True, allow multiple models to log entries off the same FVG on the same bar
    "allow_multiple_models_per_gap": True,

    "min_gap_pts": 0.75,
    "min_middle_body_pts": 1.0,
    "fvg_max_age_bars": 20,
    "max_active_per_side": 3,
    "invalidate_on_wick_through": False,

    # conflict handling & baseline guards
    "skip_conflicting_fvgs": True,
    # For iFVG, allow internal opposite gaps to coexist (do not treat as blocking conflict)
    "ifvg_ignore_internal_conflict": True,
    "require_prev_extreme_break_no_fvg": True,
    "block_if_opposite_ifvg_same_bar": True,

    # no-FVG break knobs
    # - nofvg_break_metric: "close" requires the close to break the prior extreme
    #   "wick" allows using the bar's high/low to qualify the break
    # - nofvg_allow_equal: if True, equality (==) counts as a break
    "nofvg_break_metric": "wick",
    "nofvg_allow_equal": True,

    # baseline shape (used by all models as the base continuation filter)
    "disallow_same_bar_entry": True,
    "min_bars_since_creation": 1,
    "require_pullback_from_outside": False,
    "require_directional_close": True,
    "require_prev_close_break": False,
    "require_close_outside_gap": False,

    # iFVG knobs
    "ifvg_same_bar": False,
    "ifvg_lookback_bars": 10,
    "ifvg_require_prev_high_low_break": True,
    # iFVG detection controls
    # - ifvg_internal_criterion: "inside" requires child gap fully inside parent; "overlap" allows partial
    # - ifvg_overlap_min_ratio: when in overlap mode, minimum child overlap ratio [0..1]
    # - ifvg_allow_opposite_internal: if True, an opposite-direction iFVG inside/overlapping qualifies (inversion)
    "ifvg_internal_criterion": "inside",
    "ifvg_overlap_min_ratio": 0.0,
    "ifvg_allow_opposite_internal": True,
    # Break metric/equality for iFVG prev high/low break
    "ifvg_break_metric": "wick",  # "close" | "wick"
    "ifvg_allow_equal": True,
    "ifvg_respect_IEL": False,

    # BOS knobs
    "bos_left": 2,
    "bos_right": 2,
    "bos_lookback_bars": 12,
    "bos_require_close_through": True,
    # If True, equality (close/high == level) counts as BOS
    "bos_allow_equal": True,

    "trades_csv": "trades.csv"
}

# Financial/backtest parameters
CONFIG.update({
    # Starting account balance (USD)
    "starting_balance": 25000.0,
    # Contracts per trade (e.g., 1 NQ contract)
    "contracts_per_trade": 1,
    # Dollar value per 1.0 index point (NQ = $20/point)
    "point_value": 20.0,
    # Commission per contract per round turn (USD); set to 0 if not used
    "commission_roundturn_per_contract": 0.0,
})

# Scenario-focused filters (set to None/False to disable)
# ---------------------------------------------------------------------------
# These control curated permutations you want to test. Sweep can iterate these
# explicitly rather than random grids. All are optional; when unset they don't
# filter trades.
CONFIG.update({
    # Tap vs close-inside classification on the entry bar interacting with the gap.
    # Values: "tap_only" | "close_inside_only" | None (no restriction)
    "entry_touch_type": None,

    # Minimum/maximum number of prior bar touches (overlaps) into the gap before entry
    # Counted from gap creation up to the entry bar (inclusive of bars before entry).
    "min_gap_taps": None,   # e.g., 1
    "max_gap_taps": None,   # e.g., 3

    # Whether the pullback penetration went beyond the 50% (midline) of the gap
    # Values: True | False | None (no restriction)
    "penetrated_midline": None,

    # Restrict entries to specific ET time buckets. Provide a list like
    # ["0930-0945", "0945-1000", "1000-1015"], or None for no restriction.
    "allowed_time_buckets": None,

    # If True, only allow trades during 09:30:00-09:35:00 ET
    # If False or None, no special restriction (unless allowed_time_buckets applies)
    "first_five_only": None,

    # Restrict gap size in index points (inclusive bounds). None disables.
    "gap_size_min_pts": None,  # e.g., 2.0
    "gap_size_max_pts": None,  # e.g., 40.0

    # Delivery speed: number of bars after gap creation until the first bar
    # that breaks the previous candle in the entry direction.
    # You can bound this with min/max; None disables.
    "min_bars_to_prev_break": None,
    "max_bars_to_prev_break": None,
})

# Required columns for data loading
REQUIRED_COLS = [
    "ts_event", "open", "high", "low", "close", "volume", "symbol"
]
