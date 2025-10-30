#!/usr/bin/env python3
"""Run backtest with detailed debugging output"""

import pandas as pd
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from src.core.data_loader import load_processed_30s_csv
from src.core.fvg_detection import detect_fvgs, FVG, create_fvg_from_row, update_fvg_validity, prune_active_fvgs
from src.core.config import CONFIG
from debug_entry_model import DebugFVGContinuationNoFVGModel


def main():
    print("=" * 100)
    print("DEBUG BACKTEST FOR OCTOBER 23, 2025")
    print("=" * 100)
    
    # Load data
    data_path = os.path.join("data", "processed", CONFIG["data_path"])
    df = load_processed_30s_csv(data_path)
    
    # Filter to Oct 23, 2025
    target_date = pd.Timestamp('2025-10-23').date()
    df = df[df['timestamp'].dt.date == target_date].copy().reset_index(drop=True)
    
    print(f"\nFiltered to Oct 23, 2025: {len(df)} bars")
    print(f"Time range: {df['timestamp'].min()} to {df['timestamp'].max()}")
    
    # Detect FVGs
    df = detect_fvgs(df)
    
    # Initialize model and state
    active_fvgs = []
    entry_model = DebugFVGContinuationNoFVGModel()
    trades = []
    bars_in_session = 0
    prev_session_date = None
    
    print("\n" + "=" * 100)
    print("RUNNING BACKTEST WITH DEBUG LOGGING")
    print("=" * 100)
    
    for i, row in df.iterrows():
        ts = row["timestamp"]
        local_date = ts.tz_convert(CONFIG["session_tz"]).date()
        
        # Track session changes
        if prev_session_date != local_date:
            bars_in_session = 0
            prev_session_date = local_date
        bars_in_session += 1
        
        # Update validity of existing active FVGs
        update_fvg_validity(active_fvgs, row, i)
        
        # Create new FVGs at this bar
        new_fvg_created = False
        if bool(row.get("bull_fvg", False)):
            fvg = create_fvg_from_row(row, i, "bullish")
            max_fvg_size = CONFIG.get("max_fvg_size_pts", 100.0)
            skip_start_bars = CONFIG.get("bars_to_skip_after_session_start", 3)
            max_start_size = CONFIG.get("max_fvg_size_session_start", 50.0)
            
            if fvg.size_pts and fvg.size_pts <= max_fvg_size:
                is_session_start = bars_in_session <= skip_start_bars
                if not is_session_start or fvg.size_pts <= max_start_size:
                    active_fvgs.append(fvg)
                    print(f"\n📍 Bar #{i} @ {ts.strftime('%H:%M:%S')} - BULLISH FVG #{fvg.fvg_id} created")
                    print(f"    Range: {fvg.lower:.2f} - {fvg.upper:.2f}, Size: {fvg.size_pts:.2f} pts")
                    new_fvg_created = True
        
        if bool(row.get("bear_fvg", False)):
            fvg = create_fvg_from_row(row, i, "bearish")
            max_fvg_size = CONFIG.get("max_fvg_size_pts", 100.0)
            skip_start_bars = CONFIG.get("bars_to_skip_after_session_start", 3)
            max_start_size = CONFIG.get("max_fvg_size_session_start", 50.0)
            
            if fvg.size_pts and fvg.size_pts <= max_fvg_size:
                is_session_start = bars_in_session <= skip_start_bars
                if not is_session_start or fvg.size_pts <= max_start_size:
                    active_fvgs.append(fvg)
                    print(f"\n📍 Bar #{i} @ {ts.strftime('%H:%M:%S')} - BEARISH FVG #{fvg.fvg_id} created")
                    print(f"    Range: {fvg.lower:.2f} - {fvg.upper:.2f}, Size: {fvg.size_pts:.2f} pts")
                    new_fvg_created = True
        
        # Prune active FVGs
        active_fvgs = prune_active_fvgs(active_fvgs)
        
        # Evaluate entry model for each active FVG
        valid_fvgs = [f for f in active_fvgs if f.valid and not f.expired]
        
        if len(valid_fvgs) > 0:
            if not new_fvg_created:  # Don't print if we just created a new FVG
                print(f"\n🔍 Bar #{i} @ {ts.strftime('%H:%M:%S')} - Checking {len(valid_fvgs)} active FVG(s)")
            
            for fvg in valid_fvgs:
                # Evaluate entry model
                signal = entry_model.evaluate(fvg, active_fvgs, row, i, df)
                
                if signal:
                    print(f"\n🎯 TRADE SIGNAL GENERATED!")
                    trades.append(signal)
                    
                    # Mark this FVG as used
                    fvg.trade_taken = True
                    fvg.valid = False
                    fvg.expired = True
                    fvg.deactivated_reason = "trade_taken"
                    
                    # Only allow one trade per bar
                    break
    
    print("\n" + "=" * 100)
    print(f"FINAL RESULTS: {len(trades)} trade(s) found")
    print("=" * 100)
    
    if trades:
        for idx, trade in enumerate(trades):
            print(f"\nTrade #{idx+1}:")
            print(f"  Time: {trade.entry_time.strftime('%H:%M:%S')}")
            print(f"  Direction: {trade.direction}")
            print(f"  Entry Price: {trade.entry_price:.2f}")
            print(f"  FVG ID: {trade.fvg_id}")
            print(f"  FVG Size: {trade.fvg_size_pts:.2f} pts")


if __name__ == "__main__":
    main()

