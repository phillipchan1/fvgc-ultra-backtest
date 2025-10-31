#!/usr/bin/env python3
"""
Run 4 baseline backtests (one per trade management strategy)
with NO filters - captures ALL trades for post-hoc analysis
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.core.config import CONFIG
from src.core.data_loader import load_processed_30s_csv
from src.core.backtest_engine import run_backtest
import copy


def run_baseline_for_strategy(strategy_name: str, data_df, output_dir: str):
    """Run baseline backtest for a specific trade management strategy"""
    print(f"\n{'='*80}")
    print(f"Running baseline: {strategy_name.upper()}")
    print(f"{'='*80}")
    
    # Create config with this TM strategy
    config = copy.deepcopy(CONFIG)
    config['trade_management_strategy'] = strategy_name
    config['test_period'] = 'full_dataset'
    
    # Run backtest
    start_time = time.time()
    trades_df = run_backtest(data_df.copy(), override_config=config)
    elapsed = time.time() - start_time
    
    # Save results
    output_file = os.path.join(output_dir, f"trades_{strategy_name}.csv")
    trades_df.to_csv(output_file, index=False)
    
    # Print summary
    print(f"\nCompleted in {elapsed:.1f} seconds")
    print(f"Total trades: {len(trades_df)}")
    if len(trades_df) > 0:
        win_rate = len(trades_df[trades_df['pnl'] > 0]) / len(trades_df) * 100
        net_pnl = trades_df['pnl'].sum()
        print(f"Win rate: {win_rate:.2f}%")
        print(f"Net P&L: {net_pnl:+.2f} pts")
    print(f"Saved to: {output_file}")
    
    return trades_df


def main():
    """Run all 4 baseline backtests"""
    print("\n" + "="*80)
    print("BASELINE BACKTESTS - NO FILTERS")
    print("="*80)
    print("\nRunning 4 backtests (one per trade management strategy)")
    print("This captures ALL trades for fast post-hoc filtering\n")
    
    # Create output directory
    output_dir = "outputs/baseline"
    os.makedirs(output_dir, exist_ok=True)
    
    # Load data once
    print("Loading data...")
    data_path = os.path.join("data", "processed", "data_30s.csv")
    df = load_processed_30s_csv(data_path, date_filter=None)
    print(f"Loaded {len(df):,} bars (full 2+ year dataset)")
    
    # Trade management strategies to test
    strategies = [
        "fixed",
        "dynamic_fvg",
        "partial_close",
        "trailing_sl"
    ]
    
    # Run each baseline
    total_start = time.time()
    results = {}
    
    for strategy in strategies:
        trades_df = run_baseline_for_strategy(strategy, df, output_dir)
        results[strategy] = len(trades_df)
    
    total_elapsed = time.time() - total_start
    
    # Summary
    print("\n" + "="*80)
    print("BASELINE BACKTESTS COMPLETE")
    print("="*80)
    print(f"\nTotal runtime: {total_elapsed:.1f} seconds")
    print(f"\nTrade counts by strategy:")
    for strategy, count in results.items():
        print(f"  {strategy:<20}: {count:>5} trades")
    
    print(f"\nAll baseline trades saved to: {output_dir}/")
    print("\nNext step: Run 'python analyze_baseline_results.py' for fast filtering")
    print("="*80 + "\n")


if __name__ == "__main__":
    main()

