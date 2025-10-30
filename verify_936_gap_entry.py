#!/usr/bin/env python3
"""Verify 9:39 entry based on 9:36 gap"""

import pandas as pd
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from src.core.data_loader import load_processed_30s_csv
from src.core.fvg_detection import detect_fvgs
from src.core.config import CONFIG

df = load_processed_30s_csv('data/raw/' + CONFIG['data_path'])
df = df[df['timestamp'].dt.date == pd.Timestamp('2025-10-23').date()].reset_index(drop=True)
df = detect_fvgs(df)

# Check the 9:36 FVG and see if 9:39 should trigger
print("=" * 100)
print("CHECKING 9:36 GAP → 9:39 ENTRY")
print("=" * 100)

idx_936 = df[df['timestamp'].dt.time == pd.Timestamp('09:36:00').time()].index[0]
bar_936 = df.iloc[idx_936]

if bar_936.get('bull_fvg', False):
    fvg_lower = bar_936.get('bull_lower', 0)
    fvg_upper = bar_936.get('bull_upper', 0)
    
    print(f"\nFVG created at 9:36:00")
    print(f"  Bounds: {fvg_lower:.2f} - {fvg_upper:.2f}")
    print(f"  Bar: L={bar_936['low']:.2f} (this is the upper bound of gap)")
    
    # Check bars after 9:36 - see if price moved away first
    print(f"\nChecking if price moved away from gap after creation:")
    moved_away = False
    for i in range(idx_936 + 1, idx_936 + 6):
        if i >= len(df):
            break
        later_bar = df.iloc[i]
        time_str = later_bar['timestamp'].strftime('%H:%M:%S')
        if later_bar['low'] > fvg_upper:
            moved_away = True
            print(f"  {time_str}: Low={later_bar['low']:.2f} > {fvg_upper:.2f} ✓ Price moved away")
            break
        else:
            print(f"  {time_str}: Low={later_bar['low']:.2f} (still near gap)")
    
    # Check 9:39 specifically
    idx_939 = df[df['timestamp'].dt.time == pd.Timestamp('09:39:00').time()].index[0]
    bar_939 = df.iloc[idx_939]
    prev_bar_939 = df.iloc[idx_939 - 1]
    
    print(f"\n9:39:00 bar:")
    print(f"  O={bar_939['open']:.2f} H={bar_939['high']:.2f} L={bar_939['low']:.2f} C={bar_939['close']:.2f}")
    print(f"  Previous (9:38:30): H={prev_bar_939['high']:.2f}")
    
    price_enters = bar_939['low'] <= fvg_upper and bar_939['high'] >= fvg_lower
    closes_above = bar_939['close'] > prev_bar_939['high']
    
    print(f"\nEntry conditions for 9:39:")
    print(f"  1. Price enters gap: {price_enters} (L={bar_939['low']:.2f} <= {fvg_upper:.2f})")
    print(f"  2. Price moved away first: {moved_away}")
    print(f"  3. Closes above prev high: {closes_above} (C={bar_939['close']:.2f} > {prev_bar_939['high']:.2f})")
    print(f"  4. Gap valid: {bar_939['close'] >= fvg_lower}")
    
    if price_enters and moved_away and closes_above:
        print(f"\n✅✅✅ SHOULD ENTER AT 9:39 ✅✅✅")
    else:
        print(f"\n❌ Conditions not met for 9:39 entry")

