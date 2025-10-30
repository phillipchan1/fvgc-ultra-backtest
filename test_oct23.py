#!/usr/bin/env python3
"""Run backtest for Oct 23, 2025 only and show detailed results"""

import pandas as pd
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from src.core.data_loader import load_processed_30s_csv
from src.core.backtest_engine import run_backtest, calculate_metrics
from src.core.config import CONFIG


def main():
    print("=" * 100)
    print("BACKTEST FOR OCTOBER 23, 2025")
    print("=" * 100)
    
    # Load data
    data_path = os.path.join("data", "processed", CONFIG["data_path"])
    df = load_processed_30s_csv(data_path)
    
    # Filter to Oct 23, 2025
    target_date = pd.Timestamp('2025-10-23').date()
    df = df[df['timestamp'].dt.date == target_date].copy().reset_index(drop=True)
    
    print(f"\nFiltered to Oct 23, 2025: {len(df)} bars")
    print(f"Time range: {df['timestamp'].min()} to {df['timestamp'].max()}")
    
    # Run backtest
    print("\nRunning backtest...")
    trades = run_backtest(df)
    
    if trades.empty:
        print("\n❌ No trades generated for Oct 23, 2025")
        return
    
    # Convert entry_time to datetime for easier filtering
    trades['entry_time'] = pd.to_datetime(trades['entry_time'])
    trades = trades.sort_values('entry_time').reset_index(drop=True)
    
    # Calculate metrics
    metrics = calculate_metrics(trades)
    
    print("\n" + "=" * 100)
    print("RESULTS SUMMARY")
    print("=" * 100)
    print(f"Total Trades: {metrics['trades']}")
    print(f"Wins: {metrics['winning_trades']} | Losses: {metrics['losing_trades']}")
    print(f"Win Rate: {metrics['win_rate']:.1%}")
    print(f"Net PnL: {metrics['net']:.2f} points")
    print(f"Gross Profit: {metrics['gross_profit']:.2f} points")
    print(f"Gross Loss: {metrics['gross_loss']:.2f} points")
    print(f"Profit Factor: {metrics['profit_factor']:.2f}")
    
    print("\n" + "=" * 100)
    print("ALL TRADES FOR OCT 23, 2025")
    print("=" * 100)
    
    # Display all trades in a readable format
    for idx, trade in trades.iterrows():
        entry_time = pd.Timestamp(trade['entry_time']).strftime('%H:%M:%S')
        exit_time = pd.Timestamp(trade['exit_time']).strftime('%H:%M:%S')
        direction = trade['direction'].upper()
        
        print(f"\nTrade #{idx + 1}:")
        print(f"  Entry: {entry_time} @ {trade['entry_price']:.2f} ({direction})")
        print(f"  Exit:  {exit_time} @ {trade['exit_price']:.2f} ({trade['exit_reason']})")
        print(f"  PnL:   {trade['pnl']:+.2f} points")
        print(f"  TP: {trade['tp_price']:.2f} | SL: {trade['sl_price']:.2f}")
        print(f"  FVG: ID={trade['fvg_id']}, Size={trade['fvg_size_pts']:.2f} pts, Model={trade['entry_model']}")
    
    # Save to CSV
    output_file = "outputs/trades/oct23_2025_trades.csv"
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    trades.to_csv(output_file, index=False)
    
    print(f"\n✅ Saved {len(trades)} trades to: {output_file}")
    
    # Summary by exit reason
    print("\n" + "=" * 100)
    print("EXIT REASON BREAKDOWN")
    print("=" * 100)
    exit_reasons = trades['exit_reason'].value_counts()
    for reason, count in exit_reasons.items():
        reason_trades = trades[trades['exit_reason'] == reason]
        avg_pnl = reason_trades['pnl'].mean()
        print(f"  {reason:15s}: {count:3d} trades | Avg PnL: {avg_pnl:+.2f} pts")
    
    print("\n" + "=" * 100)


if __name__ == "__main__":
    main()

