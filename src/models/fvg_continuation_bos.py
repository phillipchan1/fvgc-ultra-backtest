from typing import Optional, List
import pandas as pd
import numpy as np
from .base import EntryModel, TradeSignal
from ..core.fvg_detection import FVG
from ..core.config import CONFIG


class FVGContinuationBOSModel(EntryModel):
    """
    FVG + BOS (Break of Structure) continuation setup.
    
    Entry occurs when candle body closes THROUGH the swing point,
    confirming strong buyer/seller presence and structural break.
    """

    def __init__(self, pivot_strength=3, max_close_dist=7.5, max_touches=5):
        self._pivot_strength = pivot_strength
        self._max_close_dist = max_close_dist
        self._max_touches = max_touches

    @property
    def name(self) -> str:
        return "fvg_continuation_bos"

    def evaluate(
        self,
        fvg: FVG,
        active_fvgs: list,
        current_bar: pd.Series,
        bar_index: int,
        dataframe: pd.DataFrame
    ) -> Optional[TradeSignal]:
        """Evaluate the FVG continuation with Break of Structure setup."""

        if fvg.trade_taken or not fvg.valid:
            return None

        # FVG must have minimum age before trading
        # This prevents trading gaps that were just created
        min_age_bars = CONFIG.get("fvg_min_age_bars", 2)
        bars_since_creation = bar_index - fvg.created_idx
        if bars_since_creation < min_age_bars:
            return None

        # Note: Touch counting handled in backtest_engine
        if fvg.touch_count > self._max_touches:
            fvg.valid = False
            fvg.deactivated_reason = "max_touches_exceeded"
            return None
        
        if bar_index < 1:
            return None

        previous_bar = dataframe.iloc[bar_index - 1]

        if fvg.direction == 'bullish':
            return self._evaluate_bullish(fvg, current_bar, previous_bar, bar_index, dataframe, active_fvgs)
        elif fvg.direction == 'bearish':
            return self._evaluate_bearish(fvg, current_bar, previous_bar, bar_index, dataframe, active_fvgs)

        return None

    def _find_swing_high(self, start_index: int, end_index: int, dataframe: pd.DataFrame) -> Optional[tuple]:
        """
        Finds the most recent local high in the range (simpler detection).
        Returns (index, price) or None.
        
        Note: For BOS, the swing high is simply the highest high between FVG creation
        and current bar. This can be just the FVG creation bar itself if entering
        immediately after FVG forms.
        """
        if start_index > end_index:
            return None
        
        # Include the range from start_index to end_index (inclusive of start, exclusive of end)
        # But if start == end, we have no bars to check
        if start_index == end_index:
            return None
            
        highs = dataframe['high'].iloc[start_index:end_index]
        if len(highs) == 0:
            return None
        
        # Find the highest point in the range
        max_idx = highs.idxmax()
        max_price = highs[max_idx]
        
        return (max_idx, max_price)

    def _find_swing_low(self, start_index: int, end_index: int, dataframe: pd.DataFrame) -> Optional[tuple]:
        """
        Finds the most recent local low in the range (simpler detection).
        Returns (index, price) or None.
        
        Note: For BOS, the swing low is simply the lowest low between FVG creation
        and current bar. This can be just the FVG creation bar itself if entering
        immediately after FVG forms.
        """
        if start_index > end_index:
            return None
        
        # Include the range from start_index to end_index (inclusive of start, exclusive of end)
        # But if start == end, we have no bars to check
        if start_index == end_index:
            return None
            
        lows = dataframe['low'].iloc[start_index:end_index]
        if len(lows) == 0:
            return None
        
        # Find the lowest point in the range
        min_idx = lows.idxmin()
        min_price = lows[min_idx]
        
        return (min_idx, min_price)

    def _evaluate_bullish(
        self,
        fvg: FVG,
        current_bar: pd.Series,
        previous_bar: pd.Series,
        bar_index: int,
        dataframe: pd.DataFrame,
        active_fvgs: List[FVG] = None
    ) -> Optional[TradeSignal]:
        
        # Proximity Filter: Check for opposing FVGs within 20 points
        # For bullish entries, reject if there's an active bearish FVG within 20 pts above
        if active_fvgs:
            for other_fvg in active_fvgs:
                if other_fvg.direction == 'bearish' and other_fvg.valid:
                    # Check if bearish FVG is above and within 20 pts
                    if other_fvg.lower > fvg.upper:  # Bearish FVG is above
                        distance = other_fvg.lower - fvg.upper
                        if distance < 20:
                            return None  # Too close to opposing FVG
        
        # Check for retracement into FVG
        retrace_occurred = False
        for idx in range(fvg.created_idx + 1, bar_index + 1):
            if dataframe['low'].iloc[idx] <= fvg.upper:
                retrace_occurred = True
                break
        if not retrace_occurred:
            return None

        # 1. Find the most recent local high between FVG creation and current bar
        # The swing must be established AFTER FVG creation (not on the FVG bar itself)
        # Search from bar AFTER FVG creation to current bar (exclusive of current)
        # This ensures: FVG created -> price moves up -> swing forms -> BOS on current bar
        swing_result = self._find_swing_high(fvg.created_idx + 1, bar_index, dataframe)
        if swing_result is None:
            return None
        
        swing_high_index, swing_high_price = swing_result
        
        # Ensure swing was not created on the FVG creation bar
        # The swing point must be established AFTER the FVG
        if swing_high_index <= fvg.created_idx:
            return None
        
        # 2. BOS Rule: Current candle CLOSE must be THROUGH (above) the swing high
        if current_bar['close'] <= swing_high_price:
            return None  # Not a BOS - body didn't close through

        # 3. Distance Rule: Close must be within 7.5 pts above previous candle's HIGH
        distance = current_bar['close'] - previous_bar['high']
        if distance > self._max_close_dist:
            return None

        # Entry is valid - body closed through swing point with acceptable distance
        # Calculate metadata for permutation tracking
        distance_from_swing = current_bar['close'] - swing_high_price
        swing_bars_ago = bar_index - swing_high_index
        
        return TradeSignal(
            entry_time=current_bar["timestamp"],
            entry_price=current_bar["close"],
            direction="long",
            entry_model=self.name,
            fvg_id=fvg.fvg_id,
            fvg_lower=fvg.lower,
            fvg_upper=fvg.upper,
            fvg_direction="bullish",
            fvg_size_pts=fvg.size_pts,
            metadata={
                'swing_point_price': swing_high_price,
                'distance_from_swing': distance_from_swing,
                'swing_bars_ago': swing_bars_ago
            }
        )

    def _evaluate_bearish(
        self,
        fvg: FVG,
        current_bar: pd.Series,
        previous_bar: pd.Series,
        bar_index: int,
        dataframe: pd.DataFrame,
        active_fvgs: List[FVG] = None
    ) -> Optional[TradeSignal]:
        
        # Proximity Filter: Check for opposing FVGs within 20 points
        # For bearish entries, reject if there's an active bullish FVG within 20 pts below
        if active_fvgs:
            for other_fvg in active_fvgs:
                if other_fvg.direction == 'bullish' and other_fvg.valid:
                    # Check if bullish FVG is below and within 20 pts
                    if other_fvg.upper < fvg.lower:  # Bullish FVG is below
                        distance = fvg.lower - other_fvg.upper
                        if distance < 20:
                            return None  # Too close to opposing FVG
        
        # Check for retracement into FVG
        retrace_occurred = False
        for idx in range(fvg.created_idx + 1, bar_index + 1):
            if dataframe['high'].iloc[idx] >= fvg.lower:
                retrace_occurred = True
                break
        if not retrace_occurred:
            return None

        # 1. Find the most recent local low between FVG creation and current bar
        # The swing must be established AFTER FVG creation (not on the FVG bar itself)
        # Search from bar AFTER FVG creation to current bar (exclusive of current)
        # This ensures: FVG created -> price moves down -> swing forms -> BOS on current bar
        swing_result = self._find_swing_low(fvg.created_idx + 1, bar_index, dataframe)
        if swing_result is None:
            return None
        
        swing_low_index, swing_low_price = swing_result
        
        # Ensure swing was not created on the FVG creation bar
        # The swing point must be established AFTER the FVG
        if swing_low_index <= fvg.created_idx:
            return None
        
        # 2. BOS Rule: Current candle CLOSE must be THROUGH (below) the swing low
        if current_bar['close'] >= swing_low_price:
            return None  # Not a BOS - body didn't close through

        # 3. Distance Rule: Close must be within 7.5 pts below previous candle's LOW
        distance = previous_bar['low'] - current_bar['close']
        if distance > self._max_close_dist:
            return None

        # Entry is valid - body closed through swing point with acceptable distance
        # Calculate metadata for permutation tracking
        distance_from_swing = swing_low_price - current_bar['close']
        swing_bars_ago = bar_index - swing_low_index
        
        return TradeSignal(
            entry_time=current_bar["timestamp"],
            entry_price=current_bar["close"],
            direction="short",
            entry_model=self.name,
            fvg_id=fvg.fvg_id,
            fvg_lower=fvg.lower,
            fvg_upper=fvg.upper,
            fvg_direction="bearish",
            fvg_size_pts=fvg.size_pts,
            metadata={
                'swing_point_price': swing_low_price,
                'distance_from_swing': distance_from_swing,
                'swing_bars_ago': swing_bars_ago
            }
        )

