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
    
    # First apply explicit start/end dates if specified
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


def load_processed_30s_csv(path: str) -> pd.DataFrame:
    """Load processed 30-second CSV data with ET timestamps."""
    print(f"Loading processed 30s data: {path}")
    
    df = pd.read_csv(path)
    
    # Convert timestamp - timestamps are stored in ET timezone
    # Use apply to handle mixed timezones (EDT/EST) properly
    import pytz
    et_tz = pytz.timezone('America/New_York')
    
    def parse_timestamp(ts_str):
        """Parse timestamp and ensure it's in ET timezone."""
        ts = pd.to_datetime(ts_str)
        if ts.tzinfo is None:
            # Timezone-naive, localize to ET
            return et_tz.localize(ts)
        # Already timezone-aware, convert to ET if needed
        return ts.astimezone(et_tz)
    
    df["timestamp"] = df["timestamp"].apply(parse_timestamp)
    
    # Convert numeric columns
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    
    # Add previous bar data (already included in processed data)
    df["prev_close"] = pd.to_numeric(df["prev_close"], errors="coerce")
    df["prev_high"] = pd.to_numeric(df["prev_high"], errors="coerce") 
    df["prev_low"] = pd.to_numeric(df["prev_low"], errors="coerce")
    
    # Apply date range filtering
    df = apply_date_range_filter(df)
    
    print(f"Loaded {len(df):,} 30-second bars")
    print(f"Date range: {df['timestamp'].min()} to {df['timestamp'].max()}")
    
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
