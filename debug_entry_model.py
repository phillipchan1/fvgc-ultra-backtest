#!/usr/bin/env python3
"""Debug version of the entry model with detailed logging"""

from typing import Optional
import pandas as pd
from src.models.base import EntryModel, TradeSignal
from src.core.fvg_detection import FVG


class DebugFVGContinuationNoFVGModel(EntryModel):
    """Debug version with detailed logging."""

    def __init__(self, pivot_strength=3, max_close_dist=7.5, equal_hl_tolerance=0.5, max_touches=3):
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
        """Evaluate with detailed logging."""
        
        print(f"\n      >>> EVALUATING FVG #{fvg.fvg_id} at bar #{bar_index}")

        if fvg.trade_taken:
            print(f"          ❌ Trade already taken on this FVG")
            return None
            
        if not fvg.valid:
            print(f"          ❌ FVG not valid")
            return None

        # FVG must have been created at least one bar BEFORE the previous bar
        if bar_index - 1 <= fvg.created_idx:
            print(f"          ❌ FVG too recent (bar_index={bar_index}, fvg.created_idx={fvg.created_idx})")
            return None

        # Touch detection logic
        if fvg.direction == 'bullish':
            if current_bar['low'] <= fvg.upper:
                fvg.touch_count += 1
                print(f"          📍 Touch detected (count now {fvg.touch_count})")
        elif fvg.direction == 'bearish':
            if current_bar['high'] >= fvg.lower:
                fvg.touch_count += 1
                print(f"          📍 Touch detected (count now {fvg.touch_count})")
        
        if fvg.touch_count > self._max_touches:
            fvg.valid = False
            fvg.deactivated_reason = "max_touches_exceeded"
            print(f"          ❌ Max touches exceeded ({fvg.touch_count} > {self._max_touches})")
            return None
        
        if bar_index < 1:
            print(f"          ❌ bar_index < 1")
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
            
            # Check if high[i] is a basic pivot
            is_basic_pivot = highs.iloc[i] > highs.iloc[i-1] and highs.iloc[i] > highs.iloc[i+1]
            if not is_basic_pivot:
                continue

            # Check if it's the max in the wider window
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
        
        print(f"          → Checking BULLISH setup")
        
        # Check for retracement into FVG before entry candle criteria
        retrace_occurred = False
        for idx in range(fvg.created_idx + 1, bar_index + 1):
            if dataframe['low'].iloc[idx] <= fvg.upper:
                retrace_occurred = True
                break
        if not retrace_occurred:
            print(f"          ❌ No retracement into FVG yet")
            return None
        else:
            print(f"          ✓ Retracement into FVG confirmed")

        # 1. Identify Swing High
        swing_high_index = self._find_swing_high(fvg.created_idx + 1, dataframe)
        if swing_high_index is None:
            print(f"          ❌ No swing high found after FVG")
            return None
        if swing_high_index <= bar_index:
            print(f"          ❌ Swing high is not in the future (swing_idx={swing_high_index}, bar_idx={bar_index})")
            return None
        
        swing_high_price = dataframe['high'].iloc[swing_high_index]
        print(f"          ✓ Swing high found at bar #{swing_high_index}, price={swing_high_price:.2f}")

        # 2. Define Leg Zone
        leg_low_price = dataframe['low'].iloc[fvg.created_idx + 1 : swing_high_index + 1].min()
        leg_high_price = swing_high_price
        print(f"          ✓ Leg zone: {leg_low_price:.2f} - {leg_high_price:.2f}")
        
        # 3. Scan for conflicting FVGs
        conflicting_fvg_exists = self._scan_for_conflicting_fvgs('bearish', fvg.created_idx + 1, swing_high_index, leg_low_price, leg_high_price, dataframe)
        if conflicting_fvg_exists:
            print(f"          ❌ Conflicting BEARISH FVG found in leg zone")
            return None
        else:
            print(f"          ✓ No conflicting FVGs in leg zone")

        # 4. Entry Candle Criteria
        print(f"          → Checking entry candle criteria...")
        print(f"             Current: H={current_bar['high']:.2f}, L={current_bar['low']:.2f}, C={current_bar['close']:.2f}")
        print(f"             Previous: H={previous_bar['high']:.2f}, L={previous_bar['low']:.2f}, C={previous_bar['close']:.2f}")
        
        # Rule 1: Closure
        if current_bar['close'] <= previous_bar['high']:
            print(f"          ❌ Current close ({current_bar['close']:.2f}) NOT > previous high ({previous_bar['high']:.2f})")
            return None
        else:
            print(f"          ✓ Rule 1: Current close ({current_bar['close']:.2f}) > previous high ({previous_bar['high']:.2f})")
        
        # Rule 2: Distance
        distance = current_bar['close'] - previous_bar['high']
        if distance > self._max_close_dist:
            print(f"          ❌ Distance too large ({distance:.2f} > {self._max_close_dist})")
            return None
        else:
            print(f"          ✓ Rule 2: Distance OK ({distance:.2f} <= {self._max_close_dist})")

        # Rule 3: No Equal Highs
        if abs(current_bar['high'] - swing_high_price) < self._equal_hl_tolerance:
            print(f"          ❌ Equal highs (current={current_bar['high']:.2f}, swing={swing_high_price:.2f})")
            return None
        else:
            print(f"          ✓ Rule 3: No equal highs")
            
        # Rule 4: No Swing Point Sweep
        if current_bar['high'] > swing_high_price:
            print(f"          ❌ Swing point swept (current high {current_bar['high']:.2f} > swing {swing_high_price:.2f})")
            return None
        else:
            print(f"          ✓ Rule 4: No swing point sweep")
            
        # Rule 5: No Body Close Through Swing
        if current_bar['close'] > swing_high_price:
            print(f"          ❌ Body closes through swing (close {current_bar['close']:.2f} > swing {swing_high_price:.2f})")
            return None
        else:
            print(f"          ✓ Rule 5: Body does not close through swing")
            
        print(f"          ✅ ALL CRITERIA MET - GENERATING ENTRY SIGNAL!")
        
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
        
        print(f"          → Checking BEARISH setup")
        
        # Check for retracement into FVG before entry candle criteria
        retrace_occurred = False
        for idx in range(fvg.created_idx + 1, bar_index + 1):
            if dataframe['high'].iloc[idx] >= fvg.lower:
                retrace_occurred = True
                break
        if not retrace_occurred:
            print(f"          ❌ No retracement into FVG yet")
            return None
        else:
            print(f"          ✓ Retracement into FVG confirmed")

        # 1. Identify Swing Low
        swing_low_index = self._find_swing_low(fvg.created_idx + 1, dataframe)
        if swing_low_index is None:
            print(f"          ❌ No swing low found after FVG")
            return None
        if swing_low_index <= bar_index:
            print(f"          ❌ Swing low is not in the future (swing_idx={swing_low_index}, bar_idx={bar_index})")
            return None
        
        swing_low_price = dataframe['low'].iloc[swing_low_index]
        print(f"          ✓ Swing low found at bar #{swing_low_index}, price={swing_low_price:.2f}")

        # 2. Define Leg Zone
        leg_high_price = dataframe['high'].iloc[fvg.created_idx + 1 : swing_low_index + 1].max()
        leg_low_price = swing_low_price
        print(f"          ✓ Leg zone: {leg_low_price:.2f} - {leg_high_price:.2f}")
        
        # 3. Scan for conflicting FVGs
        conflicting_fvg_exists = self._scan_for_conflicting_fvgs('bullish', fvg.created_idx + 1, swing_low_index, leg_low_price, leg_high_price, dataframe)
        if conflicting_fvg_exists:
            print(f"          ❌ Conflicting BULLISH FVG found in leg zone")
            return None
        else:
            print(f"          ✓ No conflicting FVGs in leg zone")

        # 4. Entry Candle Criteria
        print(f"          → Checking entry candle criteria...")
        print(f"             Current: H={current_bar['high']:.2f}, L={current_bar['low']:.2f}, C={current_bar['close']:.2f}")
        print(f"             Previous: H={previous_bar['high']:.2f}, L={previous_bar['low']:.2f}, C={previous_bar['close']:.2f}")
        
        # Rule 1: Closure
        if current_bar['close'] >= previous_bar['low']:
            print(f"          ❌ Current close ({current_bar['close']:.2f}) NOT < previous low ({previous_bar['low']:.2f})")
            return None
        else:
            print(f"          ✓ Rule 1: Current close ({current_bar['close']:.2f}) < previous low ({previous_bar['low']:.2f})")
        
        # Rule 2: Distance
        distance = previous_bar['low'] - current_bar['close']
        if distance > self._max_close_dist:
            print(f"          ❌ Distance too large ({distance:.2f} > {self._max_close_dist})")
            return None
        else:
            print(f"          ✓ Rule 2: Distance OK ({distance:.2f} <= {self._max_close_dist})")

        # Rule 3: No Equal Lows
        if abs(current_bar['low'] - swing_low_price) < self._equal_hl_tolerance:
            print(f"          ❌ Equal lows (current={current_bar['low']:.2f}, swing={swing_low_price:.2f})")
            return None
        else:
            print(f"          ✓ Rule 3: No equal lows")
            
        # Rule 4: No Swing Point Sweep
        if current_bar['low'] < swing_low_price:
            print(f"          ❌ Swing point swept (current low {current_bar['low']:.2f} < swing {swing_low_price:.2f})")
            return None
        else:
            print(f"          ✓ Rule 4: No swing point sweep")
            
        # Rule 5: No Body Close Through Swing
        if current_bar['close'] < swing_low_price:
            print(f"          ❌ Body closes through swing (close {current_bar['close']:.2f} < swing {swing_low_price:.2f})")
            return None
        else:
            print(f"          ✓ Rule 5: Body does not close through swing")
            
        print(f"          ✅ ALL CRITERIA MET - GENERATING ENTRY SIGNAL!")
        
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

