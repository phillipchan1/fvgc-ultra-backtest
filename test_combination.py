# test_combination.py
# ---------------------------------------------------------------------------
# Test script for running multiple permutations together
# ---------------------------------------------------------------------------

import sys
import os
import pandas as pd
import hashlib
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.models.permutations import get_permutation, list_permutations
from src.utils.permutation_validator import apply_single_filter, generate_comparison_report
from src.core.backtest_engine import calculate_metrics
from src.core.config import CONFIG


def generate_combo_hash(perm_names: list) -> str:
    """Generate a hash for the combination of permutations."""
    combo_str = "_".join(sorted(perm_names))
    return hashlib.md5(combo_str.encode()).hexdigest()[:8]


def test_combination(perm_names: list):
    """Test a combination of permutations."""
    print(f"\n{'='*60}")
    print(f"Testing combination: {' + '.join(perm_names)}")
    print(f"{'='*60}")
    
    # Validate all permutations exist
    for perm_name in perm_names:
        try:
            get_permutation(perm_name)
        except ValueError as e:
            print(f"❌ {e}")
            return
    
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
    
    # Apply filters sequentially
    current_trades = baseline_trades.copy()
    all_filter_reasons = []
    filter_stages = []
    
    for i, perm_name in enumerate(perm_names):
        print(f"\nStage {i+1}: Applying '{perm_name}' filter...")
        
        perm = get_permutation(perm_name)
        print(f"  {perm['description']}")
        
        # Apply filter
        filtered_trades, filter_reasons = apply_single_filter(current_trades, perm_name)
        
        # Track results
        excluded_count = len(current_trades) - len(filtered_trades)
        filter_stages.append({
            "stage": i + 1,
            "permutation": perm_name,
            "trades_before": len(current_trades),
            "trades_after": len(filtered_trades),
            "excluded": excluded_count,
            "description": perm["description"]
        })
        
        all_filter_reasons.extend(filter_reasons)
        current_trades = filtered_trades
        
        print(f"  Result: {len(current_trades)} trades remaining ({excluded_count} excluded)")
    
    # Generate final comparison report
    combo_hash = generate_combo_hash(perm_names)
    combo_name = f"combo_{combo_hash}"
    
    comparison_df = generate_comparison_report(
        baseline_trades, current_trades, combo_name, all_filter_reasons
    )
    
    # Save outputs
    combo_path = os.path.join("outputs", "trades", f"{combo_name}.csv")
    comparison_path = os.path.join("outputs", "trades", f"comparison_{combo_name}.csv")
    
    current_trades.to_csv(combo_path, index=False)
    comparison_df.to_csv(comparison_path, index=False)
    
    # Calculate metrics
    baseline_metrics = calculate_metrics(baseline_trades)
    combo_metrics = calculate_metrics(current_trades)
    
    # Display results
    print(f"\n📊 FILTER STAGES:")
    print(f"{'Stage':<6} {'Filter':<20} {'Before':<8} {'After':<8} {'Excluded':<10}")
    print("-" * 60)
    
    for stage in filter_stages:
        print(f"{stage['stage']:<6} {stage['permutation']:<20} {stage['trades_before']:<8} {stage['trades_after']:<8} {stage['excluded']:<10}")
    
    print(f"\n📊 FINAL COMPARISON:")
    print(f"{'Metric':<20} {'Baseline':<15} {'Combination':<15} {'Change':<15}")
    print("-" * 65)
    
    for metric in ["trades", "win_rate", "net", "profit_factor"]:
        baseline_val = baseline_metrics["TOTAL"][metric]
        combo_val = combo_metrics["TOTAL"][metric]
        
        if isinstance(baseline_val, (int, float)) and isinstance(combo_val, (int, float)):
            change = combo_val - baseline_val
            change_pct = (change / baseline_val * 100) if baseline_val != 0 else 0
            change_str = f"{change:+.2f} ({change_pct:+.1f}%)"
        else:
            change_str = "N/A"
        
        print(f"{metric:<20} {baseline_val:<15} {combo_val:<15} {change_str:<15}")
    
    print(f"\n📁 OUTPUT FILES:")
    print(f"  Combination:  {combo_path}")
    print(f"  Comparison:   {comparison_path}")
    
    print(f"\n✅ Combination test completed!")
    print(f"   Baseline trades: {len(baseline_trades)}")
    print(f"   Final trades: {len(current_trades)}")
    print(f"   Total excluded: {len(baseline_trades) - len(current_trades)}")
    
    # Show which permutations were most restrictive
    if len(filter_stages) > 1:
        most_restrictive = max(filter_stages, key=lambda x: x["excluded"])
        print(f"   Most restrictive: {most_restrictive['permutation']} ({most_restrictive['excluded']} excluded)")


def list_combinations():
    """List some example combinations."""
    print("Example combinations you can test:")
    print()
    
    # Group permutations by type
    gap_filters = ["small_gaps", "medium_gaps", "large_gaps"]
    touch_filters = ["tap_only", "close_inside_only"]
    time_filters = ["first_five_minutes", "early_session", "mid_session", "late_session"]
    delivery_filters = ["fast_delivery", "slow_delivery"]
    
    print("Gap size combinations:")
    for gap in gap_filters:
        print(f"  python test_combination.py {gap}")
    
    print("\nGap size + touch type combinations:")
    for gap in gap_filters:
        for touch in touch_filters:
            print(f"  python test_combination.py {gap} {touch}")
    
    print("\nTime + delivery combinations:")
    for time in time_filters:
        for delivery in delivery_filters:
            print(f"  python test_combination.py {time} {delivery}")
    
    print("\nComplex combinations:")
    print("  python test_combination.py small_gaps tap_only first_five_minutes")
    print("  python test_combination.py medium_gaps close_inside_only fast_delivery")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        command = sys.argv[1]
        
        if command == "list":
            list_combinations()
        
        elif command == "examples":
            list_combinations()
        
        else:
            # Test the combination
            perm_names = sys.argv[1:]
            test_combination(perm_names)
    else:
        print("Usage:")
        print("  python test_combination.py list                    # List example combinations")
        print("  python test_combination.py <perm1> <perm2> ...      # Test combination")
        print("\nExamples:")
        print("  python test_combination.py small_gaps tap_only")
        print("  python test_combination.py first_five_minutes fast_delivery")
        print("  python test_combination.py medium_gaps close_inside_only early_session")
        print("\nRun 'python test_combination.py list' for more examples")
