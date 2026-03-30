#!/usr/bin/env python3
"""Study: FVGC performance broken down by day of week."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from fvgc.data import load_candles
from fvgc.model import generate_signals
from fvgc.engine import simulate_trades, summarize_results, print_summary

DATA_PATH = Path('data/consolidated/nq-front-month.ohlcv-30s.csv')

DAY_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday',
             'Saturday', 'Sunday']


def main():
    candles = load_candles(DATA_PATH)
    signals, _fvgs = generate_signals(candles)
    results = simulate_trades(signals, candles)

    print("=" * 60)
    print("FVGC Performance by Day of Week")
    print("=" * 60)

    for dow in range(5):  # Mon–Fri
        day_results = [r for r in results if r['timestamp'].weekday() == dow]
        if not day_results:
            continue
        print(f"\n--- {DAY_NAMES[dow]} ({len(day_results)} signals) ---")
        stats = summarize_results(day_results)
        print_summary(stats)


if __name__ == '__main__':
    main()
