# FVG Backtest - Organized Structure

A modular, well-organized Fair Value Gap (FVG) backtesting system for trading strategy development.

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
│   │   └── permutations.py     # Named permutation definitions
│   ├── utils/                    # Utility functions
│   │   └── __init__.py
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
├── test_permutation.py         # Permutation testing script
└── venv/                       # Virtual environment
```

## 🚀 Quick Start

### 1. Run Baseline Backtest
```bash
python src/main.py
```

### 2. Test Individual Permutations
```bash
# List available permutations
python test_permutation.py list

# Test a specific permutation
python test_permutation.py tap_only
python test_permutation.py first_five_minutes
python test_permutation.py small_gaps_fast_delivery
```

### 3. Run Parameter Sweeps
```bash
# Quick sweep
python src/sweep.py --top 20

# Full scenarios
python src/sweep.py --full-scenarios --top 20
```

## 🎯 Manual Testing Workflow

The system is designed for **one permutation at a time** manual testing:

### Step 1: Choose a Permutation
```bash
python test_permutation.py list
```

### Step 2: Test the Permutation
```bash
python test_permutation.py tap_only
```

### Step 3: Review Results
- Check console output for metrics
- Review `outputs/trades/trades.csv` for trade details
- Validate the permutation logic is working correctly

### Step 4: Add New Permutations
Edit `src/models/permutations.py` to add new scenarios:

```python
"my_new_scenario": {
    "description": "My custom scenario description",
    "changes": {
        "entry_touch_type": "tap_only",
        "first_five_only": True
    }
}
```

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

## 🔧 Configuration

All settings are in `src/core/config.py`. Key sections:

- **Data paths** - Input file locations
- **Session settings** - Trading session times
- **Risk management** - TP/SL points, position sizing
- **Model parameters** - FVG detection criteria
- **Scenario filters** - Entry conditions and constraints

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