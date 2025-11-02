#!/usr/bin/env python3
"""
Calculate 200 SMA on 1-min bars and merge into 30s data.

This script:
1. Loads 1s raw data
2. Resamples to 1-min bars
3. Calculates 200-period SMA on 1-min close prices
4. Downsamples SMA to 30s intervals (forward fill)
5. Merges SMA column into existing 30s data
6. Saves enhanced dataset
"""
import pandas as pd
import numpy as np
from pathlib import Path


def main():
    print("=" * 80)
    print("ADDING 200 SMA TO 30s DATA")
    print("=" * 80)
    
    # File paths
    raw_1s_path = Path("data/raw/glbx-mdp3-20231002-20251027.ohlcv-1s.csv")
    data_30s_path = Path("data/processed/data_30s.csv")
    output_path = Path("data/processed/data_30s_with_sma.csv")
    
    # Step 1: Load 1s data
    print("\n1. Loading 1s raw data...")
    df_1s = pd.read_csv(raw_1s_path)
    print(f"   Loaded {len(df_1s):,} rows")
    
    # Convert timestamp (UTC timezone for consistency)
    df_1s['timestamp'] = pd.to_datetime(df_1s['ts_event'], unit='ns', utc=True)
    df_1s = df_1s.set_index('timestamp')
    
    # Step 2: Resample to 1-min bars
    print("\n2. Resampling to 1-min bars...")
    df_1min = df_1s.resample('1min').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum'
    }).dropna()
    print(f"   Created {len(df_1min):,} 1-min bars")
    
    # Step 3: Calculate 200 SMA on 1-min close
    print("\n3. Calculating 200-period SMA on 1-min close prices...")
    df_1min['sma_200'] = df_1min['close'].rolling(window=200, min_periods=200).mean()
    
    # Count valid SMA values
    valid_sma = df_1min['sma_200'].notna().sum()
    print(f"   SMA calculated for {valid_sma:,} / {len(df_1min):,} bars")
    print(f"   First 200 bars will have NaN (warmup period)")
    
    # Step 4: Resample SMA to 30s intervals (forward fill)
    print("\n4. Downsampling SMA to 30s intervals...")
    sma_30s = df_1min[['sma_200']].resample('30s').ffill()
    print(f"   Created {len(sma_30s):,} 30s SMA values")
    
    # Remove timezone from sma_30s index for merging
    sma_30s.index = sma_30s.index.tz_localize(None)
    
    # Step 5: Load existing 30s data
    print("\n5. Loading existing 30s data...")
    df_30s = pd.read_csv(data_30s_path)
    print(f"   Loaded {len(df_30s):,} rows")
    
    # Convert timestamp for merging (timezone-naive to match sma_30s)
    df_30s['timestamp'] = pd.to_datetime(df_30s['ts_event'], unit='ns')
    df_30s = df_30s.set_index('timestamp')
    
    # Step 6: Merge SMA into 30s data
    print("\n6. Merging SMA into 30s data...")
    df_30s_enhanced = df_30s.join(sma_30s, how='left')
    
    # Check merge success
    matched = df_30s_enhanced['sma_200'].notna().sum()
    print(f"   Matched {matched:,} / {len(df_30s_enhanced):,} rows with SMA values")
    
    # Step 7: Save enhanced dataset
    print("\n7. Saving enhanced dataset...")
    df_30s_enhanced = df_30s_enhanced.reset_index()
    df_30s_enhanced.to_csv(output_path, index=False)
    print(f"   Saved to: {output_path}")
    
    # Summary statistics
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Original 30s data:     {len(df_30s):,} rows")
    print(f"Enhanced data:         {len(df_30s_enhanced):,} rows")
    print(f"SMA coverage:          {matched:,} rows ({matched/len(df_30s_enhanced)*100:.1f}%)")
    print(f"NaN values:            {df_30s_enhanced['sma_200'].isna().sum():,} rows")
    print(f"\nSMA Statistics:")
    print(f"  Min:  {df_30s_enhanced['sma_200'].min():.2f}")
    print(f"  Max:  {df_30s_enhanced['sma_200'].max():.2f}")
    print(f"  Mean: {df_30s_enhanced['sma_200'].mean():.2f}")
    print("\n✅ SMA data successfully added to 30s dataset!")
    print("=" * 80)


if __name__ == "__main__":
    main()

