#!/usr/bin/env python3
"""
Verify Sept 2 trade with correct distance check
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from src.core.data_loader import load_processed_30s_csv
from src.core.fvg_detection import detect_fvgs
from src.core.config import CONFIG

CONFIG["start_date"] = "2025-09-02"
CONFIG["end_date"] = "2025-09-02"
CONFIG["test_period"] = None

df = load_processed_30s_csv("data/processed/data_30s.csv")
df = detect_fvgs(df)
df = df.reset_index(drop=True)

# Check bars 38 and 39
bar_38 = df.iloc[38]
bar_39 = df.iloc[39]

print("Sept 2 BOS Trade Verification:")
print("="*80)
print(f"Bar 38 (previous): High={bar_38['high']:.2f}, Close={bar_38['close']:.2f}")
print(f"Bar 39 (entry):    Close={bar_39['close']:.2f}")
print(f"\nDistance calculation:")
print(f"  Close - Previous High = {bar_39['close']:.2f} - {bar_38['high']:.2f} = {bar_39['close'] - bar_38['high']:.2f}")
print(f"  Is <= 7.5? {bar_39['close'] - bar_38['high'] <= 7.5}")

if bar_39['close'] - bar_38['high'] <= 7.5:
    print("\n✅ PASSES distance check - should be BOS entry")
else:
    print("\n❌ FAILS distance check")

