#!/usr/bin/env python3
"""
Permutation testing framework for FVGC trade filters.

Joins trading_days.csv to baseline trades, applies filters to define subsets,
then runs permutation tests to determine statistical significance.

Usage:
    python analysis/permutation_test.py                     # all filters, 10k perms
    python analysis/permutation_test.py --perms 1000        # quick run
    python analysis/permutation_test.py --metric win_rate   # choose metric
    python analysis/permutation_test.py --filter "Tuesday"  # single filter
    python analysis/permutation_test.py --no-histograms     # skip histogram generation
"""

import sys
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns
from datetime import time as dtime

TRADING_DAYS_PATH = ROOT / 'data' / 'trading_days' / 'trading_days.csv'
TRADES_PATH = ROOT / 'logs' / 'baseline_trades.csv'
RESULTS_DIR = ROOT / 'analysis' / 'results'
HISTOGRAMS_DIR = RESULTS_DIR / 'histograms'


# ===================================================================
# Data loading and joining
# ===================================================================

def load_data() -> pd.DataFrame:
    print("Loading data...")
    td = pd.read_csv(TRADING_DAYS_PATH)
    td['date'] = pd.to_datetime(td['date']).dt.date

    trades = pd.read_csv(TRADES_PATH)
    trades['timestamp'] = pd.to_datetime(trades['timestamp'])
    trades['date'] = trades['timestamp'].dt.date
    trades['entry_time'] = trades['timestamp'].dt.time

    tradeable = trades[trades['outcome'].isin(['win', 'loss'])].copy()
    print(f"  {len(td)} trading days, {len(trades)} total trades, "
          f"{len(tradeable)} tradeable (win/loss)")

    merged = tradeable.merge(td, on='date', how='left')
    print(f"  {len(merged)} trades after join")

    merged = enrich_trade_properties(merged)
    return merged


def enrich_trade_properties(df: pd.DataFrame) -> pd.DataFrame:
    """Add trade-level properties derived from the trades list."""
    df = df.sort_values('timestamp').reset_index(drop=True)

    # minutes_into_session
    def mins_after_930(t):
        return (t.hour - 9) * 60 + (t.minute - 30) + t.second / 60
    df['minutes_into_session'] = df['entry_time'].apply(mins_after_930)

    # macro_window: which 15-min window (1-4)
    def macro_window(t):
        m = mins_after_930(t)
        if m < 15:
            return 1
        elif m < 30:
            return 2
        elif m < 45:
            return 3
        elif m < 60:
            return 4
        return 5  # after 10:30
    df['macro_window'] = df['entry_time'].apply(macro_window)

    # signal_number_today: 1st, 2nd, 3rd+ of the day
    df['signal_number_today'] = df.groupby('date').cumcount() + 1

    # same_direction_streak
    streaks = []
    prev_dir = None
    streak = 0
    for _, row in df.iterrows():
        if row['direction'] == prev_dir:
            streak += 1
        else:
            streak = 0
        streaks.append(streak)
        prev_dir = row['direction']
    df['same_direction_streak'] = streaks

    return df


# ===================================================================
# Permutation test engine
# ===================================================================

def compute_metric(df: pd.DataFrame, metric: str) -> float | None:
    if len(df) == 0:
        return None
    if metric == 'win_rate':
        return (df['outcome'] == 'win').mean() * 100
    elif metric == 'avg_pnl':
        pnl = pd.to_numeric(df['pnl'], errors='coerce')
        return pnl.mean()
    elif metric == 'profit_factor':
        pnl = pd.to_numeric(df['pnl'], errors='coerce')
        gross_profit = pnl[pnl > 0].sum()
        gross_loss = abs(pnl[pnl < 0].sum())
        if gross_loss == 0:
            return np.inf if gross_profit > 0 else np.nan
        return gross_profit / gross_loss
    return None


def run_permutation_test(
    full_df: pd.DataFrame,
    filter_fn,
    metric: str,
    n_perms: int = 10_000,
    rng: np.random.Generator = None,
) -> dict:
    """Run a permutation test for a single filter."""
    if rng is None:
        rng = np.random.default_rng(42)

    subset = filter_fn(full_df)
    n_subset = len(subset)

    if n_subset < 5:
        return {
            'n': n_subset,
            'actual': None,
            'mean_perm': None,
            'p_value': None,
            'significant_05': False,
            'significant_01': False,
            'perm_distribution': [],
        }

    actual = compute_metric(subset, metric)
    if actual is None or (isinstance(actual, float) and np.isnan(actual)):
        return {
            'n': n_subset,
            'actual': actual,
            'mean_perm': None,
            'p_value': None,
            'significant_05': False,
            'significant_01': False,
            'perm_distribution': [],
        }

    # Baseline metric (all trades)
    baseline = compute_metric(full_df, metric)

    outcomes = full_df['outcome'].values.copy()
    pnl_vals = pd.to_numeric(full_df['pnl'], errors='coerce').values.copy()

    # Build index mask for the filter (positions in full_df that pass filter)
    mask = filter_fn(full_df).index
    filter_indices = np.isin(np.arange(len(full_df)), full_df.index.get_indexer(mask))

    perm_metrics = np.empty(n_perms)
    for i in range(n_perms):
        perm_order = rng.permutation(len(outcomes))
        shuffled_outcomes = outcomes[perm_order]
        shuffled_pnl = pnl_vals[perm_order]

        sub_outcomes = shuffled_outcomes[filter_indices]
        sub_pnl = shuffled_pnl[filter_indices]

        if metric == 'win_rate':
            perm_metrics[i] = (sub_outcomes == 'win').mean() * 100
        elif metric == 'avg_pnl':
            perm_metrics[i] = np.nanmean(sub_pnl)
        elif metric == 'profit_factor':
            gp = sub_pnl[sub_pnl > 0].sum()
            gl = abs(sub_pnl[sub_pnl < 0].sum())
            if gl > 0:
                perm_metrics[i] = gp / gl
            elif gp > 0:
                perm_metrics[i] = np.inf
            else:
                perm_metrics[i] = np.nan

    # Two-sided p-value: how extreme is actual vs permutation distribution?
    perm_mean = np.nanmean(perm_metrics)
    if actual >= perm_mean:
        p_value = np.nanmean(perm_metrics >= actual)
    else:
        p_value = np.nanmean(perm_metrics <= actual)

    return {
        'n': n_subset,
        'actual': actual,
        'baseline': baseline,
        'mean_perm': perm_mean,
        'std_perm': np.nanstd(perm_metrics),
        'p_value': p_value,
        'significant_05': p_value < 0.05,
        'significant_01': p_value < 0.01,
        'perm_distribution': perm_metrics,
    }


# ===================================================================
# Filter library
# ===================================================================

def build_filter_library(df: pd.DataFrame) -> dict:
    """Build comprehensive filter library from the joined data."""
    filters = {}

    # --- Calendar ---
    for dow, name in enumerate(['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']):
        filters[f'Calendar: {name}'] = lambda d, dow=dow: d[d['day_of_week'] == dow]

    for month_num in range(1, 13):
        import calendar
        month_name = calendar.month_name[month_num]
        filters[f'Calendar: {month_name}'] = lambda d, m=month_num: d[d['month'] == m]

    filters['Calendar: Month Start (first 3 days)'] = lambda d: d[d['is_month_start'] == True]
    filters['Calendar: Month End (last 3 days)'] = lambda d: d[d['is_month_end'] == True]
    filters['Calendar: FOMC Week'] = lambda d: d[d['is_fomc_week'] == True]
    filters['Calendar: OpEx Week'] = lambda d: d[d['is_opex_week'] == True]
    filters['Calendar: Quad Witching Day'] = lambda d: d[d['is_quad_witching'] == True]

    # --- VIXY Regime ---
    for regime in ['low', 'normal', 'elevated', 'high']:
        filters[f'VIXY: {regime.title()} Regime'] = lambda d, r=regime: d[d['vixy_regime'] == r]

    # --- News ---
    filters['News: Red Folder Day'] = lambda d: d[d['has_red_folder_news'] == True]
    filters['News: No Red Folder'] = lambda d: d[d['has_red_folder_news'] == False]
    filters['News: Pre-RTH News'] = lambda d: d[d['has_pre_rth_news'] == True]
    filters['News: No Pre-RTH News'] = lambda d: d[d['has_pre_rth_news'] == False]
    filters['News: During-Session News'] = lambda d: d[d['has_during_session_news'] == True]

    # --- Opening Range (quintile-based) ---
    for col, label in [('or_5min_range', '5min OR'), ('or_15min_range', '15min OR'),
                       ('or_45min_range', '45min OR')]:
        valid = df[col].dropna()
        if len(valid) > 0:
            q20, q80 = valid.quantile([0.2, 0.8])
            filters[f'Range: Tight {label} (bottom 20%)'] = lambda d, c=col, v=q20: d[d[c] <= v]
            filters[f'Range: Wide {label} (top 20%)'] = lambda d, c=col, v=q80: d[d[c] >= v]

    # --- RTH Range ---
    valid_rth = df['rth_range'].dropna()
    if len(valid_rth) > 0:
        q20, q80 = valid_rth.quantile([0.2, 0.8])
        filters['Range: Tight RTH Day (bottom 20%)'] = lambda d, v=q20: d[d['rth_range'] <= v]
        filters['Range: Wide RTH Day (top 20%)'] = lambda d, v=q80: d[d['rth_range'] >= v]

    # --- Prior Day ---
    filters['Prior Day: Trending Up (close pos > 0.75)'] = lambda d: d[d['prior_day_close_position'] > 0.75]
    filters['Prior Day: Trending Down (close pos < 0.25)'] = lambda d: d[d['prior_day_close_position'] < 0.25]
    filters['Prior Day: Choppy (0.25-0.75)'] = lambda d: d[
        (d['prior_day_close_position'] >= 0.25) & (d['prior_day_close_position'] <= 0.75)
    ]

    # --- Overnight ---
    filters['Overnight: Gap Up'] = lambda d: d[d['gap_from_prior_close'] > 0]
    filters['Overnight: Gap Down'] = lambda d: d[d['gap_from_prior_close'] < 0]
    filters['Overnight: Direction Up'] = lambda d: d[d['overnight_direction'] == 'up']
    filters['Overnight: Direction Down'] = lambda d: d[d['overnight_direction'] == 'down']
    filters['Overnight: Flat'] = lambda d: d[d['overnight_direction'] == 'flat']

    valid_on = df['overnight_range'].dropna()
    if len(valid_on) > 0:
        q20, q80 = valid_on.quantile([0.2, 0.8])
        filters['Overnight: Tight Range (bottom 20%)'] = lambda d, v=q20: d[d['overnight_range'] <= v]
        filters['Overnight: Wide Range (top 20%)'] = lambda d, v=q80: d[d['overnight_range'] >= v]

    # --- 9:30 Candle ---
    filters['930 Candle: Bullish'] = lambda d: d[d['candle_930_direction'] == 'bullish']
    filters['930 Candle: Bearish'] = lambda d: d[d['candle_930_direction'] == 'bearish']

    valid_930 = df['candle_930_range'].dropna()
    if len(valid_930) > 0:
        q80 = valid_930.quantile(0.8)
        q20 = valid_930.quantile(0.2)
        filters['930 Candle: Large Range (top 20%)'] = lambda d, v=q80: d[d['candle_930_range'] >= v]
        filters['930 Candle: Small Range (bottom 20%)'] = lambda d, v=q20: d[d['candle_930_range'] <= v]

    # --- FVG Counts ---
    filters['FVGs: Zero in First 5min'] = lambda d: d[d['fvgs_first_5min'] == 0]
    filters['FVGs: 1+ in First 5min'] = lambda d: d[d['fvgs_first_5min'] >= 1]
    filters['FVGs: 3+ in First 15min'] = lambda d: d[d['fvgs_first_15min'] >= 3]

    # --- Trade-Level ---
    filters['Trade: Macro Window 1 (9:30-9:45)'] = lambda d: d[d['macro_window'] == 1]
    filters['Trade: Macro Window 2 (9:45-10:00)'] = lambda d: d[d['macro_window'] == 2]
    filters['Trade: Macro Window 3 (10:00-10:15)'] = lambda d: d[d['macro_window'] == 3]
    filters['Trade: Macro Window 4 (10:15-10:30)'] = lambda d: d[d['macro_window'] == 4]

    filters['Trade: 1st Signal of Day'] = lambda d: d[d['signal_number_today'] == 1]
    filters['Trade: 2nd Signal of Day'] = lambda d: d[d['signal_number_today'] == 2]
    filters['Trade: 3rd+ Signal of Day'] = lambda d: d[d['signal_number_today'] >= 3]

    filters['Trade: Long'] = lambda d: d[d['direction'] == 'long']
    filters['Trade: Short'] = lambda d: d[d['direction'] == 'short']

    filters['Trade: No Streak (direction change)'] = lambda d: d[d['same_direction_streak'] == 0]
    filters['Trade: 2+ Same Direction Streak'] = lambda d: d[d['same_direction_streak'] >= 2]

    # --- Variant ---
    for v in ['no_fvg', 'ifvg', 'bos', 'protected_swing']:
        filters[f'Variant: {v}'] = lambda d, var=v: d[d['variant'] == var]

    # --- Combination Filters ---
    filters['Combo: Tuesday + Low VIXY'] = lambda d: d[
        (d['day_of_week'] == 1) & (d['vixy_regime'] == 'low')
    ]
    or5_q30 = df['or_5min_range'].quantile(0.3) if df['or_5min_range'].notna().any() else np.inf
    filters['Combo: No News + Tight 5min OR'] = lambda d, v=or5_q30: d[
        (d['has_red_folder_news'] == False) & (d['or_5min_range'] <= v)
    ]

    filters['Combo: FOMC Week + 1st Signal'] = lambda d: d[
        (d['is_fomc_week'] == True) & (d['signal_number_today'] == 1)
    ]
    filters['Combo: Gap Up + Bearish 930'] = lambda d: d[
        (d['gap_from_prior_close'] > 0) & (d['candle_930_direction'] == 'bearish')
    ]
    filters['Combo: Gap Down + Bullish 930'] = lambda d: d[
        (d['gap_from_prior_close'] < 0) & (d['candle_930_direction'] == 'bullish')
    ]
    filters['Combo: Prior Day Trending Up + Long'] = lambda d: d[
        (d['prior_day_close_position'] > 0.75) & (d['direction'] == 'long')
    ]
    filters['Combo: Prior Day Trending Down + Short'] = lambda d: d[
        (d['prior_day_close_position'] < 0.25) & (d['direction'] == 'short')
    ]
    on_q70 = df['overnight_range'].quantile(0.7) if df['overnight_range'].notna().any() else np.inf
    filters['Combo: Wide Overnight + Macro Window 1'] = lambda d, v=on_q70: d[
        (d['overnight_range'] >= v) & (d['macro_window'] == 1)
    ]
    filters['Combo: High VIXY + Short'] = lambda d: d[
        (d['vixy_regime'] == 'high') & (d['direction'] == 'short')
    ]
    filters['Combo: Month End + OpEx Week'] = lambda d: d[
        (d['is_month_end'] == True) & (d['is_opex_week'] == True)
    ]

    return filters


# ===================================================================
# Histogram generation
# ===================================================================

def plot_histogram(result: dict, filter_name: str, metric: str, output_dir: Path):
    if not result['perm_distribution'].any() or result['actual'] is None:
        return

    fig, ax = plt.subplots(figsize=(8, 5))
    dist = result['perm_distribution']
    dist = dist[np.isfinite(dist)]

    sns.histplot(dist, bins=50, ax=ax, color='steelblue', alpha=0.7, edgecolor='white')
    ax.axvline(result['actual'], color='red', linewidth=2, linestyle='--',
               label=f'Actual: {result["actual"]:.2f}')
    ax.axvline(result['mean_perm'], color='gray', linewidth=1, linestyle=':',
               label=f'Mean perm: {result["mean_perm"]:.2f}')

    p_str = f'p={result["p_value"]:.4f}' if result['p_value'] is not None else 'p=N/A'
    sig = ''
    if result.get('significant_01'):
        sig = ' **'
    elif result.get('significant_05'):
        sig = ' *'

    ax.set_title(f'{filter_name}\n{metric} | n={result["n"]} | {p_str}{sig}', fontsize=11)
    ax.set_xlabel(metric.replace('_', ' ').title())
    ax.set_ylabel('Count')
    ax.legend(fontsize=9)
    plt.tight_layout()

    safe_name = filter_name.replace(':', '').replace('/', '_').replace(' ', '_')
    safe_name = safe_name.replace('(', '').replace(')', '').replace('+', 'and')
    fig.savefig(output_dir / f'{safe_name}.png', dpi=100)
    plt.close(fig)


# ===================================================================
# Main
# ===================================================================

def main():
    parser = argparse.ArgumentParser(description='FVGC Permutation Testing')
    parser.add_argument('--perms', type=int, default=10_000, help='Number of permutations')
    parser.add_argument('--metric', default='win_rate',
                        choices=['win_rate', 'avg_pnl', 'profit_factor'],
                        help='Metric to test')
    parser.add_argument('--filter', type=str, default=None,
                        help='Run only filters matching this substring')
    parser.add_argument('--no-histograms', action='store_true',
                        help='Skip histogram generation')
    parser.add_argument('--seed', type=int, default=42, help='Random seed')
    args = parser.parse_args()

    df = load_data()

    all_filters = build_filter_library(df)

    if args.filter:
        selected = {k: v for k, v in all_filters.items()
                    if args.filter.lower() in k.lower()}
        if not selected:
            print(f"No filters matching '{args.filter}'. Available:")
            for k in sorted(all_filters.keys()):
                print(f"  {k}")
            return
    else:
        selected = all_filters

    print(f"\nRunning {len(selected)} filters x {args.perms:,} permutations "
          f"(metric: {args.metric})")
    print("=" * 60)

    baseline_metric = compute_metric(df, args.metric)
    print(f"Baseline ({len(df)} trades): {args.metric} = {baseline_metric:.2f}\n")

    rng = np.random.default_rng(args.seed)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    if not args.no_histograms:
        HISTOGRAMS_DIR.mkdir(parents=True, exist_ok=True)

    results = []
    for i, (name, fn) in enumerate(sorted(selected.items()), 1):
        try:
            result = run_permutation_test(df, fn, args.metric, args.perms, rng)
        except Exception as e:
            print(f"  [{i}/{len(selected)}] {name}: ERROR - {e}")
            continue

        actual_str = f'{result["actual"]:.2f}' if result['actual'] is not None else 'N/A'
        p_str = f'{result["p_value"]:.4f}' if result['p_value'] is not None else 'N/A'
        sig = ''
        if result.get('significant_01'):
            sig = ' **'
        elif result.get('significant_05'):
            sig = ' *'
        print(f"  [{i}/{len(selected)}] {name}: n={result['n']}, "
              f"{args.metric}={actual_str}, p={p_str}{sig}")

        results.append({
            'filter': name,
            'n_trades': result['n'],
            f'actual_{args.metric}': result['actual'],
            f'baseline_{args.metric}': result.get('baseline'),
            f'mean_perm_{args.metric}': result.get('mean_perm'),
            f'std_perm_{args.metric}': result.get('std_perm'),
            'p_value': result['p_value'],
            'significant_05': result.get('significant_05', False),
            'significant_01': result.get('significant_01', False),
        })

        if not args.no_histograms and result['actual'] is not None and len(result['perm_distribution']) > 0:
            plot_histogram(result, name, args.metric, HISTOGRAMS_DIR)

    # Summary table
    summary = pd.DataFrame(results)
    summary = summary.sort_values('p_value', na_position='last').reset_index(drop=True)

    summary_path = RESULTS_DIR / 'summary_table.csv'
    summary.to_csv(summary_path, index=False)
    print(f"\n{'=' * 60}")
    print(f"Summary table written to {summary_path}")
    print(f"Histograms written to {HISTOGRAMS_DIR}/")

    # Print top results
    sig_results = summary[summary['significant_05'] == True]
    print(f"\nSignificant results (p < 0.05): {len(sig_results)}/{len(summary)}")
    if len(sig_results) > 0:
        print("\nTop significant filters:")
        for _, row in sig_results.head(20).iterrows():
            marker = '**' if row['significant_01'] else '*'
            print(f"  {marker} {row['filter']}: n={row['n_trades']}, "
                  f"{args.metric}={row[f'actual_{args.metric}']:.2f}, "
                  f"p={row['p_value']:.4f}")


if __name__ == '__main__':
    main()
