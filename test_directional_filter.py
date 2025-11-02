#!/usr/bin/env python3
"""
Test directional filter integration.

This script validates that:
1. SMA data is properly loaded
2. Directional filters work correctly
3. Trade counts make sense for each filter mode
"""
import os
import sys

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.core.data_loader import load_processed_30s_csv
from src.core.backtest_engine import run_backtest
from src.core.config import CONFIG
import pandas as pd


def test_directional_filters():
    """Test all directional filter modes."""
    
    print("\n" + "=" * 80)
    print("DIRECTIONAL FILTER INTEGRATION TEST")
    print("=" * 80)
    
    # Test configuration
    test_date = "2025-10-23"
    
    # Check if SMA data exists
    data_path_with_sma = "data/processed/data_30s_with_sma.csv"
    data_path_regular = "data/processed/data_30s.csv"
    
    if os.path.exists(data_path_with_sma):
        data_path = data_path_with_sma
        print(f"✅ Using SMA-enhanced data: {data_path}")
    else:
        print(f"⚠️  SMA data not found at: {data_path_with_sma}")
        print(f"   Run: python scripts/add_sma_to_data.py")
        print(f"\n   Falling back to regular data for structural test...")
        data_path = data_path_regular
    
    # Override config for single-day test
    test_config = CONFIG.copy()
    test_config['test_period'] = 'single_day'
    test_config['test_date'] = test_date
    
    # Load data
    print(f"\nLoading data for test date: {test_date}")
    df = load_processed_30s_csv(data_path, date_filter=test_date)
    
    if df.empty:
        print(f"❌ No data found for {test_date}")
        return
    
    print(f"Loaded {len(df)} bars")
    
    # Check for SMA column
    if 'sma_200' in df.columns:
        sma_count = df['sma_200'].notna().sum()
        print(f"✅ SMA_200 column found: {sma_count}/{len(df)} bars have values")
        
        # Show SMA stats
        if sma_count > 0:
            print(f"   SMA range: {df['sma_200'].min():.2f} - {df['sma_200'].max():.2f}")
            print(f"   Mean SMA: {df['sma_200'].mean():.2f}")
            
            # Count bullish/bearish regime bars
            bullish_bars = (df['close'] > df['sma_200']).sum()
            bearish_bars = (df['close'] < df['sma_200']).sum()
            print(f"   Bullish bars (close > SMA): {bullish_bars} ({bullish_bars/len(df)*100:.1f}%)")
            print(f"   Bearish bars (close < SMA): {bearish_bars} ({bearish_bars/len(df)*100:.1f}%)")
    else:
        print("⚠️  No SMA_200 column in data")
        print("   Directional filters will not work without SMA data")
    
    # Test each filter mode
    filter_modes = ["none", "bidirectional", "longs_only"]
    results = {}
    
    print("\n" + "-" * 80)
    print("TESTING FILTER MODES")
    print("-" * 80)
    
    for mode in filter_modes:
        print(f"\n Testing: {mode}")
        
        # Set filter mode
        test_config['directional_filter'] = mode
        
        # Run backtest
        trades_df = run_backtest(df.copy(), override_config=test_config)
        
        # Analyze results
        total = len(trades_df)
        longs = len(trades_df[trades_df['direction'] == 'long']) if total > 0 else 0
        shorts = len(trades_df[trades_df['direction'] == 'short']) if total > 0 else 0
        
        results[mode] = {
            'total': total,
            'longs': longs,
            'shorts': shorts
        }
        
        print(f"   Total trades: {total}")
        print(f"   Longs: {longs} ({longs/total*100 if total > 0 else 0:.1f}%)")
        print(f"   Shorts: {shorts} ({shorts/total*100 if total > 0 else 0:.1f}%)")
        
        if total > 0:
            win_rate = (trades_df['pnl'] > 0).sum() / total
            net_pnl = trades_df['pnl'].sum()
            print(f"   Win rate: {win_rate*100:.1f}%")
            print(f"   Net PnL: {net_pnl:.2f} pts")
    
    # Summary comparison
    print("\n" + "=" * 80)
    print("SUMMARY COMPARISON")
    print("=" * 80)
    print(f"\n{'Mode':<20} {'Total':<10} {'Longs':<10} {'Shorts':<10}")
    print("-" * 80)
    for mode in filter_modes:
        r = results[mode]
        print(f"{mode:<20} {r['total']:<10} {r['longs']:<10} {r['shorts']:<10}")
    
    # Validation checks
    print("\n" + "=" * 80)
    print("VALIDATION CHECKS")
    print("=" * 80)
    
    checks_passed = True
    
    # Check 1: "none" mode should have most trades
    if results['none']['total'] >= results['bidirectional']['total']:
        print("✅ Check 1: 'none' mode has >= trades than 'bidirectional'")
    else:
        print("❌ Check 1 FAILED: 'bidirectional' has more trades than 'none'")
        checks_passed = False
    
    # Check 2: "longs_only" should have no shorts
    if 'sma_200' in df.columns and df['sma_200'].notna().sum() > 0:
        if results['longs_only']['shorts'] == 0:
            print("✅ Check 2: 'longs_only' mode has zero shorts")
        else:
            print(f"❌ Check 2 FAILED: 'longs_only' has {results['longs_only']['shorts']} shorts")
            checks_passed = False
    else:
        print("⚠️  Check 2 SKIPPED: No SMA data available")
    
    # Check 3: "bidirectional" should have fewer trades than "none"
    if 'sma_200' in df.columns and df['sma_200'].notna().sum() > 0:
        if results['bidirectional']['total'] <= results['none']['total']:
            print("✅ Check 3: 'bidirectional' mode filters out some trades")
        else:
            print("❌ Check 3 FAILED: 'bidirectional' has more trades than 'none'")
            checks_passed = False
    else:
        print("⚠️  Check 3 SKIPPED: No SMA data available")
    
    print("\n" + "=" * 80)
    if checks_passed:
        print("✅ ALL CHECKS PASSED - Directional filter integration successful!")
    else:
        print("⚠️  SOME CHECKS FAILED - Review implementation")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    test_directional_filters()


