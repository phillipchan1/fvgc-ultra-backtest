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

### Main vs Sweep

- **main.py**: Runs the backtest once using the current defaults in `config.py`.
  - Use this to inspect a single configuration, generate `trades.csv`, and view summary metrics.
  - Good for day-to-day validation and manual review of one setup.

- **sweep.py**: Runs many configurations (a grid or curated scenarios), ranks results, and saves outputs.
  - Use this to compare permutations and find robust settings.
  - Saves all runs to `sweep_results.csv` and the best scenario's trades to `trades_best.csv`.

Quick sweep (fast, reduced permutations):
```bash
python sweep.py --top 20
```

Full curated scenarios (~432 combos):
```bash
python sweep.py --full-scenarios --top 20
```

Range mode (broader permutations, 5-point increments on risk and gap sizes):
```bash
python sweep.py --range-grid --workers 2 --top 20
```
- In range mode, `points_tp` and `points_sl` are swept in steps of 5 (5..25).
- `gap_size_min_pts`/`gap_size_max_pts` are swept on 5-point increments and validated so that min < max and both are multiples of 5.
- Taps and delivery speed are limited to coherent bands to avoid explosion (e.g., taps (0,1)/(2,3); delivery (None,2)/(3,5)).

Reliability filter (avoid tiny-sample winners):
```bash
python sweep.py --min-trades 25 --top 20
```

Resource control:
```bash
# Sequential (default) keeps CPU/fans quieter
python sweep.py --workers 1

# Parallel (faster, higher CPU)
python sweep.py --workers 4
```

Resume long sweeps (skip already-computed combos and append as you go):
```bash
python sweep.py --range-grid --workers 2 --resume --out sweep_results.csv
```
- A stable signature is computed for each scenario; on `--resume`, the script reads `--out` and skips duplicates.
- Results append incrementally so you can stop and continue later.
- The “best” scenario is selected across both previous and current results.

Outputs:
- All results auto-save to `sweep_results.csv` (override with `--out PATH`).
- Best scenario’s trades auto-save to `trades_best.csv` (override with `--best-trades-out PATH`).
- Console prints best parameters and up to 200 rows of trades (truncates if larger).

Analysis (find which variables correlate with target metric):
```bash
python sweep.py --range-grid --workers 2 --analyze --target-metric profit_factor --analysis-out sweep_analysis.csv
```
- Builds features from scenario parameters, computes Pearson/Spearman correlations, standardized linear regression coefficients, and permutation importance against the chosen target (`profit_factor` by default).
- Prints top-ranked features and writes the full table to `sweep_analysis.csv`.

Run a single scenario by JSON:
```bash
python sweep.py --grid '{"entry_touch_type":"tap_only","allowed_time_buckets":["0930-0945"]}' --best-trades-out trades_best.csv
```

Scenario dimensions controlled in `config.py` and enforced in `models.py`:
- entry_touch_type: tap_only | close_inside_only | None
- min_gap_taps / max_gap_taps
- penetrated_midline: True | False | None
- allowed_time_buckets: ["0930-0945", "0945-1000", "1000-1015"] or None
- first_five_only: True | None
- gap_size_min_pts / gap_size_max_pts
- min_bars_to_prev_break / max_bars_to_prev_break

Notes:
- In range mode, time buckets default to None to constrain combo count; you can still pass a custom JSON grid to explore time windows.
- You can fully control permutations with a custom grid via `--grid` (JSON text or path). For example:
  ```bash
  python sweep.py --grid '{"points_tp":[10,15,20],"points_sl":[10,15,20],"entry_touch_type":[null,"tap_only","close_inside_only"]}'
  ```

Progress bar shows elapsed and ETA; if `tqdm` is installed it will use it automatically.

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
