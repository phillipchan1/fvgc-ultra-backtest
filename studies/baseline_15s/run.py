#!/usr/bin/env python3
"""Indicator-only baseline: full consolidated 15s history, no narrative filters."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from fvgc import __version__
from fvgc.data import load_candles
from fvgc.model import generate_signals
from fvgc.engine import (
    simulate_trades, summarize_results, print_summary, log_signals, log_fvgs,
)

DATA_PATH = Path('data/consolidated/nq-front-month.ohlcv-15s.csv')
LOGS_DIR = Path('logs')


def main():
    print("=" * 60)
    print(f"FVGC v{__version__} — Indicator baseline (15s, full history)")
    print("=" * 60)
    LOGS_DIR.mkdir(exist_ok=True)

    candles = load_candles(DATA_PATH)
    tmin = candles['timestamp_ny'].min()
    tmax = candles['timestamp_ny'].max()
    print(f"\nData range (NY): {tmin} → {tmax}")
    print(f"Bars: {len(candles):,}")

    print("\nDetecting FVGs and scanning for entries ...")
    signals, fvgs = generate_signals(candles)

    print(f"\nTotal FVGs: {len(fvgs)}")
    print(f"Total signals: {len(signals)}")

    print("\nSimulating trades ...")
    results = simulate_trades(signals, candles)

    stats = summarize_results(results)
    print("\n--- Full-history summary (15s) ---")
    print_summary(stats)

    out_trades = LOGS_DIR / 'baseline_15s_trades.csv'
    out_fvgs = LOGS_DIR / 'baseline_15s_fvgs.csv'
    log_signals(results, path=out_trades)
    log_fvgs(fvgs, path=out_fvgs)
    print(f"\nBaseline artifacts: {out_trades}, {out_fvgs}")


if __name__ == '__main__':
    main()
