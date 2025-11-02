#!/usr/bin/env python3
"""
Debug the Sept 2 09:53:00 trade - checking if it sweeps the swing high
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

print("September 2, 2025 - Analyzing 09:53:00 trade:")
print("="*100)

# Show bars around entry (bars 44-47)
for idx in range(40, 48):
    row = df.iloc[idx]
    time_str = row['timestamp'].strftime('%H:%M:%S')
    bull_fvg = "✓" if row.get('bull_fvg', False) else ""
    marker = " <<<" if idx == 46 else ""
    print(f"Bar {idx:2d} ({time_str}): O={row['open']:>8.2f} H={row['high']:>8.2f} L={row['low']:>8.2f} C={row['close']:>8.2f}  Bull FVG: {bull_fvg}{marker}")

print("\n" + "="*100)

# Analyze the entry bar
bar_46 = df.iloc[46]  # 09:53:00 entry
bar_45 = df.iloc[45]  # Previous bar

print(f"\nEntry bar 46 (09:53:00):")
print(f"  High: {bar_46['high']:.2f}")
print(f"  Close: {bar_46['close']:.2f}")
print(f"  Previous bar high: {bar_45['high']:.2f}")

# Find the swing high (should be somewhere before entry)
# Look for recent high
recent_highs = df['high'].iloc[41:46]  # Bars leading up to entry
max_idx = recent_highs.idxmax()
swing_high = recent_highs[max_idx]

print(f"\nSwing high analysis:")
print(f"  Swing high found at bar {max_idx}: {swing_high:.2f}")
print(f"  Entry bar HIGH: {bar_46['high']:.2f}")
print(f"  Entry bar CLOSE: {bar_46['close']:.2f}")
print(f"\n  Does entry HIGH sweep swing high? {bar_46['high']:.2f} > {swing_high:.2f}? {bar_46['high'] > swing_high}")
print(f"  Does entry CLOSE break through swing high? {bar_46['close']:.2f} > {swing_high:.2f}? {bar_46['close'] > swing_high}")

if bar_46['high'] > swing_high and bar_46['close'] <= swing_high:
    print(f"\n❌ INVALID: Entry bar SWEEPS swing high but doesn't CLOSE through it!")
    print(f"   This violates noFVG rules (no swing point sweep allowed)")
elif bar_46['close'] > swing_high:
    print(f"\n✅ Valid for BOS: Close breaks through swing high")
    print(f"   But NOT valid for noFVG (cannot sweep)")
else:
    print(f"\n✅ Valid for noFVG: No sweep of swing high")

