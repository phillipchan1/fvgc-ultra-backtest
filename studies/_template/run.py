#!/usr/bin/env python3
"""Study template — copy this folder to start a new analysis."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from fvgc.data import load_candles
from fvgc.model import generate_signals
from fvgc.engine import simulate_trades, summarize_results, print_summary

DATA_PATH = Path('data/consolidated/nq-front-month.ohlcv-30s.csv')


def main():
    candles = load_candles(DATA_PATH)
    signals, _fvgs = generate_signals(candles)
    results = simulate_trades(signals, candles)

    # --- Apply your study-specific filter here ---
    # Example: filtered = [r for r in results if some_condition(r)]
    filtered = results

    stats = summarize_results(filtered)
    print_summary(stats)


if __name__ == '__main__':
    main()
