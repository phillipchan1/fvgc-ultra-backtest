from typing import Optional, List
import pandas as pd
import numpy as np
from .base import EntryModel, TradeSignal
from ..core.fvg_detection import FVG


class FVGContinuationIFVGModel(EntryModel):
    """
    FVG + iFVG (Inverted Fair Value Gap) continuation setup.
    
    This model requires a conflicting FVG in the leg zone that gets INVERTED
    on the bullish/bearish move. The inversion acts as confirmation.
    """

    def __init__(self, pivot_strength=3, max_close_dist=7.5, equal_hl_tolerance=0.5, max_touches=5):
        self._pivot_strength = pivot_strength
        self._max_close_dist = max_close_dist  # Distance from previous bar (consistent across all models)
        self._equal_hl_tolerance = equal_hl_tolerance
        self._max_touches = max_touches  # Same as other models

    @property
    def name(self) -> str:
        return "fvg_continuation_ifvg"

    def evaluate(
        self,
        fvg: FVG,
        active_fvgs: list,
        current_bar: pd.Series,
        bar_index: int,
        dataframe: pd.DataFrame
    ) -> Optional[TradeSignal]:
        """Evaluate the FVG continuation with inverted FVG setup."""

        if fvg.trade_taken or not fvg.valid:
            return None

        # For iFVG, we allow entry on the bar immediately after FVG creation
        # (to capture same-candle inversions). Only reject if we're ON the FVG creation bar.
        if bar_index <= fvg.created_idx:
            return None

        # Note: Touch counting is now handled in backtest_engine to avoid double-counting
        # when multiple models evaluate the same FVG
        
        if fvg.touch_count > self._max_touches:
            fvg.valid = False
            fvg.deactivated_reason = "max_touches_exceeded"
            return None
        
        if bar_index < 1:
            return None

        previous_bar = dataframe.iloc[bar_index - 1]

        if fvg.direction == 'bullish':
            return self._evaluate_bullish(fvg, current_bar, previous_bar, bar_index, dataframe)
        elif fvg.direction == 'bearish':
            return self._evaluate_bearish(fvg, current_bar, previous_bar, bar_index, dataframe)

        return None

    def _find_swing_high(self, start_index: int, end_index: int, dataframe: pd.DataFrame) -> Optional[int]:
        """Finds the nearest swing high between start_index and end_index (exclusive)."""
        highs = dataframe['high']
        # Search only up to (but not including) end_index to avoid looking into the future
        for i in range(start_index, min(end_index, len(dataframe) - self._pivot_strength)):
            if i < self._pivot_strength:
                continue
            
            is_basic_pivot = highs.iloc[i] > highs.iloc[i-1] and highs.iloc[i] > highs.iloc[i+1]
            if not is_basic_pivot:
                continue

            window = highs.iloc[i - self._pivot_strength : i + self._pivot_strength + 1]
            if highs.iloc[i] >= window.max():
                return i
        return None

    def _find_swing_low(self, start_index: int, end_index: int, dataframe: pd.DataFrame) -> Optional[int]:
        """Finds the nearest swing low between start_index and end_index (exclusive)."""
        lows = dataframe['low']
        # Search only up to (but not including) end_index to avoid looking into the future
        for i in range(start_index, min(end_index, len(dataframe) - self._pivot_strength)):
            if i < self._pivot_strength:
                continue

            is_basic_pivot = lows.iloc[i] < lows.iloc[i-1] and lows.iloc[i] < lows.iloc[i+1]
            if not is_basic_pivot:
                continue
            
            window = lows.iloc[i - self._pivot_strength : i + self._pivot_strength + 1]
            if lows.iloc[i] <= window.min():
                return i
        return None

    def _evaluate_bullish(
        self,
        fvg: FVG,
        current_bar: pd.Series,
        previous_bar: pd.Series,
        bar_index: int,
        dataframe: pd.DataFrame
    ) -> Optional[TradeSignal]:
        
        # Check for retracement into FVG
        retrace_occurred = False
        for idx in range(fvg.created_idx + 1, bar_index + 1):
            if dataframe['low'].iloc[idx] <= fvg.upper:
                retrace_occurred = True
                break
        if not retrace_occurred:
            return None

        # 1. Identify Swing High
        # Search from FVG creation up to (but not including) current bar
        swing_high_index = self._find_swing_high(fvg.created_idx + 1, bar_index, dataframe)
        if swing_high_index is None:
            return None
        
        swing_high_price = dataframe['high'].iloc[swing_high_index]
        
        # Check if swing high was swept
        max_high_so_far = dataframe['high'].iloc[swing_high_index:bar_index+1].max()
        if max_high_so_far > swing_high_price:
            return None

        # 2. Define Leg Zone
        leg_low_price = dataframe['low'].iloc[fvg.created_idx + 1 : swing_high_index + 1].min()
        leg_high_price = swing_high_price
        
        # 3. Look for INVERTED bearish FVG in the SAME CANDLE (critical iFVG rule)
        # The inversion must happen in the current bar, not in any prior bar
        inverted_fvg_found = self._find_and_check_inverted_fvg_same_candle(
            'bearish', fvg.created_idx + 1, swing_high_index, bar_index,
            leg_low_price, leg_high_price, current_bar, dataframe
        )
        
        # For iFVG model, we REQUIRE an inverted conflicting FVG in same candle
        if not inverted_fvg_found:
            return None

        # 4. Entry Candle Criteria
        # Rule 1: Close above previous high
        if current_bar['close'] <= previous_bar['high']:
            return None
        
        # Rule 2: Distance check (consistent across all models)
        if self._max_close_dist is not None:
            distance = current_bar['close'] - previous_bar['high']
            if distance > self._max_close_dist:
                return None
        
        # Note: "Ideal Entry Level Line" check is REMOVED for iFVG model
        # iFVG requires waiting for conflicting FVG formation and inversion,
        # which naturally takes more time and allows price to move further from
        # the original FVG's first candle open. The inversion itself provides
        # the confirmation needed for entry.

        if abs(current_bar['high'] - swing_high_price) < self._equal_hl_tolerance:
            return None
            
        if current_bar['high'] > swing_high_price:
            return None
            
        if current_bar['close'] > swing_high_price:
            return None
            
        return TradeSignal(
            entry_time=current_bar["timestamp"],
            entry_price=current_bar["close"],
            direction="long",
            entry_model=self.name,
            fvg_id=fvg.fvg_id,
            fvg_lower=fvg.lower,
            fvg_upper=fvg.upper,
            fvg_direction="bullish",
            fvg_size_pts=fvg.size_pts
        )

    def _evaluate_bearish(
        self,
        fvg: FVG,
        current_bar: pd.Series,
        previous_bar: pd.Series,
        bar_index: int,
        dataframe: pd.DataFrame
    ) -> Optional[TradeSignal]:
        
        # Check for retracement into FVG
        retrace_occurred = False
        for idx in range(fvg.created_idx + 1, bar_index + 1):
            if dataframe['high'].iloc[idx] >= fvg.lower:
                retrace_occurred = True
                break
        if not retrace_occurred:
            return None

        # 1. Identify Swing Low
        # Search from FVG creation up to (but not including) current bar
        swing_low_index = self._find_swing_low(fvg.created_idx + 1, bar_index, dataframe)
        if swing_low_index is None:
            return None
        
        swing_low_price = dataframe['low'].iloc[swing_low_index]
        
        # Check if swing low was swept
        min_low_so_far = dataframe['low'].iloc[swing_low_index:bar_index+1].min()
        if min_low_so_far < swing_low_price:
            return None

        # 2. Define Leg Zone
        leg_high_price = dataframe['high'].iloc[fvg.created_idx + 1 : swing_low_index + 1].max()
        leg_low_price = swing_low_price
        
        # 3. Look for INVERTED bullish FVG in the SAME CANDLE (critical iFVG rule)
        # The inversion must happen in the current bar, not in any prior bar
        inverted_fvg_found = self._find_and_check_inverted_fvg_same_candle(
            'bullish', fvg.created_idx + 1, swing_low_index, bar_index,
            leg_low_price, leg_high_price, current_bar, dataframe
        )
        
        # For iFVG model, we REQUIRE an inverted conflicting FVG in same candle
        if not inverted_fvg_found:
            return None

        # 4. Entry Candle Criteria
        # Rule 1: Close below previous low
        if current_bar['close'] >= previous_bar['low']:
            return None
        
        # Rule 2: Distance check (consistent across all models)
        if self._max_close_dist is not None:
            distance = previous_bar['low'] - current_bar['close']
            if distance > self._max_close_dist:
                return None
        
        # Note: "Ideal Entry Level Line" check is REMOVED for iFVG model
        # iFVG requires waiting for conflicting FVG formation and inversion,
        # which naturally takes more time and allows price to move further from
        # the original FVG's first candle open. The inversion itself provides
        # the confirmation needed for entry.

        if abs(current_bar['low'] - swing_low_price) < self._equal_hl_tolerance:
            return None
            
        if current_bar['low'] < swing_low_price:
            return None
            
        if current_bar['close'] < swing_low_price:
            return None
            
        return TradeSignal(
            entry_time=current_bar["timestamp"],
            entry_price=current_bar["close"],
            direction="short",
            entry_model=self.name,
            fvg_id=fvg.fvg_id,
            fvg_lower=fvg.lower,
            fvg_upper=fvg.upper,
            fvg_direction="bearish",
            fvg_size_pts=fvg.size_pts
        )
        
    def _find_and_check_inverted_fvg_same_candle(self, fvg_direction: str, start_idx: int, end_idx: int, 
                                                   current_bar_idx: int, leg_low: float, leg_high: float,
                                                   current_bar: pd.Series, dataframe: pd.DataFrame) -> bool:
        """
        Look for a conflicting FVG that was INVERTED IN THE CURRENT CANDLE.
        This is the critical iFVG rule: inversion must happen in the same candle as entry.
        Returns True if at least one inverted conflicting FVG is found in current bar.
        """
        for i in range(start_idx, end_idx - 1):
            if fvg_direction == 'bearish':
                # Looking for bearish FVGs in a bullish setup
                if 'bear_fvg' in dataframe.columns and dataframe['bear_fvg'].iloc[i+1]:
                    fvg_idx = i + 1
                    fvg_top = dataframe['bear_upper'].iloc[fvg_idx]
                    fvg_bottom = dataframe['bear_lower'].iloc[fvg_idx]
                    
                    # Check if FVG overlaps with leg zone
                    if (fvg_top >= leg_low) and (fvg_bottom <= leg_high):
                        # CRITICAL: Check if THIS CANDLE (current_bar) inverts the bearish FVG
                        # The current candle must close above the bearish FVG top
                        if current_bar['close'] > fvg_top:
                            # Found an inverted conflicting FVG in SAME CANDLE!
                            return True
                            
            elif fvg_direction == 'bullish':
                # Looking for bullish FVGs in a bearish setup
                if 'bull_fvg' in dataframe.columns and dataframe['bull_fvg'].iloc[i+1]:
                    fvg_idx = i + 1
                    fvg_top = dataframe['bull_upper'].iloc[fvg_idx]
                    fvg_bottom = dataframe['bull_lower'].iloc[fvg_idx]
                    
                    # Check if FVG overlaps with leg zone
                    if (fvg_bottom <= leg_high) and (fvg_top >= leg_low):
                        # CRITICAL: Check if THIS CANDLE (current_bar) inverts the bullish FVG
                        # The current candle must close below the bullish FVG bottom
                        if current_bar['close'] < fvg_bottom:
                            # Found an inverted conflicting FVG in SAME CANDLE!
                            return True
        
        return False

