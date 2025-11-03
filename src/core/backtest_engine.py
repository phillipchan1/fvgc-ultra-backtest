# backtest_engine.py
# ---------------------------------------------------------------------------
# Main backtest engine for FVG strategies
# ---------------------------------------------------------------------------

import pandas as pd
from typing import List, Dict, Optional
from .config import CONFIG
from .fvg_detection import (
    detect_fvgs, update_fvg_validity, prune_active_fvgs,
    create_fvg_from_row, FVG
)
from .trade_management import get_trade_management_strategy, TradeManagementResult
from ..models.basic_pullback import BasicPullbackEntry
from ..models.fvg_continuation_no_fvg import FVGContinuationNoFVGModel
from ..models.fvg_continuation_ifvg import FVGContinuationIFVGModel
from ..models.fvg_continuation_bos import FVGContinuationBOSModel


def calculate_time_metrics(timestamp: pd.Timestamp, session_start_idx: int, entry_idx: int) -> Dict:
    """Calculate time-based metrics for a trade."""
    local_time = timestamp.tz_convert(CONFIG['session_tz'])
    session_start_time = local_time.replace(hour=9, minute=30, second=0, microsecond=0)
    
    # Minutes into session
    minutes_into_session = (local_time - session_start_time).total_seconds() / 60.0
    
    # Time window
    if minutes_into_session < 5:
        time_window = "9:30-9:35"
    elif minutes_into_session < 10:
        time_window = "9:35-9:40"
    elif minutes_into_session < 15:
        time_window = "9:40-9:45"
    elif minutes_into_session < 30:
        time_window = "9:45-10:00"
    else:
        time_window = "10:00-10:15"
    
    return {
        'time_window': time_window,
        'minutes_into_session': minutes_into_session,
        'is_first_5_mins': minutes_into_session < 5,
        'day_of_week': local_time.weekday(),  # Monday=0, Friday=4
        'entry_time_decimal': local_time.hour + local_time.minute / 60.0,
    }


def calculate_bar_metrics(current_bar: pd.Series, previous_bar: pd.Series) -> Dict:
    """Calculate bar body, range, and wick metrics."""
    # Entry bar metrics
    entry_body = abs(current_bar['close'] - current_bar['open'])
    entry_range = current_bar['high'] - current_bar['low']
    
    # Wick ratio: (total wicks) / range
    # Total wicks = range - body
    if entry_range > 0:
        entry_wick_ratio = (entry_range - entry_body) / entry_range
    else:
        entry_wick_ratio = 0.0
    
    # Previous bar metrics
    prev_body = abs(previous_bar['close'] - previous_bar['open'])
    prev_range = previous_bar['high'] - previous_bar['low']
    
    return {
        'entry_bar_body_pts': entry_body,
        'entry_bar_range_pts': entry_range,
        'entry_bar_wick_ratio': entry_wick_ratio,
        'previous_bar_body_pts': prev_body,
        'previous_bar_range_pts': prev_range,
    }


def calculate_volatility_metrics(df: pd.DataFrame, bar_index: int, current_bar: pd.Series) -> Dict:
    """Calculate ATR and volatility-related metrics."""
    if bar_index < 5:
        return {
            'recent_atr_5bars': None,
            'entry_bar_vs_atr': None,
        }
    
    # Calculate ATR over last 5 bars
    tr_values = []
    for i in range(bar_index - 5, bar_index):
        bar = df.iloc[i]
        prev_bar = df.iloc[i - 1] if i > 0 else bar
        
        h = bar['high']
        l = bar['low']
        prev_c = prev_bar['close']
        
        tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
        tr_values.append(tr)
    
    atr = sum(tr_values) / len(tr_values) if tr_values else None
    
    # Entry bar size vs ATR
    entry_range = current_bar['high'] - current_bar['low']
    entry_vs_atr = entry_range / atr if atr and atr > 0 else None
    
    return {
        'recent_atr_5bars': atr,
        'entry_bar_vs_atr': entry_vs_atr,
    }


def find_last_swing_point(df: pd.DataFrame, current_idx: int, direction: str, pivot_strength: int = 3) -> Optional[int]:
    """Find the most recent swing high or low before current bar."""
    if current_idx < pivot_strength * 2:
        return None
    
    # Search backwards from current bar
    if direction == 'high':
        highs = df['high']
        for i in range(current_idx - pivot_strength - 1, pivot_strength, -1):
            # Check if this is a pivot high
            is_pivot = highs.iloc[i] > highs.iloc[i-1] and highs.iloc[i] > highs.iloc[i+1]
            if is_pivot:
                # Verify it's the max in wider window
                window = highs.iloc[max(0, i - pivot_strength) : min(len(highs), i + pivot_strength + 1)]
                if highs.iloc[i] >= window.max():
                    return i
    else:  # low
        lows = df['low']
        for i in range(current_idx - pivot_strength - 1, pivot_strength, -1):
            is_pivot = lows.iloc[i] < lows.iloc[i-1] and lows.iloc[i] < lows.iloc[i+1]
            if is_pivot:
                window = lows.iloc[max(0, i - pivot_strength) : min(len(lows), i + pivot_strength + 1)]
                if lows.iloc[i] <= window.min():
                    return i
    
    return None


def track_mae_mfe(df: pd.DataFrame, entry_idx: int, exit_idx: int, direction: str, 
                  entry_price: float, tp_price: float, sl_price: float) -> Dict:
    """Track Maximum Adverse Excursion and Maximum Favorable Excursion."""
    mae = 0.0  # Worst drawdown
    mfe = 0.0  # Best profit
    
    for i in range(entry_idx, exit_idx + 1):
        bar = df.iloc[i]
        
        if direction == 'long':
            # For longs: adverse = going down, favorable = going up
            current_loss = entry_price - bar['low']
            current_profit = bar['high'] - entry_price
        else:
            # For shorts: adverse = going up, favorable = going down
            current_loss = bar['high'] - entry_price
            current_profit = entry_price - bar['low']
        
        mae = max(mae, current_loss)
        mfe = max(mfe, current_profit)
    
    # Calculate as % of risk/target
    risk = abs(entry_price - sl_price)
    target = abs(tp_price - entry_price)
    
    mae_pct_of_risk = (mae / risk) if risk > 0 else None
    mfe_pct_of_target = (mfe / target) if target > 0 else None
    
    return {
        'mae_points': mae,
        'mfe_points': mfe,
        'mae_pct_of_risk': mae_pct_of_risk,
        'mfe_pct_of_target': mfe_pct_of_target,
    }


def calculate_fvg_quality_metrics(fvg: FVG, active_fvgs: List[FVG], df: pd.DataFrame, 
                                  entry_idx: int, entry_price: float) -> Dict:
    """Calculate FVG quality and conflict metrics."""
    # Check for conflicting FVGs
    has_conflict = False
    min_conflict_distance = None
    
    for other_fvg in active_fvgs:
        if other_fvg.fvg_id == fvg.fvg_id or not other_fvg.valid:
            continue
        
        if other_fvg.direction != fvg.direction:
            # Calculate distance between FVGs
            if fvg.direction == 'bullish':
                # Check if bearish FVG is above
                if other_fvg.lower > fvg.upper:
                    distance = other_fvg.lower - fvg.upper
                    if distance < 20:
                        has_conflict = True
                        if min_conflict_distance is None or distance < min_conflict_distance:
                            min_conflict_distance = distance
            else:
                # Check if bullish FVG is below
                if other_fvg.upper < fvg.lower:
                    distance = fvg.lower - other_fvg.upper
                    if distance < 20:
                        has_conflict = True
                        if min_conflict_distance is None or distance < min_conflict_distance:
                            min_conflict_distance = distance
    
    # Check if FVG was filled before entry
    fvg_filled = False
    if fvg.direction == 'bullish':
        # Filled if price went below lower bound
        for i in range(fvg.created_idx + 1, entry_idx):
            if df.iloc[i]['low'] < fvg.lower:
                fvg_filled = True
                break
    else:
        # Filled if price went above upper bound
        for i in range(fvg.created_idx + 1, entry_idx):
            if df.iloc[i]['high'] > fvg.upper:
                fvg_filled = True
                break
    
    # Calculate remaining FVG size
    if fvg.direction == 'bullish':
        # How much of FVG is still unfilled
        if entry_price < fvg.lower:
            remaining = fvg.size_pts  # All of it
        elif entry_price > fvg.upper:
            remaining = 0.0  # Filled
        else:
            remaining = entry_price - fvg.lower
    else:
        if entry_price > fvg.upper:
            remaining = fvg.size_pts
        elif entry_price < fvg.lower:
            remaining = 0.0
        else:
            remaining = fvg.upper - entry_price
    
    # Count stacked FVGs in same direction
    stacked_count = 0
    for other_fvg in active_fvgs:
        if other_fvg.direction == fvg.direction and other_fvg.valid and other_fvg.fvg_id != fvg.fvg_id:
            stacked_count += 1
    
    # Check if entered exactly at FVG boundary
    tolerance = 0.5  # Within 0.5 pts
    if fvg.direction == 'bullish':
        at_boundary = abs(entry_price - fvg.upper) < tolerance or abs(entry_price - fvg.lower) < tolerance
    else:
        at_boundary = abs(entry_price - fvg.upper) < tolerance or abs(entry_price - fvg.lower) < tolerance
    
    return {
        'has_conflicting_fvg': has_conflict,
        'conflicting_fvg_distance': min_conflict_distance,
        'fvg_middle_candle_body_pts': fvg.middle_body_pts,
        'fvg_filled_before_entry': fvg_filled,
        'fvg_remaining_size': remaining,
        'multiple_fvgs_same_direction': stacked_count,
        'entered_at_fvg_boundary': at_boundary,
    }


def run_backtest(df: pd.DataFrame, override_config: Optional[Dict] = None) -> pd.DataFrame:
    """
    Run the main backtest loop.
    
    Detects FVGs, tracks active FVGs, evaluates entry models, and generates trades.
    
    Args:
        df: DataFrame with OHLCV data
        override_config: Optional config dict to override global CONFIG
    
    Returns:
        DataFrame of trades
    """
    trades = []
    active_fvgs: List[FVG] = []
    
    # Use override config if provided, otherwise use global CONFIG
    config = override_config if override_config is not None else CONFIG
    
    # Initialize entry models (run multiple models)
    entry_models = [
        FVGContinuationBOSModel(),    # BOS (closes through swing point) - most specific, check first
        FVGContinuationIFVGModel(),   # iFVG (requires inverted conflicting FVG) - specific
        FVGContinuationNoFVGModel(),  # Bread and butter (no conflicting FVGs) - general, check last
    ]
    
    # Initialize trade management strategy
    strategy_type = config.get("trade_management_strategy", "fixed")
    if strategy_type == "fixed":
        tm_strategy = get_trade_management_strategy(
            "fixed",
            points_tp=config["points_tp"],
            points_sl=config["points_sl"]
        )
    elif strategy_type == "dynamic_fvg":
        tm_strategy = get_trade_management_strategy(
            "dynamic_fvg",
            buffer_pts=config.get("dynamic_fvg_buffer_pts", 5.0),
            min_pts=config.get("dynamic_fvg_min_pts", 15.0),
            max_pts=config.get("dynamic_fvg_max_pts", 40.0)
        )
    elif strategy_type == "partial_close":
        tm_strategy = get_trade_management_strategy(
            "partial_close",
            base_points_tp=config["points_tp"],
            base_points_sl=config["points_sl"]
        )
    elif strategy_type == "trailing_sl":
        tm_strategy = get_trade_management_strategy(
            "trailing_sl",
            base_points_tp=config["points_tp"],
            base_points_sl=config["points_sl"]
        )
    elif strategy_type == "dynamic_trailing_sl":
        tm_strategy = get_trade_management_strategy(
            "dynamic_trailing_sl",
            buffer_pts=config.get("dynamic_fvg_buffer_pts", 5.0),
            min_pts=config.get("dynamic_fvg_min_pts", 15.0),
            max_pts=config.get("dynamic_fvg_max_pts", 40.0)
        )
    elif strategy_type == "dynamic_partial_close":
        tm_strategy = get_trade_management_strategy(
            "dynamic_partial_close",
            buffer_pts=config.get("dynamic_fvg_buffer_pts", 5.0),
            min_pts=config.get("dynamic_fvg_min_pts", 15.0),
            max_pts=config.get("dynamic_fvg_max_pts", 40.0)
        )
    else:
        raise ValueError(f"Unknown trade_management_strategy: {strategy_type}")
    
    # Detect FVGs in the dataframe
    df = detect_fvgs(df)
    
    # Reset index to ensure integer-based indexing for the loop
    df = df.reset_index(drop=True)
    
    prev_session_date = None
    bars_in_session = 0
    session_start_idx = 0
    
    # Session-level tracking for trade sequence metrics
    consecutive_wins = 0
    consecutive_losses = 0
    last_trade_result = None  # 'win' or 'loss'
    trades_today = 0
    same_direction_streak = 0
    last_direction = None
    
    # Session high/low tracking
    session_high = None
    session_low = None
    session_open = None
    
    for i, row in df.iterrows():
        ts = row["timestamp"]
        local_date = ts.tz_convert(CONFIG["session_tz"]).date()
        
        # Track session changes
        if prev_session_date != local_date:
            bars_in_session = 0
            prev_session_date = local_date
            session_start_idx = i
            trades_today = 0
            # Reset session high/low
            session_high = row['high']
            session_low = row['low']
            session_open = row['open']
            # Clear active FVGs at session start (optional - can keep if cross-session)
            # active_fvgs = []
        bars_in_session += 1
        
        # Update session high/low
        if session_high is None or row['high'] > session_high:
            session_high = row['high']
        if session_low is None or row['low'] < session_low:
            session_low = row['low']
        
        # Update validity of existing active FVGs
        update_fvg_validity(active_fvgs, row, i)
        
        # Create new FVGs at this bar (filter out session gaps and tiny gaps)
        if bool(row.get("bull_fvg", False)):
            fvg = create_fvg_from_row(row, i, "bullish")
            # Filter out large session gaps and too-small gaps
            min_fvg_size = config.get("fvg_min_size_pts", 1.5)
            max_fvg_size = config.get("max_fvg_size_pts", 100.0)
            skip_start_bars = config.get("bars_to_skip_after_session_start", 3)
            max_start_size = config.get("max_fvg_size_session_start", 50.0)
            
            if fvg.size_pts and min_fvg_size <= fvg.size_pts <= max_fvg_size:
                is_session_start = bars_in_session <= skip_start_bars
                if not is_session_start or fvg.size_pts <= max_start_size:
                    active_fvgs.append(fvg)
        
        if bool(row.get("bear_fvg", False)):
            fvg = create_fvg_from_row(row, i, "bearish")
            min_fvg_size = config.get("fvg_min_size_pts", 1.5)
            max_fvg_size = config.get("max_fvg_size_pts", 100.0)
            skip_start_bars = config.get("bars_to_skip_after_session_start", 3)
            max_start_size = config.get("max_fvg_size_session_start", 50.0)
            
            if fvg.size_pts and min_fvg_size <= fvg.size_pts <= max_fvg_size:
                is_session_start = bars_in_session <= skip_start_bars
                if not is_session_start or fvg.size_pts <= max_start_size:
                    active_fvgs.append(fvg)
        
        # Prune active FVGs (keep only most recent per side)
        active_fvgs = prune_active_fvgs(active_fvgs)
        
        # Update touch counts for active FVGs (do this ONCE per bar, before model evaluation)
        for fvg in active_fvgs:
            if fvg.direction == 'bullish':
                if row['low'] <= fvg.upper:
                    fvg.touch_count += 1
            elif fvg.direction == 'bearish':
                if row['high'] >= fvg.lower:
                    fvg.touch_count += 1
        
        # Evaluate entry models for each active FVG
        signal_generated = False
        for fvg in active_fvgs:
            # CRITICAL: Skip FVGs that have already been traded
            # This ensures ONE TRADE PER FVG maximum
            if fvg.trade_taken:
                continue
            
            if not fvg.valid or fvg.expired:
                continue
            
            # Try each entry model until one generates a signal
            signal = None
            for entry_model in entry_models:
                signal = entry_model.evaluate(fvg, active_fvgs, row, i, df)
                if signal:
                    break  # Use first model that generates signal
            
            if signal:
                # IMMEDIATELY mark FVG as traded before doing anything else
                # This prevents any possibility of the same FVG being traded again
                fvg.trade_taken = True
                fvg.valid = False
                fvg.expired = True
                fvg.deactivated_reason = "trade_taken"
                
                signal_generated = True
                entry_price = signal.entry_price
                
                # Calculate exit prices using trade management strategy
                tm_result = tm_strategy.calculate_exits(
                    entry_price=entry_price,
                    direction=signal.direction,
                    fvg_lower=signal.fvg_lower,
                    fvg_upper=signal.fvg_upper,
                    fvg_size_pts=signal.fvg_size_pts
                )
                
                # Find exit using trade management result
                exit_time, exit_price, exit_reason, partial_info, exit_idx = find_exit(
                    df, i, entry_price, tm_result, signal.direction
                )
                
                # Calculate PnL (accounting for partial closes)
                if partial_info is not None and partial_info.get('partial_pct', 0) > 0:
                    # Partial close strategy: calculate weighted PnL
                    partial_pct = partial_info['partial_pct']
                    partial_price = partial_info['partial_exit_price']
                    
                    if signal.direction == "long":
                        partial_pnl = (partial_price - entry_price) * partial_pct
                        remaining_pnl = (exit_price - entry_price) * (1 - partial_pct)
                    else:  # short
                        partial_pnl = (entry_price - partial_price) * partial_pct
                        remaining_pnl = (entry_price - exit_price) * (1 - partial_pct)
                    
                    total_pnl = partial_pnl + remaining_pnl
                else:
                    # Simple full position exit
                    if signal.direction == "long":
                        total_pnl = exit_price - entry_price
                    else:
                        total_pnl = entry_price - exit_price
                
                # Calculate FVG tracking variables for optimization
                fvg_midpoint = (signal.fvg_lower + signal.fvg_upper) / 2
                retraced_in_gap = False
                retraced_beyond_50 = False
                
                # Scan bars from FVG creation to current entry bar
                for scan_idx in range(fvg.created_idx + 1, i + 1):
                    scan_close = df.iloc[scan_idx]['close']
                    
                    # Check if closed in gap
                    if signal.fvg_lower <= scan_close <= signal.fvg_upper:
                        retraced_in_gap = True
                        
                        # Check if beyond 50% mark
                        if signal.direction == "long":
                            # For bullish FVG, closing below midpoint = approaching invalidation
                            if scan_close < fvg_midpoint:
                                retraced_beyond_50 = True
                        else:  # short/bearish
                            # For bearish FVG, closing above midpoint = approaching invalidation
                            if scan_close > fvg_midpoint:
                                retraced_beyond_50 = True
                
                # Calculate engulfing closure distance (how far current close is from previous level)
                if i > 0:
                    prev_bar = df.iloc[i - 1]
                    if signal.direction == "long":
                        # For longs: distance from previous high
                        engulfing_distance = row['close'] - prev_bar['high']
                    else:
                        # For shorts: distance from previous low
                        engulfing_distance = prev_bar['low'] - row['close']
                else:
                    engulfing_distance = 0.0
                
                # Calculate bars since FVG creation
                bars_since_fvg_creation = i - fvg.created_idx
                
                # Calculate trade duration
                entry_ts = pd.Timestamp(signal.entry_time)
                exit_ts = pd.Timestamp(exit_time)
                trade_duration_minutes = (exit_ts - entry_ts).total_seconds() / 60.0
                
                # Calculate all permutation metrics
                time_metrics = calculate_time_metrics(entry_ts, session_start_idx, i)
                bar_metrics = calculate_bar_metrics(row, df.iloc[i - 1] if i > 0 else row)
                volatility_metrics = calculate_volatility_metrics(df, i, row)
                mae_mfe_metrics = track_mae_mfe(df, i, exit_idx, signal.direction, entry_price, tm_result.tp_price, tm_result.sl_price)
                fvg_quality_metrics = calculate_fvg_quality_metrics(fvg, active_fvgs, df, i, entry_price)
                
                # Calculate price context metrics
                distance_from_session_high = session_high - entry_price if session_high is not None else None
                distance_from_session_low = entry_price - session_low if session_low is not None else None
                
                if session_high is not None and session_low is not None and session_high > session_low:
                    session_range = session_high - session_low
                    session_range_pct_position = (entry_price - session_low) / session_range
                else:
                    session_range_pct_position = None
                
                if session_open is not None and session_open > 0:
                    price_pct_change_from_open = ((entry_price - session_open) / session_open) * 100
                else:
                    price_pct_change_from_open = None
                
                # Calculate bars since last swing
                last_swing_idx = find_last_swing_point(df, i, 'high' if signal.direction == 'long' else 'low')
                bars_since_last_swing = i - last_swing_idx if last_swing_idx is not None else None
                
                # Get swing point info from signal metadata (if BOS model)
                swing_point_price = signal.metadata.get('swing_point_price', None) if hasattr(signal, 'metadata') else None
                distance_from_swing = signal.metadata.get('distance_from_swing', None) if hasattr(signal, 'metadata') else None
                swing_bars_ago = signal.metadata.get('swing_bars_ago', None) if hasattr(signal, 'metadata') else None
                
                # Create trade record
                trade = {
                    # Original fields
                    "entry_time": signal.entry_time,
                    "exit_time": exit_time,
                    "direction": signal.direction,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "tp_price": tm_result.tp_price,
                    "sl_price": tm_result.sl_price,
                    "entry_model": signal.entry_model,
                    "fvg_id": signal.fvg_id,
                    "fvg_size_pts": signal.fvg_size_pts,
                    "fvg_touch_count": fvg.touch_count,
                    "bars_since_fvg_creation": bars_since_fvg_creation,
                    "engulfing_distance_pts": engulfing_distance,
                    "pnl": total_pnl,
                    "pnl_pts": total_pnl,
                    "exit_reason": exit_reason,
                    "retraced_closed_in_gap": retraced_in_gap,
                    "retraced_beyond_50pct": retraced_beyond_50,
                    
                    # Time-based metrics
                    "time_window": time_metrics['time_window'],
                    "minutes_into_session": time_metrics['minutes_into_session'],
                    "is_first_5_mins": time_metrics['is_first_5_mins'],
                    "day_of_week": time_metrics['day_of_week'],
                    "entry_time_decimal": time_metrics['entry_time_decimal'],
                    "trade_duration_minutes": trade_duration_minutes,
                    
                    # Price context metrics
                    "distance_from_session_high": distance_from_session_high,
                    "distance_from_session_low": distance_from_session_low,
                    "session_range_pct_position": session_range_pct_position,
                    "price_pct_change_from_open": price_pct_change_from_open,
                    
                    # Volatility metrics
                    "recent_atr_5bars": volatility_metrics['recent_atr_5bars'],
                    "entry_bar_vs_atr": volatility_metrics['entry_bar_vs_atr'],
                    "bars_since_last_swing": bars_since_last_swing,
                    
                    # Trade sequence metrics
                    "consecutive_losses": consecutive_losses,
                    "consecutive_wins": consecutive_wins,
                    "same_direction_count": same_direction_streak,
                    "trades_today_before_this": trades_today,
                    
                    # Entry quality metrics
                    "mae_points": mae_mfe_metrics['mae_points'],
                    "mfe_points": mae_mfe_metrics['mfe_points'],
                    "mae_pct_of_risk": mae_mfe_metrics['mae_pct_of_risk'],
                    "mfe_pct_of_target": mae_mfe_metrics['mfe_pct_of_target'],
                    "entered_at_fvg_boundary": fvg_quality_metrics['entered_at_fvg_boundary'],
                    
                    # FVG quality metrics
                    "has_conflicting_fvg": fvg_quality_metrics['has_conflicting_fvg'],
                    "conflicting_fvg_distance": fvg_quality_metrics['conflicting_fvg_distance'],
                    "fvg_middle_candle_body_pts": fvg_quality_metrics['fvg_middle_candle_body_pts'],
                    "fvg_filled_before_entry": fvg_quality_metrics['fvg_filled_before_entry'],
                    "fvg_remaining_size": fvg_quality_metrics['fvg_remaining_size'],
                    "multiple_fvgs_same_direction": fvg_quality_metrics['multiple_fvgs_same_direction'],
                    
                    # Swing/structure metrics (BOS only)
                    "swing_point_price": swing_point_price,
                    "distance_from_swing": distance_from_swing,
                    "swing_bars_ago": swing_bars_ago,
                    
                    # Bar characteristics
                    "entry_bar_body_pts": bar_metrics['entry_bar_body_pts'],
                    "entry_bar_range_pts": bar_metrics['entry_bar_range_pts'],
                    "entry_bar_wick_ratio": bar_metrics['entry_bar_wick_ratio'],
                    "previous_bar_body_pts": bar_metrics['previous_bar_body_pts'],
                    "previous_bar_range_pts": bar_metrics['previous_bar_range_pts'],
                }
                
                # Add partial close info if applicable
                if partial_info:
                    trade["partial_exit_time"] = partial_info.get('partial_exit_time')
                    trade["partial_exit_price"] = partial_info.get('partial_exit_price')
                    trade["partial_pct"] = partial_info.get('partial_pct', 0)
                
                trades.append(trade)
                
                # Update trade sequence tracking
                trades_today += 1
                
                if total_pnl > 0:
                    consecutive_wins += 1
                    consecutive_losses = 0
                    last_trade_result = 'win'
                else:
                    consecutive_losses += 1
                    consecutive_wins = 0
                    last_trade_result = 'loss'
                
                if signal.direction == last_direction:
                    same_direction_streak += 1
                else:
                    same_direction_streak = 1
                    last_direction = signal.direction
                
                # FVG already marked as trade_taken at the top when signal was generated
                # No need to mark again here
                
                # Only allow one trade per bar
                break
        
        # If a signal was generated, don't evaluate other FVGs on this bar
        if signal_generated:
            continue
    
    if len(trades) == 0:
        return pd.DataFrame(columns=[
            # Original fields
            'entry_time', 'exit_time', 'direction', 'entry_price', 
            'exit_price', 'tp_price', 'sl_price', 'entry_model', 'fvg_id',
            'fvg_size_pts', 'fvg_touch_count', 'bars_since_fvg_creation',
            'engulfing_distance_pts', 'pnl', 'pnl_pts', 'exit_reason',
            'retraced_closed_in_gap', 'retraced_beyond_50pct',
            # Time-based metrics
            'time_window', 'minutes_into_session', 'is_first_5_mins',
            'day_of_week', 'entry_time_decimal', 'trade_duration_minutes',
            # Price context metrics
            'distance_from_session_high', 'distance_from_session_low',
            'session_range_pct_position', 'price_pct_change_from_open',
            # Volatility metrics
            'recent_atr_5bars', 'entry_bar_vs_atr', 'bars_since_last_swing',
            # Trade sequence metrics
            'consecutive_losses', 'consecutive_wins', 'same_direction_count', 'trades_today_before_this',
            # Entry quality metrics
            'mae_points', 'mfe_points', 'mae_pct_of_risk', 'mfe_pct_of_target', 'entered_at_fvg_boundary',
            # FVG quality metrics
            'has_conflicting_fvg', 'conflicting_fvg_distance', 'fvg_middle_candle_body_pts',
            'fvg_filled_before_entry', 'fvg_remaining_size', 'multiple_fvgs_same_direction',
            # Swing/structure metrics
            'swing_point_price', 'distance_from_swing', 'swing_bars_ago',
            # Bar characteristics
            'entry_bar_body_pts', 'entry_bar_range_pts', 'entry_bar_wick_ratio',
            'previous_bar_body_pts', 'previous_bar_range_pts'
        ])
    
    return pd.DataFrame(trades)


def find_exit(df: pd.DataFrame, entry_idx: int, entry_price: float, 
              tm_result: TradeManagementResult, direction: str):
    """
    Find exit for a trade based on trade management strategy.
    
    Handles:
    - Simple TP/SL
    - Partial closes at specified levels
    - Trailing stop loss after partial close trigger
    
    Args:
        df: DataFrame with price data
        entry_idx: Index of entry bar
        entry_price: Entry price
        tm_result: TradeManagementResult with TP/SL and optional partial close info
        direction: "long" or "short"
    
    Returns:
        Tuple of (exit_time, exit_price, exit_reason, partial_exit_info, exit_idx)
        partial_exit_info is dict with partial close details if applicable
        exit_idx is the index of the exit bar
    """
    tp_price = tm_result.tp_price
    sl_price = tm_result.sl_price
    partial_close_triggered = False
    partial_exit_info = None
    current_sl = sl_price
    
    # Look ahead from entry bar
    for i in range(entry_idx + 1, len(df)):
        bar = df.iloc[i]
        h, l, c = float(bar["high"]), float(bar["low"]), float(bar["close"])
        
        # Check for partial close trigger (if specified)
        if not partial_close_triggered and tm_result.partial_close_price is not None:
            partial_triggered = False
            
            if direction == "long":
                if h >= tm_result.partial_close_price:
                    partial_triggered = True
            else:  # short
                if l <= tm_result.partial_close_price:
                    partial_triggered = True
            
            if partial_triggered:
                partial_close_triggered = True
                
                # Record partial close if applicable (pct > 0)
                if tm_result.partial_close_pct > 0:
                    partial_exit_info = {
                        'partial_exit_time': bar["timestamp"],
                        'partial_exit_price': tm_result.partial_close_price,
                        'partial_pct': tm_result.partial_close_pct
                    }
                
                # Update stop loss if trailing SL is specified
                if tm_result.trailing_sl_price is not None:
                    current_sl = tm_result.trailing_sl_price
        
        # Check for full exit (TP or SL)
        if direction == "long":
            # TP hit (high crosses TP)
            if h >= tp_price:
                return bar["timestamp"], tp_price, "TP", partial_exit_info, i
            # SL hit (low crosses current SL, which may have been adjusted)
            if l <= current_sl:
                return bar["timestamp"], current_sl, "SL", partial_exit_info, i
        else:  # short
            # TP hit (low crosses TP)
            if l <= tp_price:
                return bar["timestamp"], tp_price, "TP", partial_exit_info, i
            # SL hit (high crosses current SL, which may have been adjusted)
            if h >= current_sl:
                return bar["timestamp"], current_sl, "SL", partial_exit_info, i
    
    # No exit found - exit at end of data on close
    last_bar = df.iloc[-1]
    return last_bar["timestamp"], float(last_bar["close"]), "END_OF_DATA", partial_exit_info, len(df) - 1


def calculate_metrics(trades: pd.DataFrame) -> Dict:
    """Calculate backtest metrics."""
    if trades.empty:
        return {
            'trades': 0,
            'win_rate': 0.0,
            'net': 0.0,
            'gross_profit': 0.0,
            'gross_loss': 0.0,
            'profit_factor': 0.0,
            'avg_win': 0.0,
            'avg_loss': 0.0,
        }
    
    total_trades = len(trades)
    winning_trades = len(trades[trades['pnl'] > 0])
    losing_trades = len(trades[trades['pnl'] < 0])
    
    gross_profit = trades[trades['pnl'] > 0]['pnl'].sum() if winning_trades > 0 else 0.0
    gross_loss = abs(trades[trades['pnl'] < 0]['pnl'].sum()) if losing_trades > 0 else 0.0
    
    net = trades['pnl'].sum()
    win_rate = winning_trades / total_trades if total_trades > 0 else 0.0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else (gross_profit if gross_profit > 0 else 0.0)
    
    avg_win = gross_profit / winning_trades if winning_trades > 0 else 0.0
    avg_loss = gross_loss / losing_trades if losing_trades > 0 else 0.0
    
    return {
        'trades': total_trades,
        'winning_trades': winning_trades,
        'losing_trades': losing_trades,
        'win_rate': win_rate,
        'net': net,
        'gross_profit': gross_profit,
        'gross_loss': gross_loss,
        'profit_factor': profit_factor,
        'avg_win': avg_win,
        'avg_loss': avg_loss,
    }
