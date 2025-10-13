# main.py
# ---------------------------------------------------------------------------
# Main entry point for FVG Backtest
# ---------------------------------------------------------------------------

import warnings
from data_loader import load_db_1s_csv, resample_to_30s
from backtest_engine import run_backtest, calculate_metrics
from config import CONFIG


def main():
    """Main execution function."""
    warnings.filterwarnings("ignore", category=FutureWarning)
    
    # Load and preprocess data
    print("Loading data...")
    df1s = load_db_1s_csv(CONFIG["data_path"])
    print(f"Loaded {len(df1s)} 1-second bars")
    
    print("Resampling to 30-second bars...")
    df30 = resample_to_30s(df1s)
    print(f"Resampled to {len(df30)} 30-second bars")
    
    # Run backtest
    print("Running backtest...")
    trades = run_backtest(df30)
    
    if trades.empty:
        print("No trades generated.")
        return
    
    # Calculate and display metrics
    metrics = calculate_metrics(trades)
    
    print("\n=== FVG Backtest (30s) — One entry per gap ===")
    for model in ["fvg_ifvg", "fvg_bos", "fvg_no_fvg"]:
        result = metrics[model]
        print(f"{model:12s} trades={result['trades']:4d}  win_rate={result['win_rate']:.2%}")
    
    total = metrics["TOTAL"]
    print(f"TOTAL         trades={total['trades']:4d}  win_rate={total['win_rate']:.2%}")
    
    # Save results
    trades.to_csv(CONFIG["trades_csv"], index=False)
    print(f"\nSaved trades to: {CONFIG['trades_csv']}")


if __name__ == "__main__":
    main()
