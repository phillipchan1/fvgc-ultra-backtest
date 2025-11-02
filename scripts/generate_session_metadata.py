#!/usr/bin/env python3
"""
Generate session metadata for all trading days in the dataset.

Calculates:
- Total session volume (sum of all 30s bars from 9:30-10:15 AM)
- Session range in points (high - low)
- Red folder event tagging (day before, day of, day after event)
- Volume and range tier assignments

Output: data/processed/session_metadata.csv
"""

import pandas as pd
import numpy as np
from pathlib import Path
import sys

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.config import CONFIG


def load_red_folder_events(events_path: str) -> pd.DataFrame:
    """Load and process red folder events, expanding to include day before and after."""
    events_df = pd.read_csv(events_path)
    events_df['date'] = pd.to_datetime(events_df['date'])
    
    # Create expanded event list (day before, day of, day after)
    expanded_events = []
    
    for _, row in events_df.iterrows():
        event_date = row['date']
        event_type = row['event_type']
        event_name = row['event']
        
        # Day before
        expanded_events.append({
            'date': event_date - pd.Timedelta(days=1),
            'event_type': event_type,
            'event': event_name,
            'timing': 'day_before'
        })
        
        # Event day
        expanded_events.append({
            'date': event_date,
            'event_type': event_type,
            'event': event_name,
            'timing': 'event_day'
        })
        
        # Day after
        expanded_events.append({
            'date': event_date + pd.Timedelta(days=1),
            'event_type': event_type,
            'event': event_name,
            'timing': 'day_after'
        })
    
    expanded_df = pd.DataFrame(expanded_events)
    
    # Group multiple events on same day
    grouped = expanded_df.groupby('date').agg({
        'event_type': lambda x: ', '.join(sorted(set(x))),
        'event': lambda x: ' | '.join(sorted(set(x))),
        'timing': lambda x: ', '.join(sorted(set(x)))
    }).reset_index()
    
    return grouped


def calculate_volume_tiers(volumes: pd.Series) -> dict:
    """Calculate absolute volume thresholds from data."""
    percentiles = volumes.quantile([0.25, 0.50, 0.75, 0.90])
    
    thresholds = {
        'p25': int(percentiles[0.25]),
        'p50': int(percentiles[0.50]),
        'p75': int(percentiles[0.75]),
        'p90': int(percentiles[0.90])
    }
    
    print("\n📊 Volume Distribution Analysis:")
    print(f"   25th percentile: {thresholds['p25']:,}")
    print(f"   50th percentile (median): {thresholds['p50']:,}")
    print(f"   75th percentile: {thresholds['p75']:,}")
    print(f"   90th percentile: {thresholds['p90']:,}")
    
    return thresholds


def assign_volume_tier(volume: int, thresholds: dict) -> str:
    """Assign volume tier based on absolute thresholds."""
    if volume >= thresholds['p90']:
        return "Extremely High"
    elif volume >= thresholds['p75']:
        return "High"
    elif volume >= thresholds['p50']:
        return "Medium"
    else:
        return "Low"


def assign_range_tier(range_pts: float) -> str:
    """Assign range tier based on user-specified thresholds."""
    if range_pts >= 150:
        return "150+pts"
    elif range_pts >= 75:
        return "75-150pts"
    else:
        return "<75pts"


def generate_session_metadata():
    """Generate complete session metadata for all trading days."""
    
    print("=" * 80)
    print("SESSION METADATA GENERATOR")
    print("=" * 80)
    
    # Paths
    data_path = Path(__file__).parent.parent / "data" / "processed" / "data_30s.csv"
    events_path = Path(__file__).parent.parent / "data" / "raw" / "market_high_volume_events_2020_2025.csv"
    output_path = Path(__file__).parent.parent / "data" / "processed" / "session_metadata.csv"
    
    print(f"\n📂 Loading data from: {data_path}")
    
    # Load 30s data
    df = pd.read_csv(data_path)
    df['timestamp'] = pd.to_datetime(df['ts_event'], unit='ns')
    df['timestamp'] = df['timestamp'].dt.tz_localize('UTC').dt.tz_convert(CONFIG['session_tz'])
    
    print(f"   Loaded {len(df):,} bars")
    print(f"   Date range: {df['timestamp'].min().date()} to {df['timestamp'].max().date()}")
    
    # Filter to trading session (9:30-10:15 AM)
    session_start = pd.to_datetime(CONFIG['session_start']).time()
    session_end = pd.to_datetime(CONFIG['session_end']).time()
    
    df_session = df[
        (df['timestamp'].dt.time >= session_start) & 
        (df['timestamp'].dt.time <= session_end)
    ].copy()
    
    print(f"\n⏰ Filtered to session {session_start} - {session_end}")
    print(f"   Session bars: {len(df_session):,}")
    
    # Add date column for grouping
    df_session['date'] = df_session['timestamp'].dt.date
    
    # Calculate session metrics
    print("\n🔢 Calculating session metrics...")
    
    session_metrics = df_session.groupby('date').agg({
        'volume': 'sum',
        'high': 'max',
        'low': 'min'
    }).reset_index()
    
    session_metrics.rename(columns={'volume': 'total_volume'}, inplace=True)
    session_metrics['range_pts'] = session_metrics['high'] - session_metrics['low']
    session_metrics.drop(columns=['high', 'low'], inplace=True)
    
    print(f"   Sessions analyzed: {len(session_metrics):,}")
    
    # Calculate volume thresholds
    volume_thresholds = calculate_volume_tiers(session_metrics['total_volume'])
    
    # Assign tiers
    session_metrics['volume_tier'] = session_metrics['total_volume'].apply(
        lambda x: assign_volume_tier(x, volume_thresholds)
    )
    session_metrics['range_tier'] = session_metrics['range_pts'].apply(assign_range_tier)
    
    # Load red folder events
    print(f"\n📅 Loading red folder events from: {events_path}")
    events_df = load_red_folder_events(str(events_path))
    print(f"   Total event days (including day before/after): {len(events_df):,}")
    
    # Merge with events
    session_metrics['date_dt'] = pd.to_datetime(session_metrics['date'])
    merged = session_metrics.merge(
        events_df,
        left_on='date_dt',
        right_on='date',
        how='left',
        suffixes=('', '_event')
    )
    
    merged['is_red_folder'] = merged['event_type'].notna()
    merged['red_folder_event'] = merged['event'].fillna('')
    merged['event_timing'] = merged['timing'].fillna('')
    
    # Clean up
    final_df = merged[[
        'date',
        'total_volume',
        'range_pts',
        'volume_tier',
        'range_tier',
        'is_red_folder',
        'red_folder_event',
        'event_timing'
    ]].copy()
    
    final_df['date'] = pd.to_datetime(final_df['date'])
    
    # Summary statistics
    print("\n📈 Session Metrics Summary:")
    print(f"\n   Volume Stats:")
    print(f"      Min: {final_df['total_volume'].min():,}")
    print(f"      Max: {final_df['total_volume'].max():,}")
    print(f"      Mean: {final_df['total_volume'].mean():,.0f}")
    
    print(f"\n   Range Stats:")
    print(f"      Min: {final_df['range_pts'].min():.2f} pts")
    print(f"      Max: {final_df['range_pts'].max():.2f} pts")
    print(f"      Mean: {final_df['range_pts'].mean():.2f} pts")
    
    print(f"\n   Volume Tier Distribution:")
    for tier, count in final_df['volume_tier'].value_counts().sort_index().items():
        pct = 100 * count / len(final_df)
        print(f"      {tier}: {count:,} ({pct:.1f}%)")
    
    print(f"\n   Range Tier Distribution:")
    for tier, count in final_df['range_tier'].value_counts().sort_index().items():
        pct = 100 * count / len(final_df)
        print(f"      {tier}: {count:,} ({pct:.1f}%)")
    
    red_folder_count = final_df['is_red_folder'].sum()
    print(f"\n   Red Folder Days: {red_folder_count:,} ({100*red_folder_count/len(final_df):.1f}%)")
    
    # Save
    output_path.parent.mkdir(parents=True, exist_ok=True)
    final_df.to_csv(output_path, index=False)
    
    print(f"\n✅ Session metadata saved to: {output_path}")
    print(f"   Total sessions: {len(final_df):,}")
    
    # Show sample
    print(f"\n📋 Sample (first 10 rows):")
    print(final_df.head(10).to_string(index=False))
    
    print("\n" + "=" * 80)
    print("COMPLETE!")
    print("=" * 80)


if __name__ == "__main__":
    generate_session_metadata()



