# FVGC Backtest

Fair Value Gap Continuation (FVGC) model and backtesting toolkit for NQ futures.

## Repository Structure

```
fvgc/                   Core Python package
  constants.py          Tunable parameters (SL/TP, lookback, windows)
  data.py               Data loading and aggregation
  model.py              FVGC v2.0.5 entry model (signal detection)
  engine.py             Trade simulation, statistics, logging

tools/                  CLI scripts
  run_backtest.py       Run the full backtest pipeline
  consolidate_data.py   Build consolidated front-month candle files

studies/                Narrative-driven analyses
  _template/            Copy to start a new study
  day_of_week/          Example: performance by day of week

data/                   OHLCV data (Git LFS)
  raw/                  Raw 1s Databento exports
  consolidated/         Pre-aggregated 30s/15s candles
  trading_days/         (Future) Trading day metadata

logs/                   Runtime output (gitignored)
```

## Quick Start

```bash
pip install -r requirements.txt

# Run backtest with last 14 days output
python tools/run_backtest.py --last-days 14

# Use a specific data file
python tools/run_backtest.py --data data/raw/glbx-mdp3-20260226-20260325.ohlcv-1s.csv --last-days 14

# Run a study
python studies/day_of_week/run.py
```

## Model Version

Current: **v2.0.5** — See `fvgc/model.py` for full version history.

The entry model in `fvgc/model.py` is considered validated. Changes require a
corresponding Notion spec version bump and parity verification.
