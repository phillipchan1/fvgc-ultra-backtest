#!/usr/bin/env python3
"""
Study: Maximum Favorable Excursion (MFE) and Multi-R outcome analysis.

Re-simulates every trade from the baseline to track:
  - MFE: max favorable move from entry (in points and R-multiples)
  - MAE: max adverse move from entry (in points and R-multiples)
  - Whether trade would have hit 2R, 3R, 4R targets
  - Time-to-target for each R-level

Uses 30s candle data for bar-by-bar tracking from entry to EOD.

Run from repo root:
  python studies/mfe_multi_r/run.py
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

from fvgc.data import load_candles

STUDY_DIR = Path(__file__).resolve().parent
RESULTS_DIR = STUDY_DIR / 'results'
DATA_PATH = ROOT / 'data' / 'consolidated' / 'nq-front-month.ohlcv-30s.csv'
TRADES_PATH = ROOT / 'logs' / 'baseline_trades.csv'
TRADING_DAYS_PATH = ROOT / 'data' / 'trading_days' / 'trading_days.csv'

R_LEVELS = [1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0]


def track_mfe_for_trades(trades_df, candles):
    """Track MFE/MAE from baseline trades using candle data.

    Instead of re-running signal generation, we load the existing baseline
    trades (which have entry_idx) and walk forward from each entry to track
    how far price moved favorably/adversely.
    """
    results = []
    # Build a date→candle-slice index for fast lookups
    candles_ts = candles['timestamp_ny']
    candles_dates = candles_ts.dt.date

    total = len(trades_df)
    for i, (_, trade) in enumerate(trades_df.iterrows()):
        if i % 200 == 0:
            print(f"  Processing trade {i+1}/{total}...")

        entry_idx = int(trade['entry_idx'])
        direction = trade['direction']
        entry_price = trade['entry_price']
        sl_dist = trade['sl_dist']
        sl = trade['sl']
        tp = trade['tp']
        entry_date = trade['timestamp'].date()

        max_fav = 0.0
        max_adv = 0.0
        sl_hit = False
        sl_hit_bar = None
        r_hit_bars = {}

        bar_prev = None
        for j in range(entry_idx + 1, len(candles)):
            bar = candles.iloc[j]

            if bar['timestamp_ny'].date() != entry_date:
                break

            bar_prev = bar
            bars_held = j - entry_idx

            # Track MFE/MAE (full day from entry)
            if direction == 'long':
                fav = bar['high'] - entry_price
                adv = entry_price - bar['low']
            else:
                fav = entry_price - bar['low']
                adv = bar['high'] - entry_price

            max_fav = max(max_fav, fav)
            max_adv = max(max_adv, adv)

            # Check R-level hits BEFORE SL is hit
            # For multi-R sim: "would this trade win at XR target with 1R SL?"
            # = did price reach XR before reaching SL?
            if not sl_hit:
                for r in R_LEVELS:
                    if r not in r_hit_bars:
                        if fav >= sl_dist * r:
                            r_hit_bars[r] = bars_held

            # Track when SL is hit
            if not sl_hit:
                if direction == 'short' and bar['high'] >= sl:
                    sl_hit = True
                    sl_hit_bar = bars_held
                elif direction == 'long' and bar['low'] <= sl:
                    sl_hit = True
                    sl_hit_bar = bars_held

        # Determine 1R outcome from the trade record
        outcome_1r = trade['outcome']
        if outcome_1r not in ('win', 'loss'):
            continue

        mfe_r = max_fav / sl_dist if sl_dist > 0 else 0
        mae_r = max_adv / sl_dist if sl_dist > 0 else 0

        row = {
            'timestamp': trade['timestamp'],
            'direction': direction,
            'entry_price': entry_price,
            'variant': trade['variant'],
            'sl_dist': sl_dist,
            'outcome': outcome_1r,
            'mfe_pts': round(max_fav, 2),
            'mae_pts': round(max_adv, 2),
            'mfe_r': round(mfe_r, 2),
            'mae_r': round(mae_r, 2),
        }

        for r in R_LEVELS:
            r_key = str(r).replace('.', '_')
            row[f'hit_{r_key}R'] = r in r_hit_bars
            row[f'bars_to_{r_key}R'] = r_hit_bars.get(r, '')

        results.append(row)

    return results


def print_mfe_summary(df):
    """Print MFE distribution summary."""
    print("\n" + "=" * 70)
    print("MFE / MULTI-R SUMMARY")
    print("=" * 70)

    total = len(df)
    wins = (df['outcome'] == 'win').sum()
    losses = (df['outcome'] == 'loss').sum()
    print(f"\nTotal trades: {total} (W={wins}, L={losses})")

    # MFE distribution
    print(f"\n--- MFE Distribution (R-multiples) ---")
    print(f"  Mean MFE:   {df['mfe_r'].mean():.2f}R")
    print(f"  Median MFE: {df['mfe_r'].median():.2f}R")
    print(f"  Std MFE:    {df['mfe_r'].std():.2f}R")

    # R-level hit rates
    r_levels = [1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0]
    print(f"\n--- R-Level Hit Rates (all trades) ---")
    print(f"  {'R-Level':<10s} {'Hit%':>8s} {'Count':>8s} {'of Total':>10s}")
    for r in r_levels:
        r_key = str(r).replace('.', '_')
        col = f'hit_{r_key}R'
        n_hit = df[col].sum()
        pct = n_hit / total * 100
        print(f"  {r}R{'':<7s} {pct:7.1f}%  {n_hit:7d}   / {total}")

    # R-level hit rates for WINNERS only
    winners = df[df['outcome'] == 'win']
    print(f"\n--- R-Level Hit Rates (winners only, n={len(winners)}) ---")
    print(f"  {'R-Level':<10s} {'Hit%':>8s} {'Count':>8s}")
    for r in r_levels:
        r_key = str(r).replace('.', '_')
        col = f'hit_{r_key}R'
        n_hit = winners[col].sum()
        pct = n_hit / len(winners) * 100 if len(winners) > 0 else 0
        print(f"  {r}R{'':<7s} {pct:7.1f}%  {n_hit:7d}")

    # R-level hit rates for LOSERS (runners that reversed)
    losers = df[df['outcome'] == 'loss']
    print(f"\n--- R-Level Hit Rates (losers only, n={len(losers)}) ---")
    print(f"  {'R-Level':<10s} {'Hit%':>8s} {'Count':>8s}")
    for r in r_levels:
        r_key = str(r).replace('.', '_')
        col = f'hit_{r_key}R'
        n_hit = losers[col].sum()
        pct = n_hit / len(losers) * 100 if len(losers) > 0 else 0
        print(f"  {r}R{'':<7s} {pct:7.1f}%  {n_hit:7d}")

    # MAE for winners (how much heat did winners take?)
    print(f"\n--- MAE for Winners (adverse excursion before winning) ---")
    print(f"  Mean MAE:   {winners['mae_r'].mean():.2f}R")
    print(f"  Median MAE: {winners['mae_r'].median():.2f}R")
    print(f"  Max MAE:    {winners['mae_r'].max():.2f}R")


def print_multi_r_pf(df):
    """Simulate profit factors at different R-targets.

    For each target R, we assume:
    - Winners: trade hits target R → profit = target_R * sl_dist
    - Losers: trade stops out at 1R → loss = sl_dist
    - If a loser's MFE >= target_R, it would have been a winner at that target
    """
    print(f"\n--- Simulated Profit Factor at Different R-Targets ---")
    print(f"  (Assumes SL stays at 1R, only TP changes)")
    print(f"  {'Target':<10s} {'WR%':>8s} {'PF':>8s} {'Wins':>8s} {'Losses':>8s} {'Expectancy':>12s}")

    r_targets = [1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0]
    for target_r in r_targets:
        r_key = str(target_r).replace('.', '_')
        col = f'hit_{r_key}R'

        # A trade is a "win" at this R if MFE reached the target
        # But we need to check if SL was hit BEFORE the target
        # The hit_*R flag tracks if the level was ever reached during the trade day
        # For winners: they already hit 1R, so check if they also hit target_R
        # For losers: they hit SL first, so even if MFE was high, SL was hit first

        # Actually, we need a proper simulation: did price hit target_R BEFORE hitting SL?
        # Our current data tracks MFE across the entire trade, not sequentially.
        # But hit_*R is tracked bar-by-bar and only recorded if reached.
        # For 1R target, outcome == 'win' is correct.
        # For higher R targets with same SL, we need to re-check.

        # Simplification: use the hit flag which was tracked during simulation
        # Winners that hit target_R → win at target_R (they didn't hit SL before 1R)
        # Losers that hit target_R → these actually hit SL first (since outcome=loss),
        #   so they would NOT be winners at higher R either. They're still losses.

        # Wait - that's the key insight. A loser hit SL first. Even if MFE was high,
        # for targets > 1R, we can't assume they'd have won. They lost at 1R SL.
        # BUT: if we're keeping SL the same and just changing TP, the question is:
        # did price reach target_R before hitting SL?
        # For current winners: they hit 1R before SL. Some also hit 2R before hitting SL.
        #   hit_2R flag = True means 2R was reached during the trade (entry to EOD).
        #   But they exited at 1R. We need: would they have hit 2R if held?
        #   Since they won at 1R and kept going, yes - if hit_2R is True, it means
        #   price went there at some point (we track MFE through entire day after entry).

        # For current losers: they hit SL before 1R TP. With a higher TP, SL is same,
        #   so they'd still hit SL first → still losses.

        # So the correct simulation:
        # wins_at_target = current winners whose hit_{target}R == True
        # losses_at_target = current losers + current winners whose hit_{target}R == False
        #   (winners who didn't reach target_R would now become EOD/loss)

        winners = df[df['outcome'] == 'win']
        losers = df[df['outcome'] == 'loss']

        wins_at_r = winners[winners[col] == True]
        # Winners that didn't reach target become losses (exit at EOD or wherever)
        # For simplicity, assume they exit at 0 P&L (conservative) — actually they
        # could be anywhere. Let's count them as breakeven/excluded for clean PF calc.
        non_hits = winners[winners[col] == False]

        n_wins = len(wins_at_r)
        n_losses = len(losers) + len(non_hits)  # losers + winners that didn't reach target

        total_profit = n_wins * target_r  # each win = target_r * risk
        total_loss = len(losers) * 1.0  # each loss = 1R
        # Non-hit winners: they won at 1R originally, so with higher target they'd
        # have gone past 1R but not reached target. Assume they trail out at ~0.5R avg
        # Actually let's be conservative: they exit at breakeven (0 P&L) since we
        # don't know exactly where they'd exit with a trail.
        # For cleaner analysis, count them as 0 P&L.

        wr = n_wins / (n_wins + n_losses) * 100 if (n_wins + n_losses) > 0 else 0
        pf = total_profit / total_loss if total_loss > 0 else float('inf')
        expectancy = (n_wins * target_r - len(losers) * 1.0) / (n_wins + n_losses) if (n_wins + n_losses) > 0 else 0

        print(f"  {target_r}R{'':<7s} {wr:7.1f}%  {pf:7.2f}  {n_wins:7d}  {n_losses:7d}  {expectancy:+11.3f}R")


def print_direction_breakdown(df):
    """Break down multi-R stats by direction."""
    print(f"\n--- Multi-R Hit Rates by Direction ---")
    r_levels = [1.0, 1.5, 2.0, 2.5, 3.0]

    for direction in ['long', 'short']:
        sub = df[df['direction'] == direction]
        winners = sub[sub['outcome'] == 'win']
        print(f"\n  {direction.upper()} (n={len(sub)}, wins={len(winners)})")
        print(f"  {'R-Level':<10s} {'All Hit%':>10s} {'Win→Hit%':>10s}")
        for r in r_levels:
            r_key = str(r).replace('.', '_')
            col = f'hit_{r_key}R'
            all_hit = sub[col].sum()
            all_pct = all_hit / len(sub) * 100 if len(sub) > 0 else 0
            win_hit = winners[col].sum()
            win_pct = win_hit / len(winners) * 100 if len(winners) > 0 else 0
            print(f"  {r}R{'':<7s} {all_pct:9.1f}%  {win_pct:9.1f}%")


def plot_mfe_distribution(df, output_dir):
    """Plot MFE distribution histograms."""
    fig, axes = plt.subplots(1, 3, figsize=(18, 5))

    # All trades MFE
    sns.histplot(df['mfe_r'], bins=50, ax=axes[0], color='steelblue', alpha=0.7, edgecolor='white')
    axes[0].axvline(df['mfe_r'].mean(), color='red', linestyle='--', label=f'Mean: {df["mfe_r"].mean():.2f}R')
    axes[0].axvline(df['mfe_r'].median(), color='orange', linestyle='--', label=f'Median: {df["mfe_r"].median():.2f}R')
    axes[0].set_title(f'MFE Distribution — All Trades (n={len(df)})')
    axes[0].set_xlabel('MFE (R-multiples)')
    axes[0].legend()

    # Winners MFE
    winners = df[df['outcome'] == 'win']
    sns.histplot(winners['mfe_r'], bins=50, ax=axes[1], color='green', alpha=0.7, edgecolor='white')
    axes[1].axvline(winners['mfe_r'].mean(), color='red', linestyle='--', label=f'Mean: {winners["mfe_r"].mean():.2f}R')
    axes[1].set_title(f'MFE Distribution — Winners (n={len(winners)})')
    axes[1].set_xlabel('MFE (R-multiples)')
    axes[1].legend()

    # Losers MFE
    losers = df[df['outcome'] == 'loss']
    sns.histplot(losers['mfe_r'], bins=50, ax=axes[2], color='salmon', alpha=0.7, edgecolor='white')
    axes[2].axvline(losers['mfe_r'].mean(), color='red', linestyle='--', label=f'Mean: {losers["mfe_r"].mean():.2f}R')
    axes[2].set_title(f'MFE Distribution — Losers (n={len(losers)})')
    axes[2].set_xlabel('MFE (R-multiples)')
    axes[2].legend()

    plt.tight_layout()
    fig.savefig(output_dir / 'mfe_distribution.png', dpi=150)
    plt.close(fig)
    print(f"  Wrote {output_dir / 'mfe_distribution.png'}")


def plot_r_level_cascade(df, output_dir):
    """Plot the cascade of R-level hit rates."""
    r_levels = [1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0]
    total = len(df)

    all_pcts = []
    win_pcts = []
    winners = df[df['outcome'] == 'win']

    for r in r_levels:
        r_key = str(r).replace('.', '_')
        col = f'hit_{r_key}R'
        all_pcts.append(df[col].sum() / total * 100)
        win_pcts.append(winners[col].sum() / len(winners) * 100 if len(winners) > 0 else 0)

    fig, ax = plt.subplots(figsize=(10, 6))
    x = np.arange(len(r_levels))
    width = 0.35

    bars1 = ax.bar(x - width/2, all_pcts, width, label='All Trades', color='steelblue', alpha=0.8)
    bars2 = ax.bar(x + width/2, win_pcts, width, label='Winners Only', color='green', alpha=0.8)

    ax.set_xlabel('R-Level Target')
    ax.set_ylabel('Hit Rate (%)')
    ax.set_title('R-Level Hit Rate Cascade')
    ax.set_xticks(x)
    ax.set_xticklabels([f'{r}R' for r in r_levels])
    ax.legend()

    for bar, pct in zip(bars1, all_pcts):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.5,
                f'{pct:.0f}%', ha='center', va='bottom', fontsize=9)
    for bar, pct in zip(bars2, win_pcts):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.5,
                f'{pct:.0f}%', ha='center', va='bottom', fontsize=9)

    plt.tight_layout()
    fig.savefig(output_dir / 'r_level_cascade.png', dpi=150)
    plt.close(fig)
    print(f"  Wrote {output_dir / 'r_level_cascade.png'}")


def plot_simulated_pf(df, output_dir):
    """Plot profit factor at different R-targets."""
    r_targets = [1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0]
    pfs = []
    expectancies = []

    winners = df[df['outcome'] == 'win']
    losers = df[df['outcome'] == 'loss']

    for target_r in r_targets:
        r_key = str(target_r).replace('.', '_')
        col = f'hit_{r_key}R'
        wins_at_r = winners[winners[col] == True]
        n_wins = len(wins_at_r)
        n_losses = len(losers) + len(winners[winners[col] == False])
        total_profit = n_wins * target_r
        total_loss = len(losers) * 1.0
        pf = total_profit / total_loss if total_loss > 0 else 0
        exp = (n_wins * target_r - len(losers) * 1.0) / (n_wins + n_losses) if (n_wins + n_losses) > 0 else 0
        pfs.append(pf)
        expectancies.append(exp)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

    ax1.bar(range(len(r_targets)), pfs, color='steelblue', alpha=0.8)
    ax1.axhline(y=1.0, color='red', linestyle='--', alpha=0.5, label='Breakeven')
    ax1.set_xticks(range(len(r_targets)))
    ax1.set_xticklabels([f'{r}R' for r in r_targets])
    ax1.set_ylabel('Profit Factor')
    ax1.set_title('Profit Factor by R-Target')
    ax1.legend()
    for i, pf in enumerate(pfs):
        ax1.text(i, pf + 0.02, f'{pf:.2f}', ha='center', va='bottom', fontsize=10)

    colors = ['green' if e > 0 else 'red' for e in expectancies]
    ax2.bar(range(len(r_targets)), expectancies, color=colors, alpha=0.8)
    ax2.axhline(y=0, color='gray', linestyle='--', alpha=0.5)
    ax2.set_xticks(range(len(r_targets)))
    ax2.set_xticklabels([f'{r}R' for r in r_targets])
    ax2.set_ylabel('Expectancy (R)')
    ax2.set_title('Expectancy per Trade by R-Target')
    for i, e in enumerate(expectancies):
        ax2.text(i, e + 0.005, f'{e:+.3f}R', ha='center', va='bottom', fontsize=10)

    plt.tight_layout()
    fig.savefig(output_dir / 'simulated_pf_by_r.png', dpi=150)
    plt.close(fig)
    print(f"  Wrote {output_dir / 'simulated_pf_by_r.png'}")


def main():
    print("=" * 70)
    print("FVGC MFE / Multi-R Study")
    print("=" * 70)

    # Load baseline trades (already generated)
    print("\nLoading baseline trades...")
    trades = pd.read_csv(TRADES_PATH)
    trades['timestamp'] = pd.to_datetime(trades['timestamp'])
    trades['sl_dist'] = pd.to_numeric(trades['sl_dist'], errors='coerce')
    trades['sl'] = pd.to_numeric(trades['sl'], errors='coerce')
    trades['tp'] = pd.to_numeric(trades['tp'], errors='coerce')
    trades['entry_idx'] = pd.to_numeric(trades['entry_idx'], errors='coerce')
    tradeable = trades[
        trades['outcome'].isin(['win', 'loss']) &
        trades['sl_dist'].notna() &
        trades['entry_idx'].notna()
    ].copy()
    print(f"  {len(tradeable)} tradeable trades loaded from baseline")

    print("\nLoading candle data...")
    candles = load_candles(DATA_PATH)
    print(f"  {len(candles)} candles loaded")

    print("\nTracking MFE/MAE for each trade...")
    results = track_mfe_for_trades(tradeable, candles)
    print(f"  {len(results)} tradeable results")

    df = pd.DataFrame(results)

    # Save raw results
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = RESULTS_DIR / 'mfe_trades.csv'
    df.to_csv(csv_path, index=False)
    print(f"\n  Wrote {csv_path} ({len(df)} rows)")

    # Print summaries
    print_mfe_summary(df)
    print_multi_r_pf(df)
    print_direction_breakdown(df)

    # Generate plots
    print(f"\n--- Generating plots ---")
    plot_mfe_distribution(df, RESULTS_DIR)
    plot_r_level_cascade(df, RESULTS_DIR)
    plot_simulated_pf(df, RESULTS_DIR)

    # Join with trading_days for enriched export
    td = pd.read_csv(TRADING_DAYS_PATH)
    td['date'] = pd.to_datetime(td['date']).dt.date
    df['date'] = pd.to_datetime(df['timestamp']).dt.date
    enriched = df.merge(td, on='date', how='left')
    enriched_path = RESULTS_DIR / 'mfe_trades_enriched.csv'
    enriched.to_csv(enriched_path, index=False)
    print(f"  Wrote {enriched_path} ({len(enriched)} rows)")

    print("\nDone.")


if __name__ == '__main__':
    main()
