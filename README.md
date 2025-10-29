# FVG Backtest - Systematic Permutation Testing

A modular, well-organized Fair Value Gap (FVG) backtesting system designed for **systematic permutation testing** with baseline comparison and combination analysis.

## 📁 Project Structure

```
fvgc-backtest/
├── src/                          # Source code
│   ├── core/                     # Core backtest engine
│   │   ├── __init__.py
│   │   ├── config.py             # Configuration settings
│   │   ├── data_loader.py        # Data loading & preprocessing
│   │   ├── fvg_detection.py     # FVG detection & lifecycle
│   │   └── backtest_engine.py   # Main backtest engine
│   ├── models/                   # Trading models & strategies
│   │   ├── __init__.py
│   │   ├── models.py            # Entry model evaluators
│   │   ├── permutations.py     # Clean permutation definitions
│   │   └── permutations_examples.py  # Example permutations (reference)
│   ├── utils/                    # Utility functions
│   │   ├── __init__.py
│   │   └── permutation_validator.py  # Filter validation & comparison
│   ├── main.py                  # Main entry point
│   ├── sweep.py                 # Parameter sweep system
│   ├── analyze_sweep.py         # Sweep analysis tools
│   └── run_setup.py             # Setup runner
├── data/                         # Data files
│   ├── raw/                     # Raw input data
│   │   ├── glbx-mdp3-20250911-20251010.ohlcv-1s.csv
│   │   ├── symbology.csv
│   │   ├── symbology.json
│   │   ├── manifest.json
│   │   ├── metadata.json
│   │   └── condition.json
│   └── processed/               # Processed data (auto-generated)
├── outputs/                      # Output files
│   ├── trades/                  # Trade results
│   │   ├── trades.csv
│   │   └── trades_best.csv
│   ├── analysis/                # Analysis outputs
│   │   ├── report.md
│   │   ├── top_setups.csv
│   │   └── variable_effects.csv
│   └── sweeps/                  # Sweep results
│       └── sweep_results.csv
├── configs/                     # Configuration files
├── tests/                       # Test files
├── docs/                        # Documentation
│   ├── README.md               # This file
│   └── backtest.py            # Original monolithic file
├── test_permutation.py         # Individual permutation testing
├── test_combination.py         # Multi-permutation testing  
├── test_super_sweep.py         # All-combinations testing (Phase 2)
├── setup.py                     # Project setup
├── activate_env.sh              # Environment activation
└── PROJECT_OVERVIEW.md          # Quick reference
└── venv/                       # Virtual environment
```

## 🚀 Quick Start

### 1. Run Baseline Backtest
```bash
# Activate environment
source activate_env.sh

# Run baseline
python test_permutation.py baseline
```

### 2. Test Individual Permutations
```bash
# List available permutations
python test_permutation.py list

# Test a specific permutation
python test_permutation.py tap_only
python test_permutation.py small_gaps
python test_permutation.py first_five_minutes
```

### 3. Test Permutation Combinations
```bash
# List example combinations
python test_combination.py list

# Test specific combinations
python test_combination.py small_gaps tap_only
python test_combination.py first_five_minutes fast_delivery
```

### 4. Run Super Sweep (Phase 2)
```bash
# Test all combinations (up to 1000)
python test_super_sweep.py

# Analyze results
python test_super_sweep.py analyze
```

## 🎯 Systematic Testing Workflow

### Phase 1: Individual Permutation Validation

1. **Establish Baseline**
   ```bash
   python test_permutation.py baseline
   ```
   - Generates `outputs/trades/baseline.csv` with all trades
   - Establishes baseline metrics for comparison

2. **Test Each Permutation Individually**
   ```bash
   python test_permutation.py tap_only
   python test_permutation.py small_gaps
   python test_permutation.py first_five_minutes
   ```
   - Generates 3 files per test:
     - `permutation_{name}.csv` - Filtered trades
     - `comparison_{name}.csv` - Side-by-side comparison
     - Console output with metrics comparison

3. **Validate Filter Logic**
   - Review comparison CSV to ensure filter works correctly
   - Check that excluded trades have valid reasons
   - Verify metrics make sense for the filter

### Phase 2: Combination Testing

4. **Test Specific Combinations**
   ```bash
   python test_combination.py small_gaps tap_only
   python test_combination.py first_five_minutes fast_delivery
   ```
   - Shows filter stages and cumulative effects
   - Identifies which filters are most restrictive

### Phase 3: Super Sweep (Optional)

5. **Run All Combinations**
   ```bash
   python test_super_sweep.py 500  # Test up to 500 combinations
   ```
   - Automatically tests all valid combinations
   - Ranks by profit factor
   - Identifies best performing combinations

## 📊 Output Files

### Individual Tests (`outputs/trades/`)
- `baseline.csv` - All trades from baseline backtest
- `permutation_{name}.csv` - Trades passing specific filter
- `comparison_{name}.csv` - Side-by-side comparison with filter reasons

### Combination Tests (`outputs/trades/`)
- `combo_{hash}.csv` - Trades passing all filters in combination
- `comparison_combo_{hash}.csv` - Comparison report for combination

### Super Sweep Results (`outputs/sweeps/`)
- `super_sweep_results.csv` - All combinations ranked by performance

## 📊 Available Permutations

### Entry Touch Types
- `tap_only` - Only entries where bar taps gap but closes outside
- `close_inside_only` - Only entries where bar closes inside gap

### Gap Interactions
- `no_gap_taps` - No prior bars touched the gap
- `one_gap_tap` - Exactly one prior bar touched the gap
- `multiple_gap_taps` - Multiple bars touched the gap (2-3 taps)

### Midline Penetration
- `penetrated_midline` - Entry bar penetrated beyond 50% of gap
- `no_midline_penetration` - Entry bar did NOT penetrate beyond 50%

### Time-Based Filters
- `first_five_minutes` - Only entries in first 5 minutes (09:30-09:35)
- `early_session` - Only entries in 09:30-09:45
- `mid_session` - Only entries in 09:45-10:00
- `late_session` - Only entries in 10:00-10:15

### Gap Size Filters
- `small_gaps` - Only small gaps (0.75-5 points)
- `medium_gaps` - Only medium gaps (5-15 points)
- `large_gaps` - Only large gaps (15+ points)

### Delivery Speed
- `fast_delivery` - Fast delivery (breaks previous bar within 2 bars)
- `slow_delivery` - Slow delivery (takes 3+ bars to break previous)

### Risk Management
- `tight_stops` - Tighter stops (10 points)
- `wide_stops` - Wider stops (30 points)

### Model-Specific
- `ifvg_only` - Only iFVG model
- `bos_only` - Only BOS model
- `no_fvg_only` - Only no-FVG model

### Combined Scenarios
- `tap_only_first_five` - Tap-only entries in first 5 minutes
- `small_gaps_fast_delivery` - Small gaps with fast delivery
- `early_session_tight_stops` - Early session with tight stops

## 🔧 Adding New Permutations

### Permutation Structure

Edit `src/models/permutations.py` to add new filters:

```python
PERMUTATIONS = {
    "my_new_filter": {
        "description": "Description of what this filter does",
        "filter_type": "range",  # or "categorical" or "config_change"
        "param": "parameter_name",
        "min": 0.0,              # for range type
        "max": 10.0,             # for range type  
        "increment": 0.5,        # for range type
        "default_value": 5.0,    # for range type
        "value": "some_value"    # for categorical/config_change
    }
}
```

### Filter Types

- **`range`** - Filters trades based on numeric parameter ranges
- **`categorical`** - Filters trades based on exact value matches
- **`config_change`** - Changes backtest configuration (affects trade generation)

### Validation

Test your new permutation:
```bash
python test_permutation.py my_new_filter
```

The system will validate the definition and show filter logic.

## 📈 Output Files

### Trade Results (`outputs/trades/`)
- `trades.csv` - All trades from current run
- `trades_best.csv` - Best scenario trades (from sweeps)

### Analysis (`outputs/analysis/`)
- `report.md` - Analysis summary
- `top_setups.csv` - Best performing setups
- `variable_effects.csv` - Variable impact analysis

### Sweep Results (`outputs/sweeps/`)
- `sweep_results.csv` - All sweep combinations and results

## 🧪 Testing Strategy

1. **Start with baseline** - Run `python src/main.py` to establish baseline
2. **Test one permutation** - Use `test_permutation.py` to validate each scenario
3. **Validate logic** - Check that the permutation actually filters trades correctly
4. **Compare results** - Compare metrics against baseline
5. **Build library** - Add successful permutations to your testing library
6. **Scale up** - Once individual permutations work, use sweep system

## 🔍 Debugging

- Check console output for detailed metrics
- Review trade CSV files for specific trade details
- Use permutation info to understand what changed
- Validate that scenario filters are working as expected

## 📝 Adding New Permutations

1. Edit `src/models/permutations.py`
2. Add new permutation definition
3. Test with `python test_permutation.py <name>`
4. Validate results make sense
5. Add to your testing library

This organized structure makes it easy to:
- **Pinpoint changes** - Each permutation is clearly defined
- **Test incrementally** - One scenario at a time
- **Maintain clean code** - Modular, organized structure
- **Scale up** - Build from individual tests to full sweeps