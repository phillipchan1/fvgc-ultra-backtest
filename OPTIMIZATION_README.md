# Parameter Optimization System

## Overview

The parameter optimization system tests **3,840 combinations** of trading parameters to identify the best-performing setups.

## What Gets Tested

### Variables (6 dimensions)
1. **Entry Model**: noFVG, BOS, iFVG, ALL (4 options)
2. **Gap Closure**: True, False, ALL (3 options)
3. **Gap Size**: 0-3pts, 3-6pts, 6-10pts, 10+pts, ALL (5 options)
4. **Time Windows**: 9:30-9:45, 9:45-10:00, 10:00-10:15, ALL (4 options)
5. **Touch Ranges**: 1-2, 3-4, 5+, ALL (4 options)
6. **Trade Management**: fixed, dynamic_fvg, partial_close, trailing_sl (4 options)

**Total Combinations**: 4 × 3 × 5 × 4 × 4 × 4 = **3,840**

### Metrics Tracked
- Win Rate (%)
- Profit Factor (primary optimization metric)
- Net P&L (points)
- Total Trades
- Gross Profit / Gross Loss
- Average Win / Average Loss
- Sharpe-like Ratio

## How to Run

### Quick Start
```bash
cd /Users/philchan/Work/fvgc-backtest
source venv/bin/activate
python run_parameter_sweep.py
```

### Estimated Runtime
- **~8 hours** for full sweep (testing on 2+ years of data)
- Uses caching and resume capability
- Progress updates every 10 combinations

### Resume Capability
If interrupted, the sweep will automatically resume from where it left off using cached results in `outputs/optimization/sweep_cache.json`.

## Output Files

All results saved to `outputs/optimization/`:

1. **sweep_results_full.csv**
   - All 3,840 combinations with metrics
   - Use for custom analysis

2. **sweep_results_top100.csv**
   - Top 100 setups by profit factor
   - Quick reference for best performers

3. **variable_importance_*.csv**
   - Impact analysis for each variable
   - Shows which parameters matter most
   - Generated for win_rate, profit_factor, net_pnl

4. **config_best_setup.json**
   - Best configuration ready to use
   - Can be directly applied to CONFIG

5. **optimization_report.txt**
   - Comprehensive summary
   - Best setups by each metric

## Understanding Results

### Minimum Trade Threshold
Only combinations with **≥30 trades** are considered valid for statistical significance.

### Key Insights To Look For

1. **Variable Importance**
   - Which filters have biggest impact on win rate?
   - Example: "gap_closure=False: +5.2% WR improvement"

2. **Best Combinations**
   - What setup gives highest profit factor?
   - What's the trade-off between trade frequency and quality?

3. **Time Window Analysis**
   - Which session period performs best?
   - Should you avoid certain times?

4. **Entry Model Performance**
   - Does BOS perform better with certain filters?
   - When does iFVG outperform noFVG?

5. **Trade Management Impact**
   - Which exit strategy works best overall?
   - Does it vary by entry model?

## What Happens During Sweep

For each combination:
1. Generate test configuration
2. Run full backtest (2+ years)
3. Apply post-filters (gap size, time, closure)
4. Calculate all metrics
5. Save results
6. Cache progress

## Advanced Usage

### Custom Analysis
Load results and filter:
```python
import pandas as pd

df = pd.read_csv('outputs/optimization/sweep_results_full.csv')

# Find best noFVG setups
nofvg = df[df['entry_model'] == 'noFVG']
nofvg = nofvg[nofvg['total_trades'] >= 30]
nofvg = nofvg.sort_values('profit_factor', ascending=False)
print(nofvg.head(10))
```

### Interaction Analysis
```python
from src.optimization.correlation_analysis import generate_interaction_analysis

# See how gap_size and time_window interact
pivot = generate_interaction_analysis(
    results_df,
    var1='gap_size_range',
    var2='time_window',
    metric='profit_factor'
)
print(pivot)
```

## Interpreting Variable Importance

The correlation analysis will show output like:

```
Variable Impact on Win Rate:
1. gap_closure (False):      +5.2% WR improvement
2. time_window (9:45-10:00): +3.1% WR improvement  
3. gap_size (6-10pts):       +2.7% WR improvement
```

This means:
- Filtering to trades WITHOUT gap closure improves WR by 5.2%
- Trading 9:45-10:00 window adds 3.1% to WR
- FVG sizes of 6-10pts perform 2.7% better

## Next Steps After Sweep

1. **Review Top 10 Setups**
   - Check if they make intuitive sense
   - Verify trade counts are sufficient

2. **Apply Best Config**
   - Copy parameters from best setup
   - Update your live CONFIG

3. **Test Forward**
   - Run on recent out-of-sample data
   - Verify performance holds

4. **Iterate**
   - Based on insights, refine entry models
   - Add new filters if patterns emerge
   - Re-run sweep with improved models

## Framework Files

```
src/optimization/
├── __init__.py
├── parameter_sweep.py      # Main sweep engine
├── config_generator.py     # Generate test configs
├── correlation_analysis.py # Variable importance
└── results_analyzer.py     # Rankings and exports

run_parameter_sweep.py      # Main entry point
```

## Tips for Success

1. **Let it run overnight** - 8 hours is a long time
2. **Check progress** - Look at console output periodically
3. **Don't interrupt** - If you must, it will resume from cache
4. **Analyze thoroughly** - Don't just pick #1, understand WHY it works
5. **Consider trade count** - 200 trades at 60% WR > 40 trades at 65% WR

## Troubleshooting

**Sweep is slow?**
- Normal, 3,840 combinations take time
- Each backtest processes 2+ years of data

**Out of memory?**
- Unlikely with current dataset size
- If it happens, reduce date range in config_generator.py

**Want to test fewer combinations?**
- Edit ParameterGrid class in parameter_sweep.py
- Remove some variable options

**Need to restart?**
- Delete `outputs/optimization/sweep_cache.json`
- Or just run again - it will resume

## Questions?

This system gives you the data to make evidence-based decisions about your trading strategy. Use the variable importance analysis to understand what actually matters, not just what you think matters.

Happy optimizing! 🚀

