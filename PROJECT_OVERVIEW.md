# PROJECT OVERVIEW

## 🎯 Purpose
This is a modular FVG (Fair Value Gap) backtesting system designed for **manual, one-permutation-at-a-time testing**.

## 🚀 Quick Start
```bash
# Activate environment
source activate_env.sh

# Run baseline
python src/main.py

# Test a permutation
python test_permutation.py tap_only
```

## 📁 Key Directories
- `src/` - All source code (organized by function)
- `data/raw/` - Input data files
- `outputs/` - All results (trades, analysis, sweeps)
- `docs/` - Documentation and original files

## 🧪 Testing Strategy
1. **Baseline first** - Run `python src/main.py`
2. **One permutation** - Test individual scenarios
3. **Validate logic** - Ensure filters work correctly
4. **Build library** - Add successful permutations
5. **Scale up** - Use sweep system for broader testing

## 🔧 Key Files
- `src/core/config.py` - All configuration settings
- `src/models/permutations.py` - Named scenario definitions
- `test_permutation.py` - Individual permutation testing
- `src/main.py` - Baseline backtest runner

## 📊 Output Organization
- `outputs/trades/` - Trade results
- `outputs/analysis/` - Analysis reports
- `outputs/sweeps/` - Sweep results

This structure makes it easy to:
- **Pinpoint changes** - Each permutation is clearly defined
- **Test incrementally** - One scenario at a time
- **Maintain clean code** - Modular, organized structure
- **Scale up** - Build from individual tests to full sweeps
