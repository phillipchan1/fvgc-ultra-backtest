#!/usr/bin/env python3
"""
Test the sweep fix for Sept 2 09:53:00 entry
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from src.core.data_loader import load_processed_30s_csv
from src.core.fvg_detection import detect_fvgs, create_fvg_from_row
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

print("Sept 2, 09:53:00 - Testing sweep fix")
print("="*80)
print(f"Entry bar {entry_bar_idx}: High={current_bar['high']:.2f}, Close={current_bar['close']:.2f}")
print()

# Test the FVG at bar 42 (09:51:00) which was generating the invalid trade
fvg_bar = df.iloc[42]
fvg = create_fvg_from_row(fvg_bar, 42, 'bullish')

print(f"Testing FVG at bar 42 (09:51:00):")
print(f"  FVG: {fvg.upper:.2f} - {fvg.lower:.2f}")

model = FVGContinuationNoFVGModel()

# Find swing high with new logic (should find bar 43, not bar 50)
swing_high_idx = model._find_swing_high(fvg.created_idx + 1, entry_bar_idx, df)
if swing_high_idx:
    swing_high_price = df['high'].iloc[swing_high_idx]
    print(f"  Swing high: bar {swing_high_idx} ({df.iloc[swing_high_idx]['timestamp'].strftime('%H:%M:%S')}), price {swing_high_price:.2f}")
    print(f"  Entry HIGH {current_bar['high']:.2f} > swing {swing_high_price:.2f}? {current_bar['high'] > swing_high_price}")
    
    if current_bar['high'] > swing_high_price:
        print(f"\n  ✅ SWEEP DETECTED - Entry should be REJECTED")
    else:
        print(f"\n  ❌ No sweep - Entry would be accepted (WRONG!)")
else:
    print(f"  No swing high found")

# Test model evaluation
signal = model.evaluate(fvg, current_bar, previous_bar, entry_bar_idx, df)
if signal:
    print(f"\n❌ BUG STILL EXISTS: Model ACCEPTS this invalid entry!")
else:
    print(f"\n✅ BUG FIXED: Model correctly REJECTS this entry!")

