#!/usr/bin/env python3
"""Debug why 9:37 trade exists"""

import pandas as pd
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from src.core.data_loader import load_processed_30s_csv
from src.core.fvg_detection import detect_fvgs, create_fvg_from_row, update_fvg_validity, prune_active_fvgs
from src.core.config import CONFIG
from src.models.basic_pullback import BasicPullbackEntry

df = load_processed_30s_csv('data/raw/' + CONFIG['data_path'])
df = df[df['timestamp'].dt.date == pd.Timestamp('2025-10-23').date()].reset_index(drop=True)
df = detect_fvgs(df)

print("=" * 120)
print("DEBUGGING 9:37 TRADE")
print("=" * 120)

active_fvgs = []
entry_model = BasicPullbackEntry()
prev_session_date = None
bars_in_session = 0

for i, row in df.iterrows():
    ts = row["timestamp"]
    local_date = ts.tz_convert(CONFIG["session_tz"]).date()
    
    if prev_session_date != local_date:
        bars_in_session = 0
        prev_session_date = local_date
    bars_in_session += 1
    
    update_fvg_validity(active_fvgs, row, i)
    
    # Create new FVGs
    if bool(row.get("bull_fvg", False)):
        fvg = create_fvg_from_row(row, i, "bullish")
        max_fvg_size = CONFIG.get("max_fvg_size_pts", 100.0)
        skip_start_bars = CONFIG.get("bars_to_skip_after_session_start", 3)
        max_start_size = CONFIG.get("max_fvg_size_session_start", 50.0)
        
        if fvg.size_pts and fvg.size_pts <= max_fvg_size:
            is_session_start = bars_in_session <= skip_start_bars
            if not is_session_start or fvg.size_pts <= max_start_size:
                active_fvgs.append(fvg)
                if i <= 15:
                    print(f"\n{i}: {ts.strftime('%H:%M:%S')} - FVG #{fvg.fvg_id} CREATED ({fvg.lower:.2f}-{fvg.upper:.2f})")
    
    active_fvgs = prune_active_fvgs(active_fvgs)
    
    # Check 9:37 and 9:39 specifically
    if ts.strftime('%H:%M:%S') in ['09:37:00', '09:39:00']:
        print(f"\n{'='*120}")
        print(f"{i}: {ts.strftime('%H:%M:%S')}")
        print(f"{'='*120}")
        print(f"Bar: O={row['open']:.2f} H={row['high']:.2f} L={row['low']:.2f} C={row['close']:.2f}")
        
        if i > 0:
            prev = df.iloc[i-1]
            print(f"Prev: H={prev['high']:.2f} L={prev['low']:.2f} C={prev['close']:.2f}")
            print(f"Close > Prev High: {row['close'] > prev['high']}")
        
        print(f"\nActive FVGs at this bar ({len(active_fvgs)}):")
        for fvg in active_fvgs:
            if not fvg.valid or fvg.expired:
                print(f"  FVG #{fvg.fvg_id}: INVALID ({fvg.deactivated_reason})")
                continue
            
            print(f"  FVG #{fvg.fvg_id}: {fvg.direction} {fvg.lower:.2f}-{fvg.upper:.2f} (created at {fvg.created_idx})")
            
            signal = entry_model.evaluate(fvg, active_fvgs, row, i, df)
            
            if signal:
                print(f"    ✅✅✅ SIGNAL GENERATED! Entry @ {signal.entry_price:.2f} ✅✅✅")
            else:
                # Manual check
                o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
                prev_bar = df.iloc[i-1]
                prev_high = float(prev_bar["high"])
                
                wick_touches = (l <= fvg.upper) or (h >= fvg.lower)
                close_inside = fvg.lower <= c <= fvg.upper
                price_enters = wick_touches or close_inside
                
                # Check if entered on prev bar
                price_entered_prev = False
                if i > 0:
                    prev_check = df.iloc[i-1]
                    if prev_check.name > fvg.created_idx:
                        prev_l = float(prev_check["low"])
                        prev_h = float(prev_check["high"])
                        prev_c = float(prev_check["close"])
                        prev_wick_touches = (prev_l <= fvg.upper) or (prev_h >= fvg.lower)
                        prev_close_inside = fvg.lower <= prev_c <= fvg.upper
                        price_entered_prev = prev_wick_touches or prev_close_inside
                
                # Check if price moved away first
                price_moved_away = False
                if i > fvg.created_idx:
                    for check_idx in range(fvg.created_idx + 1, i):
                        check_bar = df.iloc[check_idx]
                        if float(check_bar["low"]) > fvg.upper:
                            price_moved_away = True
                            break
                
                closes_above = c > prev_high
                gap_valid = c >= fvg.lower
                created_before = i > fvg.created_idx
                
                print(f"    Conditions:")
                print(f"      Price enters gap (now): {price_enters} (wick: {wick_touches}, close: {close_inside})")
                print(f"      Price entered prev: {price_entered_prev}")
                print(f"      Price moved away first: {price_moved_away}")
                print(f"      Closes above prev high: {closes_above}")
                print(f"      Gap valid: {gap_valid}")
                print(f"      Created before: {created_before}")
                
                if not created_before:
                    print(f"    ❌ FVG created on same bar")
                elif not price_moved_away:
                    print(f"    ❌ Price didn't move away from gap first")
                elif not (price_enters or price_entered_prev):
                    print(f"    ❌ Price doesn't enter gap")
            
            # Mark as used if signal
            if signal:
                fvg.valid = False
                fvg.expired = True
                fvg.deactivated_reason = "trade_taken"
                break

