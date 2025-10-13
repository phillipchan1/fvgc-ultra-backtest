# FVG Backtest - Modular Structure

This project has been refactored from a monolithic `backtest.py` into a modular structure following the Single Responsibility Principle.

## File Structure

```
fvgc-backtest/
├── config.py              # Configuration settings and constants
├── data_loader.py          # Data loading and preprocessing utilities
├── fvg_detection.py        # FVG detection and lifecycle management
├── models.py               # Entry model evaluators (fvg_ifvg, fvg_bos, fvg_no_fvg)
├── backtest_engine.py      # Main backtest engine and trade resolution
├── main.py                 # Entry point and main execution
├── backtest.py             # Original monolithic file (kept for reference)
└── README.md               # This file
```

## Module Responsibilities

### `config.py`
- Contains all configuration settings
- Defines constants like `REQUIRED_COLS`
- Single source of truth for all parameters

### `data_loader.py`
- Data loading from CSV files
- Data validation and preprocessing
- Resampling from 1s to 30s bars
- Session time utilities

### `fvg_detection.py`
- FVG detection algorithms
- FVG lifecycle management (creation, validation, expiration)
- Conflict detection between FVGs
- FVG data structures

### `models.py`
- Entry model evaluators for different strategies
- Helper functions for each model's specific requirements
- Model evaluation mapping

### `backtest_engine.py`
- Main backtest loop
- Trade resolution logic
- Metrics calculation
- Trade record creation

### `main.py`
- Entry point for the application
- Orchestrates the entire backtest process
- Handles output and results display

## Usage

Run the backtest with:
```bash
python main.py
```

## Benefits of Modular Structure

1. **Single Responsibility**: Each module has one clear purpose
2. **Easier Testing**: Individual components can be tested in isolation
3. **Better Maintainability**: Changes to one aspect don't affect others
4. **Improved Readability**: Smaller, focused files are easier to understand
5. **Reusability**: Components can be reused in other projects
6. **Easier Debugging**: Issues can be isolated to specific modules

## Configuration

All settings are centralized in `config.py`. To modify behavior:
- Change parameters in the `CONFIG` dictionary
- Adjust model evaluation order in `models_to_eval`
- Modify risk management settings (`points_tp`, `points_sl`)
- Update session parameters (`session_start`, `session_end`)

## Adding New Models

To add a new entry model:
1. Create evaluation function in `models.py`
2. Add to `EVAL_MAP` dictionary
3. Include in `CONFIG["models_to_eval"]` list
4. Add any model-specific configuration parameters to `config.py`
