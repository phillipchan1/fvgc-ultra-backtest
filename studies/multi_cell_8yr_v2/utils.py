"""Shared constants for the 8yr v2 matrix study.

This study re-runs the multi_cell_confluence work on the extended 2018-2026
dataset. We override paths/dates from the original study but reuse its
factor-mining and tier-construction logic.

Convention follows m1_short_factor_remine: IS = 2018-01-01 to 2024-12-31,
OOS = 2025-01-01 to 2026-05-15.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
STUDY_DIR = Path(__file__).resolve().parent
RESULTS_DIR = STUDY_DIR / 'results'

# Inputs
TRADES_PATH = ROOT / 'studies' / 'mfe_multi_r' / 'results' / 'mfe_trades_enriched.csv'
TRADING_DAYS_PATH = ROOT / 'data' / 'trading_days' / 'trading_days.csv'
OLD_CELL_CONFIGS_PATH = ROOT / 'studies' / 'multi_cell_confluence' / 'results' / 'cell_configs.json'

# Outputs
ANALYSIS_FRAME_PATH = RESULTS_DIR / 'trades_analysis_8yr.csv'

# IS/OOS split — matches m1_short_factor_remine precedent
OOS_SPLIT_DATE = pd.Timestamp('2025-01-01')
TRAIN_START = pd.Timestamp('2018-01-01')

# Cells with a published Notion page (priority for reporting)
NOTION_CELLS = ('M1_short', 'M2_long', 'M3_long')
ALL_CELLS_OLD = ('M1_long', 'M1_short', 'M2_long', 'M2_short', 'M3_long', 'M3_short')

# Phase C: new windows to discover
NEW_WINDOWS = ('M4',)
NEW_DIRECTIONS = ('long', 'short')

# Tiering convention from original study
TIER_BINS = [-0.5, 1.5, 2.5, 3.5, 99]
TIER_LABELS = ['0-1', '2', '3', '4+']
