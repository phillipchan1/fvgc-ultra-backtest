from typing import Optional, List
import pandas as pd
import numpy as np
from .base import EntryModel, TradeSignal
from ..core.fvg_detection import FVG


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

        # FVG must have been created at least one bar BEFORE the previous bar
        if bar_index - 1 <= fvg.created_idx:
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
            return self._evaluate_bullish(fvg, current_bar, previous_bar, bar_index, dataframe)
        elif fvg.direction == 'bearish':
            return self._evaluate_bearish(fvg, current_bar, previous_bar, bar_index, dataframe)

        return None

    def _find_swing_high(self, start_index: int, dataframe: pd.DataFrame) -> Optional[int]:
        """Finds the nearest swing high after the start_index."""
        highs = dataframe['high']
        for i in range(start_index, len(dataframe) - self._pivot_strength):
            if i < self._pivot_strength:
                continue
            
            is_basic_pivot = highs.iloc[i] > highs.iloc[i-1] and highs.iloc[i] > highs.iloc[i+1]
            if not is_basic_pivot:
                continue

            window = highs.iloc[i - self._pivot_strength : i + self._pivot_strength + 1]
            if highs.iloc[i] >= window.max():
                return i
        return None

    def _find_swing_low(self, start_index: int, dataframe: pd.DataFrame) -> Optional[int]:
        """Finds the nearest swing low after the start_index."""
        lows = dataframe['low']
        for i in range(start_index, len(dataframe) - self._pivot_strength):
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
        swing_high_index = self._find_swing_high(fvg.created_idx + 1, dataframe)
        if swing_high_index is None:
            return None
        
        swing_high_price = dataframe['high'].iloc[swing_high_index]
        
        # Check if swing high was swept (wick violation okay, but we track it)
        max_high_so_far = dataframe['high'].iloc[swing_high_index:bar_index+1].max()
        if max_high_so_far > swing_high_price:
            return None  # Already swept

        # BOS Rule: Current candle body must close THROUGH the swing high
        # This is the key difference from noFVG - we REQUIRE closing through swing
        if current_bar['close'] <= swing_high_price:
            return None  # Not a BOS - body didn't close through

        # Distance Rule: Must be within max_close_dist from previous high
        distance = current_bar['close'] - previous_bar['high']
        if distance > self._max_close_dist:
            return None

        # Entry is valid - body closed through swing point with acceptable distance
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
        swing_low_index = self._find_swing_low(fvg.created_idx + 1, dataframe)
        if swing_low_index is None:
            return None
        
        swing_low_price = dataframe['low'].iloc[swing_low_index]
        
        # Check if swing low was swept
        min_low_so_far = dataframe['low'].iloc[swing_low_index:bar_index+1].min()
        if min_low_so_far < swing_low_price:
            return None  # Already swept

        # BOS Rule: Current candle body must close THROUGH the swing low
        # This is the key difference from noFVG - we REQUIRE closing through swing
        if current_bar['close'] >= swing_low_price:
            return None  # Not a BOS - body didn't close through

        # Distance Rule: Must be within max_close_dist from previous low
        distance = previous_bar['low'] - current_bar['close']
        if distance > self._max_close_dist:
            return None

        # Entry is valid - body closed through swing point with acceptable distance
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

