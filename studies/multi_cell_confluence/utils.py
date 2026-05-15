"""Shared utilities for the multi-cell confluence matrix study.

All metric computations live here so phase scripts share one source of truth.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
STUDY_DIR = Path(__file__).resolve().parent
RESULTS_DIR = STUDY_DIR / 'results'
CACHE_DIR = STUDY_DIR / 'cache'

TRADES_PATH = ROOT / 'studies' / 'mfe_multi_r' / 'results' / 'mfe_trades_enriched.csv'
TRADING_DAYS_PATH = ROOT / 'data' / 'trading_days' / 'trading_days.csv'
ANALYSIS_FRAME_PATH = RESULTS_DIR / 'trades_analysis.csv'

OOS_SPLIT_DATE = pd.Timestamp('2025-10-01')

R_LEVELS = ['1_0', '1_5', '2_0', '2_5', '3_0', '4_0', '5_0']

WINDOWS = ['M1', 'M2', 'M3', 'M4']
DIRECTIONS = ['long', 'short']


def derive_macro_window(ts: pd.Series) -> pd.Series:
    """Map entry timestamps to M1/M2/M3/M4. Trades outside 9:30-10:30 return NaN.

    M1 = [09:30, 09:45), M2 = [09:45, 10:00), M3 = [10:00, 10:15), M4 = [10:15, 10:30).
    """
    minute_of_day = ts.dt.hour * 60 + ts.dt.minute
    open_min = 9 * 60 + 30
    out = pd.Series(pd.NA, index=ts.index, dtype='object')
    out[(minute_of_day >= open_min) & (minute_of_day < open_min + 15)] = 'M1'
    out[(minute_of_day >= open_min + 15) & (minute_of_day < open_min + 30)] = 'M2'
    out[(minute_of_day >= open_min + 30) & (minute_of_day < open_min + 45)] = 'M3'
    out[(minute_of_day >= open_min + 45) & (minute_of_day < open_min + 60)] = 'M4'
    return out


def compute_60d_regime(trading_days: pd.DataFrame,
                       bull_thresh: float = 0.05,
                       bear_thresh: float = -0.05) -> pd.DataFrame:
    """Compute NQ 60-trading-day return and bull/bear/neutral label per date.

    Returns a DataFrame with columns: date, ret_60d, regime_60d.
    """
    td = trading_days[['date', 'rth_close']].copy()
    td['date'] = pd.to_datetime(td['date'])
    td = td.dropna(subset=['rth_close']).sort_values('date').reset_index(drop=True)
    td['ret_60d'] = td['rth_close'].pct_change(60)
    td['regime_60d'] = 'neutral'
    td.loc[td['ret_60d'] > bull_thresh, 'regime_60d'] = 'bull'
    td.loc[td['ret_60d'] < bear_thresh, 'regime_60d'] = 'bear'
    td.loc[td['ret_60d'].isna(), 'regime_60d'] = pd.NA
    return td[['date', 'ret_60d', 'regime_60d']]


def load_analysis_frame() -> pd.DataFrame:
    """Load the post-Phase-A analysis frame. Caller must ensure it's built."""
    if not ANALYSIS_FRAME_PATH.exists():
        raise FileNotFoundError(
            f"Run build_analysis_frame.py first; missing {ANALYSIS_FRAME_PATH}")
    df = pd.read_csv(ANALYSIS_FRAME_PATH)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df['date'] = pd.to_datetime(df['date'])
    return df


def cell_filter(df: pd.DataFrame, window: str, direction: str,
                exclude_protected_swing: bool = True,
                is_only: bool = False, oos_only: bool = False) -> pd.DataFrame:
    """Return the trades belonging to a (window, direction) cell."""
    mask = (df['macro_window'] == window) & (df['direction'] == direction)
    if exclude_protected_swing:
        mask &= df['variant'] != 'protected_swing'
    if is_only:
        mask &= df['split'] == 'IS'
    if oos_only:
        mask &= df['split'] == 'OOS'
    return df.loc[mask].copy()


def cell_metrics(sub: pd.DataFrame) -> dict:
    """Compute the standard metric block for one slice of trades.

    Returns: n, wins, losses, wr_pct, pf_at_2r, hit_1_0R..hit_5_0R rates,
             median_mfe_r_among_1r_plus, max_r_hit_per_trade.
    """
    n = len(sub)
    if n == 0:
        return _empty_metrics()

    outcome = sub['outcome'].astype(str)
    wins = int((outcome == 'win').sum())
    losses = int((outcome == 'loss').sum())
    wl = wins + losses
    wr_pct = 100.0 * wins / wl if wl else float('nan')

    out = {
        'n': n,
        'wins': wins,
        'losses': losses,
        'wr_pct': round(wr_pct, 1) if wl else float('nan'),
    }

    # Hit rates and PF @ 2R
    for r in R_LEVELS:
        col = f'hit_{r}R'
        if col in sub.columns:
            hits = sub[col].astype(bool).sum()
            out[f'hit_{r}R_pct'] = round(100.0 * hits / n, 1) if n else float('nan')
            out[f'hit_{r}R_n'] = int(hits)
        else:
            out[f'hit_{r}R_pct'] = float('nan')
            out[f'hit_{r}R_n'] = 0

    # PF @ 2R: assume held to 2R TP, SL=1R. Hit_2_0R win = +2R, else loss = -1R.
    # This is the standard "PF if you'd held to 2R" interpretation.
    hits_2r = int(sub['hit_2_0R'].astype(bool).sum()) if 'hit_2_0R' in sub.columns else 0
    n_no_2r = n - hits_2r
    if n_no_2r > 0:
        out['pf_at_2r'] = round((hits_2r * 2.0) / (n_no_2r * 1.0), 2)
    else:
        out['pf_at_2r'] = float('inf') if hits_2r > 0 else float('nan')

    # Max R hit per trade (no mfe_r — derived from hit_X_R ladder)
    sub_max_r = max_r_hit(sub)
    # Median MFE among trades that hit at least 1R
    one_r_plus = sub_max_r[sub_max_r >= 1.0]
    out['median_mfe_r_1r_plus'] = round(float(one_r_plus.median()), 2) if len(one_r_plus) else float('nan')
    out['n_1r_plus'] = int(len(one_r_plus))

    return out


def max_r_hit(sub: pd.DataFrame) -> pd.Series:
    """Per-trade max R level hit, derived ONLY from hit_X_R cols (not buggy mfe_r).

    Returns float series of {0, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0}.
    0 = stopped before 1R, 5.0 = hit 5R.
    """
    r_values = [1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0]
    cols = [f'hit_{r}R' for r in R_LEVELS]
    out = pd.Series(0.0, index=sub.index, dtype=float)
    for r_val, col in zip(r_values, cols):
        if col in sub.columns:
            out = out.where(~sub[col].astype(bool), r_val)
    return out


def trades_per_month(sub: pd.DataFrame) -> float:
    """Approximate trades-per-calendar-month frequency for a cell."""
    if len(sub) == 0 or 'date' not in sub.columns:
        return float('nan')
    dates = pd.to_datetime(sub['date'])
    span_days = max((dates.max() - dates.min()).days, 1)
    span_months = span_days / 30.4375
    return round(len(sub) / span_months, 2) if span_months > 0 else float('nan')


def _empty_metrics() -> dict:
    out = {'n': 0, 'wins': 0, 'losses': 0, 'wr_pct': float('nan'), 'pf_at_2r': float('nan')}
    for r in R_LEVELS:
        out[f'hit_{r}R_pct'] = float('nan')
        out[f'hit_{r}R_n'] = 0
    out['median_mfe_r_1r_plus'] = float('nan')
    out['n_1r_plus'] = 0
    return out


def cell_metrics_with_freq(sub: pd.DataFrame, total_span_days: float | None = None) -> dict:
    """cell_metrics + trades_per_month using the GLOBAL date span (so freq is comparable
    across cells with different sample sizes)."""
    m = cell_metrics(sub)
    if total_span_days is not None and total_span_days > 0:
        m['trades_per_month'] = round(len(sub) / (total_span_days / 30.4375), 2)
    else:
        m['trades_per_month'] = trades_per_month(sub)
    return m
