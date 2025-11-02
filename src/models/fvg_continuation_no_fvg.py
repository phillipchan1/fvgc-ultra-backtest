from typing import Optional, List
import pandas as pd
import numpy as np
from .base import EntryModel, TradeSignal
from ..core.fvg_detection import FVG

class FVGContinuationNoFVGModel(EntryModel):
    """
    Implementation of the "FVG + noFVG" continuation setup.
    """

    def __init__(self, pivot_strength=3, max_close_dist=7.5, equal_hl_tolerance=0.5, max_touches=5):
        self._pivot_strength = pivot_strength
        self._max_close_dist = max_close_dist
        self._equal_hl_tolerance = equal_hl_tolerance
        self._max_touches = max_touches

    @property
    def name(self) -> str:
        return "fvg_continuation_no_fvg"

    def evaluate(
        self,
        fvg: FVG,
        active_fvgs: list,
        current_bar: pd.Series,
        bar_index: int,
        dataframe: pd.DataFrame
    ) -> Optional[TradeSignal]:
        """Evaluate the FVG continuation with no conflicting FVG setup."""

        if fvg.trade_taken or not fvg.valid:
            return None

        # FVG must have been created at least one bar BEFORE the previous bar.
        # This ensures there's a bar for price to move away before the entry candle.
        if bar_index - 1 <= fvg.created_idx:
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
            if i < self._pivot_strength: continue
            
            # Check if high[i] is a basic pivot
            is_basic_pivot = highs.iloc[i] > highs.iloc[i-1] and highs.iloc[i] > highs.iloc[i+1]
            if not is_basic_pivot:
                continue

            # Check if it's the max in the wider window
            window = highs.iloc[i - self._pivot_strength : i + self._pivot_strength + 1]
            if highs.iloc[i] >= window.max():
                return i
        return None

    def _find_swing_low(self, start_index: int, end_index: int, dataframe: pd.DataFrame) -> Optional[int]:
        """Finds the nearest swing low between start_index and end_index (exclusive)."""
        lows = dataframe['low']
        # Search only up to (but not including) end_index to avoid looking into the future
        for i in range(start_index, min(end_index, len(dataframe) - self._pivot_strength)):
            if i < self._pivot_strength: continue

            # Check if low[i] is a basic pivot
            is_basic_pivot = lows.iloc[i] < lows.iloc[i-1] and lows.iloc[i] < lows.iloc[i+1]
            if not is_basic_pivot:
                continue
            
            # Check if it's the min in the wider window
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
        
        # Check for retracement into FVG before entry candle criteria
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
        
        # Check if swing high PRICE has been swept (not just if the bar is in the past)
        # This allows entries after the swing bar forms, as long as price hasn't swept it
        max_high_so_far = dataframe['high'].iloc[swing_high_index:bar_index+1].max()
        if max_high_so_far > swing_high_price:
            return None  # Swing was swept

        # 2. Define Leg Zone
        leg_low_price = dataframe['low'].iloc[fvg.created_idx + 1 : swing_high_index + 1].min()
        leg_high_price = swing_high_price
        
        # 3. Scan for conflicting FVGs (strict - no FVGs allowed, even if inverted)
        conflicting_fvg_exists = self._scan_for_conflicting_fvgs(
            'bearish', fvg.created_idx + 1, swing_high_index,
            leg_low_price, leg_high_price, dataframe
        )
        if conflicting_fvg_exists:
            return None

        # Check if swing point was already broken by ANY prior candle (BOS scenario)
        # Check all candles from swing point up to (but not including) current bar
        # If any candle closed through swing, this is BOS territory, not noFVG
        for check_idx in range(swing_high_index, bar_index):
            if dataframe['close'].iloc[check_idx] > swing_high_price:
                return None  # Swing was already broken - this is a BOS scenario, not noFVG
        
        # Also check if PREVIOUS candle closed through swing (even if current hasn't)
        # This catches the case where prev candle was BOS but failed distance check
        if bar_index >= 1:
            if previous_bar['close'] > swing_high_price:
                return None  # Previous candle closed through swing - BOS territory
        
        # Additional check: Did previous candle close through any recent local high?
        # This catches BOS scenarios where the "swing" isn't a confirmed pivot yet
        # Check last 10 bars for local highs
        lookback_start = max(fvg.created_idx + 1, bar_index - 10)
        for check_idx in range(lookback_start, bar_index):
            local_high = dataframe['high'].iloc[check_idx]
            # If previous candle closed above this local high, it's BOS territory
            if previous_bar['close'] > local_high:
                # But only if this local high was significant (not just 1-2 points)
                if local_high > fvg.upper + 5.0:  # At least 5 points above FVG
                    return None  # Previous candle broke through local structure
        
        # 4. Entry Candle Criteria
        # Rule 1: Closure
        if current_bar['close'] <= previous_bar['high']:
            return None
        
        # Rule 2: Distance
        distance = current_bar['close'] - previous_bar['high']
        if distance > self._max_close_dist:
            return None

        # Rule 3: No Equal Highs
        if abs(current_bar['high'] - swing_high_price) < self._equal_hl_tolerance:
            return None
            
        # Rule 4: No Swing Point Sweep
        if current_bar['high'] > swing_high_price:
            return None
            
        # Rule 5: No Body Close Through Swing
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
        
        # Check for retracement into FVG before entry candle criteria
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
        
        # Check if swing low PRICE has been swept (not just if the bar is in the past)
        min_low_so_far = dataframe['low'].iloc[swing_low_index:bar_index+1].min()
        if min_low_so_far < swing_low_price:
            return None  # Swing was swept

        # 2. Define Leg Zone
        leg_high_price = dataframe['high'].iloc[fvg.created_idx + 1 : swing_low_index + 1].max()
        leg_low_price = swing_low_price
        
        # 3. Scan for conflicting FVGs (strict - no FVGs allowed, even if inverted)
        conflicting_fvg_exists = self._scan_for_conflicting_fvgs(
            'bullish', fvg.created_idx + 1, swing_low_index,
            leg_low_price, leg_high_price, dataframe
        )
        if conflicting_fvg_exists:
            return None

        # Check if swing point was already broken by ANY prior candle (BOS scenario)
        # Check all candles from swing point up to (but not including) current bar
        # If any candle closed through swing, this is BOS territory, not noFVG
        for check_idx in range(swing_low_index, bar_index):
            if dataframe['close'].iloc[check_idx] < swing_low_price:
                return None  # Swing was already broken - this is a BOS scenario, not noFVG
        
        # Also check if PREVIOUS candle closed through swing (even if current hasn't)
        # This catches the case where prev candle was BOS but failed distance check
        if bar_index >= 1:
            if previous_bar['close'] < swing_low_price:
                return None  # Previous candle closed through swing - BOS territory
        
        # Additional check: Did previous candle close through any recent local low?
        # This catches BOS scenarios where the "swing" isn't a confirmed pivot yet
        # Check last 10 bars for local lows
        lookback_start = max(fvg.created_idx + 1, bar_index - 10)
        for check_idx in range(lookback_start, bar_index):
            local_low = dataframe['low'].iloc[check_idx]
            # If previous candle closed below this local low, it's BOS territory
            if previous_bar['close'] < local_low:
                # But only if this local low was significant (not just 1-2 points)
                if local_low < fvg.lower - 5.0:  # At least 5 points below FVG
                    return None  # Previous candle broke through local structure
        
        # 4. Entry Candle Criteria
        # Rule 1: Closure
        if current_bar['close'] >= previous_bar['low']:
            return None
        
        # Rule 2: Distance
        distance = previous_bar['low'] - current_bar['close']
        if distance > self._max_close_dist:
            return None

        # Rule 3: No Equal Lows
        if abs(current_bar['low'] - swing_low_price) < self._equal_hl_tolerance:
            return None
            
        # Rule 4: No Swing Point Sweep
        if current_bar['low'] < swing_low_price:
            return None
            
        # Rule 5: No Body Close Through Swing
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
        
    def _scan_for_conflicting_fvgs(self, fvg_direction: str, start_idx: int, end_idx: int, leg_low: float, leg_high: float, dataframe: pd.DataFrame) -> bool:
        """Scans for conflicting FVGs within a given range."""
        for i in range(start_idx, end_idx - 1):
            if fvg_direction == 'bearish':
                # Looking for bearish FVGs
                if 'bear_fvg' in dataframe.columns and dataframe['bear_fvg'].iloc[i+1]:
                    fvg_top = dataframe['bear_upper'].iloc[i+1]
                    fvg_bottom = dataframe['bear_lower'].iloc[i+1]
                    if (fvg_top >= leg_low) and (fvg_bottom <= leg_high):
                        return True
            elif fvg_direction == 'bullish':
                # Looking for bullish FVGs
                if 'bull_fvg' in dataframe.columns and dataframe['bull_fvg'].iloc[i+1]:
                    fvg_top = dataframe['bull_upper'].iloc[i+1]
                    fvg_bottom = dataframe['bull_lower'].iloc[i+1]
                    if (fvg_bottom <= leg_high) and (fvg_top >= leg_low):
                        return True
        return False
    
    def _scan_for_conflicting_fvgs_with_inversion(self, fvg_direction: str, start_idx: int, end_idx: int, 
                                                   current_bar_idx: int, leg_low: float, leg_high: float, 
                                                   dataframe: pd.DataFrame) -> bool:
        """
        Scans for conflicting FVGs, but excludes inverted ones.
        If a bearish FVG is completely inverted (price closed through it on bullish move), it's no longer a conflict.
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
                        # Check if this bearish FVG was inverted by a bullish close
                        # Inversion = price closed above the FVG top after it formed
                        inverted = False
                        for j in range(fvg_idx + 1, current_bar_idx + 1):
                            if dataframe['close'].iloc[j] > fvg_top:
                                inverted = True
                                break
                        
                        # If not inverted, it's still a conflict
                        if not inverted:
                            return True
                            
            elif fvg_direction == 'bullish':
                # Looking for bullish FVGs in a bearish setup
                if 'bull_fvg' in dataframe.columns and dataframe['bull_fvg'].iloc[i+1]:
                    fvg_idx = i + 1
                    fvg_top = dataframe['bull_upper'].iloc[fvg_idx]
                    fvg_bottom = dataframe['bull_lower'].iloc[fvg_idx]
                    
                    # Check if FVG overlaps with leg zone
                    if (fvg_bottom <= leg_high) and (fvg_top >= leg_low):
                        # Check if this bullish FVG was inverted by a bearish close
                        # Inversion = price closed below the FVG bottom after it formed
                        inverted = False
                        for j in range(fvg_idx + 1, current_bar_idx + 1):
                            if dataframe['close'].iloc[j] < fvg_bottom:
                                inverted = True
                                break
                        
                        # If not inverted, it's still a conflict
                        if not inverted:
                            return True
        
        return False
