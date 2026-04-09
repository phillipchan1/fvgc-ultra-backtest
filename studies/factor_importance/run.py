#!/usr/bin/env python3
"""
Study: Single-factor importance ranking for FVGC trade filters.

For each factor, measures the independent lift in win rate, profit factor,
and expectancy vs baseline. Ranks factors by impact to identify the
5-6 variables that actually move the needle.

Uses permutation testing for significance, same as the combo study
but focused on single factors with clear ranking output.

Run from repo root:
  python studies/factor_importance/run.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns

from analysis.permutation_test import load_data

STUDY_DIR = Path(__file__).resolve().parent
RESULTS_DIR = STUDY_DIR / 'results'


def build_factor_masks(df):
    """Build boolean masks for all single factors — same as combo study."""
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

    # Variant
    for v in df['variant'].unique():
        masks[f'variant_{v}'] = (df['variant'] == v).values

    return masks


# Factor category labels for grouping in output
FACTOR_CATEGORIES = {
    'prior_day_down': 'Prior Day', 'prior_day_up': 'Prior Day',
    'bearish_930': '930 Candle', 'bullish_930': '930 Candle',
    'gap_up': 'Gap', 'gap_down': 'Gap',
    'overnight_up': 'Overnight', 'overnight_down': 'Overnight',
    'wide_45min_or': 'Opening Range', 'tight_45min_or': 'Opening Range',
    'wide_5min_or': 'Opening Range', 'tight_5min_or': 'Opening Range',
    'wide_overnight': 'Overnight', 'tight_overnight': 'Overnight',
    'low_vixy': 'VIXY', 'normal_vixy': 'VIXY', 'elevated_vixy': 'VIXY',
    'no_red_folder': 'News', 'has_red_folder': 'News',
    'no_pre_rth_news': 'News', 'not_fomc_week': 'Calendar',
    'is_fomc_week': 'Calendar',
    'long_only': 'Direction', 'short_only': 'Direction',
    'macro_w1': 'Macro Window', 'macro_w2': 'Macro Window', 'macro_w3': 'Macro Window',
    'large_930_candle': '930 Candle', 'small_930_candle': '930 Candle',
}


def compute_factor_stats(mask, win_flags, pnl_vals, baseline_wr, baseline_pf):
    """Compute stats for a single factor."""
    n = mask.sum()
    if n < 10:
        return None

    sub_wins = win_flags[mask]
    sub_pnl = pnl_vals[mask]

    wr = sub_wins.mean() * 100
    avg_pnl = np.nanmean(sub_pnl)

    gp = sub_pnl[sub_pnl > 0].sum()
    gl = abs(sub_pnl[sub_pnl < 0].sum())
    pf = gp / gl if gl > 0 else (np.inf if gp > 0 else np.nan)

    wr_lift = wr - baseline_wr
    pf_lift = pf - baseline_pf if np.isfinite(pf) and np.isfinite(baseline_pf) else np.nan

    # Expectancy per trade in R-units (approx: avg pnl normalized)
    wins = sub_wins.sum()
    losses = n - wins
    if n > 0:
        expectancy = (wins * 1.0 - losses * 1.0) / n  # simplified 1R expectancy
    else:
        expectancy = 0

    return {
        'n': int(n),
        'wins': int(wins),
        'losses': int(losses),
        'win_rate': round(wr, 2),
        'profit_factor': round(pf, 4) if np.isfinite(pf) else np.inf,
        'avg_pnl': round(avg_pnl, 4),
        'wr_lift': round(wr_lift, 2),
        'pf_lift': round(pf_lift, 4) if np.isfinite(pf_lift) else np.nan,
        'expectancy_r': round(expectancy, 4),
    }


def run_permutation(mask, win_flags, pnl_vals, n_perms, rng):
    """Quick permutation test for a single factor."""
    n = mask.sum()
    actual_wr = win_flags[mask].mean() * 100

    sub_pnl = pnl_vals[mask]
    gp = sub_pnl[sub_pnl > 0].sum()
    gl = abs(sub_pnl[sub_pnl < 0].sum())
    actual_pf = gp / gl if gl > 0 else np.inf

    perm_wr = np.empty(n_perms)
    perm_pf = np.empty(n_perms)

    for i in range(n_perms):
        perm = rng.permutation(len(win_flags))
        s_wins = win_flags[perm][mask]
        s_pnl = pnl_vals[perm][mask]
        perm_wr[i] = s_wins.mean() * 100
        s_gp = s_pnl[s_pnl > 0].sum()
        s_gl = abs(s_pnl[s_pnl < 0].sum())
        perm_pf[i] = s_gp / s_gl if s_gl > 0 else (np.inf if s_gp > 0 else np.nan)

    # One-sided p-values (we care about factors that are better OR worse)
    perm_wr_mean = np.nanmean(perm_wr)
    if actual_wr >= perm_wr_mean:
        p_wr = np.nanmean(perm_wr >= actual_wr)
    else:
        p_wr = np.nanmean(perm_wr <= actual_wr)

    finite_pf = perm_pf[np.isfinite(perm_pf)]
    if len(finite_pf) > 0 and np.isfinite(actual_pf):
        if actual_pf >= np.nanmean(finite_pf):
            p_pf = np.nanmean(finite_pf >= actual_pf)
        else:
            p_pf = np.nanmean(finite_pf <= actual_pf)
    else:
        p_pf = np.nan

    return p_wr, p_pf


def plot_factor_ranking(df, metric, title, filename, output_dir):
    """Horizontal bar chart of factor ranking."""
    df_plot = df.copy()
    if len(df_plot) == 0:
        return

    # Sort by metric
    df_plot = df_plot.sort_values(metric, ascending=True).tail(40)

    fig, ax = plt.subplots(figsize=(10, max(6, len(df_plot) * 0.35)))

    colors = ['green' if v > 0 else 'red' for v in df_plot[metric]]
    bars = ax.barh(range(len(df_plot)), df_plot[metric], color=colors, alpha=0.8)
    ax.set_yticks(range(len(df_plot)))
    ax.set_yticklabels([f"{row['factor']} (n={row['n']})" for _, row in df_plot.iterrows()], fontsize=9)
    ax.axvline(x=0, color='gray', linestyle='--', alpha=0.5)
    ax.set_xlabel(metric.replace('_', ' ').title())
    ax.set_title(title)

    # Add value labels
    for i, (_, row) in enumerate(df_plot.iterrows()):
        val = row[metric]
        sig = ''
        if row.get('p_wr', 1) < 0.01:
            sig = ' **'
        elif row.get('p_wr', 1) < 0.05:
            sig = ' *'
        ax.text(val + (0.2 if val >= 0 else -0.2), i,
                f'{val:+.1f}{sig}', va='center', fontsize=8,
                ha='left' if val >= 0 else 'right')

    plt.tight_layout()
    fig.savefig(output_dir / filename, dpi=150)
    plt.close(fig)
    print(f"  Wrote {output_dir / filename}")


def plot_category_summary(df, output_dir):
    """Plot best factor per category."""
    # Get best positive factor per category
    positive = df[df['wr_lift'] > 0].copy()
    if len(positive) == 0:
        return

    best_per_cat = positive.loc[positive.groupby('category')['wr_lift'].idxmax()]
    best_per_cat = best_per_cat.sort_values('wr_lift', ascending=True)

    fig, ax = plt.subplots(figsize=(10, max(4, len(best_per_cat) * 0.5)))
    colors = plt.cm.viridis(np.linspace(0.3, 0.9, len(best_per_cat)))
    bars = ax.barh(range(len(best_per_cat)), best_per_cat['wr_lift'], color=colors, alpha=0.85)
    ax.set_yticks(range(len(best_per_cat)))
    labels = [f"{row['category']}: {row['factor']} (n={row['n']})"
              for _, row in best_per_cat.iterrows()]
    ax.set_yticklabels(labels, fontsize=9)
    ax.set_xlabel('Win Rate Lift vs Baseline (%)')
    ax.set_title('Best Factor per Category — Win Rate Lift')

    for i, (_, row) in enumerate(best_per_cat.iterrows()):
        sig = ''
        if row.get('p_wr', 1) < 0.01:
            sig = ' **'
        elif row.get('p_wr', 1) < 0.05:
            sig = ' *'
        ax.text(row['wr_lift'] + 0.1, i, f"+{row['wr_lift']:.1f}%{sig}", va='center', fontsize=9)

    plt.tight_layout()
    fig.savefig(output_dir / 'best_factor_per_category.png', dpi=150)
    plt.close(fig)
    print(f"  Wrote {output_dir / 'best_factor_per_category.png'}")


def write_report(summary, baseline_wr, baseline_pf, output_path):
    """Write ranked text report."""
    lines = []
    lines.append("=" * 70)
    lines.append("SINGLE-FACTOR IMPORTANCE RANKING")
    lines.append("=" * 70)
    lines.append(f"\nBaseline: WR={baseline_wr:.1f}%, PF={baseline_pf:.2f}")
    lines.append(f"Total factors tested: {len(summary)}")

    sig_count = (summary['p_wr'] < 0.05).sum()
    lines.append(f"Significant factors (p < 0.05): {sig_count}")

    # Top factors by WR lift
    lines.append(f"\n{'─' * 70}")
    lines.append("RANKED BY WIN RATE LIFT (positive = better than baseline)")
    lines.append(f"{'─' * 70}")
    lines.append(f"  {'Rank':<5s} {'Factor':<25s} {'n':>6s} {'WR%':>7s} {'Lift':>7s} "
                 f"{'PF':>7s} {'p_wr':>8s} {'Sig':>4s}")
    lines.append(f"  {'─'*5} {'─'*25} {'─'*6} {'─'*7} {'─'*7} {'─'*7} {'─'*8} {'─'*4}")

    sorted_wr = summary.sort_values('wr_lift', ascending=False)
    for rank, (_, row) in enumerate(sorted_wr.iterrows(), 1):
        sig = '**' if row['p_wr'] < 0.01 else ('*' if row['p_wr'] < 0.05 else '')
        pf_str = f"{row['profit_factor']:.2f}" if np.isfinite(row['profit_factor']) else 'inf'
        lines.append(f"  {rank:<5d} {row['factor']:<25s} {row['n']:>6d} "
                     f"{row['win_rate']:>6.1f}% {row['wr_lift']:>+6.1f}% "
                     f"{pf_str:>7s} {row['p_wr']:>8.4f} {sig:>4s}")

    # Top factors by PF
    lines.append(f"\n{'─' * 70}")
    lines.append("RANKED BY PROFIT FACTOR (top 20)")
    lines.append(f"{'─' * 70}")
    sorted_pf = summary[np.isfinite(summary['profit_factor'])].sort_values('profit_factor', ascending=False).head(20)
    for rank, (_, row) in enumerate(sorted_pf.iterrows(), 1):
        sig = '**' if row['p_pf'] < 0.01 else ('*' if row['p_pf'] < 0.05 else '')
        lines.append(f"  {rank:<5d} {row['factor']:<25s} n={row['n']:>5d}  "
                     f"WR={row['win_rate']:.1f}%  PF={row['profit_factor']:.2f}  "
                     f"p_pf={row['p_pf']:.4f} {sig}")

    # Avoid list
    lines.append(f"\n{'─' * 70}")
    lines.append("AVOID LIST — Factors that HURT performance (negative lift, p < 0.10)")
    lines.append(f"{'─' * 70}")
    avoid = summary[(summary['wr_lift'] < 0) & (summary['p_wr'] < 0.10)]
    avoid = avoid.sort_values('wr_lift', ascending=True)
    for rank, (_, row) in enumerate(avoid.iterrows(), 1):
        sig = '**' if row['p_wr'] < 0.01 else '*'
        lines.append(f"  {rank:<5d} {row['factor']:<25s} n={row['n']:>5d}  "
                     f"WR={row['win_rate']:.1f}%  lift={row['wr_lift']:+.1f}%  "
                     f"PF={row['profit_factor']:.2f}  p={row['p_wr']:.4f} {sig}")
    if len(avoid) == 0:
        lines.append("  (none)")

    # Category summary
    lines.append(f"\n{'─' * 70}")
    lines.append("BEST FACTOR PER CATEGORY")
    lines.append(f"{'─' * 70}")
    for cat in sorted(summary['category'].unique()):
        cat_df = summary[summary['category'] == cat].sort_values('wr_lift', ascending=False)
        best = cat_df.iloc[0]
        worst = cat_df.iloc[-1] if len(cat_df) > 1 else best
        lines.append(f"  {cat:<18s}  Best: {best['factor']:<22s} lift={best['wr_lift']:+.1f}%  "
                     f"PF={best['profit_factor']:.2f}")
        if len(cat_df) > 1:
            lines.append(f"  {'':<18s}  Worst: {worst['factor']:<21s} lift={worst['wr_lift']:+.1f}%  "
                         f"PF={worst['profit_factor']:.2f}")

    report = '\n'.join(lines)
    output_path.write_text(report)
    return report


def main():
    print("=" * 70)
    print("FVGC Single-Factor Importance Ranking")
    print("=" * 70)

    N_PERMS = 10_000
    SEED = 42

    df = load_data()

    print("\nBuilding factor masks...")
    masks = build_factor_masks(df)
    factor_names = sorted(masks.keys())
    print(f"  {len(factor_names)} factors defined")

    # Baseline stats
    win_flags = (df['outcome'] == 'win').values.astype(np.float64)
    pnl_vals = pd.to_numeric(df['pnl'], errors='coerce').values.astype(np.float64)
    baseline_wr = win_flags.mean() * 100
    gp_all = pnl_vals[pnl_vals > 0].sum()
    gl_all = abs(pnl_vals[pnl_vals < 0].sum())
    baseline_pf = gp_all / gl_all if gl_all > 0 else np.nan

    print(f"\nBaseline: {len(df)} trades, WR={baseline_wr:.1f}%, PF={baseline_pf:.2f}")
    print(f"\nRunning {len(factor_names)} factors x {N_PERMS:,} permutations...")
    print("=" * 60)

    rng = np.random.default_rng(SEED)
    results = []

    for i, name in enumerate(factor_names, 1):
        mask = masks[name]
        stats = compute_factor_stats(mask, win_flags, pnl_vals, baseline_wr, baseline_pf)

        if stats is None:
            print(f"  [{i}/{len(factor_names)}] {name}: SKIP (n < 10)")
            continue

        p_wr, p_pf = run_permutation(mask, win_flags, pnl_vals, N_PERMS, rng)

        sig = '**' if p_wr < 0.01 else ('*' if p_wr < 0.05 else '')
        print(f"  [{i}/{len(factor_names)}] {name}: n={stats['n']}, "
              f"WR={stats['win_rate']:.1f}%, lift={stats['wr_lift']:+.1f}%, "
              f"PF={stats['profit_factor']:.2f}, p={p_wr:.4f} {sig}")

        cat = FACTOR_CATEGORIES.get(name, 'Variant' if name.startswith('variant_') else 'Other')
        results.append({
            'factor': name,
            'category': cat,
            **stats,
            'p_wr': p_wr,
            'p_pf': p_pf,
        })

    summary = pd.DataFrame(results)

    # Save results
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = RESULTS_DIR / 'factor_importance.csv'
    summary.to_csv(csv_path, index=False)
    print(f"\n  Wrote {csv_path}")

    # Text report
    txt_path = RESULTS_DIR / 'factor_importance_report.txt'
    report = write_report(summary, baseline_wr, baseline_pf, txt_path)
    print(f"  Wrote {txt_path}")

    # Plots
    print(f"\n--- Generating plots ---")
    plot_factor_ranking(summary, 'wr_lift', 'Factor Ranking — Win Rate Lift vs Baseline',
                        'factor_ranking_wr_lift.png', RESULTS_DIR)

    pf_summary = summary[np.isfinite(summary['pf_lift'])].copy()
    plot_factor_ranking(pf_summary, 'pf_lift', 'Factor Ranking — Profit Factor Lift vs Baseline',
                        'factor_ranking_pf_lift.png', RESULTS_DIR)

    plot_category_summary(summary, RESULTS_DIR)

    print(f"\n{report}")
    print("\nDone.")


if __name__ == '__main__':
    main()
