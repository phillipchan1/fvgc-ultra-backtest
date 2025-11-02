#!/usr/bin/env python3
"""
Test runner for different date ranges
Quick script to test single day, week, month, or full dataset
"""

import sys
import os
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))

from src.core.data_loader import load_processed_30s_csv
from src.core.backtest_engine import run_backtest, calculate_metrics
from src.core.config import CONFIG
import warnings

warnings.filterwarnings("ignore", category=FutureWarning)


def run_test(period, test_date=None, test_start_date=None):
    """Run backtest for specified period."""
    
    # Update config
    CONFIG["test_period"] = period
    if test_date:
        CONFIG["test_date"] = test_date
    if test_start_date:
        CONFIG["test_start_date"] = test_start_date
    
    print("=" * 100)
    print(f"RUNNING BACKTEST: {period.upper().replace('_', ' ')}")
    print("=" * 100)
    
    # Load data
    data_path = os.path.join("data", "raw", CONFIG["data_path"])
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
    print(f"Period: {period}")
    if period == "single_day":
        print(f"Date: {CONFIG.get('test_date', 'N/A')}")
    elif period in ["week", "month"]:
        print(f"Start Date: {CONFIG.get('test_start_date', 'N/A')}")
    
    print(f"\nTrades: {metrics['trades']}")
    print(f"Wins: {metrics['winning_trades']} | Losses: {metrics['losing_trades']}")
    print(f"Win Rate: {metrics['win_rate']:.1%}")
    print(f"Net PnL: {metrics['net']:+.2f} points")
    print(f"Gross Profit: {metrics['gross_profit']:+.2f} points")
    print(f"Gross Loss: {metrics['gross_loss']:+.2f} points")
    print(f"Profit Factor: {metrics['profit_factor']:.2f}")
    print(f"Avg Win: {metrics['avg_win']:.2f} pts | Avg Loss: {metrics['avg_loss']:.2f} pts")
    
    # Show date range
    print(f"\nDate Range: {trades['entry_time'].min()} to {trades['entry_time'].max()}")
    
    # Save results
    period_name = period.replace("_", "")
    output_file = f"outputs/trades/test_{period_name}.csv"
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    trades.to_csv(output_file, index=False)
    print(f"\n✅ Saved to: {output_file}")
    
    # Show first 5 trades
    print("\n" + "-" * 100)
    print("FIRST 5 TRADES:")
    print("-" * 100)
    for idx, trade in trades.head(5).iterrows():
        entry_time = pd.Timestamp(trade['entry_time']).strftime('%Y-%m-%d %H:%M:%S')
        exit_time = pd.Timestamp(trade['exit_time']).strftime('%Y-%m-%d %H:%M:%S')
        print(f"  {entry_time} | {trade['direction'].upper():5s} @ {trade['entry_price']:.2f} "
              f"→ {exit_time} @ {trade['exit_price']:.2f} ({trade['exit_reason']}) | "
              f"PnL: {trade['pnl']:+.2f} pts")
    
    if len(trades) > 5:
        print(f"  ... and {len(trades) - 5} more trades")
    
    print("\n" + "=" * 100)
    
    return metrics, trades


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Run backtest for different date ranges")
    parser.add_argument(
        "--period",
        type=str,
        choices=["single_day", "week", "month", "full_dataset"],
        default="single_day",
        help="Test period: single_day, week, month, or full_dataset"
    )
    parser.add_argument(
        "--date",
        type=str,
        help="Date for single_day testing (YYYY-MM-DD), e.g., 2025-10-23"
    )
    parser.add_argument(
        "--start",
        type=str,
        help="Start date for week/month testing (YYYY-MM-DD)"
    )
    
    args = parser.parse_args()
    
    # Run test
    run_test(
        period=args.period,
        test_date=args.date,
        test_start_date=args.start
    )



