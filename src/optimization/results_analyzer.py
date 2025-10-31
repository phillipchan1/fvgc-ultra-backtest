"""
Results analysis and ranking
"""
import pandas as pd
import json
import os
from typing import Dict, Optional


def rank_results(
    results_df: pd.DataFrame,
    metric: str = "profit_factor",
    min_trades: int = 30,
    ascending: bool = False
) -> pd.DataFrame:
    """
    Rank results by specified metric.
    
    Args:
        results_df: Results DataFrame
        metric: Metric to rank by
        min_trades: Minimum trades threshold
        ascending: Sort order
    
    Returns:
        Ranked DataFrame
    """
    # Filter by minimum trades
    df = results_df[results_df['total_trades'] >= min_trades].copy()
    
    # Sort by metric
    df = df.sort_values(metric, ascending=ascending)
    
    # Add rank column
    df['rank'] = range(1, len(df) + 1)
    
    return df


def find_best_setup(
    results_df: pd.DataFrame,
    metric: str = "profit_factor",
    min_trades: int = 30
) -> Dict:
    """
    Find the single best parameter setup.
    
    Args:
        results_df: Results DataFrame
        metric: Metric to optimize for
        min_trades: Minimum trades threshold
    
    Returns:
        Dictionary with best setup parameters and metrics
    """
    # Filter and find best
    df = results_df[results_df['total_trades'] >= min_trades].copy()
    
    if len(df) == 0:
        print(f"Warning: No setups with >= {min_trades} trades")
        return {}
    
    best_idx = df[metric].idxmax()
    best_row = df.loc[best_idx]
    
    # Extract parameters and metrics
    param_cols = [
        'entry_model', 'gap_closure_filter', 'gap_size_range',
        'time_window', 'touch_range', 'trade_management'
    ]
    
    metric_cols = [
        'total_trades', 'winning_trades', 'losing_trades', 'win_rate',
        'net_pnl', 'gross_profit', 'gross_loss', 'profit_factor',
        'avg_win', 'avg_loss', 'sharpe_ratio'
    ]
    
    best_setup = {
        'parameters': {col: best_row[col] for col in param_cols if col in best_row},
        'metrics': {col: best_row[col] for col in metric_cols if col in best_row}
    }
    
    return best_setup


def compare_to_baseline(
    results_df: pd.DataFrame,
    baseline_params: Dict,
    min_trades: int = 30
) -> pd.DataFrame:
    """
    Compare all results to a baseline configuration.
    
    Args:
        results_df: Results DataFrame
        baseline_params: Dictionary with baseline parameter values
        min_trades: Minimum trades threshold
    
    Returns:
        DataFrame with improvement metrics
    """
    # Filter
    df = results_df[results_df['total_trades'] >= min_trades].copy()
    
    # Find baseline row
    baseline_mask = pd.Series([True] * len(df))
    for param, value in baseline_params.items():
        if param in df.columns:
            baseline_mask &= (df[param] == value)
    
    baseline_row = df[baseline_mask]
    
    if len(baseline_row) == 0:
        print("Warning: Baseline configuration not found in results")
        return df
    
    baseline_metrics = baseline_row.iloc[0]
    
    # Calculate improvements
    df['wr_improvement'] = df['win_rate'] - baseline_metrics['win_rate']
    df['pf_improvement'] = df['profit_factor'] - baseline_metrics['profit_factor']
    df['net_improvement'] = df['net_pnl'] - baseline_metrics['net_pnl']
    
    return df


def export_top_n(
    results_df: pd.DataFrame,
    output_dir: str,
    n: int = 100,
    metric: str = "profit_factor",
    min_trades: int = 30
):
    """
    Export top N configurations to CSV.
    
    Args:
        results_df: Results DataFrame
        output_dir: Output directory
        n: Number of top results
        metric: Metric to rank by
        min_trades: Minimum trades threshold
    """
    # Rank and filter
    ranked = rank_results(results_df, metric=metric, min_trades=min_trades)
    top_n_df = ranked.head(n)
    
    # Save to CSV
    output_file = os.path.join(output_dir, f"sweep_results_top{n}.csv")
    top_n_df.to_csv(output_file, index=False)
    
    print(f"Saved top {n} results to: {output_file}")
    
    return output_file


def export_best_config(
    results_df: pd.DataFrame,
    output_dir: str,
    metric: str = "profit_factor",
    min_trades: int = 30
):
    """
    Export the best configuration as a JSON config file.
    
    Args:
        results_df: Results DataFrame
        output_dir: Output directory
        metric: Metric to optimize for
        min_trades: Minimum trades threshold
    """
    best_setup = find_best_setup(results_df, metric=metric, min_trades=min_trades)
    
    if not best_setup:
        print("No best setup found")
        return None
    
    # Convert numpy types to Python native types for JSON serialization
    def convert_to_native(obj):
        """Convert numpy/pandas types to Python native types"""
        import numpy as np
        if isinstance(obj, dict):
            return {k: convert_to_native(v) for k, v in obj.items()}
        elif isinstance(obj, (np.integer, np.int64, np.int32)):
            return int(obj)
        elif isinstance(obj, (np.floating, np.float64, np.float32)):
            return float(obj)
        elif isinstance(obj, (np.bool_,)):
            return bool(obj)
        else:
            return obj
    
    # Convert to config format
    config_data = {
        "description": f"Best configuration optimized for {metric}",
        "parameters": convert_to_native(best_setup['parameters']),
        "expected_performance": convert_to_native(best_setup['metrics'])
    }
    
    # Save to JSON
    output_file = os.path.join(output_dir, "config_best_setup.json")
    with open(output_file, 'w') as f:
        json.dump(config_data, f, indent=2)
    
    print(f"Saved best config to: {output_file}")
    
    return output_file


def print_results_summary(
    results_df: pd.DataFrame,
    metric: str = "profit_factor",
    min_trades: int = 30,
    top_n: int = 10
):
    """
    Print formatted summary of results.
    
    Args:
        results_df: Results DataFrame
        metric: Primary metric for ranking
        min_trades: Minimum trades threshold
        top_n: Number of top results to show
    """
    # Filter
    df = results_df[results_df['total_trades'] >= min_trades].copy()
    
    # Overall stats
    total_combinations = len(results_df)
    valid_combinations = len(df)
    profitable = len(df[df['profit_factor'] > 1.0])
    
    print("\n" + "=" * 100)
    print("PARAMETER SWEEP RESULTS SUMMARY")
    print("=" * 100)
    print(f"\nTotal Combinations Tested: {total_combinations:,}")
    print(f"Valid Combinations (>= {min_trades} trades): {valid_combinations:,} ({valid_combinations/total_combinations*100:.1f}%)")
    print(f"Profitable Combinations (PF > 1.0): {profitable:,} ({profitable/valid_combinations*100:.1f}%)")
    
    # Top results
    print(f"\n" + "=" * 100)
    print(f"TOP {top_n} SETUPS BY {metric.upper().replace('_', ' ')}")
    print("=" * 100)
    
    ranked = rank_results(df, metric=metric, min_trades=min_trades)
    top = ranked.head(top_n)
    
    print(f"\n{'Rank':<6} {'Entry':<8} {'Gap':<8} {'Size':<10} {'Time':<12} "
          f"{'Touch':<8} {'TM':<12} {'Trades':<8} {'WR':<8} {'PF':<8} {'Net':<10}")
    print("-" * 100)
    
    for _, row in top.iterrows():
        print(f"{int(row['rank']):<6} "
              f"{row['entry_model']:<8} "
              f"{row['gap_closure_filter']:<8} "
              f"{row['gap_size_range']:<10} "
              f"{row['time_window']:<12} "
              f"{row['touch_range']:<8} "
              f"{row['trade_management']:<12} "
              f"{int(row['total_trades']):<8} "
              f"{row['win_rate']*100:>6.1f}% "
              f"{row['profit_factor']:>7.3f} "
              f"{row['net_pnl']:>+9.2f}")
    
    print("\n")


def generate_summary_report(
    results_df: pd.DataFrame,
    output_dir: str,
    min_trades: int = 30
):
    """
    Generate comprehensive summary report.
    
    Args:
        results_df: Results DataFrame
        output_dir: Output directory
        min_trades: Minimum trades threshold
    """
    report_file = os.path.join(output_dir, "optimization_report.txt")
    
    with open(report_file, 'w') as f:
        f.write("=" * 100 + "\n")
        f.write("PARAMETER OPTIMIZATION REPORT\n")
        f.write("=" * 100 + "\n\n")
        
        # Overall statistics
        df = results_df[results_df['total_trades'] >= min_trades]
        
        f.write(f"Total Combinations: {len(results_df):,}\n")
        f.write(f"Valid Combinations (>= {min_trades} trades): {len(df):,}\n")
        f.write(f"Profitable Combinations: {len(df[df['profit_factor'] > 1.0]):,}\n\n")
        
        # Best by each metric
        metrics = ['profit_factor', 'win_rate', 'net_pnl', 'sharpe_ratio']
        
        for metric in metrics:
            f.write(f"\nBest by {metric}:\n")
            f.write("-" * 80 + "\n")
            
            best = find_best_setup(results_df, metric=metric, min_trades=min_trades)
            if best:
                f.write(f"Parameters: {json.dumps(best['parameters'], indent=2)}\n")
                f.write(f"Metrics: {json.dumps(best['metrics'], indent=2)}\n")
        
    print(f"Summary report saved to: {report_file}")
    
    return report_file

