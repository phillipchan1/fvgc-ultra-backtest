#!/usr/bin/env python3
"""Debug script to analyze FVG detection and entry model evaluation"""

import pandas as pd
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from src.core.data_loader import load_processed_30s_csv
from src.core.fvg_detection import detect_fvgs, FVG, create_fvg_from_row, update_fvg_validity, prune_active_fvgs
from src.core.config import CONFIG
from src.models.fvg_continuation_no_fvg import FVGContinuationNoFVGModel


def main():
    print("=" * 100)
    print("DEBUG: FVG Detection and Entry Model Evaluation for Oct 23, 2025")
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
    
    # Count FVGs
    bull_fvgs = df[df['bull_fvg'] == True]
    bear_fvgs = df[df['bear_fvg'] == True]
    
    print(f"\n📊 Total Bullish FVGs detected: {len(bull_fvgs)}")
    print(f"📊 Total Bearish FVGs detected: {len(bear_fvgs)}")
    
    # List all FVGs with details
    print("\n" + "=" * 100)
    print("BULLISH FVGs:")
    print("=" * 100)
    for idx, row in bull_fvgs.iterrows():
        print(f"\nBar #{idx} @ {row['timestamp'].strftime('%H:%M:%S')}")
        print(f"  Lower: {row['bull_lower']:.2f}, Upper: {row['bull_upper']:.2f}, Size: {row['bull_size']:.2f} pts")
        print(f"  OHLC: O={row['open']:.2f}, H={row['high']:.2f}, L={row['low']:.2f}, C={row['close']:.2f}")
    
    print("\n" + "=" * 100)
    print("BEARISH FVGs:")
    print("=" * 100)
    for idx, row in bear_fvgs.iterrows():
        print(f"\nBar #{idx} @ {row['timestamp'].strftime('%H:%M:%S')}")
        print(f"  Lower: {row['bear_lower']:.2f}, Upper: {row['bear_upper']:.2f}, Size: {row['bear_size']:.2f} pts")
        print(f"  OHLC: O={row['open']:.2f}, H={row['high']:.2f}, L={row['low']:.2f}, C={row['close']:.2f}")
    
    # Now simulate the backtest loop with detailed logging
    print("\n" + "=" * 100)
    print("SIMULATING BACKTEST LOOP:")
    print("=" * 100)
    
    active_fvgs = []
    entry_model = FVGContinuationNoFVGModel()
    trades = []
    bars_in_session = 0
    prev_session_date = None
    
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
        if bool(row.get("bull_fvg", False)):
            fvg = create_fvg_from_row(row, i, "bullish")
            max_fvg_size = CONFIG.get("max_fvg_size_pts", 100.0)
            skip_start_bars = CONFIG.get("bars_to_skip_after_session_start", 3)
            max_start_size = CONFIG.get("max_fvg_size_session_start", 50.0)
            
            if fvg.size_pts and fvg.size_pts <= max_fvg_size:
                is_session_start = bars_in_session <= skip_start_bars
                if not is_session_start or fvg.size_pts <= max_start_size:
                    active_fvgs.append(fvg)
                    print(f"\n✅ Bar #{i} @ {ts.strftime('%H:%M:%S')}: Created BULLISH FVG #{fvg.fvg_id}")
                    print(f"   Range: {fvg.lower:.2f} - {fvg.upper:.2f}, Size: {fvg.size_pts:.2f} pts")
        
        if bool(row.get("bear_fvg", False)):
            fvg = create_fvg_from_row(row, i, "bearish")
            max_fvg_size = CONFIG.get("max_fvg_size_pts", 100.0)
            skip_start_bars = CONFIG.get("bars_to_skip_after_session_start", 3)
            max_start_size = CONFIG.get("max_fvg_size_session_start", 50.0)
            
            if fvg.size_pts and fvg.size_pts <= max_fvg_size:
                is_session_start = bars_in_session <= skip_start_bars
                if not is_session_start or fvg.size_pts <= max_start_size:
                    active_fvgs.append(fvg)
                    print(f"\n✅ Bar #{i} @ {ts.strftime('%H:%M:%S')}: Created BEARISH FVG #{fvg.fvg_id}")
                    print(f"   Range: {fvg.lower:.2f} - {fvg.upper:.2f}, Size: {fvg.size_pts:.2f} pts")
        
        # Prune active FVGs
        active_fvgs = prune_active_fvgs(active_fvgs)
        
        # Show current active FVGs
        valid_fvgs = [f for f in active_fvgs if f.valid and not f.expired]
        if len(valid_fvgs) > 0 and i % 10 == 0:  # Log every 10 bars
            print(f"\n📋 Bar #{i} @ {ts.strftime('%H:%M:%S')}: {len(valid_fvgs)} active valid FVGs")
            for fvg in valid_fvgs:
                print(f"   FVG #{fvg.fvg_id} ({fvg.direction}): {fvg.lower:.2f} - {fvg.upper:.2f}")
        
        # Evaluate entry model for each active FVG
        for fvg in active_fvgs:
            if not fvg.valid or fvg.expired:
                continue
            
            # Log when evaluating
            print(f"\n🔍 Bar #{i} @ {ts.strftime('%H:%M:%S')}: Evaluating FVG #{fvg.fvg_id} ({fvg.direction})")
            print(f"   Current bar: O={row['open']:.2f}, H={row['high']:.2f}, L={row['low']:.2f}, C={row['close']:.2f}")
            
            # Evaluate entry model
            signal = entry_model.evaluate(fvg, active_fvgs, row, i, df)
            
            if signal:
                print(f"   ✅ ENTRY SIGNAL GENERATED!")
                print(f"      Direction: {signal.direction}")
                print(f"      Entry Price: {signal.entry_price:.2f}")
                print(f"      FVG ID: {signal.fvg_id}")
                trades.append(signal)
                
                # Mark this FVG as used
                fvg.trade_taken = True
                fvg.valid = False
                fvg.expired = True
                fvg.deactivated_reason = "trade_taken"
                
                break
            else:
                print(f"   ❌ No entry signal (criteria not met)")
    
    print("\n" + "=" * 100)
    print(f"FINAL RESULTS: {len(trades)} trade(s) found")
    print("=" * 100)


if __name__ == "__main__":
    main()

