"""
Trade Management Strategies
"""
from dataclasses import dataclass
from typing import Optional, Tuple
import math


@dataclass
class TradeManagementResult:
    """Result of trade management evaluation."""
    tp_price: float
    sl_price: float
    partial_close_price: Optional[float] = None  # If set, take partial profit here
    partial_close_pct: float = 0.5  # What % of position to close
    trailing_sl_price: Optional[float] = None  # Updated SL after partial close


class TradeManagementStrategy:
    """Base class for trade management strategies."""
    
    def calculate_exits(
        self,
        entry_price: float,
        direction: str,
        fvg_lower: float,
        fvg_upper: float,
        fvg_size_pts: float
    ) -> TradeManagementResult:
        """Calculate exit prices based on strategy."""
        raise NotImplementedError


class FixedPointsStrategy(TradeManagementStrategy):
    """
    Type 1: Fixed points for both SL and TP.
    Simple and straightforward - same points for all trades.
    """
    
    def __init__(self, points_tp: float = 20.0, points_sl: float = 20.0):
        self.points_tp = points_tp
        self.points_sl = points_sl
    
    def calculate_exits(
        self,
        entry_price: float,
        direction: str,
        fvg_lower: float,
        fvg_upper: float,
        fvg_size_pts: float
    ) -> TradeManagementResult:
        
        if direction == "long":
            tp = entry_price + self.points_tp
            sl = entry_price - self.points_sl
        else:  # short
            tp = entry_price - self.points_tp
            sl = entry_price + self.points_sl
        
        return TradeManagementResult(tp_price=tp, sl_price=sl)


class DynamicFVGStrategy(TradeManagementStrategy):
    """
    Type 2: Dynamic sizing based on FVG size.
    
    Rules:
    - Calculate distance: +/- 5 points from FVG boundary
    - Round to nearest 5 points
    - Minimum: 15 points
    - Maximum: 40 points
    - Possible values: 15, 20, 25, 30, 35, 40
    """
    
    def __init__(self, buffer_pts: float = 5.0, min_pts: float = 15.0, max_pts: float = 40.0):
        self.buffer_pts = buffer_pts
        self.min_pts = min_pts
        self.max_pts = max_pts
    
    def _round_to_nearest_five(self, value: float) -> float:
        """Round to nearest 5."""
        return round(value / 5.0) * 5.0
    
    def calculate_exits(
        self,
        entry_price: float,
        direction: str,
        fvg_lower: float,
        fvg_upper: float,
        fvg_size_pts: float
    ) -> TradeManagementResult:
        
        if direction == "long":
            # For long: entry is typically near/above FVG upper
            # Distance from entry to FVG upper (the rebound point)
            distance_to_fvg = abs(entry_price - fvg_upper)
            raw_distance = distance_to_fvg + self.buffer_pts
        else:  # short
            # For short: entry is typically near/below FVG lower
            distance_to_fvg = abs(entry_price - fvg_lower)
            raw_distance = distance_to_fvg + self.buffer_pts
        
        # Round to nearest 5
        rounded_distance = self._round_to_nearest_five(raw_distance)
        
        # Clamp between min and max
        points = max(self.min_pts, min(rounded_distance, self.max_pts))
        
        if direction == "long":
            tp = entry_price + points
            sl = entry_price - points
        else:  # short
            tp = entry_price - points
            sl = entry_price + points
        
        return TradeManagementResult(tp_price=tp, sl_price=sl)


class PartialCloseStrategy(TradeManagementStrategy):
    """
    Type 3: Partial close at 50% profit + move SL to 50% of original SL (essentially BE).
    
    Rules:
    - When price reaches 50% of TP distance, close 50% of position
    - Move SL to 50% of original SL distance (breakeven protection)
    - Original TP remains for the other 50%
    """
    
    def __init__(self, base_points_tp: float = 20.0, base_points_sl: float = 20.0):
        self.base_points_tp = base_points_tp
        self.base_points_sl = base_points_sl
    
    def calculate_exits(
        self,
        entry_price: float,
        direction: str,
        fvg_lower: float,
        fvg_upper: float,
        fvg_size_pts: float
    ) -> TradeManagementResult:
        
        if direction == "long":
            tp = entry_price + self.base_points_tp
            sl = entry_price - self.base_points_sl
            
            # Partial close at 50% of TP distance
            partial_close = entry_price + (self.base_points_tp * 0.5)
            
            # New SL after partial close: 50% of original SL (essentially BE)
            trailing_sl = entry_price - (self.base_points_sl * 0.5)
            
        else:  # short
            tp = entry_price - self.base_points_tp
            sl = entry_price + self.base_points_sl
            
            # Partial close at 50% of TP distance
            partial_close = entry_price - (self.base_points_tp * 0.5)
            
            # New SL after partial close: 50% of original SL (essentially BE)
            trailing_sl = entry_price + (self.base_points_sl * 0.5)
        
        return TradeManagementResult(
            tp_price=tp,
            sl_price=sl,
            partial_close_price=partial_close,
            partial_close_pct=0.5,
            trailing_sl_price=trailing_sl
        )


class TrailingSLStrategy(TradeManagementStrategy):
    """
    Type 4: Move SL to 50% of original risk when trade reaches 50% of TP.
    
    Rules:
    - When price reaches 50% of TP distance, move SL to 50% of original risk
    - This reduces risk from -20 to -10, giving trade "room to breathe"
    - Allows full TP target to be reached without locking in profit early
    - No partial close, just SL adjustment
    - Original TP remains
    
    Example (Long @ 100):
    - Initial: TP @ 120 (+20), SL @ 80 (-20)
    - At 110 (+10 profit): SL moves to 90 (-10 risk)
    - Trade can still reach 120 (+20) or stop at 90 (-10)
    """
    
    def __init__(self, base_points_tp: float = 20.0, base_points_sl: float = 20.0):
        self.base_points_tp = base_points_tp
        self.base_points_sl = base_points_sl
    
    def calculate_exits(
        self,
        entry_price: float,
        direction: str,
        fvg_lower: float,
        fvg_upper: float,
        fvg_size_pts: float
    ) -> TradeManagementResult:
        
        if direction == "long":
            tp = entry_price + self.base_points_tp
            sl = entry_price - self.base_points_sl
            
            # Trigger: When price reaches 50% of TP distance
            partial_close = entry_price + (self.base_points_tp * 0.5)
            
            # New SL: 50% of original risk (room to breathe, not locking profit)
            trailing_sl = entry_price - (self.base_points_sl * 0.5)
            
        else:  # short
            tp = entry_price - self.base_points_tp
            sl = entry_price + self.base_points_sl
            
            # Trigger: When price reaches 50% of TP distance
            partial_close = entry_price - (self.base_points_tp * 0.5)
            
            # New SL: 50% of original risk (room to breathe, not locking profit)
            trailing_sl = entry_price + (self.base_points_sl * 0.5)
        
        return TradeManagementResult(
            tp_price=tp,
            sl_price=sl,
            partial_close_price=partial_close,
            partial_close_pct=0.0,  # No partial close, just trigger for SL move
            trailing_sl_price=trailing_sl
        )


class DynamicTrailingSLStrategy(TradeManagementStrategy):
    """
    Type 5: Dynamic FVG-based sizing + Trailing SL.
    
    Combines:
    - Dynamic TP/SL calculation based on FVG position (15-40pts, increments of 5)
    - When price reaches 50% of dynamic TP, move SL to 50% of original risk
    
    Example (Long @ 100, FVG gives 30pt target):
    - Initial: TP @ 130 (+30), SL @ 70 (-30)
    - At 115 (+15 profit): SL moves to 85 (-15 risk)
    - Trade can still reach 130 (+30) or stop at 85 (-15)
    """
    
    def __init__(self, buffer_pts: float = 5.0, min_pts: float = 15.0, max_pts: float = 40.0):
        self.buffer_pts = buffer_pts
        self.min_pts = min_pts
        self.max_pts = max_pts
    
    def _round_to_nearest_five(self, value: float) -> float:
        """Round to nearest 5."""
        return round(value / 5.0) * 5.0
    
    def calculate_exits(
        self,
        entry_price: float,
        direction: str,
        fvg_lower: float,
        fvg_upper: float,
        fvg_size_pts: float
    ) -> TradeManagementResult:
        
        # Calculate dynamic distance (same as DynamicFVGStrategy)
        if direction == "long":
            distance_to_fvg = abs(entry_price - fvg_upper)
            raw_distance = distance_to_fvg + self.buffer_pts
        else:  # short
            distance_to_fvg = abs(entry_price - fvg_lower)
            raw_distance = distance_to_fvg + self.buffer_pts
        
        # Round to nearest 5 and clamp
        rounded_distance = self._round_to_nearest_five(raw_distance)
        points = max(self.min_pts, min(rounded_distance, self.max_pts))
        
        if direction == "long":
            tp = entry_price + points
            sl = entry_price - points
            
            # Trigger: When price reaches 50% of TP distance
            partial_close = entry_price + (points * 0.5)
            
            # New SL: 50% of original risk
            trailing_sl = entry_price - (points * 0.5)
            
        else:  # short
            tp = entry_price - points
            sl = entry_price + points
            
            # Trigger: When price reaches 50% of TP distance
            partial_close = entry_price - (points * 0.5)
            
            # New SL: 50% of original risk
            trailing_sl = entry_price + (points * 0.5)
        
        return TradeManagementResult(
            tp_price=tp,
            sl_price=sl,
            partial_close_price=partial_close,
            partial_close_pct=0.0,  # No partial close, just trigger for SL move
            trailing_sl_price=trailing_sl
        )


class DynamicPartialCloseStrategy(TradeManagementStrategy):
    """
    Type 6: Dynamic FVG-based sizing + Partial Close.
    
    Combines:
    - Dynamic TP/SL calculation based on FVG position (15-40pts, increments of 5)
    - When price reaches 50% of dynamic TP, close 50% of position
    - Move SL to 50% of original risk (breakeven protection)
    
    Example (Long @ 100, FVG gives 30pt target):
    - Initial: TP @ 130 (+30), SL @ 70 (-30)
    - At 115 (+15 profit): Close 50%, move SL to 85 (-15)
    - If SL hits: +7.5 (partial) - 7.5 (remaining) = $0 (breakeven)
    - If TP hits: +7.5 (partial) + 15 (remaining 50% to TP) = +22.5pts total
    """
    
    def __init__(self, buffer_pts: float = 5.0, min_pts: float = 15.0, max_pts: float = 40.0):
        self.buffer_pts = buffer_pts
        self.min_pts = min_pts
        self.max_pts = max_pts
    
    def _round_to_nearest_five(self, value: float) -> float:
        """Round to nearest 5."""
        return round(value / 5.0) * 5.0
    
    def calculate_exits(
        self,
        entry_price: float,
        direction: str,
        fvg_lower: float,
        fvg_upper: float,
        fvg_size_pts: float
    ) -> TradeManagementResult:
        
        # Calculate dynamic distance (same as DynamicFVGStrategy)
        if direction == "long":
            distance_to_fvg = abs(entry_price - fvg_upper)
            raw_distance = distance_to_fvg + self.buffer_pts
        else:  # short
            distance_to_fvg = abs(entry_price - fvg_lower)
            raw_distance = distance_to_fvg + self.buffer_pts
        
        # Round to nearest 5 and clamp
        rounded_distance = self._round_to_nearest_five(raw_distance)
        points = max(self.min_pts, min(rounded_distance, self.max_pts))
        
        if direction == "long":
            tp = entry_price + points
            sl = entry_price - points
            
            # Partial close at 50% of TP distance
            partial_close = entry_price + (points * 0.5)
            
            # New SL after partial close: 50% of original risk (breakeven)
            trailing_sl = entry_price - (points * 0.5)
            
        else:  # short
            tp = entry_price - points
            sl = entry_price + points
            
            # Partial close at 50% of TP distance
            partial_close = entry_price - (points * 0.5)
            
            # New SL after partial close: 50% of original risk (breakeven)
            trailing_sl = entry_price + (points * 0.5)
        
        return TradeManagementResult(
            tp_price=tp,
            sl_price=sl,
            partial_close_price=partial_close,
            partial_close_pct=0.5,
            trailing_sl_price=trailing_sl
        )


def get_trade_management_strategy(strategy_type: str, **kwargs) -> TradeManagementStrategy:
    """Factory function to get trade management strategy by type."""
    strategies = {
        "fixed": FixedPointsStrategy,
        "dynamic_fvg": DynamicFVGStrategy,
        "partial_close": PartialCloseStrategy,
        "trailing_sl": TrailingSLStrategy,
        "dynamic_trailing_sl": DynamicTrailingSLStrategy,
        "dynamic_partial_close": DynamicPartialCloseStrategy,
    }
    
    if strategy_type not in strategies:
        raise ValueError(f"Unknown strategy type: {strategy_type}. Available: {list(strategies.keys())}")
    
    return strategies[strategy_type](**kwargs)

