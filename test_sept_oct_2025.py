#!/usr/bin/env python3
import os
import sys
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))

from src.core.data_loader import load_processed_30s_csv
from src.core.backtest_engine import run_backtest, calculate_metrics
from src.core.config import CONFIG
import warnings

warnings.filterwarnings("ignore", category=FutureWarning)

def run_sept_oct_backtest():
    # Override config for this specific test
    CONFIG["test_period"] = None # Use explicit start/end dates
    CONFIG["start_date"] = "2025-09-01"
    CONFIG["end_date"] = "2025-10-31"
    CONFIG["trade_management_strategy"] = "fixed" # Default to fixed for this check
    CONFIG["allow_multiple_entries_per_fvg"] = False # Default to single entry

    print("=" * 100)
    print("RUNNING BACKTEST: SEPTEMBER-OCTOBER 2025")
    print("=" * 100)

    # Load data
    data_path = os.path.join("data", "processed", CONFIG["data_path"]) # Corrected path
    print(f"\nLoading data from: {data_path}\n")
    df = load_processed_30s_csv(data_path)

    # Run backtest
    print("\nRunning backtest...")
    trades = run_backtest(df)

    if trades.empty:
        print("\n❌ No trades generated.")
        return

    # Calculate metrics
    metrics = calculate_metrics(trades)
    trades['entry_time'] = pd.to_datetime(trades['entry_time'])

    # Display results
    print("\n" + "=" * 100)
    print("RESULTS")
    print("=" * 100)
    print(f"\nDate Range: {trades['entry_time'].min()} to {trades['entry_time'].max()}")
    print(f"Trades: {metrics['trades']}")
    print(f"Wins: {metrics['winning_trades']} | Losses: {metrics['losing_trades']}")
    print(f"Win Rate: {metrics['win_rate']:.1%}")
    print(f"Net PnL: {metrics['net']:+.2f} points")
    print(f"Gross Profit: {metrics['gross_profit']:+.2f} points")
    print(f"Gross Loss: {metrics['gross_loss']:+.2f} points")
    print(f"Profit Factor: {metrics['profit_factor']:.2f}")
    print(f"Avg Win: {metrics['avg_win']:.2f} pts | Avg Loss: {metrics['avg_loss']:.2f} pts")

    # Save results
    output_file = f"outputs/trades/sept_oct_2025.csv"
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    trades.to_csv(output_file, index=False)
    print(f"\n✅ Saved to: {output_file}")

    # Show summary
    print("\n" + "-" * 100)
    print(f"First 20 trades:")
    print("-" * 100)
    for idx, trade in trades.head(20).iterrows():
        entry_time = pd.Timestamp(trade['entry_time']).strftime('%Y-%m-%d %H:%M:%S')
        print(f"{entry_time} {trade['direction'].upper():<5} {trade['entry_model']:<25} {trade['pnl']:>7.2f} {trade['exit_reason']}")

    print("\n" + "=" * 100)

if __name__ == "__main__":
    run_sept_oct_backtest()

