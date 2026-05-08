#!/usr/bin/env python3
"""
Study: Day-After-Trend-Day Pattern (Yesterday's Session Character → Today's Behavior).

Joins the new `prior_day_type` column from `data/trading_days/trading_days.csv`
to baseline FVGC trades and asks whether the prior RTH session's character
(trend / range / reversal) predicts today's W1/W2/W3 trade outcomes.

Pipeline:
  1. Load and join baseline trades to trading_days.csv (uses analysis.permutation_test.load_data).
  2. Emit a per-trade CSV with prior_day_type attached.
  3. Aggregate WR/PF by prior_day_type, by prior_day_type x today_direction,
     and by prior_day_type x today_direction x macro_window.
  4. Run a vectorised combo permutation against the existing factor set,
     extended with prior_day_* masks. 10k perms, BH FDR q=0.10, min n=30.
  5. Compute confluence-stack lift on existing playbook plays
     (W1 Short, M2+M3 Long, MACD-style cohorts) when prior_day_type is added.
  6. Probe known failure modes: Monday rows, large gaps, red-folder prior days.

Run from repo root:
  python studies/prior_day_type/run.py                # full 10k-permutation run
  python studies/prior_day_type/run.py --perms 1000   # quick smoke test
"""

from __future__ import annotations

import sys
import argparse
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from analysis.permutation_test import load_data
from analysis.combo_permutation_test import (
    EXCLUSION_GROUPS,
    apply_corrections,
    build_factor_masks,
    is_valid_combo,
    run_combo_permutation,
)

STUDY_DIR = Path(__file__).resolve().parent
RESULTS_DIR = STUDY_DIR / 'results'

PRIOR_TYPES = ['trend_up', 'trend_down', 'range', 'reversal_up', 'reversal_down', 'other']
MACRO_WINDOWS = [1, 2, 3]
DIRECTIONS = ['long', 'short']

WR_THRESHOLD = 65.0
PF_THRESHOLD = 2.0
FDR_Q = 0.10
MIN_N = 30


# ===================================================================
# Cohort statistics
# ===================================================================

def cohort_stats(df: pd.DataFrame, baseline_wr: float, baseline_pf: float) -> dict:
    """Win rate, profit factor, and lift vs baseline for an arbitrary subset."""
    n = len(df)
    out = {
        'n': n,
        'wins': 0,
        'losses': 0,
        'win_rate': np.nan,
        'profit_factor': np.nan,
        'avg_pnl': np.nan,
        'wr_lift': np.nan,
        'pf_lift': np.nan,
    }
    if n == 0:
        return out
    wins = int((df['outcome'] == 'win').sum())
    losses = int((df['outcome'] == 'loss').sum())
    out['wins'] = wins
    out['losses'] = losses
    out['win_rate'] = (wins / (wins + losses) * 100.0) if (wins + losses) > 0 else np.nan
    pnl = pd.to_numeric(df['pnl'], errors='coerce')
    gp = pnl[pnl > 0].sum()
    gl = abs(pnl[pnl < 0].sum())
    out['profit_factor'] = gp / gl if gl > 0 else (np.inf if gp > 0 else np.nan)
    out['avg_pnl'] = float(pnl.mean()) if n else np.nan
    if not np.isnan(baseline_wr) and not np.isnan(out['win_rate']):
        out['wr_lift'] = out['win_rate'] - baseline_wr
    if np.isfinite(out['profit_factor']) and np.isfinite(baseline_pf):
        out['pf_lift'] = out['profit_factor'] - baseline_pf
    return out


def write_summary_by_prior_day_type(df: pd.DataFrame, baseline_wr: float,
                                    baseline_pf: float) -> pd.DataFrame:
    rows = []
    for pt in PRIOR_TYPES:
        sub = df[df['prior_day_type'] == pt]
        rows.append({'prior_day_type': pt, **cohort_stats(sub, baseline_wr, baseline_pf)})
    out = pd.DataFrame(rows)
    out.to_csv(RESULTS_DIR / 'summary_by_prior_day_type.csv', index=False)
    return out


def write_headline_cells(df: pd.DataFrame, baseline_wr: float,
                         baseline_pf: float) -> pd.DataFrame:
    rows = []
    for pt in PRIOR_TYPES:
        for d in DIRECTIONS:
            for w in MACRO_WINDOWS:
                sub = df[
                    (df['prior_day_type'] == pt)
                    & (df['direction'] == d)
                    & (df['macro_window'] == w)
                ]
                rows.append({
                    'prior_day_type': pt,
                    'direction': d,
                    'macro_window': w,
                    **cohort_stats(sub, baseline_wr, baseline_pf),
                })
    out = pd.DataFrame(rows)
    out.to_csv(RESULTS_DIR / 'summary_by_prior_type_x_today_direction_x_macro.csv',
               index=False)
    return out


def write_failure_mode_summary(df: pd.DataFrame, baseline_wr: float,
                               baseline_pf: float) -> pd.DataFrame:
    """Probe Monday / large gap / red-folder-prior-day robustness checks."""
    rows = []

    is_monday = df['day_of_week'] == 0
    abs_gap = df['gap_from_prior_close'].abs()
    gap_q80 = abs_gap.dropna().quantile(0.8) if abs_gap.notna().any() else np.inf
    big_gap = abs_gap >= gap_q80

    prior_red_folder = df.groupby('date')['has_red_folder_news'].first().shift(1)
    prior_red_map = dict(zip(prior_red_folder.index, prior_red_folder.values))
    df_local = df.copy()
    mapped_red = df_local['date'].map(prior_red_map)
    df_local['prior_red_folder'] = mapped_red.where(mapped_red.notna(), False).astype(bool)

    for pt in PRIOR_TYPES:
        base = df_local[df_local['prior_day_type'] == pt]
        rows.append({
            'prior_day_type': pt, 'cohort': 'all',
            **cohort_stats(base, baseline_wr, baseline_pf),
        })
        rows.append({
            'prior_day_type': pt, 'cohort': 'monday',
            **cohort_stats(base[is_monday.reindex(base.index, fill_value=False)],
                           baseline_wr, baseline_pf),
        })
        rows.append({
            'prior_day_type': pt, 'cohort': 'non_monday',
            **cohort_stats(base[~is_monday.reindex(base.index, fill_value=False)],
                           baseline_wr, baseline_pf),
        })
        rows.append({
            'prior_day_type': pt, 'cohort': 'big_gap_top20pct',
            **cohort_stats(base[big_gap.reindex(base.index, fill_value=False)],
                           baseline_wr, baseline_pf),
        })
        rows.append({
            'prior_day_type': pt, 'cohort': 'small_gap_bottom80pct',
            **cohort_stats(base[~big_gap.reindex(base.index, fill_value=False)],
                           baseline_wr, baseline_pf),
        })
        rows.append({
            'prior_day_type': pt, 'cohort': 'prior_day_red_folder',
            **cohort_stats(base[base['prior_red_folder']], baseline_wr, baseline_pf),
        })
        rows.append({
            'prior_day_type': pt, 'cohort': 'prior_day_no_red_folder',
            **cohort_stats(base[~base['prior_red_folder']], baseline_wr, baseline_pf),
        })

    out = pd.DataFrame(rows)
    out.to_csv(RESULTS_DIR / 'summary_prior_type_gap_monday_news.csv', index=False)
    return out


# ===================================================================
# Existing playbook stack lift
# ===================================================================

def playbook_cohort_masks(df: pd.DataFrame) -> dict[str, np.ndarray]:
    """Best-effort, well-documented approximations of three existing playbook plays."""
    masks: dict[str, np.ndarray] = {}

    masks['W1_Short'] = (
        (df['macro_window'] == 1)
        & (df['direction'] == 'short')
    ).values

    masks['M2_M3_Long'] = (
        df['macro_window'].isin([2, 3])
        & (df['direction'] == 'long')
    ).values

    masks['IFVG_long'] = (
        (df['variant'] == 'ifvg')
        & (df['direction'] == 'long')
    ).values

    return masks


def write_playbook_stack_lift(df: pd.DataFrame, baseline_wr: float,
                              baseline_pf: float) -> pd.DataFrame:
    masks = playbook_cohort_masks(df)
    rows = []
    for play_name, mask in masks.items():
        play_df = df[mask]
        play_stats = cohort_stats(play_df, baseline_wr, baseline_pf)
        rows.append({
            'play': play_name,
            'prior_day_type': 'all',
            **play_stats,
            'wr_delta_vs_play': 0.0,
            'pf_delta_vs_play': 0.0,
        })
        play_wr = play_stats['win_rate']
        play_pf = play_stats['profit_factor']
        for pt in PRIOR_TYPES:
            stacked = play_df[play_df['prior_day_type'] == pt]
            stats = cohort_stats(stacked, baseline_wr, baseline_pf)
            wr_delta = (stats['win_rate'] - play_wr
                        if not np.isnan(stats['win_rate']) and not np.isnan(play_wr)
                        else np.nan)
            if np.isfinite(stats['profit_factor']) and np.isfinite(play_pf):
                pf_delta = stats['profit_factor'] - play_pf
            else:
                pf_delta = np.nan
            rows.append({
                'play': play_name,
                'prior_day_type': pt,
                **stats,
                'wr_delta_vs_play': wr_delta,
                'pf_delta_vs_play': pf_delta,
            })
    out = pd.DataFrame(rows)
    out.to_csv(RESULTS_DIR / 'playbook_stack_lift.csv', index=False)
    return out


# ===================================================================
# Combo permutation (extended factor set)
# ===================================================================

def generate_combos(factor_names: list[str], max_factors: int) -> list[tuple[str, ...]]:
    combos = []
    for k in range(2, max_factors + 1):
        for combo in combinations(factor_names, k):
            if is_valid_combo(combo):
                combos.append(combo)
    return combos


def run_combo_study(df: pd.DataFrame, perms: int, max_factors: int,
                    min_n: int, seed: int) -> pd.DataFrame:
    print("\nBuilding factor masks...")
    masks = build_factor_masks(df)
    factor_names = sorted(masks.keys())
    print(f"  {len(factor_names)} factors defined "
          f"({sum(1 for f in factor_names if f.startswith('prior_'))} prior_day_* masks)")

    print("Generating combos...")
    combos = generate_combos(factor_names, max_factors)
    print(f"  {len(combos)} valid combos (max {max_factors}-way)")

    win_flags = (df['outcome'] == 'win').values.astype(np.float64)
    pnl_vals = pd.to_numeric(df['pnl'], errors='coerce').values.astype(np.float64)
    baseline_wr = win_flags.mean() * 100
    gp_all = pnl_vals[pnl_vals > 0].sum()
    gl_all = abs(pnl_vals[pnl_vals < 0].sum())
    baseline_pf = gp_all / gl_all if gl_all > 0 else np.nan
    print(f"  Baseline: {len(df)} trades, WR={baseline_wr:.1f}%, PF={baseline_pf:.2f}")

    valid_combos = []
    for combo in combos:
        combined = masks[combo[0]].copy()
        for f in combo[1:]:
            combined &= masks[f]
        n = combined.sum()
        if n >= min_n:
            valid_combos.append((combo, combined))
    print(f"  {len(valid_combos)} combos with n >= {min_n}")
    print(f"  Running {perms:,} permutations per combo...")

    rng = np.random.default_rng(seed)
    results = []
    for i, (combo, combo_mask) in enumerate(valid_combos, 1):
        combo_name = ' + '.join(combo)
        result = run_combo_permutation(combo_mask, win_flags, pnl_vals, perms, rng)
        if i <= 10 or i % 250 == 0 or result['p_value_wr'] < 0.05:
            sig = ' *' if result['p_value_wr'] < 0.05 else ''
            print(f"    [{i}/{len(valid_combos)}] {combo_name}: "
                  f"n={result['n']}, WR={result['win_rate']:.1f}%, "
                  f"PF={result['profit_factor']:.2f}, "
                  f"p_wr={result['p_value_wr']:.4f}{sig}")
        results.append({
            'combo_name': combo_name,
            'factors': combo_name,
            'n_factors': len(combo),
            'n': result['n'],
            'win_rate': result['win_rate'],
            'avg_pnl': result['avg_pnl'],
            'profit_factor': result['profit_factor'],
            'p_value_wr': result['p_value_wr'],
            'p_value_pf': result['p_value_pf'],
            'mean_perm_wr': result['mean_perm_wr'],
            'std_perm_wr': result['std_perm_wr'],
            'mean_perm_pf': result['mean_perm_pf'],
            'baseline_wr': baseline_wr,
            'baseline_pf': baseline_pf,
        })

    summary = pd.DataFrame(results)
    summary = apply_corrections(summary, 'p_value_wr')
    summary = apply_corrections(summary, 'p_value_pf')
    summary['has_prior_day_factor'] = summary['factors'].str.contains('prior_')
    summary['survives_fdr'] = summary['p_value_wr_bh'] < FDR_Q
    summary['cleared_thresholds'] = (
        (summary['n'] >= MIN_N)
        & (summary['win_rate'] >= WR_THRESHOLD)
        & (summary['profit_factor'] >= PF_THRESHOLD)
        & (summary['survives_fdr'])
    )
    summary = summary.sort_values('win_rate', ascending=False).reset_index(drop=True)
    summary.to_csv(RESULTS_DIR / 'combo_summary.csv', index=False)
    return summary


def write_combo_text_report(summary: pd.DataFrame) -> None:
    lines = []
    lines.append('=' * 70)
    lines.append('PRIOR_DAY_TYPE STUDY — COMBO PERMUTATION RESULTS')
    lines.append('=' * 70)
    lines.append('')
    lines.append(f"Total combos tested:        {len(summary)}")
    lines.append(f"  ... with prior_day_* :     {int(summary['has_prior_day_factor'].sum())}")
    lines.append(f"Significant by raw WR:       {int((summary['p_value_wr'] < 0.05).sum())}")
    lines.append(f"Survive BH FDR (q={FDR_Q}):  {int(summary['survives_fdr'].sum())}")
    lines.append(f"Clear WR>={WR_THRESHOLD} & PF>={PF_THRESHOLD} (n>={MIN_N}, FDR): "
                 f"{int(summary['cleared_thresholds'].sum())}")
    if not summary.empty:
        lines.append(f"Baseline WR={summary['baseline_wr'].iloc[0]:.1f}%, "
                     f"PF={summary['baseline_pf'].iloc[0]:.2f}")
    lines.append('')

    def format_row(row, rank):
        flags = []
        if row['survives_fdr']:
            flags.append('FDR')
        if row['cleared_thresholds']:
            flags.append('PASS')
        flag_str = (' [' + ','.join(flags) + ']') if flags else ''
        return (f"  {rank:3d}. {row['factors']:<60s} "
                f"n={row['n']:4d}  WR={row['win_rate']:5.1f}%  "
                f"PF={row['profit_factor']:5.2f}  "
                f"p_wr={row['p_value_wr']:.4f}{flag_str}")

    def section(title: str, frame: pd.DataFrame, sort_col: str,
                ascending: bool, head: int = 20):
        lines.append('-' * 70)
        lines.append(title)
        lines.append('-' * 70)
        if frame.empty:
            lines.append('  (none)')
            lines.append('')
            return
        ranked = frame.sort_values(sort_col, ascending=ascending).head(head)
        for rank, (_, row) in enumerate(ranked.iterrows(), 1):
            lines.append(format_row(row, rank))
        lines.append('')

    section('TOP 20 BY WIN RATE (n>=30, p_wr<0.05, includes prior_day_*)',
            summary[(summary['n'] >= MIN_N) & (summary['p_value_wr'] < 0.05)
                    & summary['has_prior_day_factor']],
            'win_rate', ascending=False)

    section('TOP 20 BY PROFIT FACTOR (n>=30, p_pf<0.05, includes prior_day_*)',
            summary[(summary['n'] >= MIN_N) & (summary['p_value_pf'] < 0.05)
                    & summary['has_prior_day_factor']
                    & np.isfinite(summary['profit_factor'])],
            'profit_factor', ascending=False)

    section('CLEARED THRESHOLDS (n>=30, WR>=65, PF>=2.0, BH FDR)',
            summary[summary['cleared_thresholds']], 'win_rate', ascending=False, head=50)

    section('TOP 20 OVERALL BY WIN RATE (any factors, p_wr<0.05)',
            summary[(summary['n'] >= MIN_N) & (summary['p_value_wr'] < 0.05)],
            'win_rate', ascending=False)

    section('AVOID LIST — BOTTOM 20 BY WIN RATE (n>=30, p_wr<0.05)',
            summary[(summary['n'] >= MIN_N) & (summary['p_value_wr'] < 0.05)],
            'win_rate', ascending=True)

    out_path = RESULTS_DIR / 'combo_top_results.txt'
    out_path.write_text('\n'.join(lines))


# ===================================================================
# Main
# ===================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Day-After-Trend-Day prior_day_type study runner.')
    parser.add_argument('--perms', type=int, default=10_000,
                        help='Permutations per combo (default 10,000)')
    parser.add_argument('--max-factors', type=int, default=3, choices=[2, 3],
                        help='Max combo size (2=pairs only, 3=pairs+triples)')
    parser.add_argument('--min-n', type=int, default=MIN_N, help='Min sample size')
    parser.add_argument('--seed', type=int, default=42, help='Random seed')
    parser.add_argument('--skip-combos', action='store_true',
                        help='Skip the combo permutation grid (headline cells only)')
    args = parser.parse_args()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    print('=' * 60)
    print('Prior-day-type study — load + join')
    print('=' * 60)
    df = load_data()

    if 'prior_day_type' not in df.columns:
        raise SystemExit(
            "trading_days.csv is missing the 'prior_day_type' column. "
            "Re-run data/trading_days/build_trading_days.py first.")

    df = df.copy()
    df['prior_day_type'] = df['prior_day_type'].fillna('other')

    win_flags = (df['outcome'] == 'win').values.astype(np.float64)
    pnl_vals = pd.to_numeric(df['pnl'], errors='coerce').values.astype(np.float64)
    baseline_wr = win_flags.mean() * 100
    gp_all = pnl_vals[pnl_vals > 0].sum()
    gl_all = abs(pnl_vals[pnl_vals < 0].sum())
    baseline_pf = gp_all / gl_all if gl_all > 0 else np.nan
    print(f"\nJoined trades: {len(df):,}  baseline WR={baseline_wr:.2f}%  "
          f"PF={baseline_pf:.2f}")
    print('\nprior_day_type distribution among trades:')
    print(df['prior_day_type'].value_counts(dropna=False).to_string())

    print('\nWriting per-trade table with prior_day_type...')
    keep_cols = [
        'timestamp', 'date', 'direction', 'variant', 'macro_window', 'outcome',
        'pnl', 'sl_dist', 'entry_price', 'exit_price', 'mfe_r', 'mae_r',
        'prior_day_type', 'prior_day_range_atr_ratio',
        'prior_day_directional_changes', 'prior_day_close_vs_open_pct',
        'prior_day_close_position', 'gap_from_prior_close',
        'gap_from_prior_close_pct', 'overnight_direction', 'vixy_regime',
        'has_red_folder_news', 'is_fomc_week', 'day_of_week_name',
    ]
    keep_cols = [c for c in keep_cols if c in df.columns]
    df[keep_cols].to_csv(RESULTS_DIR / 'trades_by_prior_day_type.csv', index=False)

    print('Writing aggregate WR/PF by prior_day_type...')
    write_summary_by_prior_day_type(df, baseline_wr, baseline_pf)

    print('Writing headline cells (prior_day_type x direction x macro_window)...')
    write_headline_cells(df, baseline_wr, baseline_pf)

    print('Writing failure-mode probes (Monday / gap / news)...')
    write_failure_mode_summary(df, baseline_wr, baseline_pf)

    print('Writing playbook stack lift (W1 Short / M2+M3 Long / IFVG Long)...')
    write_playbook_stack_lift(df, baseline_wr, baseline_pf)

    if args.skip_combos:
        print('\n--skip-combos set; skipping permutation grid.')
        return

    print('\n' + '=' * 60)
    print('Running combo permutation grid')
    print('=' * 60)
    summary = run_combo_study(df, perms=args.perms, max_factors=args.max_factors,
                              min_n=args.min_n, seed=args.seed)
    write_combo_text_report(summary)

    print('\nDone. Results in', RESULTS_DIR)


if __name__ == '__main__':
    main()
