#!/usr/bin/env python3
"""CLI entry point for the FVGC backtester."""

import sys
from pathlib import Path

# Allow running from repo root: `python tools/run_backtest.py`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse
from datetime import timedelta

from fvgc.data import load_candles
from fvgc.model import generate_signals
from fvgc.engine import (
    simulate_trades, summarize_results, print_summary,
    log_signals, log_fvgs,
)
from fvgc import __version__

DEFAULT_DATA = Path('data/consolidated/nq-front-month.ohlcv-30s.csv')
LOGS_DIR = Path('logs')


def main():
    parser = argparse.ArgumentParser(description=f'FVGC v{__version__} signal detector')
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument(
        '--last-days', type=int, metavar='N',
        help='Print signals from the last N calendar days',
    )
    scope.add_argument(
        '--baseline', action='store_true',
        help='Full history: summary stats only (no per-trade listing); writes logs/baseline_*.csv',
    )
    parser.add_argument(
        '--data', type=Path, default=DEFAULT_DATA, metavar='PATH',
        help=f'Path to OHLCV CSV (default: {DEFAULT_DATA})',
    )
    args = parser.parse_args()

    print("=" * 60)
    print(f"FVGC v{__version__} Signal Detector")
    print("=" * 60)
    LOGS_DIR.mkdir(exist_ok=True)

    candles = load_candles(args.data)

    print("\nDetecting FVGs and scanning for entries ...")
    signals, fvgs = generate_signals(candles)

    print(f"\nTotal FVGs across all days: {len(fvgs)}")
    print(f"Total signals across all days: {len(signals)}")

    print("\nSimulating trades ...")
    signals = simulate_trades(signals, candles)

    if args.baseline:
        stats = summarize_results(signals)
        print("\n--- Full-history baseline (indicator only) ---")
        print_summary(stats)
        log_signals(signals, path=LOGS_DIR / 'baseline_trades.csv')
        log_fvgs(fvgs, path=LOGS_DIR / 'baseline_fvgs.csv')
        print(f"\nWrote {LOGS_DIR / 'baseline_trades.csv'}, {LOGS_DIR / 'baseline_fvgs.csv'}")
        return

    if args.last_days is not None:
        end_d = candles['timestamp_ny'].max().date()
        start_d = end_d - timedelta(days=args.last_days - 1)
        filtered = [s for s in signals if start_d <= s['timestamp'].date() <= end_d]
        print(f"\n--- Last {args.last_days} calendar days ({start_d} → {end_d}): "
              f"{len(filtered)} signals ---")
        for s in filtered:
            sl = s.get('sl', '')
            tp = s.get('tp', '')
            sl_s = f'{sl:.2f}' if sl != '' else 'skip'
            tp_s = f'{tp:.2f}' if tp != '' else 'skip'
            outcome = s.get('outcome', '')
            pnl = s.get('pnl', '')
            pnl_s = f'{pnl:+.2f}' if pnl != '' else ''
            exit_t = s.get('exit_time', '')
            exit_t_s = exit_t.strftime('%H:%M:%S') if hasattr(exit_t, 'strftime') else ''
            out_s = f'{outcome:4s}' if outcome else ''
            print(f"  {s['timestamp'].strftime('%Y-%m-%d %H:%M:%S')} {s['direction']:5s} "
                  f"@ {s['entry_price']:.2f}  [{s['variant']:15s}]  "
                  f"SL={sl_s:>9s} TP={tp_s:>9s}  "
                  f"{out_s} {pnl_s:>8s}  exit={exit_t_s}")

        stats = summarize_results(filtered)
        print_summary(stats)

        out = LOGS_DIR / f'trades_last_{args.last_days}d.csv'
        log_signals(filtered, path=out)
    else:
        for s in signals:
            print(f"  {s['timestamp'].strftime('%Y-%m-%d %H:%M:%S')} {s['direction']:5s} "
                  f"@ {s['entry_price']:.2f}  [{s['variant']}]  "
                  f"FVG#{s['fvg_id']} ({s['fvg_direction']})")

    log_fvgs(fvgs, path=LOGS_DIR / 'fvgs.csv')
    log_signals(signals, path=LOGS_DIR / 'trades_generated.csv')


if __name__ == '__main__':
    main()
