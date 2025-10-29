# process_data_1s_to_30s.py
# ---------------------------------------------------------------------------
# Process 1-second NQ data to 30-second trading session bars
# ---------------------------------------------------------------------------

import pandas as pd
import os
import pytz
from datetime import time

def process_nq_data():
    """Process NQ data with proper session filtering and contract handling."""
    
    print("🔄 Processing NQ data with proper session filtering...")
    
    input_file = "data/raw/glbx-mdp3-20231002-20251027.ohlcv-1s.csv"
    output_file = "data/raw/glbx-mdp3-20231002-20251027.ohlcv-30s-trading-session.csv"
    
    if not os.path.exists(input_file):
        print(f"❌ Input file not found: {input_file}")
        return
    
    file_size_mb = os.path.getsize(input_file) / (1024**2)
    print(f"📊 Input file size: {file_size_mb:.2f} MB")
    
    # Process in chunks to handle large file
    chunk_size = 1000000
    all_data = []
    total_rows_processed = 0
    total_rows_kept = 0
    
    print(f"📦 Processing in chunks of {chunk_size:,} rows...")
    
    for chunk_num, chunk_df in enumerate(pd.read_csv(input_file, chunksize=chunk_size)):
        total_rows_processed += len(chunk_df)
        
        if chunk_num % 10 == 0:
            print(f"  Processing chunk {chunk_num + 1}: {total_rows_processed:,} rows...")
        
        # Convert timestamp
        chunk_df['ts_event'] = pd.to_datetime(chunk_df['ts_event'], utc=True)
        
        # Filter by trading session (9:30-10:15 ET = 13:30-14:15 UTC)
        # Use hour filter for efficiency
        chunk_df['hour'] = chunk_df['ts_event'].dt.hour
        chunk_df = chunk_df[(chunk_df['hour'] >= 13) & (chunk_df['hour'] <= 14)]
        
        if len(chunk_df) == 0:
            continue
        
        # More precise time filtering
        chunk_df['time'] = chunk_df['ts_event'].dt.time
        session_start = time(13, 30)  # 9:30 AM ET
        session_end = time(14, 15)   # 10:15 AM ET
        
        chunk_df = chunk_df[(chunk_df['time'] >= session_start) & (chunk_df['time'] <= session_end)]
        
        if len(chunk_df) == 0:
            continue
        
        # Filter out rollover data (symbols with dashes)
        chunk_df = chunk_df[~chunk_df['symbol'].str.contains('-', na=False)]
        
        if len(chunk_df) == 0:
            continue
        
        # Convert to numeric
        for col in ['open', 'high', 'low', 'close', 'volume']:
            chunk_df[col] = pd.to_numeric(chunk_df[col], errors='coerce')
        
        # Remove any rows with NaN values
        chunk_df = chunk_df.dropna(subset=['open', 'high', 'low', 'close'])
        
        if len(chunk_df) == 0:
            continue
        
        # Sort by timestamp and remove duplicates
        chunk_df = chunk_df.sort_values('ts_event').drop_duplicates(subset=['ts_event'])
        
        # Resample to 30-second bars
        chunk_30s = resample_chunk_to_30s(chunk_df)
        
        if len(chunk_30s) > 0:
            all_data.append(chunk_30s)
            total_rows_kept += len(chunk_df)
    
    if not all_data:
        print("❌ No data processed!")
        return
    
    # Combine all data
    print(f"\n📊 Combining {len(all_data)} chunks...")
    final_df = pd.concat(all_data, ignore_index=True)
    
    # Sort by timestamp and remove duplicates
    final_df = final_df.sort_values('timestamp').drop_duplicates(subset=['timestamp'])
    
    # Convert timestamps from UTC to Eastern Time
    print("🕐 Converting timestamps from UTC to Eastern Time...")
    et_tz = pytz.timezone('America/New_York')
    # Ensure timestamp is timezone-aware (UTC)
    final_df['timestamp'] = pd.to_datetime(final_df['timestamp'], utc=True)
    # Convert to Eastern Time
    final_df['timestamp'] = final_df['timestamp'].dt.tz_convert(et_tz)
    
    # Add previous bar data
    final_df['prev_close'] = final_df['close'].shift(1)
    final_df['prev_high'] = final_df['high'].shift(1)
    final_df['prev_low'] = final_df['low'].shift(1)
    
    # Save to file
    final_df.to_csv(output_file, index=False)
    
    # Statistics
    output_size_mb = os.path.getsize(output_file) / (1024**2)
    compression_ratio = total_rows_kept / len(final_df)
    size_reduction = file_size_mb / output_size_mb
    
    print(f"\n✅ Processing complete!")
    print(f"📊 Total 1s rows processed: {total_rows_processed:,}")
    print(f"📊 Trading session rows kept: {total_rows_kept:,}")
    print(f"📊 Total 30s bars created: {len(final_df):,}")
    print(f"📈 Compression ratio: {compression_ratio:.1f}x")
    print(f"📉 Size reduction: {size_reduction:.1f}x smaller")
    print(f"💾 Output file size: {output_size_mb:.2f} MB")
    print(f"📁 Output file: {output_file}")
    
    # Show date range and sample
    if len(final_df) > 0:
        start_date = final_df['timestamp'].min()
        end_date = final_df['timestamp'].max()
        print(f"📅 Date range: {start_date.date()} to {end_date.date()}")
        
        # Show symbols
        symbols = final_df['symbol'].value_counts()
        print(f"\n📋 Symbols in final data:")
        for symbol, count in symbols.items():
            print(f"  {symbol}: {count:,} bars")
        
        # Show sample
        print(f"\n📋 Sample data:")
        print(final_df.head(5)[['timestamp', 'open', 'high', 'low', 'close', 'volume', 'symbol']].to_string())
    
    return output_file

def resample_chunk_to_30s(df):
    """Resample a chunk of 1-second data to 30-second bars."""
    if df.empty:
        return df
    
    # Set timestamp as index
    df_indexed = df.set_index('ts_event')
    
    # Resample to 30-second bars
    agg_dict = {
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
        'symbol': 'first'  # Keep symbol info
    }
    
    # Resample
    df_30s = df_indexed.resample('30s').agg(agg_dict)
    
    # Remove rows with NaN values
    df_30s = df_30s.dropna(subset=['open', 'high', 'low', 'close'])
    
    # Reset index
    df_30s = df_30s.reset_index()
    df_30s = df_30s.rename(columns={'ts_event': 'timestamp'})
    
    return df_30s

def main():
    """Main processing function."""
    print("🚀 NQ Data Processing - 1s to 30s Trading Session")
    print("=" * 60)
    
    try:
        # Process the data
        output_file = process_nq_data()
        
        if output_file:
            print(f"\n🎉 Processing complete!")
            print(f"📁 30s trading session data ready: {output_file}")
            print("\nNext steps:")
            print("1. Update config to use the new file")
            print("2. Test the system: python test_permutation.py baseline")
        
    except Exception as e:
        print(f"❌ Error during processing: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
