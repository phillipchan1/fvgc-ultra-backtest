# data_loader.py
# ---------------------------------------------------------------------------
# Data loading and preprocessing utilities
# ---------------------------------------------------------------------------

import pandas as pd
from datetime import timedelta
from typing import Optional
from .config import CONFIG, REQUIRED_COLS


def apply_date_range_filter(df: pd.DataFrame) -> pd.DataFrame:
    """Apply date range filtering based on CONFIG settings."""
    if len(df) == 0:
        return df
    
    # Handle new test_period settings (priority)
    test_period = CONFIG.get("test_period")
    if test_period:
        if test_period == "single_day":
            test_date = CONFIG.get("test_date", "2025-10-23")
            target_date = pd.Timestamp(test_date).date()
            df = df[df["timestamp"].dt.date == target_date].copy()
            df = df.reset_index(drop=True)
            print(f"📅 Filtered to single day: {test_date} ({len(df):,} bars)")
            
        elif test_period == "week":
            start_date = pd.Timestamp(CONFIG.get("test_start_date", "2025-10-23"))
            end_date = start_date + pd.Timedelta(days=6)  # 7 days total
            df = df[(df["timestamp"].dt.date >= start_date.date()) & 
                    (df["timestamp"].dt.date <= end_date.date())].copy()
            df = df.reset_index(drop=True)
            print(f"📅 Filtered to week: {start_date.date()} to {end_date.date()} ({len(df):,} bars)")
            
        elif test_period == "month":
            start_date = pd.Timestamp(CONFIG.get("test_start_date", "2025-10-23"))
            end_date = start_date + pd.Timedelta(days=29)  # ~30 days
            df = df[(df["timestamp"].dt.date >= start_date.date()) & 
                    (df["timestamp"].dt.date <= end_date.date())].copy()
            df = df.reset_index(drop=True)
            print(f"📅 Filtered to month: {start_date.date()} to {end_date.date()} ({len(df):,} bars)")
            
        elif test_period == "full_dataset":
            print(f"📅 Testing full dataset: {len(df):,} bars")
            # No filtering needed
        
        # Return early if test_period is set
        return df
    
    # Legacy: Apply explicit start/end dates if specified
    if CONFIG.get("start_date"):
        start_date = pd.Timestamp(CONFIG["start_date"], tz=df["timestamp"].iloc[0].tz)
        df = df[df["timestamp"] >= start_date].copy()
        df = df.reset_index(drop=True)
    
    if CONFIG.get("end_date"):
        end_date = pd.Timestamp(CONFIG["end_date"], tz=df["timestamp"].iloc[0].tz)
        df = df[df["timestamp"] <= end_date].copy()
        df = df.reset_index(drop=True)
    
    # Apply quick date range filters (from end of data, backwards)
    date_range = CONFIG.get("date_range")
    if date_range and not CONFIG.get("start_date") and not CONFIG.get("end_date"):
        if len(df) == 0:
            return df
        
        # Get the last date in the data
        last_date = df["timestamp"].max()
        last_date_only = last_date.date()
        
        # Calculate start date based on range option
        if date_range == "last_2_weeks":
            start_date = last_date_only - timedelta(days=14)
        elif date_range == "last_month":
            start_date = last_date_only - timedelta(days=30)
        elif date_range == "last_3_months":
            start_date = last_date_only - timedelta(days=90)
        elif date_range == "last_6_months":
            start_date = last_date_only - timedelta(days=180)
        elif date_range == "last_year":
            start_date = last_date_only - timedelta(days=365)
        else:
            # Unknown option, don't filter
            return df
        
        # Filter to date range
        df = df[df["timestamp"].dt.date >= start_date].copy()
        # Reset index to ensure sequential indexing after filtering
        df = df.reset_index(drop=True)
        
        print(f"📅 Filtered to {date_range}: {start_date} to {last_date_only} ({len(df):,} bars)")
    
    return df


def load_processed_30s_csv(path: str, date_filter: Optional[str] = None) -> pd.DataFrame:
    """Load and preprocess 3s data from CSV."""
    
    print(f"Loading processed 30s data: {path}")
    
    # Define required columns for basic operation
    required_cols = ["ts_event", "open", "high", "low", "close"]
    
    # Read CSV
    df = pd.read_csv(path)
    
    # Ensure required columns are present
    if not all(col in df.columns for col in required_cols):
        raise ValueError("CSV missing one or more required columns")
        
    # Convert ts_event to timestamp (assuming nanoseconds)
    df["timestamp"] = pd.to_datetime(df["ts_event"], unit="ns")

    # Set timezone to config timezone, then remove it for simplicity if not filtering by session
    # This avoids DST issues and simplifies date filtering
    df["timestamp"] = df["timestamp"].dt.tz_localize("UTC").dt.tz_convert(CONFIG["session_tz"])
    
    # --- DATE FILTERING ---
    if date_filter:
        target_date = pd.to_datetime(date_filter).date()
        df = df[df["timestamp"].dt.date == target_date]
        print(f"📅 Filtered to single day: {date_filter} ({len(df)} bars)")
        if len(df) == 0:
            return pd.DataFrame()
    else:
        # Use test_period from config if no specific date_filter is passed
        test_period = CONFIG.get("test_period")
        if test_period == "single_day":
            test_date_str = CONFIG.get("test_date")
            if test_date_str:
                target_date = pd.to_datetime(test_date_str).date()
                df = df[df["timestamp"].dt.date == target_date]
                print(f"📅 Filtered to single day from config: {test_date_str} ({len(df)} bars)")
        
        elif test_period == "week":
            start_date = pd.Timestamp(CONFIG.get("test_start_date", "2025-10-23"))
            end_date = start_date + pd.Timedelta(days=6)  # 7 days total
            df = df[(df["timestamp"].dt.date >= start_date.date()) & 
                    (df["timestamp"].dt.date <= end_date.date())]
            print(f"📅 Filtered to week: {start_date.date()} to {end_date.date()} ({len(df)} bars)")
        
        elif test_period == "month":
            start_date = pd.Timestamp(CONFIG.get("test_start_date", "2025-10-23"))
            end_date = start_date + pd.Timedelta(days=29)  # ~30 days
            df = df[(df["timestamp"].dt.date >= start_date.date()) & 
                    (df["timestamp"].dt.date <= end_date.date())]
            print(f"📅 Filtered to month: {start_date.date()} to {end_date.date()} ({len(df)} bars)")
        
        elif test_period == "full_dataset":
            # No date filtering - use entire dataset
            pass
    
    # Filter by session time
    session_start = pd.to_datetime(CONFIG["session_start"]).time()
    session_end = pd.to_datetime(CONFIG["session_end"]).time()
    df = df[
        (df["timestamp"].dt.time >= session_start) & 
        (df["timestamp"].dt.time <= session_end)
    ]
    
    if df.empty:
        print("No data in the specified date range and session time.")
        return pd.DataFrame()
        
    print(f"Date range: {df['timestamp'].min()} to {df['timestamp'].max()}")
    
    # Set index and sort
    df.set_index(pd.to_datetime(df["ts_event"], unit="ns"), inplace=True)
    df.sort_index(inplace=True)
    
    return df


def load_db_1s_csv(path: str) -> pd.DataFrame:
    """Load and validate Databento-style 1-second OHLCV data."""
    df = pd.read_csv(path)
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns: {missing}")

    df["timestamp"] = pd.to_datetime(df["ts_event"], utc=True)
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    if CONFIG["start_date"]:
        df = df[df["timestamp"] >= pd.Timestamp(CONFIG["start_date"], tz="UTC")]
    if CONFIG["end_date"]:
        df = df[df["timestamp"] <= pd.Timestamp(CONFIG["end_date"], tz="UTC")]

    sym = CONFIG["symbol"] or df["symbol"].mode().iloc[0]
    df = df[df["symbol"] == sym].copy()
    df = df.sort_values("timestamp").drop_duplicates(subset=["timestamp"])
    return df[["timestamp", "open", "high", "low", "close", "volume"]]


def resample_to_30s(df: pd.DataFrame) -> pd.DataFrame:
    """Resample 1-second data to 30-second bars."""
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    df = (
        df.set_index("timestamp")
          .resample("30s").agg(agg)
          .dropna(subset=["open", "high", "low", "close"])
          .reset_index()
    )
    df["prev_close"] = df["close"].shift(1)
    df["prev_high"] = df["high"].shift(1)
    df["prev_low"] = df["low"].shift(1)
    return df


def in_session(ts: pd.Timestamp, tz: str, start: str, end: str) -> bool:
    """Check if timestamp is within trading session."""
    local = ts.tz_convert(tz).strftime("%H:%M:%S")
    return start <= local <= end
