# test_permutation.py
# ---------------------------------------------------------------------------
# Test script for running individual permutations with baseline comparison
# ---------------------------------------------------------------------------

import sys
import os
import pandas as pd
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.models.permutations import list_permutations, print_permutation_info, get_permutation
from src.utils.permutation_validator import apply_single_filter, generate_comparison_report, explain_filter_logic
from src.core.backtest_engine import run_backtest, calculate_metrics
from src.core.data_loader import load_db_1s_csv, resample_to_30s
from src.core.config import CONFIG


def run_baseline_backtest():
    """Run baseline backtest and return trades dataframe."""
    print("Running baseline backtest...")
    
    # Load and preprocess data
    df1s = load_db_1s_csv(os.path.join("data", "raw", CONFIG["data_path"]))
    df30 = resample_to_30s(df1s)
    
    # Run backtest
    trades = run_backtest(df30)
    
    if trades.empty:
        print("⚠️  No trades generated in baseline backtest")
        return trades
    
    # Save baseline trades
    baseline_path = os.path.join("outputs", "trades", "baseline.csv")
    trades.to_csv(baseline_path, index=False)
    print(f"✅ Baseline trades saved to: {baseline_path}")
    
    return trades


def test_permutation(perm_name: str):
    """Test a specific permutation with baseline comparison."""
    print(f"\n{'='*60}")
    print(f"Testing permutation: {perm_name}")
    print(f"{'='*60}")
    
    # Show permutation info
    print_permutation_info(perm_name)
    
    # Explain filter logic
    print("Filter Logic:")
    print(explain_filter_logic(perm_name))
    
    # Run baseline if it doesn't exist
    baseline_path = os.path.join("outputs", "trades", "baseline.csv")
    if not os.path.exists(baseline_path):
        baseline_trades = run_baseline_backtest()
    else:
        print(f"Loading existing baseline from: {baseline_path}")
        baseline_trades = pd.read_csv(baseline_path)
    
    if baseline_trades.empty:
        print("❌ Cannot test permutation - no baseline trades available")
        return
    
    # Apply permutation filter to baseline trades
    print(f"\nApplying filter '{perm_name}' to baseline trades...")
    filtered_trades, filter_reasons = apply_single_filter(baseline_trades, perm_name)
    
    # Generate comparison report
    comparison_df = generate_comparison_report(
        baseline_trades, filtered_trades, perm_name, filter_reasons
    )
    
    # Save outputs
    perm_path = os.path.join("outputs", "trades", f"permutation_{perm_name}.csv")
    comparison_path = os.path.join("outputs", "trades", f"comparison_{perm_name}.csv")
    
    filtered_trades.to_csv(perm_path, index=False)
    comparison_df.to_csv(comparison_path, index=False)
    
    # Calculate and display metrics
    baseline_metrics = calculate_metrics(baseline_trades)
    filtered_metrics = calculate_metrics(filtered_trades)
    
    print(f"\n📊 RESULTS COMPARISON:")
    print(f"{'Metric':<20} {'Baseline':<15} {'Filtered':<15} {'Change':<15}")
    print("-" * 65)
    
    for metric in ["trades", "win_rate", "net", "profit_factor"]:
        baseline_val = baseline_metrics["TOTAL"][metric]
        filtered_val = filtered_metrics["TOTAL"][metric]
        
        if isinstance(baseline_val, (int, float)) and isinstance(filtered_val, (int, float)):
            change = filtered_val - baseline_val
            change_pct = (change / baseline_val * 100) if baseline_val != 0 else 0
            change_str = f"{change:+.2f} ({change_pct:+.1f}%)"
        else:
            change_str = "N/A"
        
        print(f"{metric:<20} {baseline_val:<15} {filtered_val:<15} {change_str:<15}")
    
    print(f"\n📁 OUTPUT FILES:")
    print(f"  Baseline:     {baseline_path}")
    print(f"  Filtered:     {perm_path}")
    print(f"  Comparison:   {comparison_path}")
    
    print(f"\n✅ Permutation '{perm_name}' test completed!")
    print(f"   Baseline trades: {len(baseline_trades)}")
    print(f"   Filtered trades: {len(filtered_trades)}")
    print(f"   Excluded trades: {len(baseline_trades) - len(filtered_trades)}")


def test_baseline_only():
    """Run baseline backtest only."""
    trades = run_baseline_backtest()
    if not trades.empty:
        metrics = calculate_metrics(trades)
        print(f"\n📊 BASELINE METRICS:")
        total = metrics["TOTAL"]
        print(f"  Trades: {total['trades']}")
        print(f"  Win Rate: {total['win_rate']:.2%}")
        print(f"  Net P&L: ${total['net']:,.2f}")
        print(f"  Profit Factor: {total['profit_factor']:.2f}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        command = sys.argv[1]
        
        if command == "list":
            print("Available permutations:")
            for name in list_permutations():
                perm = get_permutation(name)
                print(f"  {name:25s} - {perm['description']} ({perm['filter_type']})")
        
        elif command == "baseline":
            test_baseline_only()
        
        else:
            test_permutation(command)
    else:
        print("Usage:")
        print("  python test_permutation.py list                    # List all permutations")
        print("  python test_permutation.py baseline               # Run baseline only")
        print("  python test_permutation.py <permutation_name>      # Test specific permutation")
        print("\nExamples:")
        print("  python test_permutation.py tap_only")
        print("  python test_permutation.py small_gaps")
        print("  python test_permutation.py first_five_minutes")
