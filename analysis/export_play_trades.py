#!/usr/bin/env python3
"""
Export filtered trade lists for each play in the FVGC Playbook.

Generates one CSV per play in analysis/results/play_trades/ with the exact
trades that match each play's conditions. Used for manual backtesting verification.

Usage:
    python analysis/export_play_trades.py
"""

import sys
from pathlib import Path
from datetime import time as dtime

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd

from analysis.permutation_test import load_data

OUT_DIR = ROOT / 'analysis' / 'results' / 'play_trades'
OUT_COLS = ['date', 'entry_time', 'direction', 'outcome', 'pnl',
            'entry_price', 'exit_price', 'sl_dist', 'variant', 'macro_window']

PLAYS = {}


def register(name):
    def decorator(fn):
        PLAYS[name] = fn
        return fn
    return decorator


# ─── Play definitions ────────────────────────────────────────────────────────

@register('930_gap_short')
def play_930_gap_short(df: pd.DataFrame, trades_raw: pd.DataFrame) -> pd.DataFrame:
    """
    Short FVGC entries where the FVG was created in the RTH opening window
    (9:29:30–9:31:00 ET). Long setups in this window are excluded.
    """
    NY_TZ = 'America/New_York'
    t = trades_raw.copy()
    t = t[t['outcome'].isin(['win', 'loss'])]
    t['fvg_created_at'] = pd.to_datetime(t['fvg_created_at'], errors='coerce')
    if t['fvg_created_at'].dt.tz is None:
        t['fvg_created_ny'] = t['fvg_created_at'].dt.tz_localize(
            NY_TZ, ambiguous='infer', nonexistent='shift_forward'
        )
    else:
        t['fvg_created_ny'] = t['fvg_created_at'].dt.tz_convert(NY_TZ)

    wstart, wend = dtime(9, 29, 30), dtime(9, 31, 0)
    t['in_window'] = t['fvg_created_ny'].apply(
        lambda x: False if pd.isna(x) else wstart <= x.time() <= wend
    )
    t['timestamp'] = pd.to_datetime(t['timestamp'])
    t['date'] = t['timestamp'].dt.date
    t['entry_time'] = t['timestamp'].dt.time
    result = t[t['in_window'] & (t['direction'] == 'short')].copy()
    # Add macro_window (already computed in df via load_data; do it here simply)
    result['macro_window'] = 1
    return result


@register('prior_day_down_short')
def play_prior_day_down_short(df: pd.DataFrame, trades_raw: pd.DataFrame) -> pd.DataFrame:
    """
    Short entries on days where prior day closed in the bottom quartile
    (prior_day_close_position < 0.25). Any macro window.
    """
    return df[
        (df['prior_day_close_position'] < 0.25) &
        (df['direction'] == 'short')
    ].copy()


@register('gap_down_short_macro1')
def play_gap_down_short_macro1(df: pd.DataFrame, trades_raw: pd.DataFrame) -> pd.DataFrame:
    """
    Short entries in Macro 1 (9:30–9:45) on days where NQ gapped down
    from prior close (gap_from_prior_close < 0).
    """
    return df[
        (df['gap_from_prior_close'] < 0) &
        (df['macro_window'] == 1) &
        (df['direction'] == 'short')
    ].copy()


@register('bearish_930_candle_short')
def play_bearish_930_candle_short(df: pd.DataFrame, trades_raw: pd.DataFrame) -> pd.DataFrame:
    """
    Short entries in Macro 2 (9:45–10:00) on days where the 9:30 candle
    closed bearish. Signal only available after 9:45.
    """
    return df[
        (df['candle_930_direction'] == 'bearish') &
        (df['macro_window'] == 2) &
        (df['direction'] == 'short')
    ].copy()


@register('elevated_vixy_short_macro1')
def play_elevated_vixy_short_macro1(df: pd.DataFrame, trades_raw: pd.DataFrame) -> pd.DataFrame:
    """
    Short entries in Macro 1 on days where VIXY regime is elevated or high.
    """
    return df[
        (df['vixy_regime'].isin(['elevated', 'high'])) &
        (df['macro_window'] == 1) &
        (df['direction'] == 'short')
    ].copy()


@register('no_news_macro1_short')
def play_no_news_macro1_short(df: pd.DataFrame, trades_raw: pd.DataFrame) -> pd.DataFrame:
    """
    Short entries in Macro 1 on days with no red-folder news events.
    """
    return df[
        (df['has_red_folder_news'] == False) &
        (df['macro_window'] == 1) &
        (df['direction'] == 'short')
    ].copy()


# ─── Runner ──────────────────────────────────────────────────────────────────

def export(name: str, df_filtered: pd.DataFrame) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cols = [c for c in OUT_COLS if c in df_filtered.columns]
    out = df_filtered[cols].sort_values('date').reset_index(drop=True)
    path = OUT_DIR / f'{name}.csv'
    out.to_csv(path, index=False)
    return path


def main():
    print('Loading trade data...')
    df = load_data()

    trades_raw = pd.read_csv(ROOT / 'logs' / 'baseline_trades.csv')

    print(f'\nExporting play trade lists to {OUT_DIR.relative_to(ROOT)}/\n')
    print(f'{"Play":<40} {"n":>5}  {"WR":>6}  File')
    print('-' * 80)

    for name, fn in PLAYS.items():
        sub = fn(df, trades_raw)
        tradeable = sub[sub['outcome'].isin(['win', 'loss'])]
        n = len(tradeable)
        wr = (tradeable['outcome'] == 'win').mean() * 100 if n else 0
        path = export(name, tradeable)
        rel = path.relative_to(ROOT)
        print(f'{name:<40} {n:>5}  {wr:>5.1f}%  {rel}')

    print('\nDone.')


if __name__ == '__main__':
    main()
