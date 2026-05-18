#!/usr/bin/env python3
"""M1 Short Confluence Model — 8-year validation (2018-01 → 2026-05).

Validates the M1 Short play (originally trained on Oct 2023 → Mar 2026 data)
against the newly-extended 8-year dataset. Specifically:

1. Does the 2+ tier still produce ~68% WR / PF 2.4 @ 2R on 8 years?
2. Does the play hold up in the new bear regimes (2018Q4, 2020 COVID, 2022)?
3. Year-by-year stability — any single-year regimes that break the edge?
4. Predictability: on setup days (2+ conf, no veto), what predicts whether
   FVGC actually fires in the 9:30-9:45 window (fire rate was ~23% on
   3-year data)?
5. New factor mining: are there factors that emerged in the longer history
   that weren't visible in the 3-year sample?

Inputs:
- studies/baseline/results/trades.csv      (8-year 30s FVGC trades, n=6614)
- data/trading_days/trading_days.csv       (63 per-day factor columns, n=2158)

Outputs:
- results/trades_m1_short_tagged.csv       (per-trade with conf + veto + tier)
- results/tier_summary.csv                 (n / WR / PF / hit_X_R per tier)
- results/year_breakdown.csv               (year × tier WR matrix)
- results/regime_breakdown.csv             (60d-NQ-regime × tier WR matrix)
- results/setup_day_predictability.csv     (what predicts FVGC firing?)
- REPORT.md                                (human-readable summary)

Anti-patterns avoided:
- No look-ahead bias: all confluence factors are knowable by 9:30:30
  (pre-market + 9:30 candle close at 9:30:30)
- Don't use mfe_r for runner expectations (post-exit bug): use hit_X_R cols
- Sample size + n reported for every cell
- Per-year + per-regime split required to pass
"""

from __future__ import annotations

import sys
from datetime import time as dtime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
STUDY = Path(__file__).resolve().parent
OUT = STUDY / 'results'

# -----------------------------------------------------------------------------
# Load + join
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
    """W1/M1 short FVGCs in 9:30:00–9:44:59 with valid outcome, excl. PS."""
    w1 = trades[
        (trades['direction'] == 'short')
        & (trades['time'] >= dtime(9, 30, 0))
        & (trades['time'] < dtime(9, 45, 0))
        & (trades['variant'] != 'protected_swing')
        & trades['outcome'].isin(['win', 'loss'])
    ].copy()
    return w1


# -----------------------------------------------------------------------------
# Build per-day confluence + veto factors
# -----------------------------------------------------------------------------

def compute_per_day_factors(days: pd.DataFrame) -> pd.DataFrame:
    d = days.copy()

    # VIXY rolling 90d quartiles (top/bot) — need to handle missing VIXY before 2018-Apr
    d = d.sort_values('date').reset_index(drop=True)
    d['vixy_q25_90'] = d['vixy_prior_close'].rolling(90, min_periods=30).quantile(0.25)
    d['vixy_q75_90'] = d['vixy_prior_close'].rolling(90, min_periods=30).quantile(0.75)

    # Candle 930 body rolling 90d quartiles (for c930_body_top_q)
    d['c930_body_q75_90'] = d['candle_930_body'].rolling(90, min_periods=30).quantile(0.75)

    # Day-of-week derived (already have day_of_week_name)
    # Confluence factors (the 7 from the multi_cell_confluence study)
    d['c_gap_large_down']   = (d['gap_from_prior_close'] <= -100).astype(int)
    d['c_prior_day_weak']   = (d['prior_day_close_position'] <= 0.333).astype(int)
    d['c_is_fomc_week']     = d['is_fomc_week'].astype(int)
    d['c_vixy_high']        = (d['vixy_prior_close'] >= d['vixy_q75_90']).astype(int)
    d['c_dow_friday']       = (d['day_of_week_name'] == 'Friday').astype(int)
    d['c_bear_930']         = (d['candle_930_direction'] == 'bearish').astype(int)
    d['c_c930_body_top_q']  = (d['candle_930_body'] >= d['c930_body_q75_90']).astype(int)
    factor_cols = ['c_gap_large_down','c_prior_day_weak','c_is_fomc_week','c_vixy_high',
                   'c_dow_friday','c_bear_930','c_c930_body_top_q']
    d['confluence_count'] = d[factor_cols].sum(axis=1)

    # Hard vetoes
    d['v_vixy_low']    = (d['vixy_prior_close'] <= d['vixy_q25_90']).astype(int)
    d['v_dow_monday']  = (d['day_of_week_name'] == 'Monday').astype(int)
    d['veto_count']    = d[['v_vixy_low','v_dow_monday']].sum(axis=1)
    d['veto_any']      = (d['veto_count'] > 0).astype(int)

    return d


# -----------------------------------------------------------------------------
# Compute 60d regime
# -----------------------------------------------------------------------------

def add_regime(days: pd.DataFrame) -> pd.DataFrame:
    d = days.copy()
    d = d.sort_values('date').reset_index(drop=True)
    # use rth_close as proxy for daily close
    d['close_60d_ago'] = d['rth_close'].shift(60)
    d['ret_60d'] = (d['rth_close'] / d['close_60d_ago'] - 1) * 100
    def lbl(r):
        if pd.isna(r): return 'unknown'
        if r > 5: return 'bull'
        if r < -5: return 'bear'
        return 'neutral'
    d['regime_60d'] = d['ret_60d'].apply(lbl)
    d['year'] = d['date'].dt.year
    return d


# -----------------------------------------------------------------------------
# Per-tier reporting helpers
# -----------------------------------------------------------------------------

TIER_BINS = [(0,1,'0-1'), (2,2,'2'), (3,3,'3'), (4,7,'4+'), (2,7,'2+')]


def tier_stats(df: pd.DataFrame, group_col: str = None) -> pd.DataFrame:
    """Return WR/PF/hit_X_R per tier, optionally grouped."""
    rows = []
    def stats_for(sub, key, tier):
        n = len(sub)
        if n == 0: return
        wins = (sub['outcome']=='win').sum()
        losses = (sub['outcome']=='loss').sum()
        wr = wins / n
        pf_1r = wins / max(losses, 1)
        h1 = sub['hit_1_0R'].mean()
        h2 = sub['hit_2_0R'].mean() if 'hit_2_0R' in sub.columns else None
        h3 = sub['hit_3_0R'].mean() if 'hit_3_0R' in sub.columns else None
        h5 = sub['hit_5_0R'].mean() if 'hit_5_0R' in sub.columns else None
        pf_2r = (h2*2)/max(1-h2,1e-9) if h2 is not None else None
        # median MFE among 1R+ winners
        h1n = sub[sub['hit_1_0R']==True]
        med_mfe = h1n['mfe_r'].median() if len(h1n) else None
        row = {
            'group': key, 'tier': tier, 'n': n, 'wr': round(wr*100,1),
            'pf_1r': round(pf_1r,2),
            'hit_1R': round(h1*100,1),
            'hit_2R': round(h2*100,1) if h2 is not None else None,
            'hit_3R': round(h3*100,1) if h3 is not None else None,
            'hit_5R': round(h5*100,1) if h5 is not None else None,
            'pf_2r': round(pf_2r,2) if pf_2r is not None else None,
            'med_mfe_1R+': round(med_mfe,2) if med_mfe is not None else None,
        }
        rows.append(row)

    if group_col is None:
        for lo,hi,lbl in TIER_BINS:
            sub = df[(df['confluence_count']>=lo) & (df['confluence_count']<=hi)]
            stats_for(sub, 'all', lbl)
    else:
        for key, sub_df in df.groupby(group_col):
            for lo,hi,lbl in TIER_BINS:
                sub = sub_df[(sub_df['confluence_count']>=lo) & (sub_df['confluence_count']<=hi)]
                stats_for(sub, key, lbl)
    return pd.DataFrame(rows)


# -----------------------------------------------------------------------------
# Predictability — what predicts FVGC firing on setup days?
# -----------------------------------------------------------------------------

def setup_day_predictability(days: pd.DataFrame, trades: pd.DataFrame) -> pd.DataFrame:
    """For each setup day (no veto, 2+ conf), record whether ANY M1 short
    FVGC fired in the 9:30-9:45 window. Then mine per-day features that
    predict firing."""
    setup_days = days[(days['veto_any']==0) & (days['confluence_count']>=2)].copy()
    # Did any tradeable M1 short FVGC fire on this day?
    trade_dates = set(trades['date'].unique())
    setup_days['fired'] = setup_days['date'].isin(trade_dates).astype(int)

    fire_rate = setup_days['fired'].mean()
    print(f"\nSetup day fire rate: {fire_rate*100:.1f}% ({setup_days['fired'].sum()}/{len(setup_days)})")

    # For each candidate per-day feature, compute fire rate when feature is on vs off
    features = {
        '930_body_top_q':       (setup_days['candle_930_body'] >= setup_days['c930_body_q75_90']),
        'large_gap_down':       (setup_days['gap_from_prior_close'] <= -100),
        'medium_gap_down':      ((setup_days['gap_from_prior_close'] <= -30) & (setup_days['gap_from_prior_close'] > -100)),
        'overnight_range_q75':  (setup_days['overnight_range'] >= setup_days['overnight_range'].rolling(90, min_periods=30).quantile(0.75)),
        'is_fomc_week':         setup_days['is_fomc_week']==True,
        'is_opex_week':         setup_days['is_opex_week']==True,
        'vixy_high':            (setup_days['vixy_prior_close'] >= setup_days['vixy_q75_90']),
        'fri':                  setup_days['day_of_week_name']=='Friday',
        'thu':                  setup_days['day_of_week_name']=='Thursday',
        'wed':                  setup_days['day_of_week_name']=='Wednesday',
        'tue':                  setup_days['day_of_week_name']=='Tuesday',
        'or_5min_range_high':   (setup_days['or_5min_range'] >= setup_days['or_5min_range'].rolling(90, min_periods=30).quantile(0.75)),
        'conf_3plus':           setup_days['confluence_count']>=3,
        'conf_4plus':           setup_days['confluence_count']>=4,
    }
    rows = []
    for name, mask in features.items():
        on = setup_days[mask.fillna(False)]
        off = setup_days[~mask.fillna(False)]
        if len(on) < 10:
            continue
        on_fr = on['fired'].mean()
        off_fr = off['fired'].mean()
        rows.append({
            'feature': name,
            'n_on': len(on),
            'on_fire_rate': round(on_fr*100,1),
            'n_off': len(off),
            'off_fire_rate': round(off_fr*100,1),
            'lift_pp': round((on_fr-off_fr)*100,1),
        })
    return pd.DataFrame(rows).sort_values('lift_pp', ascending=False)


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    print("Loading data...")
    trades, days = load_data()
    print(f"  baseline trades: {len(trades)}")
    print(f"  trading days:    {len(days)}")

    print("\nComputing per-day factors + regime...")
    days = compute_per_day_factors(days)
    days = add_regime(days)

    print("\nFiltering to M1 short cohort...")
    m1 = filter_m1_short(trades)
    print(f"  M1 short (no PS): {len(m1)}")

    # Join per-trade with per-day factors
    factor_cols = ['date','confluence_count','veto_count','veto_any','regime_60d','year',
                   'c_gap_large_down','c_prior_day_weak','c_is_fomc_week','c_vixy_high',
                   'c_dow_friday','c_bear_930','c_c930_body_top_q',
                   'v_vixy_low','v_dow_monday']
    m1 = m1.merge(days[factor_cols], on='date', how='left')
    m1 = m1.dropna(subset=['confluence_count'])
    m1['confluence_count'] = m1['confluence_count'].astype(int)
    m1['veto_any'] = m1['veto_any'].astype(int)

    # Save per-trade
    m1_clean = m1[m1['veto_any']==0].copy()
    print(f"  M1 short after vetoes: {len(m1_clean)}")
    m1_clean.to_csv(OUT/'trades_m1_short_tagged.csv', index=False)

    # Tier summary
    print("\n=== TIER SUMMARY (8-year, no vetoes) ===")
    tier_df = tier_stats(m1_clean)
    print(tier_df.to_string(index=False))
    tier_df.to_csv(OUT/'tier_summary.csv', index=False)

    # Year breakdown
    print("\n=== YEAR BREAKDOWN (2+ tier) ===")
    year_rows = []
    for yr in sorted(m1_clean['year'].dropna().unique()):
        sub = m1_clean[(m1_clean['year']==yr) & (m1_clean['confluence_count']>=2)]
        if len(sub) < 5:
            continue
        wins = (sub['outcome']=='win').sum()
        wr = wins/len(sub)*100
        h2 = sub['hit_2_0R'].mean()*100
        h3 = sub['hit_3_0R'].mean()*100*100/100
        h5 = sub['hit_5_0R'].mean()*100
        h1n = sub[sub['hit_1_0R']==True]
        med_mfe = h1n['mfe_r'].median() if len(h1n) else float('nan')
        year_rows.append({'year':int(yr),'n':len(sub),'wr':round(wr,1),
                          'hit_2R':round(h2,1),'hit_3R':round(h3,1),'hit_5R':round(h5,1),
                          'med_mfe_1R+':round(med_mfe,2) if not pd.isna(med_mfe) else None})
    year_df = pd.DataFrame(year_rows)
    print(year_df.to_string(index=False))
    year_df.to_csv(OUT/'year_breakdown.csv', index=False)

    # Regime breakdown
    print("\n=== REGIME BREAKDOWN ===")
    regime_df = tier_stats(m1_clean, 'regime_60d')
    print(regime_df.to_string(index=False))
    regime_df.to_csv(OUT/'regime_breakdown.csv', index=False)

    # Setup-day predictability
    print("\n=== SETUP-DAY PREDICTABILITY (what predicts firing?) ===")
    pred_df = setup_day_predictability(days, m1_clean)
    print(pred_df.to_string(index=False))
    pred_df.to_csv(OUT/'setup_day_predictability.csv', index=False)

    # Print fire-rate context
    setup_days = days[(days['veto_any']==0) & (days['confluence_count']>=2)]
    fire_days = set(m1_clean['date'].unique())
    fired_setup = setup_days[setup_days['date'].isin(fire_days)]
    print(f"\nFire-rate context:")
    print(f"  Total setup days (no veto + 2+ conf): {len(setup_days)}")
    print(f"  Of which fired tradeable M1 short FVGC: {len(fired_setup)} ({len(fired_setup)/max(len(setup_days),1)*100:.1f}%)")
    print(f"  Avg trades per fired setup day: {len(m1_clean)/max(len(fired_setup),1):.2f}")

    # Save days frame for downstream
    days[['date','confluence_count','veto_count','veto_any','regime_60d','year',
          'c_gap_large_down','c_prior_day_weak','c_is_fomc_week','c_vixy_high',
          'c_dow_friday','c_bear_930','c_c930_body_top_q','v_vixy_low','v_dow_monday',
          'gap_from_prior_close','candle_930_body','candle_930_direction',
          'vixy_prior_close','day_of_week_name','is_fomc_week','overnight_range']
         ].to_csv(OUT/'days_with_factors.csv', index=False)

    print("\nWrote results to:")
    for f in OUT.iterdir():
        print(f"  {f}")


if __name__ == '__main__':
    main()
