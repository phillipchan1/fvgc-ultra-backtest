# main.py
# ---------------------------------------------------------------------------
# Main entry point for FVG Backtest
# ---------------------------------------------------------------------------

import warnings
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.data_loader import load_processed_30s_csv
from src.core.backtest_engine import run_backtest, calculate_metrics
from src.core.config import CONFIG


def main():
    """Main execution function."""
    warnings.filterwarnings("ignore", category=FutureWarning)
    
    # Load processed 30-second data
    print("Loading processed 30-second data...")
    data_path = os.path.join("data", "processed", CONFIG["data_path"])
    df = load_processed_30s_csv(data_path)
    print(f"Loaded {len(df):,} 30-second bars")
    
    # Run backtest
    print("Running backtest...")
    trades = run_backtest(df)
    
    if trades.empty:
        print("No trades generated.")
        return
    
    # Calculate and display metrics
    metrics = calculate_metrics(trades)
    print(f"\nMetrics: {metrics}")
    
    # Save results
    output_path = os.path.join("outputs", "trades", CONFIG["trades_csv"])
    trades.to_csv(output_path, index=False)
    print(f"\nSaved trades to: {output_path}")


if __name__ == "__main__":
    main()
