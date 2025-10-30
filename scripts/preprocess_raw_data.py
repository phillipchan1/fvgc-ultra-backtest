import pandas as pd
import os

def preprocess_data():
    """
    Reads the raw 30s CSV, renames the timestamp column, converts it to the
    expected nanosecond format, and saves it to the processed data folder.
    """
    raw_path = os.path.join("data", "raw", "glbx-mdp3-20231002-20251027.ohlcv-30s-trading-session.csv")
    processed_path = os.path.join("data", "processed", "data_30s.csv")

    print(f"Reading raw data from {raw_path}...")
    df = pd.read_csv(raw_path)

    # 1. Rename 'timestamp' to 'ts_event'
    if 'timestamp' in df.columns:
        df.rename(columns={'timestamp': 'ts_event'}, inplace=True)
    else:
        print("Warning: 'timestamp' column not found. Assuming 'ts_event' already exists.")
        return

    # 2. Convert datetime string to nanosecond timestamp integer
    df['ts_event'] = pd.to_datetime(df['ts_event'], utc=True).astype('int64')

    # 3. Save to processed file
    os.makedirs(os.path.dirname(processed_path), exist_ok=True)
    df.to_csv(processed_path, index=False)
    print(f"Successfully preprocessed data and saved to {processed_path}")

if __name__ == "__main__":
    preprocess_data()
