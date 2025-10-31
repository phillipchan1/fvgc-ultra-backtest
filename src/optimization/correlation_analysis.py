"""
Correlation analysis to determine variable importance
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Tuple


def analyze_variable_importance(
    results_df: pd.DataFrame,
    target_metric: str = "win_rate",
    min_trades: int = 30
) -> pd.DataFrame:
    """
    Analyze which variables have the strongest impact on performance.
    
    Args:
        results_df: DataFrame with sweep results
        target_metric: Metric to analyze ('win_rate', 'profit_factor', 'net_pnl')
        min_trades: Minimum trades required for analysis
    
    Returns:
        DataFrame with variable importance rankings
    """
    # Filter to combinations with enough trades
    df = results_df[results_df['total_trades'] >= min_trades].copy()
    
    if len(df) == 0:
        print(f"Warning: No combinations with >= {min_trades} trades")
        return pd.DataFrame()
    
    print(f"\nAnalyzing {len(df)} combinations with >= {min_trades} trades")
    print(f"Target metric: {target_metric}")
    print("=" * 80)
    
    # Analyze each variable
    variables = [
        'entry_model',
        'gap_closure_filter', 
        'gap_size_range',
        'time_window',
        'touch_range',
        'trade_management'
    ]
    
    importance_results = []
    
    for var in variables:
        var_importance = analyze_single_variable(df, var, target_metric)
        importance_results.extend(var_importance)
    
    # Convert to DataFrame and sort
    importance_df = pd.DataFrame(importance_results)
    importance_df = importance_df.sort_values('impact', ascending=False)
    
    return importance_df


def analyze_single_variable(
    df: pd.DataFrame,
    variable: str,
    target_metric: str
) -> List[Dict]:
    """
    Analyze impact of a single variable on target metric.
    
    Args:
        df: Results DataFrame
        variable: Variable name to analyze
        target_metric: Target metric to measure impact on
    
    Returns:
        List of dicts with variable value and impact
    """
    results = []
    
    # Calculate baseline (overall average)
    baseline = df[target_metric].mean()
    
    # Group by variable value
    for value in df[variable].unique():
        subset = df[df[variable] == value]
        
        if len(subset) == 0:
            continue
        
        mean_metric = subset[target_metric].mean()
        median_metric = subset[target_metric].median()
        std_metric = subset[target_metric].std()
        count = len(subset)
        
        # Calculate impact (difference from baseline)
        impact = mean_metric - baseline
        impact_pct = (impact / baseline * 100) if baseline != 0 else 0
        
        results.append({
            'variable': variable,
            'value': value,
            'mean': mean_metric,
            'median': median_metric,
            'std': std_metric,
            'count': count,
            'impact': impact,
            'impact_pct': impact_pct,
            'baseline': baseline
        })
    
    return results


def generate_correlation_matrix(
    results_df: pd.DataFrame,
    min_trades: int = 30
) -> pd.DataFrame:
    """
    Generate correlation matrix between variables and metrics.
    
    Args:
        results_df: Results DataFrame
        min_trades: Minimum trades threshold
    
    Returns:
        Correlation matrix DataFrame
    """
    # Filter
    df = results_df[results_df['total_trades'] >= min_trades].copy()
    
    # Encode categorical variables
    categorical_vars = [
        'entry_model', 'gap_closure_filter', 'gap_size_range',
        'time_window', 'touch_range', 'trade_management'
    ]
    
    for var in categorical_vars:
        df[f'{var}_encoded'] = pd.Categorical(df[var]).codes
    
    # Select columns for correlation
    encoded_cols = [f'{var}_encoded' for var in categorical_vars]
    metric_cols = ['win_rate', 'profit_factor', 'net_pnl', 'sharpe_ratio']
    
    correlation_df = df[encoded_cols + metric_cols].corr()
    
    # Extract just the correlations between variables and metrics
    result = correlation_df.loc[encoded_cols, metric_cols]
    result.index = categorical_vars  # Rename for readability
    
    return result


def find_best_combinations(
    results_df: pd.DataFrame,
    metric: str = "profit_factor",
    top_n: int = 10,
    min_trades: int = 30
) -> pd.DataFrame:
    """
    Find best parameter combinations by metric.
    
    Args:
        results_df: Results DataFrame
        metric: Metric to rank by
        top_n: Number of top results to return
        min_trades: Minimum trades threshold
    
    Returns:
        DataFrame with top combinations
    """
    # Filter and sort
    df = results_df[results_df['total_trades'] >= min_trades].copy()
    df = df.sort_values(metric, ascending=False).head(top_n)
    
    return df


def print_variable_importance(importance_df: pd.DataFrame):
    """Print formatted variable importance report"""
    print("\n" + "=" * 80)
    print("VARIABLE IMPORTANCE ANALYSIS")
    print("=" * 80)
    
    print(f"\nTop Variable Impacts (sorted by absolute impact):")
    print("-" * 80)
    print(f"{'Variable':<25} {'Value':<20} {'Impact':>12} {'Mean':>10} {'Count':>8}")
    print("-" * 80)
    
    for _, row in importance_df.head(20).iterrows():
        impact_str = f"{row['impact']:+.4f}"
        if 'win_rate' in str(row.get('variable', '')).lower():
            impact_str = f"{row['impact']*100:+.2f}%"
        
        print(f"{row['variable']:<25} {str(row['value']):<20} "
              f"{impact_str:>12} {row['mean']:>10.4f} {row['count']:>8}")
    
    print("\n")


def generate_interaction_analysis(
    results_df: pd.DataFrame,
    var1: str,
    var2: str,
    metric: str = "profit_factor",
    min_trades: int = 30
) -> pd.DataFrame:
    """
    Analyze interaction between two variables.
    
    Args:
        results_df: Results DataFrame
        var1: First variable
        var2: Second variable
        metric: Metric to analyze
        min_trades: Minimum trades threshold
    
    Returns:
        Pivot table showing interaction
    """
    df = results_df[results_df['total_trades'] >= min_trades].copy()
    
    pivot = df.pivot_table(
        values=metric,
        index=var1,
        columns=var2,
        aggfunc='mean'
    )
    
    return pivot

