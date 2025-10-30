# backtest_engine.py
# ---------------------------------------------------------------------------
# Main backtest engine for FVG strategies
# ---------------------------------------------------------------------------

import pandas as pd
from typing import List, Dict
from .config import CONFIG
from .fvg_detection import (
    detect_fvgs, update_fvg_validity, prune_active_fvgs,
    create_fvg_from_row, FVG
)
from ..models.basic_pullback import BasicPullbackEntry
from ..models.fvg_continuation_no_fvg import FVGContinuationNoFVGModel
from ..models.fvg_continuation_ifvg import FVGContinuationIFVGModel
from ..models.fvg_continuation_bos import FVGContinuationBOSModel


def run_backtest(df: pd.DataFrame) -> pd.DataFrame:
    """
    Run the main backtest loop.
    
    Detects FVGs, tracks active FVGs, evaluates entry models, and generates trades.
    """
    trades = []
    active_fvgs: List[FVG] = []
    
    # Initialize entry models (run multiple models)
    entry_models = [
        FVGContinuationNoFVGModel(),  # Bread and butter (no conflicting FVGs)
        FVGContinuationBOSModel(),    # BOS (closes through swing point)
        FVGContinuationIFVGModel(),   # iFVG (requires inverted conflicting FVG)
    ]
    
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
                # Calculate exit prices
                if signal.direction == "long":
                    entry_price = signal.entry_price
                    tp_price = entry_price + CONFIG["points_tp"]
                    sl_price = entry_price - CONFIG["points_sl"]
                    
                    # Find exit
                    exit_time, exit_price, exit_reason = find_exit(
                        df, i, entry_price, tp_price, sl_price, "long"
                    )
                else:  # short
                    entry_price = signal.entry_price
                    tp_price = entry_price - CONFIG["points_tp"]
                    sl_price = entry_price + CONFIG["points_sl"]
                    
                    # Find exit
                    exit_time, exit_price, exit_reason = find_exit(
                        df, i, entry_price, tp_price, sl_price, "short"
                    )
                
                # Calculate PnL
                if signal.direction == "long":
                    pnl = exit_price - entry_price
                else:
                    pnl = entry_price - exit_price
                
                # Create trade record
                trade = {
                    "entry_time": signal.entry_time,
                    "exit_time": exit_time,
                    "direction": signal.direction,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "tp_price": tp_price if signal.direction == "long" else tp_price,
                    "sl_price": sl_price if signal.direction == "long" else sl_price,
                    "entry_model": signal.entry_model,
                    "fvg_id": signal.fvg_id,
                    "fvg_size_pts": signal.fvg_size_pts,
                    "pnl": pnl,
                    "pnl_pts": pnl,
                    "exit_reason": exit_reason,
                }
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
            'fvg_size_pts', 'pnl', 'pnl_pts', 'exit_reason'
        ])
    
    return pd.DataFrame(trades)


def find_exit(df: pd.DataFrame, entry_idx: int, entry_price: float, 
              tp_price: float, sl_price: float, direction: str):
    """
    Find exit for a trade based on TP/SL.
    
    Returns:
        (exit_time, exit_price, exit_reason)
    """
    # Look ahead from entry bar
    for i in range(entry_idx + 1, len(df)):
        bar = df.iloc[i]
        h, l, c = float(bar["high"]), float(bar["low"]), float(bar["close"])
        
        if direction == "long":
            # TP hit (high crosses TP)
            if h >= tp_price:
                return bar["timestamp"], tp_price, "TP"
            # SL hit (low crosses SL)
            if l <= sl_price:
                return bar["timestamp"], sl_price, "SL"
        else:  # short
            # TP hit (low crosses TP)
            if l <= tp_price:
                return bar["timestamp"], tp_price, "TP"
            # SL hit (high crosses SL)
            if h >= sl_price:
                return bar["timestamp"], sl_price, "SL"
    
    # No exit found - exit at end of data on close
    last_bar = df.iloc[-1]
    return last_bar["timestamp"], float(last_bar["close"]), "END_OF_DATA"


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
