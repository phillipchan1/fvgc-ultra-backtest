#!/usr/bin/env python3
"""
Debug why entry models are allowing trades at 9:40, 9:43, 9:44 on Sept 1
"""
import os
import sys
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))

from src.core.data_loader import load_processed_30s_csv
from src.core.config import CONFIG
from src.core.fvg_detection import create_fvg_from_row, update_fvg_validity, FVG
from src.models.fvg_continuation_bos import FVGContinuationBOSModel
from src.models.fvg_continuation_no_fvg import FVGContinuationNoFVGModel
from src.models.fvg_continuation_ifvg import FVGContinuationIFVGModel

# Load data
data_path = os.path.join("data", "processed", CONFIG["data_path"])
df = load_processed_30s_csv(data_path)
df['timestamp'] = pd.to_datetime(df['timestamp'])

sept1 = df[df['timestamp'].dt.date == pd.Timestamp('2025-09-01').date()].copy()
sept1 = sept1.reset_index(drop=True)

print("=" * 100)
print("DEBUGGING SEPT 1 ENTRY MODELS")
print("=" * 100)

# Create the FVG at 9:39:30
# FVG: 23474.0 - 23475.0 (1.0 pts)
fvg = FVG(
    fvg_id=6,
    direction='bullish',
    created_at=pd.Timestamp('2025-09-01 09:39:30-04:00'),
    created_idx=19,  # Will adjust based on actual index
    lower=23474.0,
    upper=23475.0,
    size_pts=1.0,
    middle_body_pts=5.0  # Placeholder
)
fvg.touch_count = 0

# Find actual index of 9:39:30
fvg_creation_time = pd.Timestamp('2025-09-01 09:39:30-04:00')
fvg.created_idx = sept1[sept1['timestamp'] == fvg_creation_time].index[0]

print(f"\nFVG Created at index {fvg.created_idx} (9:39:30)")
print(f"FVG Range: {fvg.lower:.1f} - {fvg.upper:.1f} ({fvg.size_pts:.1f} pts)\n")

# Initialize entry models
bos_model = FVGContinuationBOSModel()
no_fvg_model = FVGContinuationNoFVGModel()
ifvg_model = FVGContinuationIFVGModel()

# Target times to check
target_times = [
    '2025-09-01 09:40:00-04:00',
    '2025-09-01 09:40:30-04:00', 
    '2025-09-01 09:43:00-04:00',
    '2025-09-01 09:43:30-04:00',
    '2025-09-01 09:44:00-04:00',
]

active_fvgs = [fvg]

for target_time_str in target_times:
    target_time = pd.Timestamp(target_time_str)
    bar_row = sept1[sept1['timestamp'] == target_time]
    
    if bar_row.empty:
        continue
        
    bar_idx = bar_row.index[0]
    bar = bar_row.iloc[0]
    
    # Update FVG validity
    update_fvg_validity([fvg], bar, bar_idx)
    
    # Update touch count
    if bar['low'] <= fvg.upper:
        fvg.touch_count += 1
    
    print("=" * 100)
    print(f"\n{target_time.strftime('%H:%M:%S')} (Index {bar_idx})")
    print(f"Bar: O:{bar['open']:.1f} H:{bar['high']:.1f} L:{bar['low']:.1f} C:{bar['close']:.1f}")
    print(f"FVG Status: {'✅ VALID' if fvg.valid else f'❌ INVALID ({fvg.deactivated_reason})'}")
    print(f"Touch Count: {fvg.touch_count}")
    print(f"FVG Traded: {fvg.trade_taken}")
    
    if bar['low'] <= fvg.upper:
        print(f"└─ Low ({bar['low']:.1f}) touches/enters FVG upper ({fvg.upper:.1f})")
    if bar['close'] < fvg.lower:
        print(f"└─ Close ({bar['close']:.1f}) below FVG lower ({fvg.lower:.1f}) - SHOULD INVALIDATE!")
    
    # Try each model
    print(f"\nEntry Model Checks:")
    
    # BOS Model
    bos_signal = bos_model.evaluate(fvg, active_fvgs, bar, bar_idx, sept1)
    if bos_signal:
        print(f"  ✅ BOS Model: TRADE SIGNAL")
        print(f"     Entry: {bos_signal.entry_price:.1f}, Direction: {bos_signal.direction}")
    else:
        print(f"  ❌ BOS Model: No signal")
    
    # No FVG Model
    no_fvg_signal = no_fvg_model.evaluate(fvg, active_fvgs, bar, bar_idx, sept1)
    if no_fvg_signal:
        print(f"  ✅ NO_FVG Model: TRADE SIGNAL")
        print(f"     Entry: {no_fvg_signal.entry_price:.1f}, Direction: {no_fvg_signal.direction}")
    else:
        print(f"  ❌ NO_FVG Model: No signal")
    
    # iFVG Model
    ifvg_signal = ifvg_model.evaluate(fvg, active_fvgs, bar, bar_idx, sept1)
    if ifvg_signal:
        print(f"  ✅ iFVG Model: TRADE SIGNAL")
        print(f"     Entry: {ifvg_signal.entry_price:.1f}, Direction: {ifvg_signal.direction}")
    else:
        print(f"  ❌ iFVG Model: No signal")

print("\n" + "=" * 100)
print("USER SAYS:")
print("  ✅ 9:40:00 should be VALID")
print("  ❌ 9:43:00 and 9:44:00 should be INVALID")
print("\nWe need to identify WHY 9:43 and 9:44 are invalid according to the trading rules.")
print("=" * 100)



