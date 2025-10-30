# basic_pullback.py
# ---------------------------------------------------------------------------
# Basic Pullback Entry Model - "Bread and Butter" Setup
# 
# Entry Conditions:
# 1. Price enters the gap (low/high touches or enters gap bounds)
# 2. Gap has not been inverted (valid FVG)
# 3. Current candle closes ABOVE previous candle high (for bullish) 
#    or BELOW previous candle low (for bearish)
# 4. Enter on the close of the current candle
# ---------------------------------------------------------------------------

from typing import Optional
import pandas as pd
from .base import EntryModel, TradeSignal
from ..core.fvg_detection import FVG
from ..core.config import CONFIG


class BasicPullbackEntry(EntryModel):
    """
    Basic pullback entry model - classic FVG continuation setup.
    
    For bullish FVG:
    - Price enters gap (low touches or goes below upper bound) - can be on current bar OR previous bar
    - Gap remains valid (not inverted)
    - Current candle closes ABOVE immediate previous candle high
    - Enter long on current candle close
    
    For bearish FVG:
    - Price enters gap (high touches or goes above lower bound) - can be on current bar OR previous bar
    - Gap remains valid (not inverted)
    - Current candle closes BELOW immediate previous candle low
    - Enter short on current candle close
    """
    
    def __init__(self):
        # Track when price enters each FVG {fvg_id: bar_index}
        self._fvg_entry_bars = {}
    
    @property
    def name(self) -> str:
        return "basic_pullback"
    
    def evaluate(
        self,
        fvg: FVG,
        active_fvgs: list,
        current_bar: pd.Series,
        bar_index: int,
        dataframe: pd.DataFrame
    ) -> Optional[TradeSignal]:
        """Evaluate basic pullback entry conditions."""
        
        # Only evaluate valid FVGs
        if not fvg.valid or fvg.expired:
            return None
        
        # FVG must have been created BEFORE this bar (can't enter on same bar as creation)
        # This ensures price has had time to move away and retrace back into the gap
        if bar_index <= fvg.created_idx:
            return None
        
        # Check if gap is inverted (handled by FVG validity, but double-check)
        o, h, l, c = float(current_bar["open"]), float(current_bar["high"]), float(current_bar["low"]), float(current_bar["close"])
        
        # Need previous bar for comparison
        if bar_index == 0:
            return None
        
        prev_bar = dataframe.iloc[bar_index - 1]
        prev_high = float(prev_bar["high"])
        prev_low = float(prev_bar["low"])
        
        # BULLISH FVG - Enter Long
        if fvg.direction == "bullish":
            # IMPORTANT: Price must have moved AWAY from the gap after creation, then retraced back
            # We need at least 1 bar AFTER creation where price was completely above the gap
            
            # 1. Check if price enters/interacts with gap
            # Supports both:
            #   - Full entry: close inside gap OR wick touches gap
            #   - Tap: only wick (high/low) touches gap, close outside
            # Can be on current bar OR we may have entered on a previous bar
            
            # For bullish FVG: price enters when LOW wick touches/enters upper bound
            # (price retraces down into the gap from above)
            # Allow small tolerance for near-touches
            touch_tolerance = CONFIG.get("fvg_touch_tolerance_pts", 1.0)
            low_touches_gap = l <= (fvg.upper + touch_tolerance)
            
            # Full entry: close inside gap bounds
            close_inside_gap_now = fvg.lower <= c <= fvg.upper
            
            # Price enters gap if low touches upper bound OR close is inside bounds
            price_enters_gap_now = low_touches_gap or close_inside_gap_now
            
            # Check if price entered on previous bar (but not the creation bar itself)
            price_entered_prev = False
            if bar_index > 0:
                prev_bar_for_entry_check = dataframe.iloc[bar_index - 1]
                prev_l_check = float(prev_bar_for_entry_check["low"])
                prev_h_check = float(prev_bar_for_entry_check["high"])
                prev_c_check = float(prev_bar_for_entry_check["close"])
                
                # Only count as "entered" if this wasn't the creation bar
                if prev_bar_for_entry_check.name > fvg.created_idx:
                    # For bullish: low touches upper bound (with tolerance) OR close inside
                    touch_tolerance = CONFIG.get("fvg_touch_tolerance_pts", 1.0)
                    prev_low_touches = prev_l_check <= (fvg.upper + touch_tolerance)
                    prev_close_inside = fvg.lower <= prev_c_check <= fvg.upper
                    price_entered_prev = prev_low_touches or prev_close_inside
            
            # Additional check: After FVG creation, price must have been completely above the gap first
            # This ensures price moved away, then retraced back (not just touching on creation bar)
            price_moved_away_first = False
            if bar_index > fvg.created_idx:
                # Check if there was at least one bar after creation where low > gap_upper (price was above gap)
                for check_idx in range(fvg.created_idx + 1, bar_index):
                    check_bar = dataframe.iloc[check_idx]
                    if float(check_bar["low"]) > fvg.upper:
                        price_moved_away_first = True
                        break
            
            price_enters_gap = (price_enters_gap_now or price_entered_prev) and price_moved_away_first
            
            # Track when price entered this FVG
            if price_enters_gap_now:
                self._fvg_entry_bars[fvg.fvg_id] = bar_index
            elif price_entered_prev and fvg.fvg_id not in self._fvg_entry_bars:
                self._fvg_entry_bars[fvg.fvg_id] = bar_index - 1
            
            # 2. Gap must still be valid (not inverted)
            gap_valid = c >= fvg.lower  # Close must be above lower bound
            
            # 3. Current candle closes ABOVE immediate previous candle high
            closes_above_prev_high = c > prev_high
            
            # Entry condition: price must have entered gap (now or previously) AND
            # current bar closes above immediate previous high AND gap is still valid
            if price_enters_gap and gap_valid and closes_above_prev_high:
                return TradeSignal(
                    entry_time=current_bar["timestamp"],
                    entry_price=c,  # Enter on current candle close
                    direction="long",
                    entry_model=self.name,
                    fvg_id=fvg.fvg_id,
                    fvg_lower=fvg.lower,
                    fvg_upper=fvg.upper,
                    fvg_direction="bullish",
                    fvg_size_pts=fvg.size_pts
                )
        
        # BEARISH FVG - Enter Short
        elif fvg.direction == "bearish":
            # IMPORTANT: Price must have moved AWAY from the gap after creation, then retraced back
            # We need at least 1 bar AFTER creation where price was completely below the gap
            
            # 1. Check if price enters/interacts with gap
            # Supports both:
            #   - Full entry: close inside gap OR wick touches gap
            #   - Tap: only wick (high/low) touches gap, close outside
            # Can be on current bar OR we may have entered on a previous bar
            
            # For bearish FVG: price enters when HIGH wick touches/enters lower bound
            # (price retraces up into the gap from below)
            # Allow small tolerance for near-touches
            touch_tolerance = CONFIG.get("fvg_touch_tolerance_pts", 1.0)
            high_touches_gap = h >= (fvg.lower - touch_tolerance)
            
            # Full entry: close inside gap bounds
            close_inside_gap_now = fvg.lower <= c <= fvg.upper
            
            # Price enters gap if high touches lower bound OR close is inside bounds
            price_enters_gap_now = high_touches_gap or close_inside_gap_now
            
            # Check if price entered on previous bar (but not the creation bar itself)
            price_entered_prev = False
            if bar_index > 0:
                prev_bar_for_entry_check = dataframe.iloc[bar_index - 1]
                prev_l_check = float(prev_bar_for_entry_check["low"])
                prev_h_check = float(prev_bar_for_entry_check["high"])
                prev_c_check = float(prev_bar_for_entry_check["close"])
                
                # Only count as "entered" if this wasn't the creation bar
                if prev_bar_for_entry_check.name > fvg.created_idx:
                    # For bearish: high touches lower bound (with tolerance) OR close inside
                    touch_tolerance = CONFIG.get("fvg_touch_tolerance_pts", 1.0)
                    prev_high_touches = prev_h_check >= (fvg.lower - touch_tolerance)
                    prev_close_inside = fvg.lower <= prev_c_check <= fvg.upper
                    price_entered_prev = prev_high_touches or prev_close_inside
            
            # Additional check: After FVG creation, price must have been completely below the gap first
            # This ensures price moved away, then retraced back (not just touching on creation bar)
            price_moved_away_first = False
            if bar_index > fvg.created_idx:
                # Check if there was at least one bar after creation where high < gap_lower (price was below gap)
                for check_idx in range(fvg.created_idx + 1, bar_index):
                    check_bar = dataframe.iloc[check_idx]
                    if float(check_bar["high"]) < fvg.lower:
                        price_moved_away_first = True
                        break
            
            price_enters_gap = (price_enters_gap_now or price_entered_prev) and price_moved_away_first
            
            # Track when price entered this FVG
            if price_enters_gap_now:
                self._fvg_entry_bars[fvg.fvg_id] = bar_index
            elif price_entered_prev and fvg.fvg_id not in self._fvg_entry_bars:
                self._fvg_entry_bars[fvg.fvg_id] = bar_index - 1
            
            # 2. Gap must still be valid (not inverted)
            gap_valid = c <= fvg.upper  # Close must be below upper bound
            
            # 3. Current candle closes BELOW immediate previous candle low
            closes_below_prev_low = c < prev_low
            
            # Entry condition: price must have entered gap (now or previously) AND
            # current bar closes below immediate previous low AND gap is still valid
            if price_enters_gap and gap_valid and closes_below_prev_low:
                return TradeSignal(
                    entry_time=current_bar["timestamp"],
                    entry_price=c,  # Enter on current candle close
                    direction="short",
                    entry_model=self.name,
                    fvg_id=fvg.fvg_id,
                    fvg_lower=fvg.lower,
                    fvg_upper=fvg.upper,
                    fvg_direction="bearish",
                    fvg_size_pts=fvg.size_pts
                )
        
        return None

