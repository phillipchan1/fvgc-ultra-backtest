#!/usr/bin/env python3
"""
Study: Continuations toward Opening Range (OR) High/Low

After the OR is set at 9:45 ET (first 15 min of RTH), do FVGC entries
that target the OR high (longs) or OR low (shorts) produce edge?

Logic:
  1. Compute OR high/low per day from candle data (9:30:00–9:44:59 ET)
  2. Filter baseline trades entered at or after 9:45
  3. For longs: OR_high > entry → "continuation up to OR high"
     For shorts: OR_low < entry → "continuation down to OR low"
  4. Compute R_to_OR = distance_to_OR_level / sl_dist
  5. Filter by minimum R threshold (1.0R default, 0.5R variant)
  6. Use MFE to check if price actually reached the OR level

Run from repo root:
  python studies/or_continuation/run.py
"""

import sys
from pathlib import Path
from datetime import time as dtime

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import numpy as np

from fvgc.data import load_candles
from fvgc.model import generate_signals
from fvgc.engine import simulate_trades, summarize_results, print_summary, log_signals

STUDY_DIR = Path(__file__).resolve().parent
RESULTS_DIR = STUDY_DIR / 'results'

TIMEFRAMES = {
    '15s': ROOT / 'data' / 'consolidated' / 'nq-front-month.ohlcv-15s.csv',
    '30s': ROOT / 'data' / 'consolidated' / 'nq-front-month.ohlcv-30s.csv',
    '1m':  ROOT / 'data' / 'consolidated' / 'nq-front-month.ohlcv-1m.csv',
}

OR_START = dtime(9, 30)
OR_END = dtime(9, 45)        # OR set at 9:45
ENTRY_AFTER = dtime(9, 45)   # Only consider entries at or after 9:45

MIN_R_THRESHOLDS = [0.5, 1.0, 1.5, 2.0]


def compute_or_levels(candles: pd.DataFrame) -> dict:
    """Compute Opening Range (first 15 min RTH) high/low per trading day.

    Returns {date: {'or_high': float, 'or_low': float, 'or_range': float}}
    """
    or_mask = (
        (candles['timestamp_ny'].dt.time >= OR_START) &
        (candles['timestamp_ny'].dt.time < OR_END)
    )
    or_candles = candles[or_mask].copy()
    or_candles['date'] = or_candles['timestamp_ny'].dt.date

    or_levels = {}
    for date, group in or_candles.groupby('date'):
        or_high = group['high'].max()
        or_low = group['low'].min()
        or_levels[date] = {
            'or_high': or_high,
            'or_low': or_low,
            'or_range': or_high - or_low,
        }
    return or_levels


def enrich_trades_with_or(results: list, or_levels: dict) -> pd.DataFrame:
    """Add OR fields to each trade and compute R-to-OR metrics."""
    rows = []
    for r in results:
        if r.get('outcome') in ('skip', '', None):
            continue

        entry_time = r['timestamp']
        if entry_time.time() < ENTRY_AFTER:
            continue

        entry_date = entry_time.date()
        if entry_date not in or_levels:
            continue

        orh = or_levels[entry_date]['or_high']
        orl = or_levels[entry_date]['or_low']
        or_range = or_levels[entry_date]['or_range']

        direction = r['direction']
        entry_price = r['entry_price']
        sl_dist = r.get('sl_dist', 0)
        if sl_dist <= 0:
            continue

        mfe_pts = r.get('mfe_pts', 0) or 0

        # Determine if this trade is a continuation toward an OR level
        if direction == 'long' and orh > entry_price:
            dist_to_or = orh - entry_price
            or_target = orh
            or_target_label = 'or_high'
        elif direction == 'short' and orl < entry_price:
            dist_to_or = entry_price - orl
            or_target = orl
            or_target_label = 'or_low'
        else:
            # Entry is beyond OR level (already past the target) — not a continuation
            continue

        r_to_or = dist_to_or / sl_dist
        reached_or = mfe_pts >= dist_to_or

        row = {
            'timestamp': entry_time,
            'date': entry_date,
            'direction': direction,
            'entry_price': entry_price,
            'variant': r.get('variant', ''),
            'sl': r.get('sl', ''),
            'tp': r.get('tp', ''),
            'sl_dist': sl_dist,
            'outcome': r['outcome'],
            'pnl': r.get('pnl', 0),
            'exit_price': r.get('exit_price', ''),
            'exit_time': r.get('exit_time', ''),
            'mfe_pts': mfe_pts,
            'mae_pts': r.get('mae_pts', 0) or 0,
            'mfe_r': r.get('mfe_r', 0) or 0,
            'mae_r': r.get('mae_r', 0) or 0,
            'or_high': orh,
            'or_low': orl,
            'or_range': or_range,
            'or_target': or_target,
            'or_target_label': or_target_label,
            'dist_to_or': round(dist_to_or, 2),
            'r_to_or': round(r_to_or, 2),
            'reached_or': reached_or,
        }
        # R-level hit flags
        from fvgc.engine import R_LEVELS
        for rl in R_LEVELS:
            r_key = str(rl).replace('.', '_')
            row[f'hit_{r_key}R'] = r.get(f'hit_{r_key}R', False)
            row[f'bars_to_{r_key}R'] = r.get(f'bars_to_{r_key}R', '')

        rows.append(row)

    return pd.DataFrame(rows)


def compute_or_target_stats(df: pd.DataFrame, min_r: float) -> dict:
    """Compute stats for trades where R-to-OR >= min_r.

    'Reaching OR' means MFE >= dist_to_or (price touched the OR level).
    We report both standard 1R stats AND OR-target stats.
    """
    cohort = df[df['r_to_or'] >= min_r].copy()
    if len(cohort) == 0:
        return None

    # Standard 1R stats (from existing simulation)
    wins_1r = (cohort['outcome'] == 'win').sum()
    losses_1r = (cohort['outcome'] == 'loss').sum()
    eod = (cohort['outcome'] == 'eod').sum()
    decided_1r = wins_1r + losses_1r
    wr_1r = wins_1r / decided_1r * 100 if decided_1r > 0 else 0
    pnl_1r = cohort.loc[cohort['pnl'].apply(lambda x: x != ''), 'pnl'].astype(float).sum()
    gross_win_1r = cohort.loc[cohort['outcome'] == 'win', 'pnl'].astype(float).sum()
    gross_loss_1r = abs(cohort.loc[cohort['outcome'] == 'loss', 'pnl'].astype(float).sum())
    pf_1r = gross_win_1r / gross_loss_1r if gross_loss_1r > 0 else float('inf')

    # OR-target stats: did price reach the OR level?
    reached = cohort['reached_or'].sum()
    not_reached = len(cohort) - reached
    or_hit_rate = reached / len(cohort) * 100

    # Simulate OR-target PF: win at r_to_or distance, lose at 1R SL
    # Winners at OR target = trades where MFE >= dist_to_or AND didn't hit SL first
    # We approximate: if outcome != 'loss' and reached_or, it's a win at OR target
    # If outcome == 'loss', SL was hit first → loss regardless
    wins_or = cohort[(cohort['outcome'] != 'loss') & (cohort['reached_or'])].copy()
    losses_or = cohort[cohort['outcome'] == 'loss'].copy()
    # Trades that didn't reach OR and didn't lose → EOD/partial
    partial = cohort[(cohort['outcome'] != 'loss') & (~cohort['reached_or'])].copy()

    gross_win_or = wins_or['dist_to_or'].sum()  # profit = distance to OR (in pts)
    gross_loss_or = losses_or['sl_dist'].sum()   # loss = SL distance (in pts)
    pf_or = gross_win_or / gross_loss_or if gross_loss_or > 0 else float('inf')

    # Expectancy at OR target (R-normalized)
    n_decided_or = len(wins_or) + len(losses_or)
    if n_decided_or > 0:
        # Total R profit from OR wins
        r_profit_or = wins_or['r_to_or'].sum()
        r_loss_or = len(losses_or) * 1.0
        expectancy_or = (r_profit_or - r_loss_or) / n_decided_or
    else:
        expectancy_or = 0

    return {
        'min_r': min_r,
        'n_trades': len(cohort),
        'n_long': (cohort['direction'] == 'long').sum(),
        'n_short': (cohort['direction'] == 'short').sum(),
        # Standard 1R
        'wins_1r': wins_1r,
        'losses_1r': losses_1r,
        'eod': eod,
        'wr_1r': wr_1r,
        'pf_1r': pf_1r,
        'pnl_1r': pnl_1r,
        # OR target
        'or_hit_rate': or_hit_rate,
        'wins_or': len(wins_or),
        'losses_or': len(losses_or),
        'partial_or': len(partial),
        'pf_or': pf_or,
        'expectancy_or': expectancy_or,
        'mean_r_to_or': cohort['r_to_or'].mean(),
        'median_r_to_or': cohort['r_to_or'].median(),
        'mean_mfe_r': cohort['mfe_r'].mean(),
    }


def print_or_study(df: pd.DataFrame, tf_label: str):
    """Print comprehensive OR continuation analysis."""
    print(f"\n{'=' * 70}")
    print(f"  OR CONTINUATION STUDY — {tf_label}")
    print(f"{'=' * 70}")
    print(f"\n  Total post-9:45 OR-aligned trades: {len(df)}")
    if len(df) == 0:
        print("  No trades found.")
        return

    print(f"  Long→OR_high: {(df['or_target_label'] == 'or_high').sum()}")
    print(f"  Short→OR_low:  {(df['or_target_label'] == 'or_low').sum()}")
    print(f"  Mean R-to-OR:  {df['r_to_or'].mean():.2f}R")
    print(f"  Median R-to-OR: {df['r_to_or'].median():.2f}R")
    print(f"  OR reached overall: {df['reached_or'].sum()}/{len(df)} "
          f"({df['reached_or'].mean()*100:.1f}%)")

    # Stats at each R threshold
    print(f"\n  {'─' * 66}")
    print(f"  {'Min R':>6s} │ {'N':>5s} │ {'WR(1R)':>7s} {'PF(1R)':>7s} │ "
          f"{'OR Hit%':>7s} {'PF(OR)':>7s} {'Exp(OR)':>8s} │ {'L/S':>7s}")
    print(f"  {'─' * 66}")

    for min_r in MIN_R_THRESHOLDS:
        stats = compute_or_target_stats(df, min_r)
        if stats is None:
            print(f"  {min_r:5.1f}R │ {'0':>5s} │ {'—':>7s} {'—':>7s} │ "
                  f"{'—':>7s} {'—':>7s} {'—':>8s} │ {'—':>7s}")
            continue
        ls = f"{stats['n_long']}/{stats['n_short']}"
        print(f"  {min_r:5.1f}R │ {stats['n_trades']:5d} │ "
              f"{stats['wr_1r']:6.1f}% {stats['pf_1r']:6.2f}x │ "
              f"{stats['or_hit_rate']:6.1f}% {stats['pf_or']:6.2f}x "
              f"{stats['expectancy_or']:+7.3f}R │ {ls:>7s}")
    print(f"  {'─' * 66}")

    # Direction breakdown at 1.0R threshold
    print(f"\n  --- Direction Breakdown (R-to-OR >= 1.0) ---")
    cohort = df[df['r_to_or'] >= 1.0]
    for direction in ['long', 'short']:
        sub = cohort[cohort['direction'] == direction]
        if len(sub) == 0:
            continue
        wins = (sub['outcome'] == 'win').sum()
        losses = (sub['outcome'] == 'loss').sum()
        decided = wins + losses
        wr = wins / decided * 100 if decided > 0 else 0
        reached = sub['reached_or'].sum()
        or_pct = reached / len(sub) * 100
        print(f"  {direction.upper():6s}: n={len(sub):4d}  WR(1R)={wr:5.1f}%  "
              f"OR_reached={reached}/{len(sub)} ({or_pct:.1f}%)  "
              f"mean_MFE={sub['mfe_r'].mean():.2f}R")

    # Variant breakdown at 1.0R
    print(f"\n  --- Variant Breakdown (R-to-OR >= 1.0) ---")
    for variant in sorted(cohort['variant'].unique()):
        sub = cohort[cohort['variant'] == variant]
        wins = (sub['outcome'] == 'win').sum()
        losses = (sub['outcome'] == 'loss').sum()
        decided = wins + losses
        wr = wins / decided * 100 if decided > 0 else 0
        reached = sub['reached_or'].sum()
        or_pct = reached / len(sub) * 100
        print(f"  {variant:15s}: n={len(sub):4d}  WR(1R)={wr:5.1f}%  "
              f"OR_reached={or_pct:.1f}%")

    # R-to-OR distribution
    print(f"\n  --- R-to-OR Distribution ---")
    for lo, hi, label in [(0, 0.5, '< 0.5R'), (0.5, 1.0, '0.5–1.0R'),
                           (1.0, 1.5, '1.0–1.5R'), (1.5, 2.0, '1.5–2.0R'),
                           (2.0, 3.0, '2.0–3.0R'), (3.0, 99, '3.0R+')]:
        sub = df[(df['r_to_or'] >= lo) & (df['r_to_or'] < hi)]
        if len(sub) == 0:
            continue
        reached = sub['reached_or'].sum()
        or_pct = reached / len(sub) * 100
        wins = (sub['outcome'] == 'win').sum()
        losses = (sub['outcome'] == 'loss').sum()
        decided = wins + losses
        wr = wins / decided * 100 if decided > 0 else 0
        print(f"  {label:10s}: n={len(sub):4d}  WR(1R)={wr:5.1f}%  "
              f"OR_reached={or_pct:.1f}%")


def run_timeframe(tf_label: str, data_path: Path) -> pd.DataFrame:
    """Run the full pipeline for one timeframe."""
    print(f"\n{'#' * 70}")
    print(f"  TIMEFRAME: {tf_label}")
    print(f"{'#' * 70}")

    candles = load_candles(data_path)
    tmin = candles['timestamp_ny'].min()
    tmax = candles['timestamp_ny'].max()
    print(f"  Data range: {tmin} → {tmax}")
    print(f"  Bars: {len(candles):,}")

    # Compute OR levels
    or_levels = compute_or_levels(candles)
    print(f"  OR levels computed for {len(or_levels)} trading days")

    # Generate signals and simulate
    print("  Detecting FVGs and entries...")
    signals, _fvgs = generate_signals(candles)
    print(f"  {len(signals)} signals")

    print("  Simulating trades...")
    results = simulate_trades(signals, candles)

    # Enrich with OR data and filter
    df = enrich_trades_with_or(results, or_levels)
    print(f"  {len(df)} post-9:45 OR-continuation trades")

    # Print analysis
    print_or_study(df, tf_label)

    return df


def main():
    print("=" * 70)
    print("FVGC — Opening Range Continuation Study")
    print("Post-9:45 entries targeting OR high (longs) / OR low (shorts)")
    print("=" * 70)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    all_dfs = {}

    for tf_label, data_path in TIMEFRAMES.items():
        if not data_path.exists():
            print(f"\n  Skipping {tf_label}: {data_path} not found")
            continue
        df = run_timeframe(tf_label, data_path)
        all_dfs[tf_label] = df

        # Save per-timeframe CSV
        csv_path = RESULTS_DIR / f'or_continuation_{tf_label}.csv'
        df.to_csv(csv_path, index=False)
        print(f"  Wrote {csv_path} ({len(df)} rows)")

    # Cross-timeframe comparison
    if len(all_dfs) > 1:
        print(f"\n{'=' * 70}")
        print(f"  CROSS-TIMEFRAME COMPARISON (R-to-OR >= 1.0)")
        print(f"{'=' * 70}")
        print(f"\n  {'TF':>4s} │ {'N':>5s} │ {'WR(1R)':>7s} {'PF(1R)':>7s} │ "
              f"{'OR Hit%':>7s} {'PF(OR)':>7s} {'Exp(OR)':>8s}")
        print(f"  {'─' * 58}")
        for tf_label, df in all_dfs.items():
            stats = compute_or_target_stats(df, 1.0)
            if stats is None:
                continue
            print(f"  {tf_label:>4s} │ {stats['n_trades']:5d} │ "
                  f"{stats['wr_1r']:6.1f}% {stats['pf_1r']:6.2f}x │ "
                  f"{stats['or_hit_rate']:6.1f}% {stats['pf_or']:6.2f}x "
                  f"{stats['expectancy_or']:+7.3f}R")

        # 0.5R comparison
        print(f"\n  CROSS-TIMEFRAME COMPARISON (R-to-OR >= 0.5)")
        print(f"  {'─' * 58}")
        print(f"  {'TF':>4s} │ {'N':>5s} │ {'WR(1R)':>7s} {'PF(1R)':>7s} │ "
              f"{'OR Hit%':>7s} {'PF(OR)':>7s} {'Exp(OR)':>8s}")
        print(f"  {'─' * 58}")
        for tf_label, df in all_dfs.items():
            stats = compute_or_target_stats(df, 0.5)
            if stats is None:
                continue
            print(f"  {tf_label:>4s} │ {stats['n_trades']:5d} │ "
                  f"{stats['wr_1r']:6.1f}% {stats['pf_1r']:6.2f}x │ "
                  f"{stats['or_hit_rate']:6.1f}% {stats['pf_or']:6.2f}x "
                  f"{stats['expectancy_or']:+7.3f}R")

    print("\nDone.")


if __name__ == '__main__':
    main()
