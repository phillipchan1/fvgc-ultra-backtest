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
    CONFIG["trade_management_strategy"] = "dynamic_partial_close" # Best strategy
    CONFIG["allow_multiple_entries_per_fvg"] = True # Capture all trades for review

    print("=" * 100)
    print("RUNNING BACKTEST: SEPTEMBER-OCTOBER 2025")
    print("Strategy: Dynamic + Partial Close (Best Performer)")
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

    # Show detailed summary for manual verification
    print("\n" + "-" * 100)
    print(f"ALL TRADES (for manual verification):")
    print("-" * 100)
    print(f"{'Entry Time':<20} {'Dir':<6} {'Model':<15} {'Entry':<8} {'FVG':<12} {'Touch':<6} {'PnL':<8} {'Exit':<10}")
    print("-" * 100)
    
    for idx, trade in trades.iterrows():
        entry_time = pd.Timestamp(trade['entry_time']).strftime('%m-%d %H:%M')
        entry_price = f"{trade['entry_price']:.1f}"
        fvg_info = f"{trade['fvg_size_pts']:.1f}pts"
        touch = f"{trade['fvg_touch_count']:.0f}"
        pnl = f"{trade['pnl']:+.1f}"
        
        print(f"{entry_time:<20} {trade['direction'].upper():<6} {trade['entry_model'].replace('fvg_continuation_', ''):<15} {entry_price:<8} {fvg_info:<12} {touch:<6} {pnl:<8} {trade['exit_reason']:<10}")

    print("\n" + "=" * 100)
    print(f"\n📊 All {len(trades)} trades saved to: {output_file}")
    print("💡 Review this CSV in detail to identify entry model issues")
    print("=" * 100)

if __name__ == "__main__":
    run_sept_oct_backtest()

