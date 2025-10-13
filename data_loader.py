# data_loader.py
# ---------------------------------------------------------------------------
# Data loading and preprocessing utilities
# ---------------------------------------------------------------------------

import pandas as pd
from typing import Optional
from config import CONFIG, REQUIRED_COLS


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
