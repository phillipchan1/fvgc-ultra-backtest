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
    "test_period": "week",  # Change this to test different periods
    
    # For single_day testing
    "test_date": "2025-10-23",  # Format: YYYY-MM-DD
    
    # For week/month testing (start date)
    "test_start_date": "2025-10-23",  # Format: YYYY-MM-DD
    
    # Legacy date range filters (alternative to test_period)
    "date_range": None,  # Options: None, "last_2_weeks", "last_month", etc.
    "start_date": None,  # Explicit start date (YYYY-MM-DD)
    "end_date": None,    # Explicit end date (YYYY-MM-DD)
    
    # Trading session
    "session_tz": "America/New_York",
    "session_start": "09:30:00",
    "session_end": "10:15:00",
    
    # Risk management
    "points_tp": 20.0,
    "points_sl": 20.0,
    
    # FVG settings
    "fvg_max_age_bars": 20,
    "max_active_per_side": 3,
    
    # Session gap filtering
    "max_fvg_size_pts": 100.0,  # Maximum FVG size - larger are likely session gaps
    "bars_to_skip_after_session_start": 3,  # Skip FVG detection in first N bars
    "max_fvg_size_session_start": 50.0,  # Even smaller max for first few bars
    
    # Entry model settings
    "fvg_touch_tolerance_pts": 1.0,  # Allow wick to be within this many points of gap bound to count as "touch"
    
    # Output
    "trades_csv": "trades.csv",
}

# Required columns for data loading
REQUIRED_COLS = [
    "ts_event", "open", "high", "low", "close", "volume", "symbol"
]
