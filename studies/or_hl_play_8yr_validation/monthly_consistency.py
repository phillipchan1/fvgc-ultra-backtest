#!/usr/bin/env python3
"""
Monthly consistency study + filter-stacking impact.

Goal: find filters that reduce the number of losing months and the worst-month
drawdown — even if they cost some total R per year. Smoother equity curve
matters more than peak R for live execution.

For each candidate filter combo, report:
  - Total R/yr
  - # of months traded
  - # losing months / % losing
  - Worst month R
  - Std dev of monthly R
  - Mean monthly R
  - Sharpe-like ratio (mean / std)
"""

import sys
from pathlib import Path
from datetime import date

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import numpy as np

STUDY_DIR = Path(__file__).resolve().parent
RESULTS_DIR = STUDY_DIR / 'results'


def load():
    df = pd.read_csv(RESULTS_DIR / 'magnet_aligned_30s.csv')
    df = df[df['magnet']=='aligned']
    df = df[df['or_range']<=150]
    df = df[df['variant']!='ifvg']
    df = df[df['outcome'].isin(['win','loss','eod'])]
    df['date'] = pd.to_datetime(df['date']).dt.date
    df['pnl_r'] = df['outcome_2r'].map({'WIN':2.0,'LOSS':-1.0,'PARTIAL':0.0})

    td = pd.read_csv(ROOT / 'data' / 'trading_days' / 'trading_days.csv')
    td['date'] = pd.to_datetime(td['date']).dt.date
    keep = ['date', 'gap_from_prior_close_pct', 'prior_day_type', 'prior_day_close_position',
             'candle_930_direction', 'fvgs_first_5min', 'fvgs_first_5min_bullish',
             'vixy_regime', 'has_pre_rth_news', 'has_red_folder_news',
             'is_fomc_week', 'is_opex_week', 'overnight_direction', 'day_of_week_name']
    keep = [c for c in keep if c in td.columns]
    df = df.merge(td[keep], on='date', how='left')

    cand = pd.read_parquet(ROOT / 'data' / 'consolidated' / 'nq-front-month.ohlcv-1m.parquet',
                            columns=['timestamp_ny','close'])
    cand['date'] = cand['timestamp_ny'].dt.date
    daily = cand.groupby('date')['close'].last().sort_index()
    df['ret_20d'] = df['date'].map((daily.pct_change(20)*100).to_dict())
    df['ret_5d'] = df['date'].map((daily.pct_change(5)*100).to_dict())
    df['ret_10d'] = df['date'].map((daily.pct_change(10)*100).to_dict())
    return df


def monthly_metrics(df: pd.DataFrame, label: str) -> dict:
    df = df.copy()
    df['ym'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m')
    months = df.groupby('ym').agg(
        n=('outcome_2r','size'),
        w=('outcome_2r', lambda x: (x=='WIN').sum()),
        l=('outcome_2r', lambda x: (x=='LOSS').sum()),
        r=('pnl_r','sum'),
    ).reset_index()
    months['wr'] = months['w']/(months['w']+months['l']).replace(0, np.nan)*100
    months['pf'] = months['w']*2 / months['l'].replace(0, np.nan)

    n_months = len(months)
    losing = months[months['r'] < 0]
    n_losing = len(losing)
    worst = months['r'].min()
    best = months['r'].max()
    mean_r = months['r'].mean()
    std_r = months['r'].std()
    sharpe = mean_r/std_r if std_r > 0 else 0
    total_r = months['r'].sum()
    yrs = n_months / 12
    pct_winning = (months['r']>0).mean() * 100

    n_trades = len(df)
    pf_overall = ((df['outcome_2r']=='WIN').sum()*2) / max(1,(df['outcome_2r']=='LOSS').sum())
    ev_per_trade = df['pnl_r'].mean()

    return {
        'label': label, 'n_trades': n_trades, 'n_months': n_months,
        'pf_overall': pf_overall, 'ev_r': ev_per_trade,
        'pct_winning_months': pct_winning,
        'n_losing': n_losing, 'worst_month_r': worst, 'best_month_r': best,
        'mean_month_r': mean_r, 'std_month_r': std_r,
        'sharpe': sharpe, 'total_r': total_r, 'r_per_yr': total_r/yrs if yrs > 0 else 0,
    }


def print_row(m):
    print(f"  {m['label']:<55s} {m['n_trades']:>5d} {m['pf_overall']:>5.2f} "
          f"{m['r_per_yr']:>+6.1f} {m['pct_winning_months']:>5.1f}% {m['n_losing']:>3d} "
          f"{m['worst_month_r']:>+5.1f} {m['mean_month_r']:>+5.2f} {m['sharpe']:>5.2f}")


def main():
    df = load()
    print(f"Universe: {len(df)} trades, {pd.to_datetime(df['date']).dt.strftime('%Y-%m').nunique()} months")

    # Quick look at Jan 2026 specifically
    print(f"\n{'='*80}\n  JAN 2026 DIAGNOSTIC\n{'='*80}")
    jan = df[(pd.to_datetime(df['date']).dt.year==2026) & (pd.to_datetime(df['date']).dt.month==1)]
    print(f"  Trades: {len(jan)}")
    print(f"  W/L: {(jan['outcome_2r']=='WIN').sum()}/{(jan['outcome_2r']=='LOSS').sum()}")
    print(f"  Long: {(jan['direction']=='long').sum()} trades, "
          f"WR {((jan['direction']=='long')&(jan['outcome_2r']=='WIN')).sum()/max(1,(jan['direction']=='long').sum())*100:.0f}%")
    print(f"  Short: {(jan['direction']=='short').sum()} trades, "
          f"WR {((jan['direction']=='short')&(jan['outcome_2r']=='WIN')).sum()/max(1,(jan['direction']=='short').sum())*100:.0f}%")
    print(f"\n  Context flags during Jan 2026:")
    print(f"    FOMC weeks:   {(jan['is_fomc_week']==True).sum()} trades")
    print(f"    OpEx weeks:   {(jan['is_opex_week']==True).sum()} trades")
    print(f"    Range days:   {(jan['prior_day_type']=='range').sum()} trades")
    print(f"    VIX elevated: {(jan['vixy_regime']=='elevated').sum()} trades")
    print(f"    VIX low:      {(jan['vixy_regime']=='low').sum()} trades")
    print(f"    VIX high:     {(jan['vixy_regime']=='high').sum()} trades")
    print(f"    VIX normal:   {(jan['vixy_regime']=='normal').sum()} trades")
    print(f"  20d return range in Jan 2026: {jan['ret_20d'].min():.1f}% to {jan['ret_20d'].max():.1f}%")

    # Filter combos
    print(f"\n{'='*80}\n  FILTER STACKING — monthly consistency comparison\n{'='*80}")
    print(f"  {'Config':<55s} {'n':>5s} {'PF':>5s} {'R/yr':>6s} {'Win%':>6s} {'Lose':>3s} {'Worst':>5s} {'mean':>5s} {'Shar':>5s}")
    print(f"  {'─'*120}")

    base = df.copy()

    results = []
    results.append(monthly_metrics(base, 'BASELINE (current v4 spec)'))

    # Kill switch 1: drop FOMC weeks
    a = base[base['is_fomc_week']!=True]
    results.append(monthly_metrics(a, '- FOMC week'))

    # Kill switch 2: drop OpEx weeks
    a = base[base['is_opex_week']!=True]
    results.append(monthly_metrics(a, '- OpEx week'))

    # Kill switch 3: drop range-day priors
    a = base[base['prior_day_type']!='range']
    results.append(monthly_metrics(a, '- prior_day=range'))

    # Kill switch 4: drop VIX=elevated
    a = base[base['vixy_regime']!='elevated']
    results.append(monthly_metrics(a, '- VIX=elevated'))

    # Combined kill switches
    combo1 = base[(base['is_fomc_week']!=True) & (base['is_opex_week']!=True)]
    results.append(monthly_metrics(combo1, '- FOMC - OpEx'))

    combo2 = base[(base['is_fomc_week']!=True) & (base['prior_day_type']!='range')]
    results.append(monthly_metrics(combo2, '- FOMC - range'))

    combo3 = base[(base['is_fomc_week']!=True) & (base['is_opex_week']!=True) & (base['prior_day_type']!='range')]
    results.append(monthly_metrics(combo3, '- FOMC - OpEx - range'))

    combo4 = base[(base['is_fomc_week']!=True) & (base['is_opex_week']!=True) & (base['prior_day_type']!='range') & (base['vixy_regime']!='elevated')]
    results.append(monthly_metrics(combo4, '- FOMC - OpEx - range - VIX_elev'))

    # Add positive factor filter (require ≥1 5min FVG)
    combo5 = base[base['fvgs_first_5min'] >= 1]
    results.append(monthly_metrics(combo5, '+ requires ≥1 5min FVG'))

    combo6 = combo3[combo3['fvgs_first_5min'] >= 1]
    results.append(monthly_metrics(combo6, '- FOMC - OpEx - range  +5min FVG'))

    # Conservative regime stack
    combo7 = base[(base['is_fomc_week']!=True) & (base['is_opex_week']!=True) &
                   (base['prior_day_type']!='range') & (base['vixy_regime']!='elevated') &
                   (base['fvgs_first_5min'] >= 1)]
    results.append(monthly_metrics(combo7, 'FULL: -FOMC -OpEx -range -VIXelev +5minFVG'))

    for r in results:
        print_row(r)

    # Save the best combo's monthly breakdown
    print(f"\n{'='*80}\n  WORST 10 MONTHS — best filter combo\n{'='*80}")
    best_combo = combo7.copy()
    best_combo['ym'] = pd.to_datetime(best_combo['date']).dt.strftime('%Y-%m')
    months = best_combo.groupby('ym').agg(
        n=('outcome_2r','size'),
        w=('outcome_2r', lambda x: (x=='WIN').sum()),
        l=('outcome_2r', lambda x: (x=='LOSS').sum()),
        r=('pnl_r','sum'),
    ).reset_index()
    months['wr'] = months['w']/(months['w']+months['l']).replace(0,np.nan)*100
    for _, m in months.nsmallest(10, 'r').iterrows():
        print(f"  {m['ym']}  n={m['n']:3d}  W={m['w']:3d} L={m['l']:3d}  WR={m['wr']:.0f}%  R={m['r']:+5.1f}R")

    print(f"\n  Total profitable months: {(months['r']>0).sum()}/{len(months)} ({(months['r']>0).mean()*100:.0f}%)")

    # Save full monthly table
    months.to_csv(RESULTS_DIR / 'monthly_filtered_best.csv', index=False)


if __name__ == '__main__':
    main()
