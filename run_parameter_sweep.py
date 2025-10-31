#!/usr/bin/env python3
"""
Main script to run parameter optimization sweep
"""
import os
import sys

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.optimization.parameter_sweep import run_parameter_sweep, ParameterGrid
from src.optimization.correlation_analysis import (
    analyze_variable_importance,
    print_variable_importance,
    generate_correlation_matrix,
    generate_interaction_analysis
)
from src.optimization.results_analyzer import (
    print_results_summary,
    export_top_n,
    export_best_config,
    generate_summary_report,
    find_best_setup
)


def main():
    """Run full parameter optimization"""
    
    print("\n" + "=" * 100)
    print("PARAMETER OPTIMIZATION SWEEP")
    print("=" * 100)
    print("\nThis will test all combinations of:")
    print("  - Entry Models: noFVG, BOS, iFVG, ALL")
    print("  - Gap Closure: True, False, ALL")
    print("  - Gap Size: 0-3, 3-6, 6-10, 10+, ALL")
    print("  - Time Windows: 9:30-9:45, 9:45-10:00, 10:00-10:15, ALL")
    print("  - Touch Ranges: 1-2, 3-4, 5+, ALL")
    print("  - Trade Management: fixed, dynamic_fvg, partial_close, trailing_sl")
    
    # Show estimate
    grid = ParameterGrid()
    print(f"\nTotal combinations: {grid.total_combinations:,}")
    print(f"Estimated runtime: {grid.estimate_runtime()}")
    print(f"\nData will be tested on full 2+ year dataset")
    print("\n" + "=" * 100)
    
    # Confirm
    response = input("\nProceed with parameter sweep? (yes/no): ")
    if response.lower() not in ['yes', 'y']:
        print("Cancelled.")
        return
    
    # Run sweep
    data_path = os.path.join("data", "processed", "data_30s.csv")
    output_dir = "outputs/optimization"
    
    print("\nStarting parameter sweep...")
    print("(This will take several hours - progress will be shown)\n")
    
    results_df = run_parameter_sweep(
        data_path=data_path,
        output_dir=output_dir,
        resume=True,
        parallel=False
    )
    
    # Analyze results
    print("\n" + "=" * 100)
    print("ANALYZING RESULTS")
    print("=" * 100)
    
    min_trades = 30  # Minimum trades for statistical validity
    
    # Print summary
    print_results_summary(
        results_df,
        metric="profit_factor",
        min_trades=min_trades,
        top_n=10
    )
    
    # Variable importance analysis
    print("\n" + "=" * 100)
    print("VARIABLE IMPORTANCE ANALYSIS")
    print("=" * 100)
    
    for metric in ['win_rate', 'profit_factor', 'net_pnl']:
        print(f"\n### Impact on {metric.upper().replace('_', ' ')} ###\n")
        importance_df = analyze_variable_importance(
            results_df,
            target_metric=metric,
            min_trades=min_trades
        )
        
        if not importance_df.empty:
            print_variable_importance(importance_df)
            
            # Save to CSV
            importance_file = os.path.join(output_dir, f"variable_importance_{metric}.csv")
            importance_df.to_csv(importance_file, index=False)
            print(f"Saved to: {importance_file}")
    
    # Export top configurations
    print("\n" + "=" * 100)
    print("EXPORTING RESULTS")
    print("=" * 100 + "\n")
    
    export_top_n(results_df, output_dir, n=100, metric="profit_factor", min_trades=min_trades)
    export_top_n(results_df, output_dir, n=50, metric="win_rate", min_trades=min_trades)
    
    # Export best config
    export_best_config(results_df, output_dir, metric="profit_factor", min_trades=min_trades)
    
    # Generate report
    generate_summary_report(results_df, output_dir, min_trades=min_trades)
    
    # Show best setup
    print("\n" + "=" * 100)
    print("BEST CONFIGURATION")
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
    print("OPTIMIZATION COMPLETE!")
    print("=" * 100)
    print(f"\nAll results saved to: {output_dir}/")
    print("  - sweep_results_full.csv      : All combinations")
    print("  - sweep_results_top100.csv    : Top 100 by profit factor")
    print("  - variable_importance_*.csv   : Variable impact analysis")
    print("  - config_best_setup.json      : Best configuration")
    print("  - optimization_report.txt     : Summary report")
    print("\n")


if __name__ == "__main__":
    main()

