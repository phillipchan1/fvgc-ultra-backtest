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
    touch_count: int = 0
    trade_taken: bool = False


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
            
        # Check for inversion - only check close (not wick)
        # Special handling for iFVG: If a conflicting FVG is inverted, the original FVG stays valid
        
        if f.direction == "bullish":
            if c < f.lower:
                # Check if this close inverts any conflicting bearish FVGs
                # OR if there are conflicting bearish FVGs present that could be inverted
                inverted_conflicting_fvg = False
                has_conflicting_fvgs = False
                
                # Check existing FVGs
                for other in active_fvgs:
                    if other.fvg_id == f.fvg_id or other.direction != "bearish":
                        continue
                    # Check if this bearish FVG was created after the bullish FVG
                    if other.created_idx > f.created_idx:
                        # Check if it overlaps with a reasonable range (leg zone concept)
                        if other.lower <= f.upper + 20.0:  # Within 20 pts above the bullish FVG
                            has_conflicting_fvgs = True
                            # Did current close invert this bearish FVG?
                            if c > other.upper:
                                inverted_conflicting_fvg = True
                                break  # Found an inverted conflicting FVG, keep bullish FVG valid
                
                # Also check if current bar is FORMING a bearish FVG
                if not has_conflicting_fvgs and 'bear_fvg' in row.index:
                    if bool(row.get('bear_fvg', False)):
                        # A bearish FVG is forming on this bar
                        has_conflicting_fvgs = True
                
                # Keep the FVG valid if:
                # 1. We inverted a conflicting FVG (iFVG completion)
                # 2. We have conflicting FVGs present OR forming (potential iFVG setup)
                if not inverted_conflicting_fvg and not has_conflicting_fvgs:
                    f.valid = False
                    f.deactivated_reason = "inverted"
                # Otherwise, keep it valid (iFVG scenario or potential iFVG)
                
        elif f.direction == "bearish":
            if c > f.upper:
                # Check if this close inverts any conflicting bullish FVGs
                # OR if there are conflicting bullish FVGs present that could be inverted
                inverted_conflicting_fvg = False
                has_conflicting_fvgs = False
                
                # Check existing FVGs
                for other in active_fvgs:
                    if other.fvg_id == f.fvg_id or other.direction != "bullish":
                        continue
                    # Check if this bullish FVG was created after the bearish FVG
                    if other.created_idx > f.created_idx:
                        # Check if it overlaps with a reasonable range
                        if other.upper >= f.lower - 20.0:  # Within 20 pts below the bearish FVG
                            has_conflicting_fvgs = True
                            # Did current close invert this bullish FVG?
                            if c < other.lower:
                                inverted_conflicting_fvg = True
                                break  # Found an inverted conflicting FVG, keep bearish FVG valid
                
                # Also check if current bar is FORMING a bullish FVG
                if not has_conflicting_fvgs and 'bull_fvg' in row.index:
                    if bool(row.get('bull_fvg', False)):
                        # A bullish FVG is forming on this bar
                        has_conflicting_fvgs = True
                
                # Keep the FVG valid if:
                # 1. We inverted a conflicting FVG (iFVG completion)
                # 2. We have conflicting FVGs present OR forming (potential iFVG setup)
                if not inverted_conflicting_fvg and not has_conflicting_fvgs:
                    f.valid = False
                    f.deactivated_reason = "inverted"
                # Otherwise, keep it valid (iFVG scenario or potential iFVG)


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
