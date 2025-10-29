# data_loader.py
# ---------------------------------------------------------------------------
# Data loading and preprocessing utilities
# ---------------------------------------------------------------------------

import pandas as pd
from typing import Optional
from .config import CONFIG, REQUIRED_COLS


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
