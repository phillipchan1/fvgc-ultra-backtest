#!/usr/bin/env python3
"""Date-based train/test split + factor bucketers shared by phases B–F.

Discovery (B,C,D) runs on TRAIN only; TEST is reserved for Phase E OOS.
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from studies.swept_fvgc_break_retest.metrics import tradeable  # noqa: E402

RESULTS_DIR = Path(__file__).resolve().parent / 'results'
TRAIN_FRAC = 0.70


def load_tradeable() -> pd.DataFrame:
    df = pd.read_csv(RESULTS_DIR / 'signals_simulated.csv')
    tr = tradeable(df)
    tr['ts'] = pd.to_datetime(tr['timestamp'])
    tr['date'] = tr['ts'].dt.date
    tr['tod'] = tr['ts'].dt.time
    return tr.reset_index(drop=True)


def train_test(df: pd.DataFrame, frac: float = TRAIN_FRAC):
    dates = sorted(df['date'].unique())
    cut = int(len(dates) * frac)
    train_dates = set(dates[:cut])
    tr = df[df['date'].isin(train_dates)].copy()
    te = df[~df['date'].isin(train_dates)].copy()
    return tr, te


def early_late(df: pd.DataFrame):
    dates = sorted(df['date'].unique())
    mid = len(dates) // 2
    early_dates = set(dates[:mid])
    return df[df['date'].isin(early_dates)].copy(), df[~df['date'].isin(early_dates)].copy()


# ===================================================================
# Factor bucketers: factor_name -> categorical Series aligned to df.index
# ===================================================================

def _mag_R_bucket(v):
    if pd.isna(v):
        return 'none'
    if v <= 1:
        return '<=1R'
    if v <= 2:
        return '1-2R'
    if v <= 3:
        return '2-3R'
    return '>3R'


def _touch_bucket(v):
    if pd.isna(v):
        return 'na'
    v = int(v)
    if v <= 1:
        return '1'
    if v == 2:
        return '2'
    if v <= 5:
        return '3-5'
    return '>5'


def _conf_bucket(v):
    if pd.isna(v):
        return 'na'
    v = int(v)
    return str(v) if v <= 2 else '3+'


def _htf_pos_bucket(v):
    if pd.isna(v):
        return 'na'
    if v <= 0.33:
        return 'near'
    if v <= 0.66:
        return 'mid'
    return 'far'


def _provenance_class(g):
    g = str(g)
    if g.startswith('round'):
        return 'round'
    if g.startswith('htf_fvg'):
        return 'htf'
    if g in ('prev_day', 'overnight', 'asia', 'london', '6am'):
        return 'session_hl'
    if g == 'opening_range':
        return 'or'
    if g == 'bsl_ssl':
        return 'bsl_ssl'
    if g == 'nwog':
        return 'nwog'
    return 'other'


def _magnet_group_class(g):
    g = str(g)
    if g.startswith('round'):
        return 'round'
    if g.startswith('htf_fvg'):
        return 'htf'
    if g == 'vwap':
        return 'vwap'
    if g.startswith('prior_') or g.startswith('dev_'):
        return 'vp'
    if g in ('prev_day', 'overnight', 'asia', 'london', '6am', 'opening_range', 'bsl_ssl', 'nwog'):
        return 'session'
    return 'other'


def _or_width_bucket(v):
    if pd.isna(v):
        return 'na'
    if v <= 20:
        return 'tight<=20'
    if v <= 40:
        return 'mid20-40'
    return 'wide>40'


def _per_bucket(v):
    if pd.isna(v):
        return 'none'
    if v <= 1:
        return '<=1'
    if v <= 3:
        return '1-3'
    return '>3'


def factor_buckets(df: pd.DataFrame) -> dict[str, pd.Series]:
    f: dict[str, pd.Series] = {}
    f['direction'] = df['direction'].astype(str)
    f['sweep_type'] = df['sweep_type'].astype(str)
    f['provenance'] = df['swept_level_provenance'].map(_provenance_class)
    f['bars_since_sweep'] = df['bars_since_sweep_bucket'].astype(str)
    f['retest_within_10min'] = df['retest_within_10min'].astype(str)
    f['btr_timing'] = df['bars_break_to_retest_bucket'].astype(str)
    f['magnet_R'] = df['magnet_dist_R'].map(_mag_R_bucket)
    f['magnet_per_fvg'] = df['magnet_dist_per_fvg'].map(_per_bucket)
    f['magnet_per_atr'] = df['magnet_dist_per_atr'].map(_per_bucket)
    f['clean_runway'] = df['clean_runway'].astype(str)
    f['magnet_group'] = df['magnet_group'].map(_magnet_group_class)
    f['vwap_above'] = df['vwap_above'].astype(str)
    f['r0_ge_10pt'] = df['r0_ge_10pt'].astype(str)
    f['va_pos_prior'] = df['va_pos_prior'].astype(str)
    f['va_pos_dev'] = df['va_pos_dev'].astype(str)
    f['level_virgin'] = df['level_virgin'].astype(str)
    f['level_touch'] = df['level_touch_count'].map(_touch_bucket)
    f['confluence_stack'] = df['confluence_stack'].map(_conf_bucket)
    f['inside_htf_fvg'] = df['inside_htf_fvg'].astype(str)
    f['htf_aligned'] = df['htf_aligned'].astype(str)
    f['htf_position'] = df['htf_position_within_gap'].map(_htf_pos_bucket)
    f['macro_trend'] = df['macro_trend'].astype(str)
    f['regime_alignment'] = df['regime_alignment'].astype(str)
    f['vixy_regime'] = df['vixy_regime'].astype(str)
    f['prior_day_type'] = df['prior_day_type'].astype(str)
    f['open_vs_prior_va'] = df['open_vs_prior_va'].astype(str)
    f['or_width'] = df['or_width_asof'].map(_or_width_bucket)
    f['price_above_dev_vwap'] = df['price_above_dev_vwap'].astype(str)
    f['variant'] = df['variant'].astype(str)
    # swept-level tightness (distance FVG-mid -> swept level)
    fvg_mid = (df['fvg_top'] + df['fvg_bottom']) / 2.0
    dist = (df['swept_level_price'] - fvg_mid).abs()

    def _tight(v):
        if pd.isna(v):
            return 'none'
        if v <= 2:
            return '<=2'
        if v <= 5:
            return '2-5'
        if v <= 10:
            return '5-10'
        return '10-20'
    f['swept_tightness'] = dist.map(_tight)
    return f
