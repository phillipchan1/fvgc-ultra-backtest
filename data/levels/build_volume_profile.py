#!/usr/bin/env python3
"""
Build daily volume profile (POC/VAH/VAL) from consolidated NQ 30s candles.

Output: data/levels/daily_volume_profile.csv
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from data.levels.nq_1m_front import load_nq_consolidated  # noqa: E402
from fvgc.volume_profile import build_daily_vp  # noqa: E402

OUTPUT_PATH = ROOT / 'data' / 'levels' / 'daily_volume_profile.csv'


def main():
    print('=== Build Daily Volume Profile ===')
    candles = load_nq_consolidated(verbose=True)
    df = build_daily_vp(candles, output_path=OUTPUT_PATH)

    if df.empty:
        print('WARNING: no VP rows produced')
        return

    print(f'\nSummary:')
    print(f'  Date range: {df["date"].min()} to {df["date"].max()}')
    print(f'  Trading days: {len(df)}')
    print(f'  Mean POC: {df["poc"].mean():.2f}')
    print(f'  Mean VA width: {df["va_width"].mean():.1f} pts')
    print(f'  Median VA width: {df["va_width"].median():.1f} pts')
    print(f'  Mean RTH volume: {df["rth_volume"].mean():,.0f}')


if __name__ == '__main__':
    main()
