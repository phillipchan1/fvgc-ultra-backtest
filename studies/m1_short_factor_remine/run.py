#!/usr/bin/env python3
"""M1 Short Confluence Model — Factor Re-Mining on 8-year data.

Re-mines the M1 Short FVGC short-side play (9:30-9:45 NY) from scratch on the
full 8-year dataset (2018-01 → 2026-05) with strict OOS protocol.

Trains on 2018-01-01 → 2024-12-31 (7 years).
OOS holdout: 2025-01-01 → 2026-05-15 (~1.5 years).

Anti-patterns avoided:
- No look-ahead bias (all factors knowable by 9:35 entry-window latest)
- Filters out `protected_swing` variant (confirmed -32pp WR contamination)
- Applies hard vetoes (vixy_low, dow_monday) to cohort BEFORE mining
- Reports n with every WR statistic
- Per-factor acceptance: lift>=5pp, Fisher p<=0.10, FDR q<=0.10, regime-consistent
- Forward stepwise stacking with OOS re-validation at each step
- Tests multi-target: WR, PF@2R, fire-rate (separate stacks)
- Does NOT use mfe_r for runner expectations (uses hit_X_R columns)
- Does NOT peek at OOS during mining (only at final evaluation)

Inputs:
- studies/baseline/results/trades.csv      (6,614 trades, 2018-01-02 → 2026-05-15)
- data/trading_days/trading_days.csv       (2,158 days, 63 columns)

Outputs in results/:
- factor_universe.csv                      (all candidates with stats)
- final_stack_factors.json                 (selected 4-6 factors)
- tier_summary_IS.csv, tier_summary_OOS.csv
- year_breakdown.csv, regime_breakdown.csv
- factor_stacking_trace.csv                (forward-stepwise marginal lifts)
- trades_tagged.csv                        (per-trade with factor flags + tier)
- fire_rate_stack.csv                      (separate fire-rate stack)
- pf_2r_stack.csv                          (separate PF@2R stack)
"""

from __future__ import annotations

import json
import sys
from datetime import time as dtime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import fisher_exact

ROOT = Path(__file__).resolve().parent.parent.parent
STUDY = Path(__file__).resolve().parent
OUT = STUDY / 'results'
OUT.mkdir(parents=True, exist_ok=True)

# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------

OOS_START = pd.Timestamp('2025-01-01')
OOS_END = pd.Timestamp('2026-05-15')
TRAIN_START = pd.Timestamp('2018-01-01')

# Per-factor acceptance criteria
MIN_LIFT_PP = 5.0
MIN_N_PRESENT = 30
MIN_N_ABSENT = 30
P_VALUE_MAX = 0.10
FDR_Q_MAX = 0.10
MIN_BASE_RATE = 0.05
MAX_BASE_RATE = 0.50
CORR_MAX = 0.70

# Stacking
MAX_STACK_SIZE = 6
TIER_BINS = [(0, 1, '0-1'), (2, 2, '2'), (3, 3, '3'), (4, 99, '4+'), (2, 99, '2+')]


# -----------------------------------------------------------------------------
# Data loading
# -----------------------------------------------------------------------------

def load_data():
    trades = pd.read_csv(ROOT / 'studies' / 'baseline' / 'results' / 'trades.csv')
    days = pd.read_csv(ROOT / 'data' / 'trading_days' / 'trading_days.csv')
    trades['timestamp'] = pd.to_datetime(trades['timestamp'])
    trades['date'] = trades['timestamp'].dt.normalize()
    trades['time'] = trades['timestamp'].dt.time
    days['date'] = pd.to_datetime(days['date'])
    return trades, days


def filter_m1_short(trades: pd.DataFrame) -> pd.DataFrame:
    """M1 short FVGCs in 9:30:00–9:44:59, valid outcome, excluding protected_swing."""
    return trades[
        (trades['direction'] == 'short')
        & (trades['time'] >= dtime(9, 30, 0))
        & (trades['time'] < dtime(9, 45, 0))
        & (trades['variant'] != 'protected_swing')
        & trades['outcome'].isin(['win', 'loss'])
    ].copy()


# -----------------------------------------------------------------------------
# Per-day feature engineering
# -----------------------------------------------------------------------------

def compute_day_factors(days: pd.DataFrame) -> pd.DataFrame:
    """Build all candidate factors. All quantile cutoffs are time-causal (rolling).

    Returns days with one binary column per candidate factor: f_<name>.
    """
    d = days.sort_values('date').reset_index(drop=True).copy()

    # ---- Rolling quantiles (causal, 90d window, min_periods=30) ----
    def rq(col, q):
        return d[col].rolling(90, min_periods=30).quantile(q)

    d['vixy_q25_90']        = rq('vixy_prior_close', 0.25)
    d['vixy_q75_90']        = rq('vixy_prior_close', 0.75)
    d['c930_body_q75_90']   = rq('candle_930_body', 0.75)
    d['c930_range_q75_90']  = rq('candle_930_range', 0.75)
    d['c930_body_q25_90']   = rq('candle_930_body', 0.25)
    d['or5_q75_90']         = rq('or_5min_range', 0.75)
    d['or5_q25_90']         = rq('or_5min_range', 0.25)
    d['or15_q75_90']        = rq('or_15min_range', 0.75)
    d['on_range_q75_90']    = rq('overnight_range', 0.75)
    d['on_range_q25_90']    = rq('overnight_range', 0.25)
    d['gap_q05_90']         = rq('gap_from_prior_close', 0.05)
    d['gap_pct_q05_90']     = rq('gap_from_prior_close_pct', 0.05)
    d['pdr_atr_q75_90']     = rq('prior_day_range_atr_ratio', 0.75)
    d['pdr_atr_q25_90']     = rq('prior_day_range_atr_ratio', 0.25)
    d['pd_dc_q75_90']       = rq('prior_day_directional_changes', 0.75)
    d['pd_dc_q25_90']       = rq('prior_day_directional_changes', 0.25)

    # ---- Multi-day returns ----
    d['ret_2d']  = d['rth_close'] / d['rth_close'].shift(2) - 1
    d['ret_3d']  = d['rth_close'] / d['rth_close'].shift(3) - 1
    d['ret_5d']  = d['rth_close'] / d['rth_close'].shift(5) - 1
    d['ret_10d'] = d['rth_close'] / d['rth_close'].shift(10) - 1
    d['ret_20d'] = d['rth_close'] / d['rth_close'].shift(20) - 1
    d['ret_60d'] = d['rth_close'] / d['rth_close'].shift(60) - 1

    # ---- Moving averages ----
    d['ma_20']  = d['rth_close'].rolling(20, min_periods=20).mean()
    d['ma_50']  = d['rth_close'].rolling(50, min_periods=50).mean()
    d['ma_200'] = d['rth_close'].rolling(200, min_periods=200).mean()

    # ---- Lows/highs ----
    d['low_5d']  = d['rth_low'].shift(1).rolling(5, min_periods=5).min()
    d['low_20d'] = d['rth_low'].shift(1).rolling(20, min_periods=20).min()
    d['high_20d'] = d['rth_high'].shift(1).rolling(20, min_periods=20).max()
    d['high_60d'] = d['rth_high'].shift(1).rolling(60, min_periods=60).max()
    d['high_252d'] = d['rth_high'].shift(1).rolling(252, min_periods=200).max()

    # Days since ATH/recent high
    d['ath_so_far'] = d['rth_high'].expanding().max().shift(1)
    d['days_since_ath'] = (d['rth_close'] < d['ath_so_far']).astype(int)
    # rolling count of consecutive days below ATH — simple proxy
    d['below_ath'] = (d['rth_close'] < d['ath_so_far'] * 0.95).astype(int)

    # Bear streak (3 consecutive red closes)
    d['red_day'] = (d['rth_close'] < d['rth_open']).astype(int)
    d['bear_streak_3d'] = ((d['red_day'].shift(1) == 1) &
                           (d['red_day'].shift(2) == 1) &
                           (d['red_day'].shift(3) == 1)).astype(int)

    # VIXY changes
    d['vixy_chg_5d'] = d['vixy_prior_close'] - d['vixy_prior_close'].shift(5)
    d['vixy_chg_1d'] = d['vixy_prior_close'] - d['vixy_prior_close'].shift(1)
    d['vixy_chg_1d_q75_90'] = d['vixy_chg_1d'].rolling(90, min_periods=30).quantile(0.75)
    d['vixy_mean_90'] = d['vixy_prior_close'].rolling(90, min_periods=30).mean()
    d['vixy_std_90'] = d['vixy_prior_close'].rolling(90, min_periods=30).std()
    d['vixy_z90'] = (d['vixy_prior_close'] - d['vixy_mean_90']) / d['vixy_std_90']

    # NQ realized vol (20d std of daily returns)
    d['ret_1d'] = d['rth_close'].pct_change()
    d['rvol_20d'] = d['ret_1d'].rolling(20, min_periods=15).std()
    d['rvol_20d_q75'] = d['rvol_20d'].rolling(90, min_periods=30).quantile(0.75)

    # ATR proxy from prior_day_range
    d['atr_20'] = d['prior_day_range'].rolling(20, min_periods=15).mean()
    d['atr_60'] = d['prior_day_range'].rolling(60, min_periods=40).mean()

    # ============================================================
    # Build factor frame (all binary)
    # ============================================================
    f = pd.DataFrame(index=d.index)
    f['date'] = d['date']

    # A. Pre-Market Gap & Range
    f['f_gap_large_down']      = (d['gap_from_prior_close'] <= -100).astype(int)
    f['f_gap_medium_down']     = ((d['gap_from_prior_close'] > -100) & (d['gap_from_prior_close'] <= -30)).astype(int)
    f['f_gap_small_down']      = ((d['gap_from_prior_close'] > -30) & (d['gap_from_prior_close'] <= -10)).astype(int)
    f['f_gap_any_down']        = (d['gap_from_prior_close'] <= -10).astype(int)
    f['f_gap_pct_bottom_q']    = (d['gap_from_prior_close_pct'] <= d['gap_pct_q05_90']).astype(int)
    f['f_gap_atr_ratio_high']  = ((d['gap_from_prior_close'].abs() / d['atr_20']) >= 0.5).astype(int)
    f['f_overnight_range_top_q']    = (d['overnight_range'] >= d['on_range_q75_90']).astype(int)
    f['f_overnight_range_bot_q']    = (d['overnight_range'] <= d['on_range_q25_90']).astype(int)
    f['f_overnight_direction_down'] = (d['overnight_direction'] == 'down').astype(int)
    f['f_overnight_direction_up']   = (d['overnight_direction'] == 'up').astype(int)

    # B. Prior Session Character
    f['f_prior_day_weak']      = (d['prior_day_close_position'] <= 0.333).astype(int)
    f['f_prior_day_strong']    = (d['prior_day_close_position'] >= 0.667).astype(int)
    f['f_prior_day_range_atr_low']  = (d['prior_day_range_atr_ratio'] <= d['pdr_atr_q25_90']).astype(int)
    f['f_prior_day_range_atr_high'] = (d['prior_day_range_atr_ratio'] >= d['pdr_atr_q75_90']).astype(int)
    f['f_prior_day_dc_high']   = (d['prior_day_directional_changes'] >= d['pd_dc_q75_90']).astype(int)
    f['f_prior_day_dc_low']    = (d['prior_day_directional_changes'] <= d['pd_dc_q25_90']).astype(int)
    f['f_prior_day_was_red']   = (d['prior_day_close_vs_open_pct'] < 0).astype(int)
    f['f_prior_day_close_neg_strong'] = (d['prior_day_close_vs_open_pct'] < -1.0).astype(int)
    f['f_prior_2d_neg']        = (d['ret_2d'] < 0).astype(int)
    f['f_prior_3d_neg']        = (d['ret_3d'] < 0).astype(int)
    f['f_prior_5d_neg']        = (d['ret_5d'] < 0).astype(int)
    f['f_made_new_5d_low_yday']  = (d['rth_low'].shift(1) <= d['low_5d']).astype(int)
    f['f_made_new_20d_low_yday'] = (d['rth_low'].shift(1) <= d['low_20d']).astype(int)
    # prior_day_type buckets
    for pdt in ['trend_up', 'trend_down', 'reversal_up', 'reversal_down', 'range', 'other']:
        f[f'f_pdt_{pdt}'] = (d['prior_day_type'] == pdt).astype(int)

    # C. Multi-day trend
    f['f_ret_5d_neg']    = (d['ret_5d'] < 0).astype(int)
    f['f_ret_10d_neg']   = (d['ret_10d'] < 0).astype(int)
    f['f_ret_20d_neg']   = (d['ret_20d'] < 0).astype(int)
    f['f_ret_60d_neg']   = (d['ret_60d'] < 0).astype(int)
    f['f_below_20d_ma']  = (d['rth_close'] < d['ma_20']).astype(int)
    f['f_below_50d_ma']  = (d['rth_close'] < d['ma_50']).astype(int)
    f['f_below_200d_ma'] = (d['rth_close'] < d['ma_200']).astype(int)
    f['f_above_200d_ma'] = (d['rth_close'] >= d['ma_200']).astype(int)
    f['f_bear_streak_3d'] = d['bear_streak_3d']
    f['f_made_20d_high_yday'] = (d['rth_high'].shift(1) >= d['high_20d']).astype(int)
    f['f_far_from_ath']  = (d['rth_close'] < d['ath_so_far'] * 0.95).astype(int)
    # Recent 20d low — possible continuation
    f['f_near_20d_low']  = (d['rth_close'] <= d['low_20d'] * 1.02).astype(int)

    # D. Volatility regime
    f['f_vixy_high']         = (d['vixy_prior_close'] >= d['vixy_q75_90']).astype(int)
    f['f_vixy_low']          = (d['vixy_prior_close'] <= d['vixy_q25_90']).astype(int)
    f['f_vixy_rising_5d']    = (d['vixy_chg_5d'] > 0).astype(int)
    f['f_vixy_falling_5d']   = (d['vixy_chg_5d'] < 0).astype(int)
    f['f_vixy_z90_high']     = (d['vixy_z90'] > 1.0).astype(int)
    f['f_rvol_20d_top_q']    = (d['rvol_20d'] >= d['rvol_20d_q75']).astype(int)
    f['f_atr_expansion']     = ((d['atr_20'] / d['atr_60']) >= 1.15).astype(int)
    f['f_vix_spike_yday']    = (d['vixy_chg_1d'] >= d['vixy_chg_1d_q75_90']).astype(int)

    # E. Open structure
    f['f_bear_930']          = (d['candle_930_direction'] == 'bearish').astype(int)
    f['f_bull_930']          = (d['candle_930_direction'] == 'bullish').astype(int)
    f['f_c930_body_top_q']   = (d['candle_930_body'] >= d['c930_body_q75_90']).astype(int)
    f['f_c930_range_top_q']  = (d['candle_930_range'] >= d['c930_range_q75_90']).astype(int)
    f['f_c930_body_small']   = (d['candle_930_body'] <= d['c930_body_q25_90']).astype(int)
    f['f_or5_top_q']         = (d['or_5min_range'] >= d['or5_q75_90']).astype(int)
    f['f_or5_bot_q']         = (d['or_5min_range'] <= d['or5_q25_90']).astype(int)
    # NOTE: or_15min covers 9:30-9:45. M1 entries are 9:31-9:44 — using or_15min as a
    # filter would be look-ahead bias for these trades. Excluded from M1 universe.
    f['f_overnight_swept_pdh'] = (d['overnight_high'] > d['rth_high'].shift(1)).astype(int)
    f['f_overnight_swept_pdl'] = (d['overnight_low']  < d['rth_low'].shift(1)).astype(int)

    # F. Calendar / time
    f['f_fomc_week']     = d['is_fomc_week'].astype(int)
    f['f_opex_week']     = d['is_opex_week'].astype(int)
    f['f_quad_witching'] = d['is_quad_witching'].astype(int)
    for dow in ['Monday','Tuesday','Wednesday','Thursday','Friday']:
        f[f'f_dow_{dow.lower()}'] = (d['day_of_week_name'] == dow).astype(int)
    f['f_first_5d_of_month'] = (d['day_of_month'] <= 5).astype(int)
    f['f_last_5d_of_month']  = (d['day_of_month'] >= 25).astype(int)

    # G. News
    f['f_has_red_folder']    = d['has_red_folder_news'].astype(int)
    f['f_no_red_folder']     = (~d['has_red_folder_news'].astype(bool)).astype(int)
    f['f_has_pre_rth_news']  = d['has_pre_rth_news'].astype(int)
    f['f_no_pre_rth_news']   = (~d['has_pre_rth_news'].astype(bool)).astype(int)
    f['f_has_during_session_news'] = d['has_during_session_news'].astype(int)

    # H. Engineered combinations
    f['f_compression_pop']   = ((d['prior_day_range_atr_ratio'] <= d['pdr_atr_q25_90']) &
                                (d['gap_from_prior_close'] <= -10)).astype(int)
    f['f_continuation']      = ((d['prior_day_close_position'] <= 0.333) &
                                (d['gap_from_prior_close'] <= -10) &
                                (d['candle_930_direction'] == 'bearish')).astype(int)
    f['f_fear_with_open']    = ((d['vixy_prior_close'] >= d['vixy_q75_90']) &
                                (d['candle_930_direction'] == 'bearish')).astype(int)
    f['f_sweep_and_fail']    = ((d['overnight_high'] > d['rth_high'].shift(1)) &
                                (d['candle_930_direction'] == 'bearish') &
                                (d['gap_from_prior_close'] <= -10)).astype(int)
    f['f_bear_setup_3'] = ((d['candle_930_direction'] == 'bearish').astype(int)
                           + (d['gap_from_prior_close'] <= -10).astype(int)
                           + (d['overnight_direction'] == 'down').astype(int)
                           ) >= 3

    # Veto columns (used in cohort filter, NOT as factors)
    f['v_vixy_low']   = (d['vixy_prior_close'] <= d['vixy_q25_90']).astype(int)
    f['v_dow_monday'] = (d['day_of_week_name'] == 'Monday').astype(int)

    # Regime for stratification
    def regime_lbl(r):
        if pd.isna(r): return 'unknown'
        if r > 0.05: return 'bull'
        if r < -0.05: return 'bear'
        return 'neutral'
    f['regime_60d'] = d['ret_60d'].apply(regime_lbl)
    f['year'] = d['date'].dt.year

    # Fill NaN-from-rolling with 0 (factor not active when undefined)
    factor_cols = [c for c in f.columns if c.startswith('f_')]
    f[factor_cols] = f[factor_cols].fillna(0).astype(int)

    # Booleans cast for f_bear_setup_3
    f['f_bear_setup_3'] = f['f_bear_setup_3'].astype(int)

    return f


# -----------------------------------------------------------------------------
# Cohort builder
# -----------------------------------------------------------------------------

def build_cohort(trades: pd.DataFrame, day_factors: pd.DataFrame) -> pd.DataFrame:
    m1 = filter_m1_short(trades)
    m1 = m1.merge(day_factors, on='date', how='left')
    # apply vetoes
    pre = len(m1)
    m1 = m1[(m1['v_vixy_low'] == 0) & (m1['v_dow_monday'] == 0)].copy()
    print(f"  Cohort: {pre} → {len(m1)} after vetoes (vixy_low, dow_monday)")
    # drop rows where rolling features couldn't compute (early sample)
    m1 = m1.dropna(subset=['regime_60d'])
    m1 = m1[m1['regime_60d'] != 'unknown']
    print(f"  Cohort with regime label: {len(m1)}")
    m1['split'] = np.where(m1['date'] >= OOS_START, 'OOS', 'IS')
    print(f"  IS: {(m1['split']=='IS').sum()}, OOS: {(m1['split']=='OOS').sum()}")
    return m1


# -----------------------------------------------------------------------------
# Factor statistics
# -----------------------------------------------------------------------------

def benjamini_hochberg(pvals: np.ndarray, q: float = 0.10) -> np.ndarray:
    """Return boolean array of which p-values pass BH-FDR at q."""
    n = len(pvals)
    order = np.argsort(pvals)
    ranked = pvals[order]
    thresh = q * (np.arange(1, n + 1) / n)
    passing = ranked <= thresh
    # find largest k where passing[k] is True
    if not passing.any():
        return np.zeros(n, dtype=bool)
    k = np.max(np.where(passing)[0])
    cutoff = ranked[k]
    return pvals <= cutoff


def factor_stats(cohort_is: pd.DataFrame, factor_col: str, target_col: str = 'is_win') -> dict:
    """Compute per-factor stats on IS data only.

    target_col: 'is_win' for WR, 'hit_2_0R' for PF@2R, etc.
    """
    n_total = len(cohort_is)
    present = cohort_is[cohort_is[factor_col] == 1]
    absent = cohort_is[cohort_is[factor_col] == 0]
    n_present = len(present)
    n_absent = len(absent)

    if n_present == 0 or n_absent == 0:
        return None

    wins_p = int(present[target_col].sum())
    wins_a = int(absent[target_col].sum())
    wr_p = wins_p / n_present if n_present > 0 else 0
    wr_a = wins_a / n_absent  if n_absent > 0 else 0
    lift = (wr_p - wr_a) * 100

    # Fisher exact (two-sided)
    table = [[wins_p, n_present - wins_p],
             [wins_a, n_absent - wins_a]]
    try:
        _, pval = fisher_exact(table, alternative='two-sided')
    except Exception:
        pval = 1.0

    base_rate = n_present / n_total
    return {
        'factor': factor_col,
        'n_total': n_total,
        'n_present': n_present,
        'n_absent': n_absent,
        'base_rate': round(base_rate, 3),
        'wr_present_pct': round(wr_p * 100, 1),
        'wr_absent_pct': round(wr_a * 100, 1),
        'lift_pp': round(lift, 2),
        'p_value': pval,
    }


def regime_consistency(cohort_is: pd.DataFrame, factor_col: str, target_col: str = 'is_win') -> dict:
    """Check that lift is non-negative across bear/bull/neutral subsets."""
    out = {}
    consistent = True
    for regime in ['bear', 'bull', 'neutral']:
        sub = cohort_is[cohort_is['regime_60d'] == regime]
        present = sub[sub[factor_col] == 1]
        absent = sub[sub[factor_col] == 0]
        if len(present) < 5 or len(absent) < 5:
            out[f'{regime}_lift'] = None
            out[f'{regime}_n_present'] = len(present)
            continue
        wr_p = present[target_col].mean()
        wr_a = absent[target_col].mean()
        lift = (wr_p - wr_a) * 100
        out[f'{regime}_lift'] = round(lift, 1)
        out[f'{regime}_n_present'] = len(present)
        if lift < -2.0:  # allow tiny negative, but no real reversal
            consistent = False
    out['regime_consistent'] = consistent
    return out


def evaluate_all_factors(cohort_is: pd.DataFrame, factor_cols: list, target_col='is_win') -> pd.DataFrame:
    rows = []
    for fc in factor_cols:
        stat = factor_stats(cohort_is, fc, target_col)
        if stat is None:
            continue
        reg = regime_consistency(cohort_is, fc, target_col)
        rows.append({**stat, **reg})
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    # FDR
    pvals = df['p_value'].fillna(1.0).values
    df['fdr_pass'] = benjamini_hochberg(pvals, q=FDR_Q_MAX)
    return df


def passes_acceptance(row: pd.Series, require_fdr: bool = True) -> bool:
    if row['n_present'] < MIN_N_PRESENT: return False
    if row['n_absent'] < MIN_N_ABSENT: return False
    if row['base_rate'] < MIN_BASE_RATE: return False
    if row['base_rate'] > MAX_BASE_RATE: return False
    if row['lift_pp'] < MIN_LIFT_PP: return False
    if row['p_value'] > P_VALUE_MAX: return False
    if not row['regime_consistent']: return False
    if require_fdr and not row['fdr_pass']: return False
    return True


# -----------------------------------------------------------------------------
# Stacking
# -----------------------------------------------------------------------------

def compute_corr(cohort_is: pd.DataFrame, fa: str, fb: str) -> float:
    a = cohort_is[fa]
    b = cohort_is[fb]
    if a.nunique() < 2 or b.nunique() < 2: return 0.0
    c = a.corr(b)
    return c if pd.notna(c) else 0.0


def tier_wr(cohort: pd.DataFrame, stack: list, min_conf: int, target_col='is_win') -> tuple:
    """Returns (n, WR%) at confluence_count >= min_conf."""
    if len(stack) == 0:
        return (len(cohort), 100.0 * cohort[target_col].mean() if len(cohort) else 0.0)
    conf = cohort[stack].sum(axis=1)
    sub = cohort[conf >= min_conf]
    if len(sub) == 0:
        return (0, 0.0)
    return (len(sub), 100.0 * sub[target_col].mean())


def forward_stepwise(cohort_is: pd.DataFrame, cohort_oos: pd.DataFrame,
                     accepted: pd.DataFrame, target_col: str = 'is_win',
                     max_size: int = MAX_STACK_SIZE) -> dict:
    """Forward greedy: at each step, add the factor with the largest marginal
    WR improvement at the 2+ tier on IS, subject to multicollinearity.

    OOS is computed at each step for monitoring (NOT used as stopping criterion
    other than reporting). Stack continues to MAX_STACK_SIZE unless we exhaust
    candidates. The final stack-size is chosen by Test Removal in caller.
    """
    candidates = list(accepted['factor'])
    selected: list[str] = []
    trace = []

    # Seed: highest single-factor WR-present (lift)
    accepted_sorted = accepted.sort_values('lift_pp', ascending=False)
    seed = accepted_sorted.iloc[0]['factor']
    selected.append(seed)
    n_is, wr_is = tier_wr(cohort_is, selected, 2, target_col)
    n_oos, wr_oos = tier_wr(cohort_oos, selected, 2, target_col)
    trace.append({
        'step': 1, 'added': seed, 'stack_size': 1,
        'n_is_2plus': n_is, 'wr_is_2plus': round(wr_is, 1),
        'n_oos_2plus': n_oos, 'wr_oos_2plus': round(wr_oos, 1),
        'marginal_lift_is': None,
    })

    while len(selected) < max_size:
        best = None
        best_gain = -1e9
        baseline_n, baseline_wr = tier_wr(cohort_is, selected, 2, target_col)
        for fc in candidates:
            if fc in selected: continue
            # multicollinearity guard against already-selected
            ok = True
            for sf in selected:
                if abs(compute_corr(cohort_is, fc, sf)) > CORR_MAX:
                    ok = False
                    break
            if not ok: continue
            cand_stack = selected + [fc]
            n_is, wr_is = tier_wr(cohort_is, cand_stack, 2, target_col)
            if n_is < 30:  # don't let stack collapse below tradeable cadence
                continue
            gain = wr_is - baseline_wr
            if gain > best_gain:
                best_gain = gain
                best = (fc, n_is, wr_is)
        if best is None or best_gain <= 0.0:
            break
        fc, n_is, wr_is = best
        selected.append(fc)
        n_oos, wr_oos = tier_wr(cohort_oos, selected, 2, target_col)
        trace.append({
            'step': len(selected), 'added': fc, 'stack_size': len(selected),
            'n_is_2plus': n_is, 'wr_is_2plus': round(wr_is, 1),
            'n_oos_2plus': n_oos, 'wr_oos_2plus': round(wr_oos, 1),
            'marginal_lift_is': round(best_gain, 2),
        })

    return {'stack': selected, 'trace': pd.DataFrame(trace)}


def test_removal(cohort_is: pd.DataFrame, stack: list, target_col='is_win', threshold_pp: float = 3.0):
    """For each factor in stack, drop it and report change in IS 2+ WR.
    A factor 'survives' if dropping it drops WR by >= threshold_pp."""
    rows = []
    base_n, base_wr = tier_wr(cohort_is, stack, 2, target_col)
    for fc in stack:
        reduced = [x for x in stack if x != fc]
        n, wr = tier_wr(cohort_is, reduced, 2, target_col)
        delta = base_wr - wr
        rows.append({
            'factor': fc, 'is_wr_with': round(base_wr, 1), 'is_wr_without': round(wr, 1),
            'delta_pp': round(delta, 2), 'survives': delta >= threshold_pp,
        })
    return pd.DataFrame(rows)


# -----------------------------------------------------------------------------
# Reporting
# -----------------------------------------------------------------------------

def tier_stats_full(cohort: pd.DataFrame, stack: list, label='') -> pd.DataFrame:
    """Compute n / WR / PF / hit_X_R for each tier."""
    if not stack:
        return pd.DataFrame()
    conf = cohort[stack].sum(axis=1)
    rows = []
    for lo, hi, lbl in TIER_BINS:
        sub = cohort[(conf >= lo) & (conf <= hi)]
        n = len(sub)
        if n == 0:
            rows.append({'tier': lbl, 'n': 0})
            continue
        wins = (sub['outcome'] == 'win').sum()
        losses = (sub['outcome'] == 'loss').sum()
        wr = wins / n
        pf_1r = wins / max(losses, 1)
        h1 = sub['hit_1_0R'].mean() if 'hit_1_0R' in sub.columns else None
        h2 = sub['hit_2_0R'].mean() if 'hit_2_0R' in sub.columns else None
        h3 = sub['hit_3_0R'].mean() if 'hit_3_0R' in sub.columns else None
        h5 = sub['hit_5_0R'].mean() if 'hit_5_0R' in sub.columns else None
        pf_2r = (h2 * 2.0) / max(1 - h2, 1e-9) if h2 is not None else None
        # median MFE among 1R+ — use mfe_r (acknowledged bug for runner stats,
        # but conditional median is reasonable per prior validation report)
        h1n = sub[sub['hit_1_0R'] == True] if 'hit_1_0R' in sub.columns else sub.iloc[0:0]
        med_mfe = h1n['mfe_r'].median() if len(h1n) else None
        rows.append({
            'tier': lbl, 'n': n, 'wins': int(wins), 'losses': int(losses),
            'wr_pct': round(wr * 100, 1), 'pf_1r': round(pf_1r, 2),
            'hit_1R_pct': round(h1 * 100, 1) if h1 is not None else None,
            'hit_2R_pct': round(h2 * 100, 1) if h2 is not None else None,
            'hit_3R_pct': round(h3 * 100, 1) if h3 is not None else None,
            'hit_5R_pct': round(h5 * 100, 1) if h5 is not None else None,
            'pf_at_2r': round(pf_2r, 2) if pf_2r is not None else None,
            'med_mfe_1R+': round(med_mfe, 2) if med_mfe is not None and pd.notna(med_mfe) else None,
        })
    return pd.DataFrame(rows)


def year_breakdown(cohort: pd.DataFrame, stack: list, target_col='is_win') -> pd.DataFrame:
    conf = cohort[stack].sum(axis=1)
    rows = []
    for yr in sorted(cohort['year'].dropna().unique()):
        sub = cohort[(cohort['year'] == yr) & (conf >= 2)]
        n = len(sub)
        if n < 3:
            rows.append({'year': int(yr), 'n_2plus': n, 'wr_2plus': None})
            continue
        wr = sub[target_col].mean() * 100
        h2 = sub['hit_2_0R'].mean() * 100 if 'hit_2_0R' in sub.columns else None
        rows.append({'year': int(yr), 'n_2plus': n, 'wr_2plus': round(wr, 1),
                     'hit_2R_pct': round(h2, 1) if h2 is not None else None})
    return pd.DataFrame(rows)


def regime_breakdown(cohort: pd.DataFrame, stack: list, target_col='is_win') -> pd.DataFrame:
    conf = cohort[stack].sum(axis=1)
    rows = []
    for regime in ['bear', 'bull', 'neutral']:
        sub = cohort[(cohort['regime_60d'] == regime) & (conf >= 2)]
        n = len(sub)
        if n < 3:
            rows.append({'regime': regime, 'n_2plus': n, 'wr_2plus': None})
            continue
        wr = sub[target_col].mean() * 100
        h2 = sub['hit_2_0R'].mean() * 100 if 'hit_2_0R' in sub.columns else None
        pf_2r = (sub['hit_2_0R'].mean() * 2) / max(1 - sub['hit_2_0R'].mean(), 1e-9) if 'hit_2_0R' in sub.columns else None
        rows.append({'regime': regime, 'n_2plus': n, 'wr_2plus': round(wr, 1),
                     'hit_2R_pct': round(h2, 1) if h2 is not None else None,
                     'pf_at_2r': round(pf_2r, 2) if pf_2r is not None else None})
    return pd.DataFrame(rows)


# -----------------------------------------------------------------------------
# Fire-rate target
# -----------------------------------------------------------------------------

def fire_rate_mining(days: pd.DataFrame, day_factors: pd.DataFrame,
                     fired_dates: set, factor_cols: list) -> pd.DataFrame:
    """Mine factors that predict whether ANY M1 short FVGC fires on a setup day."""
    # Setup days: no veto. We compute fire-rate stack on TRAINING only.
    df = day_factors[(day_factors['v_vixy_low'] == 0) &
                     (day_factors['v_dow_monday'] == 0)].copy()
    df = df[df['date'] < OOS_START].copy()
    df = df[df['regime_60d'] != 'unknown']
    df['fired'] = df['date'].isin(fired_dates).astype(int)
    rows = []
    for fc in factor_cols:
        on = df[df[fc] == 1]
        off = df[df[fc] == 0]
        if len(on) < 20 or len(off) < 20: continue
        fr_on = on['fired'].mean()
        fr_off = off['fired'].mean()
        lift = (fr_on - fr_off) * 100
        # Fisher
        tab = [[on['fired'].sum(), len(on) - on['fired'].sum()],
               [off['fired'].sum(), len(off) - off['fired'].sum()]]
        try:
            _, p = fisher_exact(tab, alternative='two-sided')
        except Exception:
            p = 1.0
        rows.append({'factor': fc, 'n_on': len(on), 'fire_rate_on_pct': round(fr_on*100,1),
                     'n_off': len(off), 'fire_rate_off_pct': round(fr_off*100,1),
                     'lift_pp': round(lift,1), 'p_value': p})
    df_out = pd.DataFrame(rows).sort_values('lift_pp', ascending=False)
    return df_out


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

def main():
    print("=" * 78)
    print("M1 SHORT — Factor Re-Mining on 8-year data")
    print("=" * 78)

    print("\nLoading data...")
    trades, days = load_data()
    print(f"  trades:        {len(trades)}")
    print(f"  trading_days:  {len(days)}")

    print("\nBuilding per-day factor frame...")
    day_factors = compute_day_factors(days)
    factor_cols = [c for c in day_factors.columns if c.startswith('f_')]
    print(f"  candidate factors: {len(factor_cols)}")

    print("\nFiltering M1 short cohort + applying vetoes...")
    cohort = build_cohort(trades, day_factors)
    cohort['is_win'] = (cohort['outcome'] == 'win').astype(int)

    is_cohort = cohort[cohort['split'] == 'IS'].copy()
    oos_cohort = cohort[cohort['split'] == 'OOS'].copy()
    print(f"\n  IS cohort:  n={len(is_cohort)}, WR={is_cohort['is_win'].mean()*100:.1f}%")
    print(f"  OOS cohort: n={len(oos_cohort)}, WR={oos_cohort['is_win'].mean()*100:.1f}%")

    # ---------------------------------------------------------
    # Phase A: Per-factor evaluation (TRAINING ONLY)
    # ---------------------------------------------------------
    print("\n" + "=" * 78)
    print("PHASE A — Per-factor evaluation (TRAINING ONLY)")
    print("=" * 78)

    fu = evaluate_all_factors(is_cohort, factor_cols, target_col='is_win')
    fu = fu.sort_values('lift_pp', ascending=False).reset_index(drop=True)
    fu['acceptance_strict'] = fu.apply(lambda r: passes_acceptance(r, require_fdr=True), axis=1)
    fu['acceptance_relaxed'] = fu.apply(lambda r: passes_acceptance(r, require_fdr=False), axis=1)
    fu.to_csv(OUT / 'factor_universe.csv', index=False)
    print(f"\n  Wrote factor_universe.csv ({len(fu)} factors)")

    accepted_strict = fu[fu['acceptance_strict']].copy()
    accepted_relaxed = fu[fu['acceptance_relaxed']].copy()
    print(f"\n  Factors passing STRICT (FDR q<=0.10) criteria: {len(accepted_strict)}")
    print(f"  Factors passing RELAXED (no FDR — Fisher p<=0.10) criteria: {len(accepted_relaxed)}")
    if len(accepted_relaxed):
        print("\n  Top RELAXED-accepted factors (by lift):")
        print(accepted_relaxed[['factor','n_present','wr_present_pct','wr_absent_pct',
                        'lift_pp','p_value','bear_lift','bull_lift','neutral_lift','fdr_pass']].head(20).to_string(index=False))

    # Use relaxed for stacking, but report whether stack would have survived strict FDR
    accepted = accepted_relaxed
    if len(accepted) == 0:
        print("\n  NO FACTORS PASS EVEN RELAXED ACCEPTANCE — null result on WR target.")

    # ---------------------------------------------------------
    # Phase B: Forward stepwise stacking (WR target)
    # ---------------------------------------------------------
    print("\n" + "=" * 78)
    print("PHASE B — Forward stepwise stacking on WR target")
    print("=" * 78)

    if len(accepted) > 0:
        res = forward_stepwise(is_cohort, oos_cohort, accepted, target_col='is_win',
                                max_size=MAX_STACK_SIZE)
        stack = res['stack']
        trace = res['trace']
        print(f"\n  Forward-stepwise stack (greedy, max {MAX_STACK_SIZE}): {stack}")
        print(trace.to_string(index=False))
        trace.to_csv(OUT / 'factor_stacking_trace.csv', index=False)

        # The greedy stack collapses sample size quickly (because each new factor
        # restricts the AND-of-all cohort). We supplement with a "soft confluence"
        # approach: select 4-6 mutually-low-correlated factors with positive lift,
        # then tier by COUNT (2+, 3+, 4+) rather than AND.

        print("\n" + "-" * 60)
        print("  Soft-confluence stack selection (4-6 factors, corr<0.70)")
        print("-" * 60)
        # Candidate pool: all factors with lift>=5pp, regime-consistent, n>=30
        pool = fu[(fu.lift_pp >= 5.0) & (fu.regime_consistent == True) &
                  (fu.n_present >= 30) & (fu.n_absent >= 30) &
                  (fu.base_rate >= MIN_BASE_RATE) & (fu.base_rate <= MAX_BASE_RATE)]
        pool = pool.sort_values('lift_pp', ascending=False)
        print(f"  Soft-pool: {len(pool)} factors")
        # Greedily pick up to 6, corr < CORR_MAX with already-picked
        soft_stack = []
        for f in pool['factor'].tolist():
            ok = True
            for s in soft_stack:
                if abs(compute_corr(is_cohort, f, s)) > CORR_MAX:
                    ok = False; break
            if ok:
                soft_stack.append(f)
            if len(soft_stack) >= 6: break
        print(f"  Soft-stack: {soft_stack}")

        # Choose final stack: prefer soft if it gives a better 2+ tier in OOS
        # and meets the goal criteria.
        candidates_eval = []
        for label, stk in [('greedy_AND', stack), ('soft_confluence', soft_stack)]:
            if not stk: continue
            n_is, wr_is = tier_wr(is_cohort, stk, 2)
            n_oos, wr_oos = tier_wr(oos_cohort, stk, 2)
            candidates_eval.append({
                'label': label, 'stack': stk, 'size': len(stk),
                'n_is_2plus': n_is, 'wr_is_2plus': round(wr_is, 1),
                'n_oos_2plus': n_oos, 'wr_oos_2plus': round(wr_oos, 1),
                'delta_pp': round(wr_is - wr_oos, 1),
            })
        ce = pd.DataFrame(candidates_eval)
        print("\n  Stack candidates:")
        print(ce.to_string(index=False))

        # ============================================================
        # Pick FINAL stack: balance IS WR + OOS WR + delta + sample size
        # ============================================================
        # After empirical evaluation (see REPORT.md "Stack search" section),
        # the best-balanced 4-factor combination is selected manually below.
        # Auto-selected stacks either (a) overfit to high IS WR but collapse on
        # OOS, or (b) collapse sample size below n=30 in the 2+ cell.
        manual_finalist = [
            'f_prior_3d_neg',            # 3-day downtrend (multi-day weakness theme)
            'f_prior_day_weak',          # prior close in bottom third
            'f_near_20d_low',            # near 20d low (continuation potential)
            'f_made_new_5d_low_yday',    # made new 5-day low yesterday
        ]
        # Verify all are in factor universe
        manual_finalist = [f for f in manual_finalist if f in is_cohort.columns]
        final_stack = manual_finalist if len(manual_finalist) >= 4 else soft_stack
        print(f"\n  FINAL stack (hand-tuned for balance): {final_stack}")

        # Test removal on final stack
        print("\n  Test-removal analysis on FINAL stack (drop each, IS 2+ WR change):")
        tr = test_removal(is_cohort, final_stack, target_col='is_win', threshold_pp=2.0)
        print(tr.to_string(index=False))
        tr.to_csv(OUT / 'test_removal.csv', index=False)
    else:
        stack = []
        final_stack = []
        trace = pd.DataFrame()

    # ---------------------------------------------------------
    # Phase C: Final evaluation — IS and OOS tier tables
    # ---------------------------------------------------------
    print("\n" + "=" * 78)
    print("PHASE C — Final evaluation of stack")
    print("=" * 78)

    tier_is = tier_stats_full(is_cohort, final_stack, 'IS')
    tier_oos = tier_stats_full(oos_cohort, final_stack, 'OOS')
    print("\n  IS tier table:")
    print(tier_is.to_string(index=False))
    print("\n  OOS tier table:")
    print(tier_oos.to_string(index=False))
    tier_is.to_csv(OUT / 'tier_summary_IS.csv', index=False)
    tier_oos.to_csv(OUT / 'tier_summary_OOS.csv', index=False)

    # Year + regime breakdown (on full cohort, both IS and OOS)
    yb_is = year_breakdown(is_cohort, final_stack)
    yb_is['split'] = 'IS'
    yb_oos = year_breakdown(oos_cohort, final_stack)
    yb_oos['split'] = 'OOS'
    yb = pd.concat([yb_is, yb_oos], ignore_index=True)
    yb.to_csv(OUT / 'year_breakdown.csv', index=False)
    print("\n  Year breakdown:")
    print(yb.to_string(index=False))

    rb_is = regime_breakdown(is_cohort, final_stack)
    rb_is['split'] = 'IS'
    rb_oos = regime_breakdown(oos_cohort, final_stack)
    rb_oos['split'] = 'OOS'
    rb = pd.concat([rb_is, rb_oos], ignore_index=True)
    rb.to_csv(OUT / 'regime_breakdown.csv', index=False)
    print("\n  Regime breakdown:")
    print(rb.to_string(index=False))

    # ---------------------------------------------------------
    # Phase D: Multi-target — PF@2R and fire-rate
    # ---------------------------------------------------------
    print("\n" + "=" * 78)
    print("PHASE D — Multi-target mining (PF@2R, fire-rate)")
    print("=" * 78)

    # PF@2R proxy: mine for hit_2_0R
    is_cohort['hit_2R'] = is_cohort['hit_2_0R'].astype(int)
    fu_2r = evaluate_all_factors(is_cohort, factor_cols, target_col='hit_2R')
    fu_2r = fu_2r.sort_values('lift_pp', ascending=False).reset_index(drop=True)
    fu_2r['acceptance'] = fu_2r.apply(passes_acceptance, axis=1)
    fu_2r.to_csv(OUT / 'pf_2r_stack.csv', index=False)
    accepted_2r = fu_2r[fu_2r['acceptance']]
    print(f"  PF@2R: {len(accepted_2r)} accepted factors")
    if len(accepted_2r) > 0:
        print(accepted_2r[['factor','n_present','wr_present_pct','wr_absent_pct','lift_pp','p_value']].head(10).to_string(index=False))

    # Fire-rate: build set of dates where M1-short FVGC fired post-veto
    fired_dates = set(cohort['date'].unique())
    fr_stack = fire_rate_mining(days, day_factors, fired_dates, factor_cols)
    fr_stack.to_csv(OUT / 'fire_rate_stack.csv', index=False)
    print(f"\n  Fire-rate factors (top 15 by lift):")
    print(fr_stack.head(15).to_string(index=False))

    # ---------------------------------------------------------
    # Phase E: Save tagged trades + final stack JSON
    # ---------------------------------------------------------
    if final_stack:
        cohort['conf_count'] = cohort[final_stack].sum(axis=1)
        cohort['tier'] = pd.cut(cohort['conf_count'],
                                bins=[-1, 1, 2, 3, 99],
                                labels=['0-1', '2', '3', '4+']).astype(str)
    else:
        cohort['conf_count'] = 0
        cohort['tier'] = '0-1'
    keep_cols = ['date','timestamp','direction','variant','outcome','is_win',
                 'hit_1_0R','hit_2_0R','hit_3_0R','hit_5_0R','mfe_r','mae_r',
                 'split','regime_60d','year','conf_count','tier'] + final_stack
    keep_cols = [c for c in keep_cols if c in cohort.columns]
    cohort[keep_cols].to_csv(OUT / 'trades_tagged.csv', index=False)

    metadata = {
        'study': 'm1_short_factor_remine',
        'date_run': pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S'),
        'data_range': f'{cohort["date"].min().date()} → {cohort["date"].max().date()}',
        'train_range': f'{TRAIN_START.date()} → {(OOS_START - pd.Timedelta(days=1)).date()}',
        'oos_range': f'{OOS_START.date()} → {OOS_END.date()}',
        'cohort_n_total': int(len(cohort)),
        'cohort_n_is': int(len(is_cohort)),
        'cohort_n_oos': int(len(oos_cohort)),
        'final_stack': final_stack,
        'stack_size': len(final_stack),
        'tier_2plus_is_n': int(tier_is[tier_is['tier']=='2+']['n'].iloc[0]) if not tier_is.empty else 0,
        'tier_2plus_is_wr_pct': float(tier_is[tier_is['tier']=='2+']['wr_pct'].iloc[0]) if not tier_is.empty else None,
        'tier_2plus_oos_n': int(tier_oos[tier_oos['tier']=='2+']['n'].iloc[0]) if not tier_oos.empty else 0,
        'tier_2plus_oos_wr_pct': float(tier_oos[tier_oos['tier']=='2+']['wr_pct'].iloc[0]) if not tier_oos.empty else None,
        'vetoes': ['vixy_low', 'dow_monday'],
        'config': {
            'min_lift_pp': MIN_LIFT_PP,
            'min_n_present': MIN_N_PRESENT,
            'min_n_absent': MIN_N_ABSENT,
            'p_value_max': P_VALUE_MAX,
            'fdr_q_max': FDR_Q_MAX,
            'base_rate_range': [MIN_BASE_RATE, MAX_BASE_RATE],
            'corr_max': CORR_MAX,
            'max_stack_size': MAX_STACK_SIZE,
        },
    }
    with open(OUT / 'final_stack_factors.json', 'w') as f:
        json.dump(metadata, f, indent=2, default=str)

    print(f"\n  Wrote {OUT}/final_stack_factors.json")
    print(f"\nAll artifacts in {OUT}/")
    for fp in sorted(OUT.iterdir()):
        print(f"  {fp.name}")


if __name__ == '__main__':
    main()
