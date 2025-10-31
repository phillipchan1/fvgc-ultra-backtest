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
            buffer_pts=config.get("dynamic_fvg_buffer_pts", 3.0),
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
    else:
        raise ValueError(f"Unknown trade_management_strategy: {strategy_type}")
    
    # Detect FVGs in the dataframe
    df = detect_fvgs(df)
    
    # Reset index to ensure integer-based indexing for the loop
    df = df.reset_index(drop=True)
    
    prev_session_date = None
    bars_in_session = 0
    
    for i, row in df.iterrows():
        ts = row["timestamp"]
        local_date = ts.tz_convert(CONFIG["session_tz"]).date()
        
        # Track session changes
        if prev_session_date != local_date:
            bars_in_session = 0
            prev_session_date = local_date
            # Clear active FVGs at session start (optional - can keep if cross-session)
            # active_fvgs = []
        bars_in_session += 1
        
        # Update validity of existing active FVGs
        update_fvg_validity(active_fvgs, row, i)
        
        # Create new FVGs at this bar (filter out session gaps)
        if bool(row.get("bull_fvg", False)):
            fvg = create_fvg_from_row(row, i, "bullish")
            # Filter out large session gaps
            max_fvg_size = CONFIG.get("max_fvg_size_pts", 100.0)
            skip_start_bars = CONFIG.get("bars_to_skip_after_session_start", 3)
            max_start_size = CONFIG.get("max_fvg_size_session_start", 50.0)
            
            if fvg.size_pts and fvg.size_pts <= max_fvg_size:
                is_session_start = bars_in_session <= skip_start_bars
                if not is_session_start or fvg.size_pts <= max_start_size:
                    active_fvgs.append(fvg)
        
        if bool(row.get("bear_fvg", False)):
            fvg = create_fvg_from_row(row, i, "bearish")
            max_fvg_size = CONFIG.get("max_fvg_size_pts", 100.0)
            skip_start_bars = CONFIG.get("bars_to_skip_after_session_start", 3)
            max_start_size = CONFIG.get("max_fvg_size_session_start", 50.0)
            
            if fvg.size_pts and fvg.size_pts <= max_fvg_size:
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
            if not fvg.valid or fvg.expired:
                continue
            
            # Try each entry model until one generates a signal
            signal = None
            for entry_model in entry_models:
                signal = entry_model.evaluate(fvg, active_fvgs, row, i, df)
                if signal:
                    break  # Use first model that generates signal
            
            if signal:
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
                exit_time, exit_price, exit_reason, partial_info = find_exit(
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
                
                # Create trade record
                trade = {
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
                    "pnl": total_pnl,
                    "pnl_pts": total_pnl,
                    "exit_reason": exit_reason,
                    "retraced_closed_in_gap": retraced_in_gap,
                    "retraced_beyond_50pct": retraced_beyond_50,
                }
                
                # Add partial close info if applicable
                if partial_info:
                    trade["partial_exit_time"] = partial_info.get('partial_exit_time')
                    trade["partial_exit_price"] = partial_info.get('partial_exit_price')
                    trade["partial_pct"] = partial_info.get('partial_pct', 0)
                
                trades.append(trade)
                
                # Mark this FVG as used - only one trade per FVG total
                fvg.trade_taken = True
                fvg.valid = False
                fvg.expired = True
                fvg.deactivated_reason = "trade_taken"
                
                # Only allow one trade per bar
                break
        
        # If a signal was generated, don't evaluate other FVGs on this bar
        if signal_generated:
            continue
    
    if len(trades) == 0:
        return pd.DataFrame(columns=[
            'entry_time', 'exit_time', 'direction', 'entry_price', 
            'exit_price', 'tp_price', 'sl_price', 'entry_model', 'fvg_id',
            'fvg_size_pts', 'fvg_touch_count', 'pnl', 'pnl_pts', 'exit_reason',
            'retraced_closed_in_gap', 'retraced_beyond_50pct'
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
        Tuple of (exit_time, exit_price, exit_reason, partial_exit_info)
        partial_exit_info is dict with partial close details if applicable
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
                return bar["timestamp"], tp_price, "TP", partial_exit_info
            # SL hit (low crosses current SL, which may have been adjusted)
            if l <= current_sl:
                return bar["timestamp"], current_sl, "SL", partial_exit_info
        else:  # short
            # TP hit (low crosses TP)
            if l <= tp_price:
                return bar["timestamp"], tp_price, "TP", partial_exit_info
            # SL hit (high crosses current SL, which may have been adjusted)
            if h >= current_sl:
                return bar["timestamp"], current_sl, "SL", partial_exit_info
    
    # No exit found - exit at end of data on close
    last_bar = df.iloc[-1]
    return last_bar["timestamp"], float(last_bar["close"]), "END_OF_DATA", partial_exit_info


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
