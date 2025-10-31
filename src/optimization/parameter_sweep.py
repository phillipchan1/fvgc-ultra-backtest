"""
Parameter sweep framework for optimization
"""
import itertools
import pandas as pd
import time
from typing import Dict, List, Any
from dataclasses import dataclass, asdict
import json
import os


@dataclass
class ParameterSet:
    """Represents a single parameter configuration"""
    entry_model: str
    gap_closure_filter: str  # "True", "False", "ALL"
    gap_size_range: str      # "0-3", "3-6", "6-10", "10+", "ALL"
    time_window: str         # "9:30-9:45", "9:45-10:00", "10:00-10:15", "ALL"
    touch_range: str         # "1-2", "3-4", "5+", "ALL"
    trade_management: str    # "fixed", "dynamic_fvg", "partial_close", "trailing_sl"


class ParameterGrid:
    """Generates all parameter combinations for testing"""
    
    # Define the parameter space
    ENTRY_MODELS = ["noFVG", "BOS", "iFVG", "ALL"]
    GAP_CLOSURE = ["True", "False", "ALL"]
    GAP_SIZE_RANGES = ["0-3", "3-6", "6-10", "10+", "ALL"]
    TIME_WINDOWS = ["9:30-9:45", "9:45-10:00", "10:00-10:15", "ALL"]
    TOUCH_RANGES = ["1-2", "3-4", "5+", "ALL"]
    TRADE_MANAGEMENT = ["fixed", "dynamic_fvg", "partial_close", "trailing_sl"]
    
    def __init__(self):
        self.total_combinations = (
            len(self.ENTRY_MODELS) * 
            len(self.GAP_CLOSURE) * 
            len(self.GAP_SIZE_RANGES) * 
            len(self.TIME_WINDOWS) * 
            len(self.TOUCH_RANGES) * 
            len(self.TRADE_MANAGEMENT)
        )
    
    def generate_all(self) -> List[ParameterSet]:
        """Generate all parameter combinations"""
        combinations = itertools.product(
            self.ENTRY_MODELS,
            self.GAP_CLOSURE,
            self.GAP_SIZE_RANGES,
            self.TIME_WINDOWS,
            self.TOUCH_RANGES,
            self.TRADE_MANAGEMENT
        )
        
        param_sets = []
        for combo in combinations:
            param_set = ParameterSet(
                entry_model=combo[0],
                gap_closure_filter=combo[1],
                gap_size_range=combo[2],
                time_window=combo[3],
                touch_range=combo[4],
                trade_management=combo[5]
            )
            param_sets.append(param_set)
        
        return param_sets
    
    def estimate_runtime(self, seconds_per_test: float = 7.5) -> str:
        """Estimate total runtime for the sweep"""
        total_seconds = self.total_combinations * seconds_per_test
        hours = int(total_seconds // 3600)
        minutes = int((total_seconds % 3600) // 60)
        return f"{hours}h {minutes}m"


@dataclass
class SweepResult:
    """Results from a single parameter configuration test"""
    # Parameters
    entry_model: str
    gap_closure_filter: str
    gap_size_range: str
    time_window: str
    touch_range: str
    trade_management: str
    
    # Metrics
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    net_pnl: float
    gross_profit: float
    gross_loss: float
    profit_factor: float
    avg_win: float
    avg_loss: float
    sharpe_ratio: float
    
    # Metadata
    runtime_seconds: float
    timestamp: str


def run_parameter_sweep(
    data_path: str,
    output_dir: str = "outputs/optimization",
    resume: bool = True,
    parallel: bool = False
) -> pd.DataFrame:
    """
    Run full parameter sweep across all combinations.
    
    Args:
        data_path: Path to processed data CSV
        output_dir: Directory to save results
        resume: Whether to resume from cached results
        parallel: Whether to use parallel processing (TODO)
    
    Returns:
        DataFrame with all results
    """
    from .config_generator import generate_test_config
    from ..core.data_loader import load_processed_30s_csv
    from ..core.backtest_engine import run_backtest, calculate_metrics
    
    # Create output directory
    os.makedirs(output_dir, exist_ok=True)
    results_file = os.path.join(output_dir, "sweep_results_full.csv")
    cache_file = os.path.join(output_dir, "sweep_cache.json")
    
    # Initialize parameter grid
    grid = ParameterGrid()
    param_sets = grid.generate_all()
    
    print("=" * 80)
    print("PARAMETER SWEEP")
    print("=" * 80)
    print(f"Total combinations: {grid.total_combinations}")
    print(f"Estimated runtime: {grid.estimate_runtime()}")
    print(f"Output directory: {output_dir}")
    print("")
    
    # Load cached results if resuming
    completed = set()
    results = []
    
    if resume and os.path.exists(cache_file):
        with open(cache_file, 'r') as f:
            cache_data = json.load(f)
            completed = set(tuple(d['params'].values()) for d in cache_data)
            results = cache_data
        print(f"Resuming: {len(completed)} combinations already completed")
        print("")
    
    # Load data once (will be filtered differently for each test)
    print("Loading data...")
    base_df = load_processed_30s_csv(data_path, date_filter=None)
    print(f"Loaded {len(base_df):,} bars")
    print("")
    
    # Run sweep
    start_time = time.time()
    
    for idx, param_set in enumerate(param_sets, 1):
        # Check if already completed
        param_tuple = tuple(asdict(param_set).values())
        if param_tuple in completed:
            continue
        
        # Progress update
        if idx % 10 == 0 or idx == 1:
            elapsed = time.time() - start_time
            avg_time = elapsed / max(idx - len(completed), 1)
            remaining = (grid.total_combinations - idx) * avg_time
            print(f"[{idx}/{grid.total_combinations}] {idx/grid.total_combinations*100:.1f}% | "
                  f"ETA: {remaining/60:.0f}m | Current: {param_set.entry_model}/{param_set.gap_closure_filter}/{param_set.gap_size_range}")
        
        # Run single configuration
        test_start = time.time()
        try:
            result = run_single_configuration(param_set, base_df)
            result.runtime_seconds = time.time() - test_start
            result.timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            
            # Save result
            result_dict = {'params': asdict(param_set), 'metrics': asdict(result)}
            results.append(result_dict)
            
            # Update cache periodically
            if idx % 50 == 0:
                with open(cache_file, 'w') as f:
                    json.dump(results, f)
        
        except Exception as e:
            print(f"ERROR in combination {idx}: {e}")
            continue
    
    # Save final results
    with open(cache_file, 'w') as f:
        json.dump(results, f)
    
    # Convert to DataFrame
    results_df = convert_results_to_dataframe(results)
    results_df.to_csv(results_file, index=False)
    
    total_time = time.time() - start_time
    print("")
    print("=" * 80)
    print(f"Sweep complete! Total time: {total_time/60:.1f} minutes")
    print(f"Results saved to: {results_file}")
    print("=" * 80)
    
    return results_df


def run_single_configuration(param_set: ParameterSet, base_df: pd.DataFrame) -> SweepResult:
    """
    Run backtest for a single parameter configuration.
    
    Args:
        param_set: Parameter configuration
        base_df: Full dataset DataFrame
    
    Returns:
        SweepResult with metrics
    """
    from .config_generator import generate_test_config
    from ..core.backtest_engine import run_backtest
    import numpy as np
    
    # Generate config for this test
    config = generate_test_config(param_set)
    
    # Run backtest with this config
    trades_df = run_backtest(base_df.copy(), override_config=config)
    
    # Apply post-backtest filters
    trades_df = apply_post_filters(trades_df, param_set)
    
    # Calculate metrics
    if len(trades_df) == 0:
        return SweepResult(
            entry_model=param_set.entry_model,
            gap_closure_filter=param_set.gap_closure_filter,
            gap_size_range=param_set.gap_size_range,
            time_window=param_set.time_window,
            touch_range=param_set.touch_range,
            trade_management=param_set.trade_management,
            total_trades=0,
            winning_trades=0,
            losing_trades=0,
            win_rate=0.0,
            net_pnl=0.0,
            gross_profit=0.0,
            gross_loss=0.0,
            profit_factor=0.0,
            avg_win=0.0,
            avg_loss=0.0,
            sharpe_ratio=0.0,
            runtime_seconds=0.0,
            timestamp=""
        )
    
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
    
    return SweepResult(
        entry_model=param_set.entry_model,
        gap_closure_filter=param_set.gap_closure_filter,
        gap_size_range=param_set.gap_size_range,
        time_window=param_set.time_window,
        touch_range=param_set.touch_range,
        trade_management=param_set.trade_management,
        total_trades=total_trades,
        winning_trades=winning_trades,
        losing_trades=losing_trades,
        win_rate=win_rate,
        net_pnl=net_pnl,
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        profit_factor=profit_factor,
        avg_win=avg_win,
        avg_loss=avg_loss,
        sharpe_ratio=sharpe_ratio,
        runtime_seconds=0.0,
        timestamp=""
    )


def apply_post_filters(trades_df: pd.DataFrame, param_set: ParameterSet) -> pd.DataFrame:
    """
    Apply post-backtest filters to trades.
    
    Args:
        trades_df: DataFrame of trades
        param_set: Parameter configuration
    
    Returns:
        Filtered DataFrame
    """
    import pandas as pd
    
    if len(trades_df) == 0:
        return trades_df
    
    # Filter by entry model
    if param_set.entry_model != "ALL":
        model_map = {
            "noFVG": "fvg_continuation_no_fvg",
            "BOS": "fvg_continuation_bos",
            "iFVG": "fvg_continuation_ifvg"
        }
        target_model = model_map.get(param_set.entry_model)
        if target_model:
            trades_df = trades_df[trades_df['entry_model'] == target_model]
    
    # Filter by gap closure
    if param_set.gap_closure_filter != "ALL":
        if 'retraced_closed_in_gap' in trades_df.columns:
            target_value = param_set.gap_closure_filter == "True"
            trades_df = trades_df[trades_df['retraced_closed_in_gap'] == target_value]
    
    # Filter by gap size
    if param_set.gap_size_range != "ALL" and 'fvg_size_pts' in trades_df.columns:
        if param_set.gap_size_range == "0-3":
            trades_df = trades_df[trades_df['fvg_size_pts'] <= 3.0]
        elif param_set.gap_size_range == "3-6":
            trades_df = trades_df[(trades_df['fvg_size_pts'] > 3.0) & (trades_df['fvg_size_pts'] <= 6.0)]
        elif param_set.gap_size_range == "6-10":
            trades_df = trades_df[(trades_df['fvg_size_pts'] > 6.0) & (trades_df['fvg_size_pts'] <= 10.0)]
        elif param_set.gap_size_range == "10+":
            trades_df = trades_df[trades_df['fvg_size_pts'] > 10.0]
    
    # Filter by time window
    if param_set.time_window != "ALL" and 'entry_time' in trades_df.columns:
        trades_df['entry_time'] = pd.to_datetime(trades_df['entry_time'])
        entry_times = trades_df['entry_time'].dt.time
        
        if param_set.time_window == "9:30-9:45":
            start = pd.to_datetime("09:30:00").time()
            end = pd.to_datetime("09:45:00").time()
            trades_df = trades_df[(entry_times >= start) & (entry_times < end)]
        elif param_set.time_window == "9:45-10:00":
            start = pd.to_datetime("09:45:00").time()
            end = pd.to_datetime("10:00:00").time()
            trades_df = trades_df[(entry_times >= start) & (entry_times < end)]
        elif param_set.time_window == "10:00-10:15":
            start = pd.to_datetime("10:00:00").time()
            end = pd.to_datetime("10:15:00").time()
            trades_df = trades_df[(entry_times >= start) & (entry_times <= end)]
    
    return trades_df


def convert_results_to_dataframe(results: List[Dict]) -> pd.DataFrame:
    """Convert results list to DataFrame"""
    rows = []
    for r in results:
        row = {}
        row.update(r['params'])
        row.update(r['metrics'])
        rows.append(row)
    
    return pd.DataFrame(rows)

