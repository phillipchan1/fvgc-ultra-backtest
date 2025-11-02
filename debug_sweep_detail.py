#!/usr/bin/env python3
"""
Detailed trace of Sept 2 09:53:00 entry logic
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from src.core.data_loader import load_processed_30s_csv
from src.core.fvg_detection import detect_fvgs, create_fvg_from_row, FVG
from src.models.fvg_continuation_no_fvg import FVGContinuationNoFVGModel
from src.core.config import CONFIG
import pandas as pd

CONFIG["start_date"] = "2025-09-02"
CONFIG["end_date"] = "2025-09-02"
CONFIG["test_period"] = None

df = load_processed_30s_csv("data/processed/data_30s.csv")
df = detect_fvgs(df)
df = df.reset_index(drop=True)

# Bar 46 is 09:53:00
entry_bar_idx = 46
current_bar = df.iloc[entry_bar_idx]
previous_bar = df.iloc[entry_bar_idx - 1]

print(f"Entry bar {entry_bar_idx} ({current_bar['timestamp'].strftime('%H:%M:%S')}):")
print(f"  High: {current_bar['high']:.2f}, Close: {current_bar['close']:.2f}")
print()

# Find active bullish FVGs at this bar
print("Active bullish FVGs at entry:")
active_fvgs = []
for i in range(entry_bar_idx):
    row = df.iloc[i]
    if row.get('bull_fvg', False) and pd.notna(row.get('bull_size')):
        fvg = create_fvg_from_row(row, i, 'bullish')
        # Simple validity check
        still_valid = True
        for j in range(i+1, entry_bar_idx+1):
            if df.iloc[j]['close'] < fvg.lower:
                still_valid = False
                break
        if still_valid:
            active_fvgs.append(fvg)
            print(f"  FVG at bar {i} ({df.iloc[i]['timestamp'].strftime('%H:%M:%S')}): "
                  f"Upper={fvg.upper:.2f}, Lower={fvg.lower:.2f}, Size={fvg.size_pts:.2f}")

print()

# Test each FVG with the noFVG model
model = FVGContinuationNoFVGModel()

for fvg in active_fvgs[-3:]:  # Just test the last 3 FVGs
    print(f"\nTesting FVG created at bar {fvg.created_idx} ({df.iloc[fvg.created_idx]['timestamp'].strftime('%H:%M:%S')}):")
    print(f"  FVG: {fvg.upper:.2f} - {fvg.lower:.2f}")
    
    # Find swing high according to model logic
    swing_high_idx = model._find_swing_high(fvg.created_idx + 1, df)
    if swing_high_idx is None:
        print(f"  ❌ No swing high found after FVG creation")
        continue
    
    swing_high_price = df['high'].iloc[swing_high_idx]
    print(f"  Swing high: bar {swing_high_idx} ({df.iloc[swing_high_idx]['timestamp'].strftime('%H:%M:%S')}), price {swing_high_price:.2f}")
    
    # Check sweep
    print(f"  Entry bar HIGH {current_bar['high']:.2f} > swing {swing_high_price:.2f}? {current_bar['high'] > swing_high_price}")
    
    # Check if model accepts this
    signal = model.evaluate(fvg, current_bar, previous_bar, entry_bar_idx, df)
    if signal:
        print(f"  ✅ Model ACCEPTS entry at {signal.entry_price:.2f}")
    else:
        print(f"  ❌ Model REJECTS entry")
