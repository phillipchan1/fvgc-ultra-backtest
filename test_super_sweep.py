# test_super_sweep.py
# ---------------------------------------------------------------------------
# Super sweep script for testing all combinations of vetted permutations
# ---------------------------------------------------------------------------

import sys
import os
import pandas as pd
import itertools
from typing import List, Dict, Any
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.models.permutations import list_permutations, get_permutation
from src.utils.permutation_validator import apply_single_filter
from src.core.backtest_engine import calculate_metrics
from src.core.config import CONFIG


def generate_permutation_combinations(max_combinations: int = 1000) -> List[List[str]]:
    """Generate combinations of permutations for testing."""
    all_perms = list_permutations()
    
    # Group permutations by type to avoid redundant combinations
    gap_perms = [p for p in all_perms if "gap" in p]
    touch_perms = [p for p in all_perms if "tap" in p or "close" in p]
    time_perms = [p for p in all_perms if "session" in p or "five" in p]
    delivery_perms = [p for p in all_perms if "delivery" in p]
    midline_perms = [p for p in all_perms if "midline" in p]
    risk_perms = [p for p in all_perms if "stop" in p]
    model_perms = [p for p in all_perms if "only" in p]
    
    combinations = []
    
    # Single permutations
    combinations.extend([[p] for p in all_perms])
    
    # Two-way combinations (avoid same category)
    for perm1 in all_perms:
        for perm2 in all_perms:
            if perm1 != perm2:
                # Avoid combinations within same category
                if not (perm1 in gap_perms and perm2 in gap_perms):
                    if not (perm1 in touch_perms and perm2 in touch_perms):
                        if not (perm1 in time_perms and perm2 in time_perms):
                            combinations.append([perm1, perm2])
    
    # Three-way combinations (curated)
    curated_three_way = [
        ["small_gaps", "tap_only", "first_five_minutes"],
        ["medium_gaps", "close_inside_only", "early_session"],
        ["large_gaps", "tap_only", "fast_delivery"],
        ["small_gaps", "close_inside_only", "slow_delivery"],
        ["medium_gaps", "tap_only", "penetrated_midline"],
        ["small_gaps", "no_midline_penetration", "fast_delivery"],
    ]
    combinations.extend(curated_three_way)
    
    # Limit to max_combinations
    if len(combinations) > max_combinations:
        combinations = combinations[:max_combinations]
    
    return combinations


def run_super_sweep(max_combinations: int = 1000, min_trades: int = 5):
    """Run super sweep testing all combinations."""
    print(f"\n{'='*60}")
    print(f"SUPER SWEEP - Testing all permutation combinations")
    print(f"{'='*60}")
    
    # Load baseline trades
    baseline_path = os.path.join("outputs", "trades", "baseline.csv")
    if not os.path.exists(baseline_path):
        print(f"❌ Baseline not found at {baseline_path}")
        print("Run 'python test_permutation.py baseline' first")
        return
    
    baseline_trades = pd.read_csv(baseline_path)
    if baseline_trades.empty:
        print("❌ No baseline trades available")
        return
    
    print(f"Loaded baseline with {len(baseline_trades)} trades")
    
    # Generate combinations
    combinations = generate_permutation_combinations(max_combinations)
    print(f"Generated {len(combinations)} combinations to test")
    
    # Results storage
    results = []
    
    # Test each combination
    for i, combo in enumerate(combinations):
        print(f"\nTesting combination {i+1}/{len(combinations)}: {' + '.join(combo)}")
        
        # Apply filters sequentially
        current_trades = baseline_trades.copy()
        
        for perm_name in combo:
            try:
                filtered_trades, _ = apply_single_filter(current_trades, perm_name)
                current_trades = filtered_trades
            except Exception as e:
                print(f"  ❌ Error applying {perm_name}: {e}")
                break
        
        # Skip if too few trades
        if len(current_trades) < min_trades:
            print(f"  ⚠️  Skipped - only {len(current_trades)} trades (min: {min_trades})")
            continue
        
        # Calculate metrics
        try:
            metrics = calculate_metrics(current_trades)
            total_metrics = metrics["TOTAL"]
            
            result = {
                "combination": " + ".join(combo),
                "combination_count": len(combo),
                "trades": total_metrics["trades"],
                "win_rate": total_metrics["win_rate"],
                "net": total_metrics["net"],
                "profit_factor": total_metrics["profit_factor"],
                "gross_profit": total_metrics["gross_profit"],
                "gross_loss": total_metrics["gross_loss"],
                "avg_trade": total_metrics["avg_trade"],
                "permutations": combo
            }
            
            results.append(result)
            
            print(f"  ✅ {total_metrics['trades']} trades, WR: {total_metrics['win_rate']:.2%}, Net: ${total_metrics['net']:,.2f}, PF: {total_metrics['profit_factor']:.2f}")
            
        except Exception as e:
            print(f"  ❌ Error calculating metrics: {e}")
            continue
    
    # Convert to DataFrame and sort
    if results:
        results_df = pd.DataFrame(results)
        
        # Sort by profit factor (descending)
        results_df = results_df.sort_values("profit_factor", ascending=False)
        
        # Save results
        sweep_path = os.path.join("outputs", "sweeps", "super_sweep_results.csv")
        results_df.to_csv(sweep_path, index=False)
        
        # Display top results
        print(f"\n{'='*60}")
        print(f"TOP 10 COMBINATIONS BY PROFIT FACTOR")
        print(f"{'='*60}")
        
        top_10 = results_df.head(10)
        for i, row in top_10.iterrows():
            print(f"{row['combination']:<50} | Trades: {row['trades']:3d} | WR: {row['win_rate']:6.2%} | Net: ${row['net']:8,.2f} | PF: {row['profit_factor']:5.2f}")
        
        print(f"\n📁 Results saved to: {sweep_path}")
        print(f"✅ Super sweep completed! Tested {len(results)} valid combinations")
        
        # Find best combination
        best = results_df.iloc[0]
        print(f"\n🏆 BEST COMBINATION:")
        print(f"   Permutations: {best['combination']}")
        print(f"   Trades: {best['trades']}")
        print(f"   Win Rate: {best['win_rate']:.2%}")
        print(f"   Net P&L: ${best['net']:,.2f}")
        print(f"   Profit Factor: {best['profit_factor']:.2f}")
        
    else:
        print("❌ No valid combinations found")


def analyze_results():
    """Analyze super sweep results."""
    sweep_path = os.path.join("outputs", "sweeps", "super_sweep_results.csv")
    
    if not os.path.exists(sweep_path):
        print(f"❌ No super sweep results found at {sweep_path}")
        print("Run 'python test_super_sweep.py' first")
        return
    
    results_df = pd.read_csv(sweep_path)
    
    print(f"\n{'='*60}")
    print(f"SUPER SWEEP ANALYSIS")
    print(f"{'='*60}")
    
    print(f"Total combinations tested: {len(results_df)}")
    print(f"Average trades per combination: {results_df['trades'].mean():.1f}")
    print(f"Average win rate: {results_df['win_rate'].mean():.2%}")
    print(f"Average profit factor: {results_df['profit_factor'].mean():.2f}")
    
    # Find most common permutations in top performers
    top_20 = results_df.head(20)
    all_perms = []
    for perms in top_20['permutations']:
        # Parse the permutations string
        perm_list = [p.strip() for p in perms.split('+')]
        all_perms.extend(perm_list)
    
    from collections import Counter
    perm_counts = Counter(all_perms)
    
    print(f"\nMost common permutations in top 20:")
    for perm, count in perm_counts.most_common(10):
        print(f"  {perm}: {count} times")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        command = sys.argv[1]
        
        if command == "analyze":
            analyze_results()
        
        else:
            # Run super sweep
            max_combinations = int(command) if command.isdigit() else 1000
            run_super_sweep(max_combinations)
    else:
        print("Usage:")
        print("  python test_super_sweep.py [max_combinations]    # Run super sweep")
        print("  python test_super_sweep.py analyze               # Analyze results")
        print("\nExamples:")
        print("  python test_super_sweep.py 500                   # Test up to 500 combinations")
        print("  python test_super_sweep.py analyze               # Analyze existing results")
