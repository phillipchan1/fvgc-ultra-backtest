#!/usr/bin/env python3
"""
Orchestrator: session H/L + HTF FVG rows → single data/levels/liquidity_levels.csv
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from data.levels.build_htf_fvgs import build_htf_dataframe  # noqa: E402
from data.levels.build_session_levels import (  # noqa: E402
    LIQUIDITY_COLUMN_ORDER,
    build_session_dataframe,
)

OUTPUT_PATH = ROOT / 'data' / 'levels' / 'liquidity_levels.csv'


def main() -> pd.DataFrame:
    print('Building session rows...')
    df_s = build_session_dataframe()
    print('Building HTF FVG rows...')
    df_h = build_htf_dataframe()
    out = pd.concat([df_s, df_h], ignore_index=True)
    for c in LIQUIDITY_COLUMN_ORDER:
        if c not in out.columns:
            out[c] = pd.NA
    out = out[list(LIQUIDITY_COLUMN_ORDER)]
    out = out.sort_values(['date', 'group', 'level_name'], kind='mergesort').reset_index(drop=True)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUTPUT_PATH, index=False)
    print(f'Wrote {len(out)} rows to {OUTPUT_PATH}')
    return out


if __name__ == '__main__':
    main()
