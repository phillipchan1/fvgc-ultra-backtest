#!/usr/bin/env python3
"""
Fast post-hoc analysis of baseline results
Applies all filter combinations to pre-computed trades
"""
import os
import sys
import pandas as pd
import itertools
import time
from dataclasses import dataclass, asdict
from typing import List, Dict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.optimization.correlation_analysis import (
    analyze_variable_importance,
    print_variable_importance,
    generate_correlation_matrix
)
from src.optimization.results_analyzer import (
    print_results_summary,
    export_top_n,
    export_best_config,
    find_best_setup
)


@dataclass
class FilterSet:
    """Represents a filter combination"""
    entry_model: str
    gap_closure: str
    gap_size_range: str
    time_window: str
    touch_range: str
    engulfing_distance: str
    multiple_entries: str
    volume_tier: str
    range_tier: str
    red_folder: str
    trade_management: str


def generate_filter_combinations() -> List[FilterSet]:
    """Generate all filter combinations"""
    entry_models = ["noFVG", "BOS", "iFVG", "ALL"]
    gap_closures = ["True", "False", "ALL"]
    gap_sizes = ["0-3", "3-6", "6-10", "10+", "ALL"]
    time_windows = ["9:30-9:45", "9:45-10:00", "10:00-10:15", "ALL"]
    touch_ranges = ["1-2", "3-4", "5+", "ALL"]
    engulfing_distances = ["0-3", "3-6", "6+", "ALL"]
    multiple_entries_opts = ["True", "False", "ALL"]
    volume_tiers = ["Low", "Medium", "High", "Extremely High", "ALL"]  # NEW
    range_tiers = ["<75pts", "75-150pts", "150+pts", "ALL"]  # NEW
    red_folder_opts = ["True", "False", "ALL"]  # NEW
    
    combinations = itertools.product(
        entry_models, gap_closures, gap_sizes, time_windows, touch_ranges,
        engulfing_distances, multiple_entries_opts, volume_tiers, range_tiers, red_folder_opts
    )
    
    filter_sets = []
    for combo in combinations:
        fs = FilterSet(
            entry_model=combo[0],
            gap_closure=combo[1],
            gap_size_range=combo[2],
            time_window=combo[3],
            touch_range=combo[4],
            engulfing_distance=combo[5],
            multiple_entries=combo[6],
            volume_tier=combo[7],
            range_tier=combo[8],
            red_folder=combo[9],
            trade_management="placeholder"  # Will be set per TM strategy
        )
        filter_sets.append(fs)
    
    return filter_sets


def apply_filters(trades_df: pd.DataFrame, filter_set: FilterSet) -> pd.DataFrame:
    """Apply filter set to trades DataFrame"""
    df = trades_df.copy()
    
    # Filter by entry model
    if filter_set.entry_model != "ALL":
        model_map = {
            "noFVG": "fvg_continuation_no_fvg",
            "BOS": "fvg_continuation_bos",
            "iFVG": "fvg_continuation_ifvg"
        }
        target_model = model_map.get(filter_set.entry_model)
        if target_model:
            df = df[df['entry_model'] == target_model]
    
    # Filter by gap closure
    if filter_set.gap_closure != "ALL" and 'retraced_closed_in_gap' in df.columns:
        target_value = (filter_set.gap_closure == "True")
        df = df[df['retraced_closed_in_gap'] == target_value]
    
    # Filter by gap size
    if filter_set.gap_size_range != "ALL" and 'fvg_size_pts' in df.columns:
        if filter_set.gap_size_range == "0-3":
            df = df[df['fvg_size_pts'] <= 3.0]
        elif filter_set.gap_size_range == "3-6":
            df = df[(df['fvg_size_pts'] > 3.0) & (df['fvg_size_pts'] <= 6.0)]
        elif filter_set.gap_size_range == "6-10":
            df = df[(df['fvg_size_pts'] > 6.0) & (df['fvg_size_pts'] <= 10.0)]
        elif filter_set.gap_size_range == "10+":
            df = df[df['fvg_size_pts'] > 10.0]
    
    # Filter by time window
    if filter_set.time_window != "ALL" and 'entry_time' in df.columns:
        df['entry_time'] = pd.to_datetime(df['entry_time'])
        entry_times = df['entry_time'].dt.time
        
        if filter_set.time_window == "9:30-9:45":
            start = pd.to_datetime("09:30:00").time()
            end = pd.to_datetime("09:45:00").time()
            df = df[(entry_times >= start) & (entry_times < end)]
        elif filter_set.time_window == "9:45-10:00":
            start = pd.to_datetime("09:45:00").time()
            end = pd.to_datetime("10:00:00").time()
            df = df[(entry_times >= start) & (entry_times < end)]
        elif filter_set.time_window == "10:00-10:15":
            start = pd.to_datetime("10:00:00").time()
            end = pd.to_datetime("10:15:00").time()
            df = df[(entry_times >= start) & (entry_times <= end)]
    
    # Filter by touch range
    if filter_set.touch_range != "ALL" and 'fvg_touch_count' in df.columns:
        if filter_set.touch_range == "1-2":
            df = df[(df['fvg_touch_count'] >= 1) & (df['fvg_touch_count'] <= 2)]
        elif filter_set.touch_range == "3-4":
            df = df[(df['fvg_touch_count'] >= 3) & (df['fvg_touch_count'] <= 4)]
        elif filter_set.touch_range == "5+":
            df = df[df['fvg_touch_count'] >= 5]
    
    # Filter by engulfing distance
    if filter_set.engulfing_distance != "ALL" and 'engulfing_distance_pts' in df.columns:
        if filter_set.engulfing_distance == "0-3":
            df = df[(df['engulfing_distance_pts'] >= 0) & (df['engulfing_distance_pts'] <= 3.0)]
        elif filter_set.engulfing_distance == "3-6":
            df = df[(df['engulfing_distance_pts'] > 3.0) & (df['engulfing_distance_pts'] <= 6.0)]
        elif filter_set.engulfing_distance == "6+":
            df = df[df['engulfing_distance_pts'] > 6.0]
    
    # Filter by multiple entries per FVG
    if filter_set.multiple_entries != "ALL" and 'fvg_id' in df.columns:
        if filter_set.multiple_entries == "False":
            # Simulate single entry only: keep first trade per FVG
            df = df.sort_values('entry_time').groupby('fvg_id').first().reset_index()
        # If "True", keep all trades (no filtering needed)
    
    # Filter by volume tier
    if filter_set.volume_tier != "ALL" and 'session_volume_tier' in df.columns:
        df = df[df['session_volume_tier'] == filter_set.volume_tier]
    
    # Filter by range tier
    if filter_set.range_tier != "ALL" and 'session_range_tier' in df.columns:
        df = df[df['session_range_tier'] == filter_set.range_tier]
    
    # Filter by red folder
    if filter_set.red_folder != "ALL" and 'is_red_folder_day' in df.columns:
        if filter_set.red_folder == "True":
            df = df[df['is_red_folder_day'] == True]
        elif filter_set.red_folder == "False":
            df = df[df['is_red_folder_day'] == False]
    
    return df


def calculate_metrics(trades_df: pd.DataFrame) -> Dict:
    """Calculate performance metrics"""
    if len(trades_df) == 0:
        return {
            'total_trades': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'win_rate': 0.0,
            'net_pnl': 0.0,
            'gross_profit': 0.0,
            'gross_loss': 0.0,
            'profit_factor': 0.0,
            'avg_win': 0.0,
            'avg_loss': 0.0,
            'sharpe_ratio': 0.0
        }
    
    total_trades = len(trades_df)
    winning_trades = len(trades_df[trades_df['pnl'] > 0])
    losing_trades = len(trades_df[trades_df['pnl'] < 0])
    win_rate = winning_trades / total_trades if total_trades > 0 else 0.0
    
    gross_profit = trades_df[trades_df['pnl'] > 0]['pnl'].sum() if winning_trades > 0 else 0.0
    gross_loss = abs(trades_df[trades_df['pnl'] < 0]['pnl'].sum()) if losing_trades > 0 else 0.0
    net_pnl = trades_df['pnl'].sum()
    
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else (gross_profit if gross_profit > 0 else 0.0)
    avg_win = gross_profit / winning_trades if winning_trades > 0 else 0.0
    avg_loss = gross_loss / losing_trades if losing_trades > 0 else 0.0
    
    # Sharpe-like ratio
    pnl_std = trades_df['pnl'].std() if total_trades > 1 else 1.0
    sharpe_ratio = net_pnl / pnl_std if pnl_std > 0 else 0.0
    
    return {
        'total_trades': total_trades,
        'winning_trades': winning_trades,
        'losing_trades': losing_trades,
        'win_rate': win_rate,
        'net_pnl': net_pnl,
        'gross_profit': gross_profit,
        'gross_loss': gross_loss,
        'profit_factor': profit_factor,
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'sharpe_ratio': sharpe_ratio
    }


def main():
    """Run fast post-hoc analysis"""
    print("\n" + "="*80)
    print("FAST POST-HOC OPTIMIZATION ANALYSIS")
    print("="*80)
    
    # Load baseline trades
    baseline_dir = "outputs/baseline"
    strategies = ["fixed", "dynamic_fvg", "partial_close", "trailing_sl"]
    
    print("\nLoading baseline trades...")
    baseline_trades = {}
    for strategy in strategies:
        filepath = os.path.join(baseline_dir, f"trades_{strategy}.csv")
        if not os.path.exists(filepath):
            print(f"ERROR: {filepath} not found!")
            print("Run 'python run_baseline_backtests.py' first")
            return
        
        df = pd.read_csv(filepath)
        baseline_trades[strategy] = df
        print(f"  {strategy:<20}: {len(df):>5} trades")
    
    # Generate filter combinations
    print("\nGenerating filter combinations...")
    filter_sets = generate_filter_combinations()
    print(f"Total filter combinations: {len(filter_sets)}")
    print(f"Total tests (4 TM × {len(filter_sets)} filters): {4 * len(filter_sets)}")
    
    # Run analysis (sequential - faster than multiprocessing for this case)
    print("\nApplying filters...")
    print("(Note: Sequential processing is fastest for DataFrame filtering)")
    start_time = time.time()
    
    results = []
    total_tests = len(strategies) * len(filter_sets)
    
    for strategy in strategies:
        trades_df = baseline_trades[strategy]
        
        print(f"\nProcessing {strategy} strategy ({len(filter_sets):,} combinations)...")
        
        for idx, filter_set in enumerate(filter_sets, 1):
            # Apply filters
            filtered = apply_filters(trades_df, filter_set)
            
            # Calculate metrics
            metrics = calculate_metrics(filtered)
            
            # Store result
            result = {
                'entry_model': filter_set.entry_model,
                'gap_closure_filter': filter_set.gap_closure,
                'gap_size_range': filter_set.gap_size_range,
                'time_window': filter_set.time_window,
                'touch_range': filter_set.touch_range,
                'engulfing_distance': filter_set.engulfing_distance,
                'multiple_entries_per_fvg': filter_set.multiple_entries,
                'volume_tier': filter_set.volume_tier,
                'range_tier': filter_set.range_tier,
                'red_folder': filter_set.red_folder,
                'trade_management': strategy
            }
            result.update(metrics)
            results.append(result)
            
            # Progress update every 10000 combinations
            if idx % 10000 == 0 or idx == 1:
                progress = (strategies.index(strategy) * len(filter_sets) + idx) / total_tests * 100
                elapsed_so_far = time.time() - start_time
                est_total = elapsed_so_far / progress * 100 if progress > 0 else 0
                est_remaining = est_total - elapsed_so_far
                print(f"  [{progress:>5.1f}%] {idx:,}/{len(filter_sets):,} "
                      f"(elapsed: {elapsed_so_far/60:.1f}m, remaining: ~{est_remaining/60:.1f}m)")
    
    elapsed = time.time() - start_time
    
    # Convert to DataFrame
    results_df = pd.DataFrame(results)
    
    # Save results
    output_dir = "outputs/optimization"
    os.makedirs(output_dir, exist_ok=True)
    
    results_file = os.path.join(output_dir, "sweep_results_full.csv")
    results_df.to_csv(results_file, index=False)
    
    print(f"\nFiltering complete in {elapsed:.1f} seconds")
    print(f"Results saved to: {results_file}")
    
    # Analysis
    print("\n" + "="*80)
    print("RESULTS ANALYSIS")
    print("="*80)
    
    min_trades = 30
    
    # Print summary
    print_results_summary(
        results_df,
        metric="profit_factor",
        min_trades=min_trades,
        top_n=10
    )
    
    # Variable importance
    print("\n" + "="*80)
    print("VARIABLE IMPORTANCE ANALYSIS")
    print("="*80)
    
    for metric in ['win_rate', 'profit_factor', 'net_pnl']:
        print(f"\n### Impact on {metric.upper().replace('_', ' ')} ###")
        importance_df = analyze_variable_importance(
            results_df,
            target_metric=metric,
            min_trades=min_trades
        )
        
        if not importance_df.empty:
            print_variable_importance(importance_df)
            
            # Save
            importance_file = os.path.join(output_dir, f"variable_importance_{metric}.csv")
            importance_df.to_csv(importance_file, index=False)
    
    # Export top configs
    print("\n" + "="*80)
    print("EXPORTING RESULTS")
    print("="*80 + "\n")
    
    export_top_n(results_df, output_dir, n=100, metric="profit_factor", min_trades=min_trades)
    export_top_n(results_df, output_dir, n=50, metric="win_rate", min_trades=min_trades)
    export_best_config(results_df, output_dir, metric="profit_factor", min_trades=min_trades)
    
    # Show best setup
    print("\n" + "="*80)
    print("BEST CONFIGURATION")
    print("="*80)
    
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
    
    print("\n" + "="*80)
    print("ANALYSIS COMPLETE!")
    print("="*80)
    print(f"\nResults saved to: {output_dir}/")
    print("  - sweep_results_full.csv")
    print("  - sweep_results_top100.csv")
    print("  - variable_importance_*.csv")
    print("  - config_best_setup.json")
    print("\n")


if __name__ == "__main__":
    main()

