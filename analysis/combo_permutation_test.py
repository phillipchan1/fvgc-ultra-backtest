#!/usr/bin/env python3
"""
Multi-factor combo permutation testing for FVGC trade filters.

Tests all 2-way and 3-way combinations of binary factor conditions,
runs permutation significance tests with multiple-comparison corrections
(Bonferroni and Benjamini-Hochberg FDR), and outputs ranked results.

Usage:
    python analysis/combo_permutation_test.py                        # full run
    python analysis/combo_permutation_test.py --max-factors 2        # 2-way only
    python analysis/combo_permutation_test.py --perms 1000           # quick
    python analysis/combo_permutation_test.py --min-n 50             # stricter sample size
    python analysis/combo_permutation_test.py --metric profit_factor # rank by PF
"""

import sys
import argparse
from pathlib import Path
from itertools import combinations

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns

from analysis.permutation_test import load_data

RESULTS_DIR = ROOT / 'analysis' / 'results'
COMBO_HIST_DIR = RESULTS_DIR / 'combo_histograms'


# ===================================================================
# Factor definitions
# ===================================================================

def build_factor_masks(df: pd.DataFrame) -> dict[str, np.ndarray]:
    """Build boolean mask arrays for each factor condition."""
    masks = {}

    # Percentile thresholds
    or45_q20 = df['or_45min_range'].quantile(0.2)
    or45_q80 = df['or_45min_range'].quantile(0.8)
    or5_q20 = df['or_5min_range'].quantile(0.2)
    or5_q80 = df['or_5min_range'].quantile(0.8)
    on_q20 = df['overnight_range'].quantile(0.2)
    on_q80 = df['overnight_range'].quantile(0.8)
    c930_q20 = df['candle_930_range'].quantile(0.2)
    c930_q80 = df['candle_930_range'].quantile(0.8)

    # Directional context
    masks['prior_day_down'] = (df['prior_day_close_position'] < 0.25).values
    masks['prior_day_up'] = (df['prior_day_close_position'] > 0.75).values
    masks['bearish_930'] = (df['candle_930_direction'] == 'bearish').values
    masks['bullish_930'] = (df['candle_930_direction'] == 'bullish').values
    masks['gap_up'] = (df['gap_from_prior_close'] > 0).values
    masks['gap_down'] = (df['gap_from_prior_close'] < 0).values
    masks['overnight_up'] = (df['overnight_direction'] == 'up').values
    masks['overnight_down'] = (df['overnight_direction'] == 'down').values

    # Range / volatility
    masks['wide_45min_or'] = (df['or_45min_range'] >= or45_q80).values
    masks['tight_45min_or'] = (df['or_45min_range'] <= or45_q20).values
    masks['wide_5min_or'] = (df['or_5min_range'] >= or5_q80).values
    masks['tight_5min_or'] = (df['or_5min_range'] <= or5_q20).values
    masks['wide_overnight'] = (df['overnight_range'] >= on_q80).values
    masks['tight_overnight'] = (df['overnight_range'] <= on_q20).values

    # VIXY regime
    masks['low_vixy'] = (df['vixy_regime'] == 'low').values
    masks['normal_vixy'] = (df['vixy_regime'] == 'normal').values
    masks['elevated_vixy'] = (df['vixy_regime'].isin(['elevated', 'high'])).values

    # Calendar / news
    masks['no_red_folder'] = (df['has_red_folder_news'] == False).values
    masks['has_red_folder'] = (df['has_red_folder_news'] == True).values
    masks['no_pre_rth_news'] = (df['has_pre_rth_news'] == False).values
    masks['not_fomc_week'] = (df['is_fomc_week'] == False).values
    masks['is_fomc_week'] = (df['is_fomc_week'] == True).values

    # Trade direction
    masks['long_only'] = (df['direction'] == 'long').values
    masks['short_only'] = (df['direction'] == 'short').values

    # Macro window
    masks['macro_w1'] = (df['macro_window'] == 1).values
    masks['macro_w2'] = (df['macro_window'] == 2).values
    masks['macro_w3'] = (df['macro_window'] == 3).values

    # 930 candle size
    masks['large_930_candle'] = (df['candle_930_range'] >= c930_q80).values
    masks['small_930_candle'] = (df['candle_930_range'] <= c930_q20).values

    # Prior day character (added by Day-After-Trend-Day study)
    if 'prior_day_type' in df.columns:
        masks['prior_trend_up'] = (df['prior_day_type'] == 'trend_up').values
        masks['prior_trend_down'] = (df['prior_day_type'] == 'trend_down').values
        masks['prior_range'] = (df['prior_day_type'] == 'range').values
        masks['prior_reversal_up'] = (df['prior_day_type'] == 'reversal_up').values
        masks['prior_reversal_down'] = (df['prior_day_type'] == 'reversal_down').values

    return masks


EXCLUSION_GROUPS = [
    {'prior_day_up', 'prior_day_down'},
    {'bearish_930', 'bullish_930'},
    {'gap_up', 'gap_down'},
    {'overnight_up', 'overnight_down'},
    {'long_only', 'short_only'},
    {'low_vixy', 'normal_vixy', 'elevated_vixy'},
    {'wide_45min_or', 'tight_45min_or'},
    {'wide_5min_or', 'tight_5min_or'},
    {'wide_overnight', 'tight_overnight'},
    {'large_930_candle', 'small_930_candle'},
    {'no_red_folder', 'has_red_folder'},
    {'not_fomc_week', 'is_fomc_week'},
    {'macro_w1', 'macro_w2', 'macro_w3'},
    {'prior_trend_up', 'prior_trend_down', 'prior_range',
     'prior_reversal_up', 'prior_reversal_down'},
]


def is_valid_combo(factors: tuple[str, ...]) -> bool:
    """Check that no two factors in the combo belong to the same exclusion group."""
    factor_set = set(factors)
    for group in EXCLUSION_GROUPS:
        if len(factor_set & group) >= 2:
            return False
    return True


def generate_combos(factor_names: list[str], max_factors: int) -> list[tuple[str, ...]]:
    """Generate all valid 2-way and 3-way combos, filtering exclusions."""
    combos = []
    for k in range(2, max_factors + 1):
        for combo in combinations(factor_names, k):
            if is_valid_combo(combo):
                combos.append(combo)
    return combos


# ===================================================================
# Vectorized permutation engine
# ===================================================================

def run_combo_permutation(
    combo_mask: np.ndarray,
    win_flags: np.ndarray,
    pnl_vals: np.ndarray,
    n_perms: int,
    rng: np.random.Generator,
) -> dict:
    """Run permutation test for a single combo mask using vectorized numpy."""
    n_total = len(win_flags)
    n_subset = combo_mask.sum()

    # Actual metrics
    sub_wins = win_flags[combo_mask]
    sub_pnl = pnl_vals[combo_mask]

    actual_wr = sub_wins.mean() * 100
    actual_avg_pnl = np.nanmean(sub_pnl)

    gp = sub_pnl[sub_pnl > 0].sum()
    gl = abs(sub_pnl[sub_pnl < 0].sum())
    if gl > 0:
        actual_pf = gp / gl
    elif gp > 0:
        actual_pf = np.inf
    else:
        actual_pf = np.nan

    # Permutation loop
    perm_wr = np.empty(n_perms)
    perm_pf = np.empty(n_perms)

    for i in range(n_perms):
        perm = rng.permutation(n_total)
        s_wins = win_flags[perm][combo_mask]
        s_pnl = pnl_vals[perm][combo_mask]

        perm_wr[i] = s_wins.mean() * 100

        s_gp = s_pnl[s_pnl > 0].sum()
        s_gl = abs(s_pnl[s_pnl < 0].sum())
        if s_gl > 0:
            perm_pf[i] = s_gp / s_gl
        elif s_gp > 0:
            perm_pf[i] = np.inf
        else:
            perm_pf[i] = np.nan

    # p-values (two-sided)
    perm_wr_mean = np.nanmean(perm_wr)
    if actual_wr >= perm_wr_mean:
        p_wr = np.nanmean(perm_wr >= actual_wr)
    else:
        p_wr = np.nanmean(perm_wr <= actual_wr)

    finite_pf = perm_pf[np.isfinite(perm_pf)]
    if len(finite_pf) > 0 and np.isfinite(actual_pf):
        perm_pf_mean = np.nanmean(finite_pf)
        if actual_pf >= perm_pf_mean:
            p_pf = np.nanmean(finite_pf >= actual_pf)
        else:
            p_pf = np.nanmean(finite_pf <= actual_pf)
    else:
        perm_pf_mean = np.nan
        p_pf = np.nan

    return {
        'n': int(n_subset),
        'win_rate': actual_wr,
        'avg_pnl': actual_avg_pnl,
        'profit_factor': actual_pf,
        'p_value_wr': p_wr,
        'p_value_pf': p_pf,
        'mean_perm_wr': perm_wr_mean,
        'std_perm_wr': np.nanstd(perm_wr),
        'mean_perm_pf': perm_pf_mean,
        'perm_wr_dist': perm_wr,
        'perm_pf_dist': perm_pf,
    }


# ===================================================================
# Multiple comparison corrections
# ===================================================================

def apply_corrections(df: pd.DataFrame, p_col: str) -> pd.DataFrame:
    """Add Bonferroni and Benjamini-Hochberg corrected p-values."""
    valid = df[p_col].notna()
    n_tests = valid.sum()

    # Bonferroni
    bonf_col = f'{p_col}_bonferroni'
    df[bonf_col] = np.nan
    df.loc[valid, bonf_col] = np.minimum(df.loc[valid, p_col] * n_tests, 1.0)

    # Benjamini-Hochberg
    bh_col = f'{p_col}_bh'
    df[bh_col] = np.nan

    if n_tests > 0:
        valid_idx = df.index[valid]
        p_vals = df.loc[valid_idx, p_col].values
        sorted_order = np.argsort(p_vals)
        ranks = np.empty_like(sorted_order)
        ranks[sorted_order] = np.arange(1, len(sorted_order) + 1)

        bh_vals = p_vals * n_tests / ranks
        # Enforce monotonicity (step-up)
        reverse_sorted = np.argsort(-ranks)
        bh_sorted = bh_vals[reverse_sorted]
        for j in range(1, len(bh_sorted)):
            bh_sorted[j] = min(bh_sorted[j], bh_sorted[j - 1])
        bh_vals[reverse_sorted] = bh_sorted
        bh_vals = np.minimum(bh_vals, 1.0)

        df.loc[valid_idx, bh_col] = bh_vals

    return df


# ===================================================================
# Histogram generation
# ===================================================================

def plot_combo_histogram(perm_dist: np.ndarray, actual: float, mean_perm: float,
                         combo_name: str, metric: str, n: int, p_value: float,
                         output_dir: Path):
    dist = perm_dist[np.isfinite(perm_dist)]
    if len(dist) == 0 or not np.isfinite(actual):
        return

    fig, ax = plt.subplots(figsize=(8, 5))
    sns.histplot(dist, bins=50, ax=ax, color='steelblue', alpha=0.7, edgecolor='white')
    ax.axvline(actual, color='red', linewidth=2, linestyle='--',
               label=f'Actual: {actual:.2f}')
    if np.isfinite(mean_perm):
        ax.axvline(mean_perm, color='gray', linewidth=1, linestyle=':',
                   label=f'Mean perm: {mean_perm:.2f}')

    p_str = f'p={p_value:.4f}' if not np.isnan(p_value) else 'p=N/A'
    sig = ' **' if p_value < 0.01 else (' *' if p_value < 0.05 else '')

    title = combo_name
    if len(title) > 60:
        title = title[:57] + '...'
    ax.set_title(f'{title}\n{metric} | n={n} | {p_str}{sig}', fontsize=10)
    ax.set_xlabel(metric.replace('_', ' ').title())
    ax.set_ylabel('Count')
    ax.legend(fontsize=9)
    plt.tight_layout()

    safe_name = combo_name.replace(' ', '_').replace('+', 'AND')
    safe_name = ''.join(c for c in safe_name if c.isalnum() or c in '_-')[:120]
    fig.savefig(output_dir / f'{safe_name}.png', dpi=100)
    plt.close(fig)


# ===================================================================
# Report generation
# ===================================================================

def write_text_report(summary: pd.DataFrame, n_tests: int, _metric: str,
                      output_path: Path):
    lines = []
    lines.append("=" * 70)
    lines.append("MULTI-FACTOR COMBO PERMUTATION TEST RESULTS")
    lines.append("=" * 70)
    lines.append("")

    n_sig_wr = (summary['p_value_wr'] < 0.05).sum()
    n_sig_pf = summary['p_value_pf'].dropna().lt(0.05).sum()
    expected_chance = n_tests * 0.05
    n_fdr = (summary['p_value_wr_bh'] < 0.10).sum() if 'p_value_wr_bh' in summary.columns else 0

    lines.append(f"Tested {n_tests} combos at p < 0.05")
    lines.append(f"Expected ~{expected_chance:.0f} significant by chance alone (WR)")
    lines.append(f"Found {n_sig_wr} significant by win rate (raw p < 0.05)")
    lines.append(f"Found {n_sig_pf} significant by profit factor (raw p < 0.05)")
    lines.append(f"Survive BH FDR correction at q < 0.10 (WR): {n_fdr}")
    lines.append("")

    lines.append(f"Note: Baseline win rate across all trades = {summary['baseline_wr'].iloc[0]:.1f}%")
    lines.append("")

    def format_row(row, rank):
        factors = row['factors']
        fdr_flag = ''
        if 'p_value_wr_bh' in row.index and row['p_value_wr_bh'] < 0.10:
            fdr_flag = ' [FDR]'
        return (f"  {rank:3d}. {factors:<55s} n={row['n']:4d}  "
                f"WR={row['win_rate']:5.1f}%  PF={row['profit_factor']:5.2f}  "
                f"p_wr={row['p_value_wr']:.4f}{fdr_flag}")

    # Section 1: Top 20 by WR (n >= 30, p < 0.05)
    lines.append("-" * 70)
    lines.append("TOP 20 BY WIN RATE (n >= 30, p_wr < 0.05)")
    lines.append("-" * 70)
    top_wr = summary[(summary['n'] >= 30) & (summary['p_value_wr'] < 0.05)]
    top_wr = top_wr.sort_values('win_rate', ascending=False).head(20)
    for rank, (_, row) in enumerate(top_wr.iterrows(), 1):
        lines.append(format_row(row, rank))
    if len(top_wr) == 0:
        lines.append("  (none)")
    lines.append("")

    # Section 2: Top 20 by PF (n >= 30, p_pf < 0.05)
    lines.append("-" * 70)
    lines.append("TOP 20 BY PROFIT FACTOR (n >= 30, p_pf < 0.05)")
    lines.append("-" * 70)
    top_pf = summary[(summary['n'] >= 30) & (summary['p_value_pf'] < 0.05)]
    top_pf = top_pf[np.isfinite(top_pf['profit_factor'])]
    top_pf = top_pf.sort_values('profit_factor', ascending=False).head(20)
    for rank, (_, row) in enumerate(top_pf.iterrows(), 1):
        lines.append(format_row(row, rank))
    if len(top_pf) == 0:
        lines.append("  (none)")
    lines.append("")

    # Section 3: Top 20 by WR with n >= 50
    lines.append("-" * 70)
    lines.append("TOP 20 BY WIN RATE (n >= 50, robust sample)")
    lines.append("-" * 70)
    robust = summary[(summary['n'] >= 50) & (summary['p_value_wr'] < 0.05)]
    robust = robust.sort_values('win_rate', ascending=False).head(20)
    for rank, (_, row) in enumerate(robust.iterrows(), 1):
        lines.append(format_row(row, rank))
    if len(robust) == 0:
        lines.append("  (none)")
    lines.append("")

    # Section 4: Bottom 20 (avoid list)
    lines.append("-" * 70)
    lines.append("BOTTOM 20 — AVOID LIST (lowest WR, n >= 30, p_wr < 0.05)")
    lines.append("-" * 70)
    avoid = summary[(summary['n'] >= 30) & (summary['p_value_wr'] < 0.05)]
    avoid = avoid.sort_values('win_rate', ascending=True).head(20)
    for rank, (_, row) in enumerate(avoid.iterrows(), 1):
        lines.append(format_row(row, rank))
    if len(avoid) == 0:
        lines.append("  (none)")
    lines.append("")

    report = '\n'.join(lines)
    output_path.write_text(report)
    return report


# ===================================================================
# Main
# ===================================================================

def main():
    parser = argparse.ArgumentParser(description='FVGC Multi-Factor Combo Permutation Testing')
    parser.add_argument('--perms', type=int, default=10_000, help='Permutation iterations')
    parser.add_argument('--max-factors', type=int, default=3, choices=[2, 3],
                        help='Max combo size (2=pairs only, 3=pairs+triples)')
    parser.add_argument('--min-n', type=int, default=30, help='Minimum sample size')
    parser.add_argument('--metric', default='win_rate',
                        choices=['win_rate', 'profit_factor'],
                        help='Primary metric for ranking output')
    parser.add_argument('--no-histograms', action='store_true', help='Skip histograms')
    parser.add_argument('--seed', type=int, default=42, help='Random seed')
    args = parser.parse_args()

    df = load_data()

    print("\nBuilding factor masks...")
    masks = build_factor_masks(df)
    factor_names = sorted(masks.keys())
    print(f"  {len(factor_names)} factors defined")

    print("Generating combos...")
    combos = generate_combos(factor_names, args.max_factors)
    print(f"  {len(combos)} valid combos (max {args.max_factors}-way)")

    # Pre-compute arrays for the permutation engine
    win_flags = (df['outcome'] == 'win').values.astype(np.float64)
    pnl_vals = pd.to_numeric(df['pnl'], errors='coerce').values.astype(np.float64)
    baseline_wr = win_flags.mean() * 100
    baseline_pnl = np.nanmean(pnl_vals)
    gp_all = pnl_vals[pnl_vals > 0].sum()
    gl_all = abs(pnl_vals[pnl_vals < 0].sum())
    baseline_pf = gp_all / gl_all if gl_all > 0 else np.nan

    print(f"\nBaseline: {len(df)} trades, WR={baseline_wr:.1f}%, "
          f"PF={baseline_pf:.2f}, Avg PnL={baseline_pnl:.2f}")

    # Pre-filter combos by sample size
    valid_combos = []
    for combo in combos:
        combined = masks[combo[0]].copy()
        for f in combo[1:]:
            combined &= masks[f]
        n = combined.sum()
        if n >= args.min_n:
            valid_combos.append((combo, combined))

    print(f"  {len(valid_combos)} combos with n >= {args.min_n}")
    print(f"\nRunning {len(valid_combos)} combos x {args.perms:,} permutations...")
    print("=" * 60)

    rng = np.random.default_rng(args.seed)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    results = []
    for i, (combo, combo_mask) in enumerate(valid_combos, 1):
        combo_name = ' + '.join(combo)

        result = run_combo_permutation(combo_mask, win_flags, pnl_vals, args.perms, rng)

        sig_wr = '*' if result['p_value_wr'] < 0.05 else ''
        if result['p_value_wr'] < 0.01:
            sig_wr = '**'

        if i <= 20 or i % 100 == 0 or result['p_value_wr'] < 0.05:
            print(f"  [{i}/{len(valid_combos)}] {combo_name}: "
                  f"n={result['n']}, WR={result['win_rate']:.1f}%, "
                  f"PF={result['profit_factor']:.2f}, "
                  f"p_wr={result['p_value_wr']:.4f}{sig_wr}")
        elif i == 21:
            print(f"  ... (showing every 100th + significant results) ...")

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
            '_perm_wr_dist': result['perm_wr_dist'],
            '_perm_pf_dist': result['perm_pf_dist'],
        })

    print(f"\n{len(results)} combos tested.")

    summary = pd.DataFrame(results)

    # Multiple comparison corrections
    print("Applying multiple comparison corrections...")
    summary = apply_corrections(summary, 'p_value_wr')
    summary = apply_corrections(summary, 'p_value_pf')

    summary['significant_wr'] = summary['p_value_wr'] < 0.05
    summary['significant_pf'] = summary['p_value_pf'] < 0.05
    summary['survives_fdr_010_wr'] = summary['p_value_wr_bh'] < 0.10
    summary['survives_fdr_010_pf'] = summary['p_value_pf_bh'] < 0.10

    # Histograms for top results
    if not args.no_histograms and len(summary) > 0:
        COMBO_HIST_DIR.mkdir(parents=True, exist_ok=True)
        print("Generating histograms for top results...")

        hist_set = set()

        top_wr_idx = summary.nlargest(30, 'win_rate').index
        hist_set.update(top_wr_idx)

        finite_pf = summary[np.isfinite(summary['profit_factor'])]
        if len(finite_pf) > 0:
            top_pf_idx = finite_pf.nlargest(30, 'profit_factor').index
            hist_set.update(top_pf_idx)

        for idx in hist_set:
            row = summary.loc[idx]
            plot_combo_histogram(
                row['_perm_wr_dist'], row['win_rate'], row['mean_perm_wr'],
                row['combo_name'], 'win_rate', row['n'], row['p_value_wr'],
                COMBO_HIST_DIR,
            )

    # Drop distribution arrays before saving CSV
    save_cols = [c for c in summary.columns if not c.startswith('_')]
    summary_save = summary[save_cols].sort_values('win_rate', ascending=False).reset_index(drop=True)

    csv_path = RESULTS_DIR / 'combo_summary.csv'
    summary_save.to_csv(csv_path, index=False)
    print(f"Wrote {csv_path}")

    # Text report
    txt_path = RESULTS_DIR / 'combo_top_results.txt'
    report = write_text_report(summary_save, len(results), args.metric, txt_path)
    print(f"Wrote {txt_path}")
    print()
    print(report)


if __name__ == '__main__':
    main()
