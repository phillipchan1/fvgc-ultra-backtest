#!/usr/bin/env python3
"""
Run Bayesian optimization for parameter search.

This is a much faster alternative to grid search (run_parameter_sweep.py).
Instead of testing all ~3,840 combinations, Bayesian optimization intelligently
samples the parameter space to find optimal configurations in ~200-400 evaluations.

Expected speedup: 10-20x faster (8 hours → 30-60 minutes)
"""
import os
import sys
import argparse

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.optimization.bayesian_optimization import BayesianOptimizer
from src.optimization.results_analyzer import (
    print_results_summary,
    export_top_n,
    export_best_config,
    find_best_setup
)
import pandas as pd


def main():
    """Run Bayesian optimization"""
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Run Bayesian parameter optimization')
    parser.add_argument('--yes', '-y', action='store_true', help='Skip confirmation prompt')
    parser.add_argument('--n-calls', type=int, default=200, help='Number of evaluations (default: 200)')
    args = parser.parse_args()
    
    print("\n" + "=" * 100)
    print("BAYESIAN PARAMETER OPTIMIZATION")
    print("=" * 100)
    print("\nThis will intelligently search the parameter space using Bayesian optimization:")
    print("  - Entry Models: noFVG, BOS, iFVG, ALL")
    print("  - Gap Closure: True, False, ALL")
    print("  - Gap Size: 0-3, 3-6, 6-10, 10+, ALL")
    print("  - Time Windows: 9:30-9:45, 9:45-10:00, 10:00-10:15, ALL")
    print("  - Touch Ranges: 1-2, 3-4, 5+, ALL")
    print("  - Trade Management: fixed, dynamic_fvg, partial_close, trailing_sl")
    print("  - Directional Filter: none, bidirectional, longs_only")
    
    # Configuration
    n_calls = args.n_calls  # Number of evaluations (can increase to 400 for more thorough search)
    n_random_starts = 20  # Random exploration before using GP model
    min_trades = 30  # Minimum trades for valid configuration
    
    print(f"\nBayesian Optimization Settings:")
    print(f"  Total evaluations: {n_calls}")
    print(f"  Random starts: {n_random_starts}")
    print(f"  Minimum trades: {min_trades}")
    print(f"  Expected runtime: ~{n_calls * 7.5 / 60:.0f} minutes")
    print("\n" + "=" * 100)
    
    # Confirm (skip if --yes flag provided)
    if not args.yes:
        response = input("\nProceed with Bayesian optimization? (yes/no): ")
        if response.lower() not in ['yes', 'y']:
            print("Cancelled.")
            return
    else:
        print("\n✅ Auto-confirmed (--yes flag)")
    print()
    
    # Setup paths
    data_path = os.path.join("data", "processed", "data_30s_with_sma.csv")
    
    # Check if SMA data exists
    if not os.path.exists(data_path):
        print("\n⚠️  WARNING: SMA data not found!")
        print(f"   Expected: {data_path}")
        print("\n   Falling back to regular data without SMA...")
        print("   (Directional filter will be disabled for this run)")
        data_path = os.path.join("data", "processed", "data_30s.csv")
        
        if not os.path.exists(data_path):
            print("\n❌ ERROR: No data file found!")
            print("   Run: python scripts/add_sma_to_data.py")
            return
    
    output_dir = "outputs/optimization"
    
    # Initialize optimizer
    optimizer = BayesianOptimizer(min_trades=min_trades)
    
    # Run optimization
    print("\nStarting Bayesian optimization...")
    print("(Progress shown every 10 iterations, best configs highlighted)\n")
    
    try:
        result = optimizer.optimize(
            data_path=data_path,
            n_calls=n_calls,
            n_random_starts=n_random_starts,
            output_dir=output_dir,
            checkpoint_every=10
        )
    except KeyboardInterrupt:
        print("\n\n⚠️  Optimization interrupted by user!")
        print("Partial results have been saved.")
        return
    except Exception as e:
        print(f"\n\n❌ ERROR during optimization: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Load results as DataFrame for analysis
    results_file = os.path.join(output_dir, "bayesian_results.csv")
    results_df = pd.read_csv(results_file)
    
    # Filter to valid results only
    results_df = results_df[results_df['valid'] == True].copy()
    
    # Analysis
    print("\n" + "=" * 100)
    print("ANALYZING RESULTS")
    print("=" * 100)
    
    # Print summary
    print_results_summary(
        results_df,
        metric="profit_factor",
        min_trades=min_trades,
        top_n=10
    )
    
    # Export top configurations
    print("\n" + "=" * 100)
    print("EXPORTING RESULTS")
    print("=" * 100 + "\n")
    
    # Export top N by different metrics
    # Note: Save with custom filenames by copying after export
    export_top_n(results_df, output_dir, n=50, metric="profit_factor", min_trades=min_trades)
    
    # Rename to bayesian-specific files
    import shutil
    pf_file = os.path.join(output_dir, "sweep_results_top100.csv")
    if os.path.exists(pf_file):
        shutil.copy(pf_file, os.path.join(output_dir, "bayesian_top50_pf.csv"))
    
    # Show best setup
    print("\n" + "=" * 100)
    print("BEST CONFIGURATION FOUND")
    print("=" * 100)
    
    best = find_best_setup(results_df, metric="profit_factor", min_trades=min_trades)
    if best:
        print("\nParameters:")
        for key, value in best['parameters'].items():
            print(f"  {key}: {value}")
        
        print("\nExpected Performance:")
        for key, value in best['metrics'].items():
            if isinstance(value, float):
                print(f"  {key}: {value:.4f}")
            else:
                print(f"  {key}: {value}")
    
    print("\n" + "=" * 100)
    print("BAYESIAN OPTIMIZATION COMPLETE!")
    print("=" * 100)
    print(f"\nResults saved to: {output_dir}/")
    print("  - bayesian_results.csv           : All evaluations")
    print("  - bayesian_best_config.json      : Best configuration")
    print("  - bayesian_top50_pf.csv          : Top 50 by profit factor")
    print("  - bayesian_top50_wr.csv          : Top 50 by win rate")
    print("  - bayesian_top50_pnl.csv         : Top 50 by net PnL")
    print("\nComparison with grid search:")
    print(f"  Time saved: ~{(3840 * 7.5 - n_calls * 7.5) / 3600:.1f} hours")
    print(f"  Evaluations: {n_calls} vs 3,840 (grid search)")
    print(f"  Efficiency: {(3840 / n_calls):.1f}x faster")
    print("\n")


if __name__ == "__main__":
    main()

