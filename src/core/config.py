# config.py
# ---------------------------------------------------------------------------
# Minimal configuration for FVG Backtest
# ---------------------------------------------------------------------------

CONFIG = {
    # Data settings
    "data_path": "data_30s.csv",
    
    # ============================================================================
    # DATE RANGE TESTING - Configure test period for validation
    # ============================================================================
    # Options:
    #   "single_day" - Test single date specified in test_date
    #   "week" - Test 7 days starting from test_start_date
    #   "month" - Test ~30 days starting from test_start_date  
    #   "full_dataset" - Test entire dataset (2+ years)
    #   None - Use date_range or start_date/end_date below
    "test_period": None,  # Change this to test different periods (None = use start_date/end_date)
    
    # For single_day testing
    "test_date": "2025-10-23",  # Format: YYYY-MM-DD
    
    # For week/month testing (start date)
    "test_start_date": "2025-10-01",  # Format: YYYY-MM-DD
    
    # Legacy date range filters (alternative to test_period)
    "date_range": None,  # Options: None, "last_2_weeks", "last_month", etc.
    "start_date": "2025-09-01",  # Explicit start date (YYYY-MM-DD)
    "end_date": "2025-10-31",    # Explicit end date (YYYY-MM-DD)
    
    # Trading session
    "session_tz": "America/New_York",
    "session_start": "09:30:00",
    "session_end": "10:15:00",
    
    # ============================================================================
    # TRADE MANAGEMENT STRATEGY
    # ============================================================================
    # Options: "fixed", "dynamic_fvg", "partial_close", "trailing_sl"
    # 
    # "fixed": Simple fixed TP/SL points (configurable below)
    # "dynamic_fvg": Size based on FVG, rounded to nearest 5, min 15, max 40
    # "partial_close": Take 50% off at 50% profit, move SL to BE
    # "trailing_sl": Move SL to 50% profit at 50% TP (2R minimum, no partial)
    "trade_management_strategy": "fixed",
    
    # Risk management (used by fixed, partial_close, and trailing_sl strategies)
    "points_tp": 20.0,
    "points_sl": 20.0,
    
    # Dynamic FVG strategy settings
    "dynamic_fvg_buffer_pts": 3.0,  # Buffer from FVG boundary
    "dynamic_fvg_min_pts": 15.0,    # Minimum TP/SL points
    "dynamic_fvg_max_pts": 40.0,    # Maximum TP/SL points
    
    # FVG settings
    "fvg_max_age_bars": 20,
    "max_active_per_side": 3,
    
    # Session gap filtering
    "max_fvg_size_pts": 100.0,  # Maximum FVG size - larger are likely session gaps
    "bars_to_skip_after_session_start": 3,  # Skip FVG detection in first N bars
    "max_fvg_size_session_start": 50.0,  # Even smaller max for first few bars
    
    # Entry model settings
    "fvg_touch_tolerance_pts": 1.0,  # Allow wick to be within this many points of gap bound to count as "touch"
    
    # Entry limits
    "allow_multiple_entries_per_fvg": False,  # Allow multiple trades on same FVG
    
    # Output
    "trades_csv": "trades.csv",
}

# Required columns for data loading
REQUIRED_COLS = [
    "ts_event", "open", "high", "low", "close", "volume", "symbol"
]
