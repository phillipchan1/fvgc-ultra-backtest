#!/usr/bin/env python3
"""
FVG Detection Test Script
Validates FVG detection by outputting all detected gaps for manual chart verification.
"""

import pandas as pd
import os
import sys
from datetime import datetime

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.core.data_loader import load_processed_30s_csv
from src.core.fvg_detection import detect_fvgs
from src.core.config import CONFIG


def test_fvg_detection(date_filter=None, output_csv="outputs/fvg_detection_test.csv"):
    """
    Test FVG detection and output results for manual verification.
    
    Args:
        date_filter: Optional date string (YYYY-MM-DD) or list of dates to filter
        output_csv: Path to output CSV file
    """
    print("=" * 80)
    print("FVG Detection Test")
    print("=" * 80)
    
    # Load data
    data_path = os.path.join("data", "raw", CONFIG["data_path"])
    print(f"\nLoading data from: {data_path}")
    
    if not os.path.exists(data_path):
        print(f"ERROR: Data file not found: {data_path}")
        return
    
    df = load_processed_30s_csv(data_path)
    
    # Apply date filter if specified
    if date_filter:
        if isinstance(date_filter, str):
            target_date = pd.Timestamp(date_filter).date()
            df = df[df['timestamp'].dt.date == target_date].copy().reset_index(drop=True)
            print(f"Filtered to date: {date_filter} ({len(df)} bars)")
        elif isinstance(date_filter, list):
            dates = [pd.Timestamp(d).date() for d in date_filter]
            df = df[df['timestamp'].dt.date.isin(dates)].copy().reset_index(drop=True)
            print(f"Filtered to dates: {date_filter} ({len(df)} bars)")
    
    if len(df) == 0:
        print("ERROR: No data after filtering!")
        return
    
    print(f"\nLoaded {len(df):,} 30-second bars")
    print(f"Date range: {df['timestamp'].min()} to {df['timestamp'].max()}")
    
    # Detect FVGs
    print("\nDetecting FVGs...")
    df = detect_fvgs(df)
    
    # Extract detected FVGs into separate dataframe
    fvgs = []
    
    for idx, row in df.iterrows():
        # Bullish FVG
        if row.get('bull_fvg', False):
            fvgs.append({
                'timestamp': row['timestamp'],
                'direction': 'bullish',
                'lower': row.get('bull_lower', 0),
                'upper': row.get('bull_upper', 0),
                'size_pts': row.get('bull_size', 0),
                'middle_body_pts': row.get('bull_middle_body', 0),
                'bar_open': row['open'],
                'bar_high': row['high'],
                'bar_low': row['low'],
                'bar_close': row['close'],
            })
        
        # Bearish FVG
        if row.get('bear_fvg', False):
            fvgs.append({
                'timestamp': row['timestamp'],
                'direction': 'bearish',
                'lower': row.get('bear_lower', 0),
                'upper': row.get('bear_upper', 0),
                'size_pts': row.get('bear_size', 0),
                'middle_body_pts': row.get('bear_middle_body', 0),
                'bar_open': row['open'],
                'bar_high': row['high'],
                'bar_low': row['low'],
                'bar_close': row['close'],
            })
    
    if not fvgs:
        print("No FVGs detected!")
        return
    
    # Create FVG dataframe
    fvg_df = pd.DataFrame(fvgs)
    fvg_df = fvg_df.sort_values('timestamp').reset_index(drop=True)
    
    # Print summary statistics
    print("\n" + "=" * 80)
    print("FVG Detection Summary")
    print("=" * 80)
    print(f"Total FVGs detected: {len(fvg_df)}")
    print(f"  Bullish: {len(fvg_df[fvg_df['direction'] == 'bullish'])}")
    print(f"  Bearish: {len(fvg_df[fvg_df['direction'] == 'bearish'])}")
    
    if len(fvg_df) > 0:
        print(f"\nSize Statistics:")
        print(f"  Min size: {fvg_df['size_pts'].min():.2f} pts")
        print(f"  Max size: {fvg_df['size_pts'].max():.2f} pts")
        print(f"  Mean size: {fvg_df['size_pts'].mean():.2f} pts")
        print(f"  Median size: {fvg_df['size_pts'].median():.2f} pts")
        
        print(f"\nDate Distribution:")
        date_counts = fvg_df['timestamp'].dt.date.value_counts().sort_index()
        print(f"  Dates with FVGs: {len(date_counts)}")
        print(f"  Most FVGs on single day: {date_counts.max()}")
        print(f"  Average FVGs per day: {date_counts.mean():.1f}")
        
        print(f"\nSample FVGs (first 10):")
        sample_cols = ['timestamp', 'direction', 'lower', 'upper', 'size_pts']
        print(fvg_df[sample_cols].head(10).to_string(index=False))
    
    # Save to CSV
    os.makedirs(os.path.dirname(output_csv), exist_ok=True)
    fvg_df.to_csv(output_csv, index=False)
    print(f"\n✅ Saved {len(fvg_df)} FVGs to: {output_csv}")
    
    # Show date range in output
    if len(fvg_df) > 0:
        print(f"\nFVG date range: {fvg_df['timestamp'].min()} to {fvg_df['timestamp'].max()}")
    
    return fvg_df


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Test FVG detection")
    parser.add_argument(
        "--date",
        type=str,
        help="Specific date to test (YYYY-MM-DD), e.g., 2025-10-23"
    )
    parser.add_argument(
        "--dates",
        nargs="+",
        help="Multiple dates to test, e.g., --dates 2025-10-23 2025-10-24"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="outputs/fvg_detection_test.csv",
        help="Output CSV file path (default: outputs/fvg_detection_test.csv)"
    )
    
    args = parser.parse_args()
    
    date_filter = None
    if args.dates:
        date_filter = args.dates
    elif args.date:
        date_filter = args.date
    
    test_fvg_detection(date_filter=date_filter, output_csv=args.output)



