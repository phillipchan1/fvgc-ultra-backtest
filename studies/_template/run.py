#!/usr/bin/env python3
"""Study template — copy this folder to start a new analysis."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from fvgc.data import load_candles
from fvgc.model import generate_signals
from fvgc.engine import simulate_trades, summarize_results, print_summary

DATA_PATH = Path('data/consolidated/nq-front-month.ohlcv-30s.csv')
STUDY_DIR = Path(__file__).resolve().parent
RESULTS_DIR = STUDY_DIR / 'results'


def main():
    candles = load_candles(DATA_PATH)
    signals, _fvgs = generate_signals(candles)
    results = simulate_trades(signals, candles)

    # --- Apply your study-specific filter here ---
    # Example: filtered = [r for r in results if some_condition(r)]
    filtered = results

    stats = summarize_results(filtered)
    print_summary(stats)

    # --- Trade list for verification (required for segmenting studies) ---
    # If you filter trades, write the filtered cohort to results/:
    # rows = [{**r, 'study_flag': True} for r in filtered if ...]
    # pd.DataFrame(rows).to_csv(RESULTS_DIR / 'trades_<cohort>.csv', index=False)
    # RESULTS_DIR.mkdir(parents=True, exist_ok=True)


if __name__ == '__main__':
    main()
