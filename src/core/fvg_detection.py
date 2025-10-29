# fvg_detection.py
# ---------------------------------------------------------------------------
# FVG (Fair Value Gap) detection and lifecycle management
# ---------------------------------------------------------------------------

import pandas as pd
import itertools
from dataclasses import dataclass
from typing import List, Tuple, Optional
from .config import CONFIG

# Global FVG sequence counter
_fvg_seq = itertools.count(1)


@dataclass
class FVG:
    """Fair Value Gap data structure."""
    fvg_id: int
    direction: str
    created_at: pd.Timestamp
    created_idx: int
    lower: float
    upper: float
    size_pts: float
    middle_body_pts: float
    valid: bool = True
    expired: bool = False
    deactivated_reason: str = ""


def detect_fvgs(df: pd.DataFrame) -> pd.DataFrame:
    """Detect bullish and bearish FVGs in the dataframe."""
    hi2 = df["high"].shift(2)
    lo2 = df["low"].shift(2)
    mid_open = df["open"].shift(1)
    mid_close = df["close"].shift(1)
    mid_body = (mid_close - mid_open).abs()

    # Bullish FVG detection
    df["bull_fvg"] = df["low"] > hi2
    df["bull_lower"] = hi2
    df["bull_upper"] = df["low"]
    df["bull_size"] = (df["bull_upper"] - df["bull_lower"]).where(df["bull_fvg"])
    df["bull_middle_body"] = mid_body.where(df["bull_fvg"])

    # Bearish FVG detection
    df["bear_fvg"] = df["high"] < lo2
    df["bear_lower"] = df["high"]
    df["bear_upper"] = lo2
    df["bear_size"] = (df["bear_upper"] - df["bear_lower"]).where(df["bear_fvg"]).abs()
    df["bear_middle_body"] = mid_body.where(df["bear_fvg"])
    
    return df


def update_fvg_validity(active_fvgs: List[FVG], row: pd.Series, idx: int):
    """Update FVG validity based on current bar data."""
    o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
    
    for f in active_fvgs:
        if not f.valid or f.expired:
            continue
            
        # Check age
        if idx - f.created_idx >= CONFIG["fvg_max_age_bars"]:
            f.valid = False
            f.expired = True
            f.deactivated_reason = "expired"
            continue
            
        # Check for inversion - use low/high wicks for more accurate detection
        # A bullish FVG is invalidated if price closes below the lower bound OR
        # if the low wick touches/goes below the lower bound (full inversion)
        if f.direction == "bullish":
            if c < f.lower or l < f.lower:
                f.valid = False
                f.deactivated_reason = "inverted"
        # A bearish FVG is invalidated if price closes above the upper bound OR
        # if the high wick touches/goes above the upper bound (full inversion)
        elif f.direction == "bearish":
            if c > f.upper or h > f.upper:
                f.valid = False
                f.deactivated_reason = "inverted"


def prune_active_fvgs(active: List[FVG]) -> List[FVG]:
    """Prune active FVGs to maintain max per side limit."""
    valid = [f for f in active if f.valid and not f.expired]
    bulls = [f for f in valid if f.direction == "bullish"]
    bears = [f for f in valid if f.direction == "bearish"]
    
    bulls.sort(key=lambda x: x.created_at, reverse=True)
    bears.sort(key=lambda x: x.created_at, reverse=True)
    
    return bulls[:CONFIG["max_active_per_side"]] + bears[:CONFIG["max_active_per_side"]]


def find_conflicts(active: List[FVG], fvg: FVG) -> Tuple[bool, List[int]]:
    """Find conflicting FVGs (opposite direction with overlap)."""
    conflicts = []
    for f in active:
        if f.fvg_id == fvg.fvg_id or not f.valid or f.direction == fvg.direction:
            continue
        overlap = not (fvg.upper < f.lower or fvg.lower > f.upper)
        if overlap:
            conflicts.append(f.fvg_id)
    return (len(conflicts) > 0, conflicts)


def create_fvg_from_row(row: pd.Series, idx: int, direction: str) -> FVG:
    """Create FVG object from dataframe row."""
    if direction == "bullish":
        return FVG(
            fvg_id=next(_fvg_seq),
            direction="bullish",
            created_at=row["timestamp"],
            created_idx=idx,
            lower=float(row["bull_lower"]),
            upper=float(row["bull_upper"]),
            size_pts=float(row["bull_size"]),
            middle_body_pts=float(row["bull_middle_body"])
        )
    else:
        return FVG(
            fvg_id=next(_fvg_seq),
            direction="bearish",
            created_at=row["timestamp"],
            created_idx=idx,
            lower=float(row["bear_lower"]),
            upper=float(row["bear_upper"]),
            size_pts=float(row["bear_size"]),
            middle_body_pts=float(row["bear_middle_body"])
        )
