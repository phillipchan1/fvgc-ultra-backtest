#!/usr/bin/env python3
"""
Volume Profile Confluence Study

Tests whether FVGC entries near prior-day volume profile levels (POC, VAH, VAL)
produce better outcomes. Includes segmentation analysis, directional alignment,
multi-R exit analysis, permutation testing, and multi-timeframe comparison.

Usage:
    python studies/volume_profile_confluence/run.py                  # full run
    python studies/volume_profile_confluence/run.py --perms 1000     # quick
    python studies/volume_profile_confluence/run.py --no-histograms  # skip plots
    python studies/volume_profile_confluence/run.py --no-multitf     # skip multi-TF
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from analysis.permutation_test import (  # noqa: E402
    compute_metric,
    run_permutation_test,
)

ROOT = Path(__file__).resolve().parent.parent.parent
STUDY_DIR = Path(__file__).resolve().parent
RESULTS_DIR = STUDY_DIR / 'results'
HISTOGRAMS_DIR = RESULTS_DIR / 'histograms'

VP_TRADES_PATH = ROOT / 'data' / 'levels' / 'trades_with_vp.csv'
TRADING_DAYS_PATH = ROOT / 'data' / 'trading_days' / 'trading_days.csv'

R_LEVELS = ['1_0', '1_5', '2_0', '2_5', '3_0', '4_0', '5_0']


# ===================================================================
# Data loading
# ===================================================================

def load_data() -> pd.DataFrame:
    """Load VP-enriched trades and join with trading_days context."""
    print('Loading data...')
    trades = pd.read_csv(VP_TRADES_PATH)
    trades['timestamp'] = pd.to_datetime(trades['timestamp'])
    trades['date'] = trades['timestamp'].dt.date

    td = pd.read_csv(TRADING_DAYS_PATH)
    td['date'] = pd.to_datetime(td['date']).dt.date

    # Keep only tradeable (win/loss) with valid VP
    tradeable = trades[
        trades['outcome'].isin(['win', 'loss']) &
        trades['prior_vp_poc'].notna()
    ].copy()

    merged = tradeable.merge(td, on='date', how='left')
    print(f'  {len(tradeable)} tradeable trades with VP data')
    return merged


# ===================================================================
# Segmentation analysis
# ===================================================================

def compute_segment_stats(df: pd.DataFrame, label: str) -> dict:
    """Compute WR, PF, N, avg PnL for a segment."""
    n = len(df)
    if n == 0:
        return {'label': label, 'n': 0, 'wins': 0, 'losses': 0,
                'wr': None, 'pf': None, 'avg_pnl': None, 'total_pnl': None}

    wins = (df['outcome'] == 'win').sum()
    losses = (df['outcome'] == 'loss').sum()
    pnl = pd.to_numeric(df['pnl'], errors='coerce')
    gross_profit = pnl[pnl > 0].sum()
    gross_loss = abs(pnl[pnl < 0].sum())
    pf = gross_profit / gross_loss if gross_loss > 0 else (np.inf if gross_profit > 0 else np.nan)
    wr = wins / (wins + losses) * 100 if (wins + losses) > 0 else None

    return {
        'label': label,
        'n': n,
        'wins': int(wins),
        'losses': int(losses),
        'wr': round(wr, 1) if wr is not None else None,
        'pf': round(pf, 2) if not np.isinf(pf) and not np.isnan(pf) else pf,
        'avg_pnl': round(pnl.mean(), 2),
        'total_pnl': round(pnl.sum(), 2),
    }


def run_segmentation(df: pd.DataFrame) -> pd.DataFrame:
    """Run segmentation analysis across all VP cuts."""
    segments = []

    # Baseline
    segments.append(compute_segment_stats(df, 'ALL TRADES'))

    # Near POC at multiple thresholds
    for th in [10, 15, 20]:
        col = f'near_poc_{th}pt'
        segments.append(compute_segment_stats(df[df[col] == True], f'Near POC ({th}pt)'))
        segments.append(compute_segment_stats(df[df[col] == False], f'NOT near POC ({th}pt)'))

    # Near VAH / VAL
    for level in ['vah', 'val']:
        for th in [10, 15, 20]:
            col = f'near_{level}_{th}pt'
            segments.append(compute_segment_stats(
                df[df[col] == True], f'Near {level.upper()} ({th}pt)'))

    # Near any VP level
    for th in [10, 15, 20]:
        col = f'near_any_vp_{th}pt'
        segments.append(compute_segment_stats(df[df[col] == True], f'Near ANY VP ({th}pt)'))
        segments.append(compute_segment_stats(df[df[col] == False], f'NOT near ANY VP ({th}pt)'))

    # R-based proximity
    segments.append(compute_segment_stats(
        df[df['near_any_vp_1R'] == True], 'Near ANY VP (≤1R)'))
    segments.append(compute_segment_stats(
        df[df['near_any_vp_half_R'] == True], 'Near ANY VP (≤0.5R)'))

    # Value area position
    segments.append(compute_segment_stats(
        df[df['entry_in_value_area'] == True], 'Inside Value Area'))
    segments.append(compute_segment_stats(
        df[df['entry_in_value_area'] == False], 'Outside Value Area'))
    segments.append(compute_segment_stats(
        df[df['entry_above_va'] == True], 'Above VA'))
    segments.append(compute_segment_stats(
        df[df['entry_below_va'] == True], 'Below VA'))

    return pd.DataFrame(segments)


# ===================================================================
# Directional alignment
# ===================================================================

def run_directional_alignment(df: pd.DataFrame) -> pd.DataFrame:
    """Test if direction-aligned VP proximity improves outcomes."""
    rows = []

    # Longs near VAL (support confluence)
    longs = df[df['direction'] == 'long']
    rows.append(compute_segment_stats(longs, 'ALL longs'))
    rows.append(compute_segment_stats(
        longs[longs['long_near_val'] == True], 'Longs near VAL (15pt)'))
    rows.append(compute_segment_stats(
        longs[longs['long_near_val'] == False], 'Longs NOT near VAL'))

    # Also test longs near POC
    for th in [10, 15]:
        rows.append(compute_segment_stats(
            longs[longs[f'near_poc_{th}pt'] == True], f'Longs near POC ({th}pt)'))

    # Shorts near VAH (resistance confluence)
    shorts = df[df['direction'] == 'short']
    rows.append(compute_segment_stats(shorts, 'ALL shorts'))
    rows.append(compute_segment_stats(
        shorts[shorts['short_near_vah'] == True], 'Shorts near VAH (15pt)'))
    rows.append(compute_segment_stats(
        shorts[shorts['short_near_vah'] == False], 'Shorts NOT near VAH'))

    for th in [10, 15]:
        rows.append(compute_segment_stats(
            shorts[shorts[f'near_poc_{th}pt'] == True], f'Shorts near POC ({th}pt)'))

    # Combined directional alignment
    rows.append(compute_segment_stats(
        df[df['directional_vp_aligned'] == True], 'Directional VP aligned'))
    rows.append(compute_segment_stats(
        df[df['directional_vp_aligned'] == False], 'NOT directional VP aligned'))

    return pd.DataFrame(rows)


# ===================================================================
# Multi-R exit analysis
# ===================================================================

def run_multi_r_analysis(df: pd.DataFrame) -> pd.DataFrame:
    """Compare R-level hit rates across VP cohorts."""
    cohorts = {
        'ALL': df,
        'Near ANY VP (15pt)': df[df['near_any_vp_15pt'] == True],
        'NOT near VP (15pt)': df[df['near_any_vp_15pt'] == False],
        'Near POC (15pt)': df[df['near_poc_15pt'] == True],
        'Inside VA': df[df['entry_in_value_area'] == True],
        'Outside VA': df[df['entry_in_value_area'] == False],
        'Dir. VP aligned': df[df['directional_vp_aligned'] == True],
    }

    rows = []
    for label, cohort in cohorts.items():
        if len(cohort) == 0:
            continue
        row = {'cohort': label, 'n': len(cohort)}
        for r in R_LEVELS:
            col = f'hit_{r}R'
            if col in cohort.columns:
                hits = pd.to_numeric(cohort[col], errors='coerce')
                row[f'hit_{r}R_rate'] = round(hits.mean() * 100, 1)
            else:
                row[f'hit_{r}R_rate'] = None
        rows.append(row)

    return pd.DataFrame(rows)


# ===================================================================
# Permutation testing
# ===================================================================

def run_vp_permutation_tests(
    df: pd.DataFrame,
    n_perms: int = 10_000,
    draw_histograms: bool = True,
) -> pd.DataFrame:
    """Run permutation tests for VP filters on win_rate and profit_factor."""
    rng = np.random.default_rng(42)

    filters = {}

    # Proximity filters
    for th in [10, 15, 20]:
        filters[f'near_poc_{th}pt'] = lambda d, c=f'near_poc_{th}pt': d[d[c] == True]
        filters[f'near_vah_{th}pt'] = lambda d, c=f'near_vah_{th}pt': d[d[c] == True]
        filters[f'near_val_{th}pt'] = lambda d, c=f'near_val_{th}pt': d[d[c] == True]
        filters[f'near_any_vp_{th}pt'] = lambda d, c=f'near_any_vp_{th}pt': d[d[c] == True]

    # R-based
    filters['near_any_vp_1R'] = lambda d: d[d['near_any_vp_1R'] == True]
    filters['near_any_vp_half_R'] = lambda d: d[d['near_any_vp_half_R'] == True]

    # Value area
    filters['inside_va'] = lambda d: d[d['entry_in_value_area'] == True]
    filters['outside_va'] = lambda d: d[d['entry_in_value_area'] == False]

    # Directional
    filters['long_near_val'] = lambda d: d[d['long_near_val'] == True]
    filters['short_near_vah'] = lambda d: d[d['short_near_vah'] == True]
    filters['directional_aligned'] = lambda d: d[d['directional_vp_aligned'] == True]

    results = []
    for metric in ['win_rate', 'profit_factor']:
        print(f'\n  Permutation tests ({metric}, {n_perms} perms):')
        for name, fn in filters.items():
            res = run_permutation_test(df, fn, metric, n_perms=n_perms, rng=rng)
            sig = '***' if res.get('significant_01') else ('**' if res.get('significant_05') else '')
            actual_str = f"{res['actual']:.1f}" if res['actual'] is not None else 'N/A'
            p_str = f"{res['p_value']:.4f}" if res['p_value'] is not None else 'N/A'
            print(f'    {name:30s}  n={res["n"]:4d}  actual={actual_str:>6s}  '
                  f'p={p_str}  {sig}')

            results.append({
                'filter': name,
                'metric': metric,
                'n': res['n'],
                'actual': res['actual'],
                'baseline': res.get('baseline'),
                'mean_perm': res['mean_perm'],
                'p_value': res['p_value'],
                'significant_05': res.get('significant_05', False),
                'significant_01': res.get('significant_01', False),
            })

            # Histogram
            if draw_histograms and res.get('perm_distribution') is not None and len(res['perm_distribution']) > 0:
                _draw_histogram(name, metric, res)

    return pd.DataFrame(results)


def _draw_histogram(name: str, metric: str, res: dict):
    """Draw permutation distribution histogram with actual value line."""
    HISTOGRAMS_DIR.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(8, 4))
    dist = res['perm_distribution']
    finite = dist[np.isfinite(dist)]
    if len(finite) == 0:
        plt.close(fig)
        return
    ax.hist(finite, bins=50, alpha=0.7, color='steelblue', edgecolor='white')
    if res['actual'] is not None and np.isfinite(res['actual']):
        ax.axvline(res['actual'], color='red', linewidth=2,
                   label=f'Actual: {res["actual"]:.2f}')
    ax.set_title(f'{name} — {metric}\n(n={res["n"]}, p={res["p_value"]:.4f})')
    ax.set_xlabel(metric)
    ax.set_ylabel('Permutation count')
    ax.legend()
    fig.tight_layout()
    fname = f'{name}_{metric}.png'.replace(' ', '_').replace('/', '_')
    fig.savefig(HISTOGRAMS_DIR / fname, dpi=100)
    plt.close(fig)


# ===================================================================
# Multi-timeframe comparison
# ===================================================================

def run_multi_timeframe(n_perms: int = 10_000) -> pd.DataFrame:
    """
    Run FVGC model at 30s, 1m, 5m and enrich each with VP.
    Compare VP-proximity WR/PF across timeframes.
    """
    from fvgc.data import load_candles
    from fvgc.model import generate_signals
    from fvgc.engine import simulate_trades

    vp = pd.read_csv(ROOT / 'data' / 'levels' / 'daily_volume_profile.csv')
    vp['date'] = pd.to_datetime(vp['date']).dt.date
    vp = vp.sort_values('date').reset_index(drop=True)
    vp_dates = vp['date'].values
    vp_by_date = vp.set_index('date')

    timeframes = {
        '30s': ROOT / 'data' / 'consolidated' / 'nq-front-month.ohlcv-30s.csv',
        '1m': ROOT / 'data' / 'consolidated' / 'nq-front-month.ohlcv-1m.csv',
        '5m': ROOT / 'data' / 'consolidated' / 'nq-front-month.ohlcv-5m.csv',
    }

    rows = []
    for tf_label, data_path in timeframes.items():
        if not data_path.exists():
            print(f'  Skipping {tf_label}: {data_path.name} not found')
            continue

        print(f'\n  === Timeframe: {tf_label} ===')
        candles = load_candles(data_path)
        signals, _ = generate_signals(candles)
        results = simulate_trades(signals, candles)

        # Convert to DataFrame and enrich with VP
        rdf = pd.DataFrame(results)
        if rdf.empty:
            continue

        rdf['timestamp'] = pd.to_datetime(rdf['timestamp'])
        rdf['date'] = rdf['timestamp'].dt.date
        tradeable = rdf[rdf['outcome'].isin(['win', 'loss'])].copy()

        # Join prior-day VP
        def get_prior_vp(trade_date):
            prior = [d for d in vp_dates if d < trade_date]
            return prior[-1] if prior else None

        vp_data = []
        for _, t in tradeable.iterrows():
            pvd = get_prior_vp(t['date'])
            if pvd is not None and pvd in vp_by_date.index:
                r = vp_by_date.loc[pvd]
                vp_data.append({'poc': r['poc'], 'vah': r['vah'], 'val': r['val']})
            else:
                vp_data.append({'poc': np.nan, 'vah': np.nan, 'val': np.nan})

        vpdf = pd.DataFrame(vp_data, index=tradeable.index)
        tradeable = pd.concat([tradeable, vpdf], axis=1)
        tradeable = tradeable[tradeable['poc'].notna()].copy()

        entry = tradeable['entry_price']
        dist_poc = (entry - tradeable['poc']).abs()
        dist_vah = (entry - tradeable['vah']).abs()
        dist_val = (entry - tradeable['val']).abs()
        tradeable['near_any_vp_15pt'] = (dist_poc <= 15) | (dist_vah <= 15) | (dist_val <= 15)

        # Stats
        all_stats = compute_segment_stats(tradeable, f'{tf_label} ALL')
        near_stats = compute_segment_stats(
            tradeable[tradeable['near_any_vp_15pt']], f'{tf_label} Near VP (15pt)')
        far_stats = compute_segment_stats(
            tradeable[~tradeable['near_any_vp_15pt']], f'{tf_label} NOT near VP (15pt)')

        for s in [all_stats, near_stats, far_stats]:
            s['timeframe'] = tf_label
            rows.append(s)

        print(f'    Trades: {all_stats["n"]}, WR: {all_stats["wr"]}%, PF: {all_stats["pf"]}')
        print(f'    Near VP: n={near_stats["n"]}, WR: {near_stats["wr"]}%, PF: {near_stats["pf"]}')
        print(f'    Far VP:  n={far_stats["n"]}, WR: {far_stats["wr"]}%, PF: {far_stats["pf"]}')

    return pd.DataFrame(rows)


# ===================================================================
# Additive confluence
# ===================================================================

def run_additive_confluence(df: pd.DataFrame) -> pd.DataFrame:
    """
    Test VP factors combined with existing context factors.
    Tests 2-way combinations to find additive confluence.
    """
    td = pd.read_csv(TRADING_DAYS_PATH)
    td['date'] = pd.to_datetime(td['date']).dt.date
    merged = df.copy()
    if 'day_of_week' not in merged.columns:
        merged = merged.merge(td[['date', 'day_of_week', 'has_red_folder_news',
                                   'vixy_regime', 'candle_930_direction',
                                   'overnight_direction', 'gap_from_prior_close']],
                               on='date', how='left', suffixes=('', '_td'))

    # Define VP factor masks
    vp_factors = {
        'near_any_vp_15pt': merged['near_any_vp_15pt'] == True,
        'near_poc_15pt': merged['near_poc_15pt'] == True,
        'inside_va': merged['entry_in_value_area'] == True,
        'outside_va': merged['entry_in_value_area'] == False,
        'dir_vp_aligned': merged['directional_vp_aligned'] == True,
    }

    # Define context factor masks
    context_factors = {}
    if 'has_red_folder_news' in merged.columns:
        context_factors['no_red_folder'] = merged['has_red_folder_news'] == False
        context_factors['has_red_folder'] = merged['has_red_folder_news'] == True
    if 'vixy_regime' in merged.columns:
        context_factors['vixy_low'] = merged['vixy_regime'] == 'low'
        context_factors['vixy_elevated'] = merged['vixy_regime'] == 'elevated'
    if 'candle_930_direction' in merged.columns:
        context_factors['930_bullish'] = merged['candle_930_direction'] == 'bullish'
        context_factors['930_bearish'] = merged['candle_930_direction'] == 'bearish'
    if 'overnight_direction' in merged.columns:
        context_factors['overnight_up'] = merged['overnight_direction'] == 'up'
        context_factors['overnight_down'] = merged['overnight_direction'] == 'down'
    if 'day_of_week' in merged.columns:
        for dow, name in enumerate(['Mon', 'Tue', 'Wed', 'Thu', 'Fri']):
            context_factors[name] = merged['day_of_week'] == dow

    # Also add entry variant
    for v in ['no_fvg', 'ifvg', 'bos', 'protected_swing']:
        if 'variant' in merged.columns:
            context_factors[f'variant_{v}'] = merged['variant'] == v

    MIN_N = 20
    rows = []

    for vp_name, vp_mask in vp_factors.items():
        # VP factor alone
        vp_sub = merged[vp_mask]
        if len(vp_sub) >= MIN_N:
            rows.append({
                'combo': vp_name,
                **compute_segment_stats(vp_sub, vp_name),
            })

        # 2-way combos
        for ctx_name, ctx_mask in context_factors.items():
            combo_mask = vp_mask & ctx_mask
            combo_sub = merged[combo_mask]
            if len(combo_sub) >= MIN_N:
                combo_label = f'{vp_name} + {ctx_name}'
                rows.append({
                    'combo': combo_label,
                    **compute_segment_stats(combo_sub, combo_label),
                })

    result = pd.DataFrame(rows)
    if not result.empty:
        result = result.sort_values('pf', ascending=False)
    return result


# ===================================================================
# Main
# ===================================================================

def print_table(title: str, df: pd.DataFrame):
    """Print a summary table to stdout."""
    print(f'\n{"=" * 70}')
    print(f'  {title}')
    print(f'{"=" * 70}')
    if df.empty:
        print('  (no data)')
        return
    print(df.to_string(index=False))


def main():
    parser = argparse.ArgumentParser(description='Volume Profile Confluence Study')
    parser.add_argument('--perms', type=int, default=10_000, help='Permutation count')
    parser.add_argument('--no-histograms', action='store_true')
    parser.add_argument('--no-multitf', action='store_true')
    parser.add_argument('--no-confluence', action='store_true')
    args = parser.parse_args()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    print('=' * 70)
    print('  VOLUME PROFILE CONFLUENCE STUDY')
    print('=' * 70)

    df = load_data()

    # 1. Segmentation
    seg = run_segmentation(df)
    print_table('SEGMENTATION ANALYSIS', seg)
    seg.to_csv(RESULTS_DIR / 'vp_segmentation_summary.csv', index=False)

    # 2. Directional alignment
    align = run_directional_alignment(df)
    print_table('DIRECTIONAL ALIGNMENT', align)
    align.to_csv(RESULTS_DIR / 'vp_directional_alignment.csv', index=False)

    # 3. Multi-R analysis
    multi_r = run_multi_r_analysis(df)
    print_table('MULTI-R HIT RATES BY VP COHORT', multi_r)
    multi_r.to_csv(RESULTS_DIR / 'vp_multi_r_analysis.csv', index=False)

    # 4. Permutation tests
    perm_results = run_vp_permutation_tests(
        df, n_perms=args.perms, draw_histograms=not args.no_histograms)
    perm_results.to_csv(RESULTS_DIR / 'vp_permutation_results.csv', index=False)

    sig = perm_results[perm_results['significant_05'] == True]
    if not sig.empty:
        print_table('SIGNIFICANT VP FILTERS (p < 0.05)', sig)
    else:
        print('\n  No VP filters reached p < 0.05 significance.')

    # 5. Multi-timeframe
    if not args.no_multitf:
        print('\n\n--- Multi-timeframe comparison ---')
        mtf = run_multi_timeframe(n_perms=args.perms)
        if not mtf.empty:
            print_table('MULTI-TIMEFRAME VP COMPARISON', mtf)
            mtf.to_csv(RESULTS_DIR / 'vp_by_timeframe.csv', index=False)

    # 6. Additive confluence
    if not args.no_confluence:
        print('\n\n--- Additive confluence testing ---')
        conf = run_additive_confluence(df)
        if not conf.empty:
            print_table('TOP ADDITIVE CONFLUENCE COMBOS (by PF)', conf.head(30))
            conf.to_csv(RESULTS_DIR / 'vp_additive_confluence.csv', index=False)

    print(f'\n\nAll results written to {RESULTS_DIR}/')
    print('Done.')


if __name__ == '__main__':
    main()
