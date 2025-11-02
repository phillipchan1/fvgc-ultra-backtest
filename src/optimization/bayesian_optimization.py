"""
Bayesian optimization for parameter search using scikit-optimize.

This module implements a much faster alternative to grid search by using
Gaussian Process-based Bayesian optimization to intelligently sample the
parameter space.
"""
import numpy as np
import pandas as pd
import time
import json
import os
from typing import Dict, List, Any, Tuple
from dataclasses import dataclass, asdict
from skopt import gp_minimize
from skopt.space import Categorical
from skopt.utils import use_named_args


@dataclass
class BayesianResult:
    """Results from Bayesian optimization"""
    # Best parameters found
    best_params: Dict[str, Any]
    best_score: float  # Best profit factor
    
    # All evaluations
    all_params: List[Dict[str, Any]]
    all_scores: List[float]
    all_metrics: List[Dict[str, Any]]
    
    # Optimization metadata
    n_iterations: int
    total_time_seconds: float
    convergence_iteration: int  # When best score was found


class BayesianOptimizer:
    """
    Bayesian optimization for FVG backtest parameters.
    
    Uses Gaussian Process regression to model the relationship between
    parameters and performance, then intelligently samples promising regions.
    """
    
    def __init__(self, min_trades: int = 30):
        """
        Initialize Bayesian optimizer.
        
        Args:
            min_trades: Minimum trades required for valid configuration
        """
        self.min_trades = min_trades
        
        # Define search space
        self.space = [
            Categorical(["noFVG", "BOS", "iFVG", "ALL"], name="entry_model"),
            Categorical(["True", "False", "ALL"], name="gap_closure_filter"),
            Categorical(["0-3", "3-6", "6-10", "10+", "ALL"], name="gap_size_range"),
            Categorical(["9:30-9:45", "9:45-10:00", "10:00-10:15", "ALL"], name="time_window"),
            Categorical(["1-2", "3-4", "5+", "ALL"], name="touch_range"),
            Categorical(["fixed", "dynamic_fvg", "partial_close", "trailing_sl"], name="trade_management"),
            Categorical(["none", "bidirectional", "longs_only"], name="directional_filter"),
        ]
        
        self.dimension_names = [dim.name for dim in self.space]
        
        # Cache for tracking evaluations
        self.evaluation_cache = []
        self.base_df = None
        self.best_score_so_far = -np.inf
        self.best_params_so_far = None
        self.iteration = 0
        
    def _params_to_dict(self, params: List) -> Dict[str, Any]:
        """Convert parameter list to named dictionary."""
        return {name: value for name, value in zip(self.dimension_names, params)}
    
    def _objective_function(self, params: List) -> float:
        """
        Objective function for optimization.
        
        Args:
            params: List of parameter values in order of self.space
        
        Returns:
            Negative profit factor (for minimization)
        """
        from ..optimization.parameter_sweep import run_single_configuration, ParameterSet
        
        self.iteration += 1
        
        # Convert to parameter dict
        param_dict = self._params_to_dict(params)
        
        # Create ParameterSet
        param_set = ParameterSet(
            entry_model=param_dict["entry_model"],
            gap_closure_filter=param_dict["gap_closure_filter"],
            gap_size_range=param_dict["gap_size_range"],
            time_window=param_dict["time_window"],
            touch_range=param_dict["touch_range"],
            trade_management=param_dict["trade_management"]
        )
        
        # Generate config with directional filter
        from ..optimization.config_generator import generate_test_config
        config = generate_test_config(param_set)
        config['directional_filter'] = param_dict["directional_filter"]
        
        # Run backtest
        start_time = time.time()
        try:
            from ..core.backtest_engine import run_backtest
            trades_df = run_backtest(self.base_df.copy(), override_config=config)
            
            # Apply post-filters
            from ..optimization.parameter_sweep import apply_post_filters
            trades_df = apply_post_filters(trades_df, param_set)
            
            # Calculate metrics
            if len(trades_df) < self.min_trades:
                # Penalize configurations with too few trades
                score = -999.0
                metrics = {
                    'total_trades': len(trades_df),
                    'profit_factor': 0.0,
                    'win_rate': 0.0,
                    'net_pnl': 0.0,
                    'valid': False
                }
            else:
                total_trades = len(trades_df)
                winning_trades = len(trades_df[trades_df['pnl'] > 0])
                losing_trades = len(trades_df[trades_df['pnl'] < 0])
                
                win_rate = winning_trades / total_trades if total_trades > 0 else 0.0
                gross_profit = trades_df[trades_df['pnl'] > 0]['pnl'].sum() if winning_trades > 0 else 0.0
                gross_loss = abs(trades_df[trades_df['pnl'] < 0]['pnl'].sum()) if losing_trades > 0 else 0.0
                net_pnl = trades_df['pnl'].sum()
                
                profit_factor = gross_profit / gross_loss if gross_loss > 0 else (gross_profit if gross_profit > 0 else 0.0)
                
                # Return negative profit factor (we minimize)
                score = -profit_factor
                
                metrics = {
                    'total_trades': total_trades,
                    'winning_trades': winning_trades,
                    'losing_trades': losing_trades,
                    'profit_factor': profit_factor,
                    'win_rate': win_rate,
                    'net_pnl': net_pnl,
                    'gross_profit': gross_profit,
                    'gross_loss': gross_loss,
                    'valid': True
                }
            
            runtime = time.time() - start_time
            
            # Cache evaluation
            self.evaluation_cache.append({
                'iteration': self.iteration,
                'params': param_dict,
                'metrics': metrics,
                'score': score,
                'runtime': runtime
            })
            
            # Track best
            if score > self.best_score_so_far and metrics['valid']:
                self.best_score_so_far = score
                self.best_params_so_far = param_dict.copy()
                print(f"\n🎯 New best! Iteration {self.iteration}: PF={-score:.3f}, Trades={metrics['total_trades']}")
                print(f"   Params: {param_dict}")
            
            # Progress update
            if self.iteration % 10 == 0:
                print(f"[{self.iteration}] PF={-score:.3f} (best: {-self.best_score_so_far:.3f}), Trades={metrics['total_trades']}")
            
            return score
            
        except Exception as e:
            print(f"ERROR in iteration {self.iteration}: {e}")
            # Return worst possible score on error
            self.evaluation_cache.append({
                'iteration': self.iteration,
                'params': param_dict,
                'metrics': {'error': str(e), 'valid': False},
                'score': -999.0,
                'runtime': time.time() - start_time
            })
            return -999.0
    
    def optimize(
        self,
        data_path: str,
        n_calls: int = 200,
        n_random_starts: int = 20,
        output_dir: str = "outputs/optimization",
        checkpoint_every: int = 10
    ) -> BayesianResult:
        """
        Run Bayesian optimization.
        
        Args:
            data_path: Path to processed data CSV
            n_calls: Total number of evaluations
            n_random_starts: Number of random evaluations before using GP
            output_dir: Directory to save results
            checkpoint_every: Save checkpoint every N iterations
        
        Returns:
            BayesianResult with optimization results
        """
        from ..core.data_loader import load_processed_30s_csv
        
        print("=" * 80)
        print("BAYESIAN OPTIMIZATION")
        print("=" * 80)
        print(f"Total evaluations: {n_calls}")
        print(f"Random starts: {n_random_starts}")
        print(f"Min trades filter: {self.min_trades}")
        print(f"Output directory: {output_dir}")
        print("=" * 80)
        print()
        
        # Load data once
        print("Loading data...")
        self.base_df = load_processed_30s_csv(data_path, date_filter=None)
        print(f"Loaded {len(self.base_df):,} bars")
        print()
        
        # Create output directory
        os.makedirs(output_dir, exist_ok=True)
        checkpoint_file = os.path.join(output_dir, "bayesian_checkpoint.json")
        
        # Run optimization
        print("Starting Bayesian optimization...")
        print("(Progress updates every 10 iterations)\n")
        
        start_time = time.time()
        
        # Create objective with named args for skopt
        @use_named_args(self.space)
        def objective(**params):
            # Convert named params back to list in correct order
            param_list = [params[name] for name in self.dimension_names]
            return self._objective_function(param_list)
        
        # Run optimization
        result = gp_minimize(
            objective,
            self.space,
            n_calls=n_calls,
            n_random_starts=n_random_starts,
            random_state=42,
            verbose=False,
            n_jobs=1  # Sequential for now
        )
        
        total_time = time.time() - start_time
        
        # Find best valid result
        best_idx = None
        best_score = -np.inf
        for idx, eval_data in enumerate(self.evaluation_cache):
            if eval_data['metrics'].get('valid', False):
                if eval_data['score'] > best_score:
                    best_score = eval_data['score']
                    best_idx = idx
        
        if best_idx is None:
            raise ValueError("No valid configurations found!")
        
        best_eval = self.evaluation_cache[best_idx]
        
        # Create result object
        bayesian_result = BayesianResult(
            best_params=best_eval['params'],
            best_score=-best_eval['score'],  # Convert back to positive
            all_params=[e['params'] for e in self.evaluation_cache],
            all_scores=[-e['score'] for e in self.evaluation_cache],  # Convert to positive
            all_metrics=[e['metrics'] for e in self.evaluation_cache],
            n_iterations=len(self.evaluation_cache),
            total_time_seconds=total_time,
            convergence_iteration=best_eval['iteration']
        )
        
        # Save results
        self._save_results(bayesian_result, output_dir)
        
        print("\n" + "=" * 80)
        print("OPTIMIZATION COMPLETE!")
        print("=" * 80)
        print(f"Total time: {total_time/60:.1f} minutes")
        print(f"Evaluations: {len(self.evaluation_cache)}")
        print(f"Best found at iteration: {best_eval['iteration']}")
        print(f"\nBest Profit Factor: {-best_score:.3f}")
        print(f"Best Parameters:")
        for key, value in best_eval['params'].items():
            print(f"  {key}: {value}")
        print(f"\nBest Metrics:")
        for key, value in best_eval['metrics'].items():
            if isinstance(value, float):
                print(f"  {key}: {value:.4f}")
            else:
                print(f"  {key}: {value}")
        print("=" * 80)
        
        return bayesian_result
    
    def _save_results(self, result: BayesianResult, output_dir: str):
        """Save optimization results to files."""
        # Save all evaluations to CSV
        rows = []
        for params, score, metrics in zip(result.all_params, result.all_scores, result.all_metrics):
            row = {}
            row.update(params)
            row.update(metrics)
            row['profit_factor'] = score
            rows.append(row)
        
        df = pd.DataFrame(rows)
        csv_path = os.path.join(output_dir, "bayesian_results.csv")
        df.to_csv(csv_path, index=False)
        print(f"\n✅ Saved all evaluations to: {csv_path}")
        
        # Save best config to JSON
        best_config_path = os.path.join(output_dir, "bayesian_best_config.json")
        with open(best_config_path, 'w') as f:
            json.dump({
                'parameters': result.best_params,
                'profit_factor': result.best_score,
                'convergence_iteration': result.convergence_iteration,
                'total_iterations': result.n_iterations,
                'total_time_seconds': result.total_time_seconds
            }, f, indent=2)
        print(f"✅ Saved best config to: {best_config_path}")
        
        # Save full result object
        result_path = os.path.join(output_dir, "bayesian_optimization_result.json")
        with open(result_path, 'w') as f:
            json.dump(asdict(result), f, indent=2)
        print(f"✅ Saved full results to: {result_path}")


