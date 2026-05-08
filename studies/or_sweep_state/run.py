#!/usr/bin/env python3
"""
Study: OR Sweep State by 10:15 ET — base rates + FVGC outcomes by cell

Hypothesis (Phil): once one OR side is swept, the other rarely gets swept by
10:15 — so continuation FVGC trades targeting the unswept OR side may be poor.

Part A — Sweep base rates by 10:15 ET:
  Per day, classify into {neither, only_H_swept, only_L_swept, both_swept}.
  Sweep = any wick beyond the level (high > OR.H for H-sweep, low < OR.L for
  L-sweep). Strict definition (wick-through + close-back-inside) reported as
  sanity-check.

  Conditional: given side X swept first at time t, P(opposite side swept by
  10:15)? Distribution of time-to-second-sweep.

Part B — FVGC outcomes conditional on sweep state at entry:
  For every FVGC entry 9:45–10:15 (and 9:45–11:00 secondary), tag:
    sweep_state at entry: {neither, only_H_swept, only_L_swept, both_swept}
    direction: long / short
  Cells of interest (continuation = direction toward unswept OR side):
    L_swept_first → long (continuation toward OR.H)   ← Phil's failed trade
    L_swept_first → short (fade the bullish bounce)
    H_swept_first → short (continuation toward OR.L)
    H_swept_first → long (fade)
    neither_swept → long / short (baseline)

Run from repo root:
  python studies/or_sweep_state/run.py
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
from fvgc.engine import simulate_trades

STUDY_DIR = Path(__file__).resolve().parent
RESULTS_DIR = STUDY_DIR / 'results'

TIMEFRAMES = {
    '30s': ROOT / 'data' / 'consolidated' / 'nq-front-month.ohlcv-30s.csv',
    '1m':  ROOT / 'data' / 'consolidated' / 'nq-front-month.ohlcv-1m.csv',
}

OR_START = dtime(9, 30)
OR_END = dtime(9, 45)
SWEEP_WINDOW_END = dtime(10, 15)
ENTRY_AFTER = dtime(9, 45)
ENTRY_END_PRIMARY = dtime(10, 15)
ENTRY_END_SECONDARY = dtime(11, 0)


# ===================================================================
# Part A — Sweep base rates
# ===================================================================

def compute_or_and_sweeps(candles: pd.DataFrame) -> pd.DataFrame:
    """Per day: OR.H, OR.L, first-sweep times (loose + strict) by 10:15.

    Loose sweep = any wick beyond the level.
    Strict sweep = wick beyond AND candle closes back inside the OR.
    """
    candles = candles.copy()
    candles['date'] = candles['timestamp_ny'].dt.date
    candles['t'] = candles['timestamp_ny'].dt.time

    rows = []
    for date, day in candles.groupby('date'):
        or_bars = day[(day['t'] >= OR_START) & (day['t'] < OR_END)]
        if len(or_bars) == 0:
            continue
        orh = or_bars['high'].max()
        orl = or_bars['low'].min()

        post = day[(day['t'] >= OR_END) & (day['t'] < SWEEP_WINDOW_END)]
        if len(post) == 0:
            continue

        # Loose sweep: any wick beyond
        h_loose = post[post['high'] > orh]
        l_loose = post[post['low'] < orl]
        h_loose_t = h_loose['timestamp_ny'].iloc[0] if len(h_loose) else None
        l_loose_t = l_loose['timestamp_ny'].iloc[0] if len(l_loose) else None

        # Strict sweep: wick beyond AND close back inside OR
        h_strict = post[(post['high'] > orh) & (post['close'] <= orh)]
        l_strict = post[(post['low'] < orl) & (post['close'] >= orl)]
        h_strict_t = h_strict['timestamp_ny'].iloc[0] if len(h_strict) else None
        l_strict_t = l_strict['timestamp_ny'].iloc[0] if len(l_strict) else None

        rows.append({
            'date': date,
            'or_high': orh,
            'or_low': orl,
            'or_range': orh - orl,
            'h_sweep_loose': h_loose_t,
            'l_sweep_loose': l_loose_t,
            'h_sweep_strict': h_strict_t,
            'l_sweep_strict': l_strict_t,
        })
    return pd.DataFrame(rows)


def classify_sweep_state(row, mode='loose'):
    h = row[f'h_sweep_{mode}']
    l = row[f'l_sweep_{mode}']
    if pd.isna(h) and pd.isna(l):
        return 'neither'
    if pd.notna(h) and pd.isna(l):
        return 'only_H_swept'
    if pd.isna(h) and pd.notna(l):
        return 'only_L_swept'
    return 'both_swept'


def first_swept(row, mode='loose'):
    h = row[f'h_sweep_{mode}']
    l = row[f'l_sweep_{mode}']
    if pd.isna(h) and pd.isna(l):
        return None
    if pd.isna(l) or (pd.notna(h) and h < l):
        return 'H'
    return 'L'


def print_part_a(or_df: pd.DataFrame, tf_label: str):
    print(f"\n{'=' * 70}")
    print(f"  PART A — Sweep base rates by 10:15 ET ({tf_label})")
    print(f"{'=' * 70}")
    n = len(or_df)
    print(f"\n  Trading days analysed: {n}")

    for mode in ('loose', 'strict'):
        cls = or_df.apply(lambda r: classify_sweep_state(r, mode), axis=1)
        print(f"\n  --- {mode.upper()} sweep ({'any wick' if mode == 'loose' else 'wick + close back'}) ---")
        for state in ('neither', 'only_H_swept', 'only_L_swept', 'both_swept'):
            c = (cls == state).sum()
            print(f"    {state:16s}: {c:4d} ({c/n*100:5.1f}%)")

        # Conditional: given first side swept, P(other side also swept by 10:15)
        first = or_df.apply(lambda r: first_swept(r, mode), axis=1)
        for first_side in ('H', 'L'):
            mask = (first == first_side)
            sub = or_df[mask]
            if len(sub) == 0:
                continue
            both_in_sub = (cls[mask] == 'both_swept').sum()
            other = 'L' if first_side == 'H' else 'H'
            print(f"    given {first_side}-swept first (n={len(sub)}): "
                  f"P({other}-also-swept by 10:15) = {both_in_sub/len(sub)*100:5.1f}% "
                  f"({both_in_sub}/{len(sub)})")

        # Time-to-second-sweep when both happen
        both_mask = (cls == 'both_swept')
        if both_mask.sum() > 0:
            both = or_df[both_mask].copy()
            t1 = both[[f'h_sweep_{mode}', f'l_sweep_{mode}']].min(axis=1)
            t2 = both[[f'h_sweep_{mode}', f'l_sweep_{mode}']].max(axis=1)
            gap = (t2 - t1).dt.total_seconds() / 60.0
            print(f"    time-to-second-sweep when both: "
                  f"median={gap.median():.1f}min  mean={gap.mean():.1f}min  "
                  f"p25={gap.quantile(0.25):.1f}  p75={gap.quantile(0.75):.1f}")


# ===================================================================
# Part B — FVGC outcomes by sweep state × direction
# ===================================================================

def tag_trades_with_sweep_state(results: list, or_df: pd.DataFrame,
                                 mode='loose') -> pd.DataFrame:
    or_idx = or_df.set_index('date')

    rows = []
    for r in results:
        if r.get('outcome') in ('skip', '', None):
            continue
        ts = r['timestamp']
        if ts.time() < ENTRY_AFTER:
            continue
        if ts.time() >= ENTRY_END_SECONDARY:
            continue
        date = ts.date()
        if date not in or_idx.index:
            continue
        ord_row = or_idx.loc[date]
        orh = ord_row['or_high']
        orl = ord_row['or_low']

        h_swept_at = ord_row[f'h_sweep_{mode}']
        l_swept_at = ord_row[f'l_sweep_{mode}']

        h_swept_by_entry = pd.notna(h_swept_at) and h_swept_at <= ts
        l_swept_by_entry = pd.notna(l_swept_at) and l_swept_at <= ts

        if not h_swept_by_entry and not l_swept_by_entry:
            state = 'neither'
        elif h_swept_by_entry and not l_swept_by_entry:
            state = 'only_H_swept'
        elif l_swept_by_entry and not h_swept_by_entry:
            state = 'only_L_swept'
        else:
            state = 'both_swept'

        direction = r['direction']
        entry_price = r['entry_price']
        sl_dist = r.get('sl_dist', 0)
        if sl_dist <= 0:
            continue
        mfe_pts = r.get('mfe_pts', 0) or 0

        # Continuation vs fade label (relative to first-swept side)
        first = None
        if pd.notna(h_swept_at) and pd.notna(l_swept_at):
            first = 'H' if h_swept_at < l_swept_at else 'L'
        elif pd.notna(h_swept_at):
            first = 'H'
        elif pd.notna(l_swept_at):
            first = 'L'

        if first is None:
            play = 'baseline'
        elif first == 'L' and direction == 'long':
            play = 'L_swept_first→long(cont→OR.H)'
        elif first == 'L' and direction == 'short':
            play = 'L_swept_first→short(fade)'
        elif first == 'H' and direction == 'short':
            play = 'H_swept_first→short(cont→OR.L)'
        elif first == 'H' and direction == 'long':
            play = 'H_swept_first→long(fade)'
        else:
            play = 'other'

        # Distance to opposite OR (for continuation: target the un-tested side)
        if direction == 'long':
            dist_to_opposite_or = orh - entry_price
        else:
            dist_to_opposite_or = entry_price - orl
        r_to_opposite_or = dist_to_opposite_or / sl_dist if sl_dist > 0 else 0
        reached_opposite_or = (dist_to_opposite_or > 0) and (mfe_pts >= dist_to_opposite_or)

        rows.append({
            'timestamp': ts,
            'date': date,
            'time': ts.time(),
            'direction': direction,
            'variant': r.get('variant', ''),
            'entry_price': entry_price,
            'sl_dist': sl_dist,
            'outcome': r['outcome'],
            'pnl': r.get('pnl', 0),
            'mfe_pts': mfe_pts,
            'mae_pts': r.get('mae_pts', 0) or 0,
            'mfe_r': r.get('mfe_r', 0) or 0,
            'or_high': orh,
            'or_low': orl,
            'or_range': ord_row['or_range'],
            'sweep_state': state,
            'first_swept_side': first,
            'play': play,
            'r_to_opposite_or': round(r_to_opposite_or, 2),
            'reached_opposite_or': reached_opposite_or,
            'before_1015': ts.time() < ENTRY_END_PRIMARY,
        })

    return pd.DataFrame(rows)


def cell_stats(sub: pd.DataFrame) -> dict:
    if len(sub) == 0:
        return None
    wins = (sub['outcome'] == 'win').sum()
    losses = (sub['outcome'] == 'loss').sum()
    eod = (sub['outcome'] == 'eod').sum()
    decided = wins + losses
    wr = wins / decided * 100 if decided > 0 else 0.0
    pnl_series = sub.loc[sub['pnl'].apply(lambda x: x != ''), 'pnl'].astype(float)
    gross_win = sub.loc[sub['outcome'] == 'win', 'pnl'].astype(float).sum()
    gross_loss = abs(sub.loc[sub['outcome'] == 'loss', 'pnl'].astype(float).sum())
    pf = gross_win / gross_loss if gross_loss > 0 else float('inf')

    # Continuation-target (opposite OR) hit rate
    cont_mask = sub['r_to_opposite_or'] > 0
    if cont_mask.sum() > 0:
        op_hit = sub.loc[cont_mask, 'reached_opposite_or'].sum()
        op_hit_rate = op_hit / cont_mask.sum() * 100
        op_n = int(cont_mask.sum())
    else:
        op_hit_rate = 0.0
        op_n = 0

    return {
        'n': len(sub),
        'wins': int(wins),
        'losses': int(losses),
        'eod': int(eod),
        'wr': wr,
        'pf': pf,
        'pnl_sum': pnl_series.sum() if len(pnl_series) else 0.0,
        'mean_mfe_r': sub['mfe_r'].mean(),
        'op_n': op_n,
        'op_hit_rate': op_hit_rate,
    }


def print_cell_table(df: pd.DataFrame, label: str):
    print(f"\n  --- {label} ---")
    print(f"  {'cell':40s} {'n':>4s} {'W':>4s} {'L':>4s} {'WR%':>6s} {'PF':>6s} "
          f"{'mfeR':>6s} {'opN':>4s} {'opHit%':>7s}")
    plays = [
        'L_swept_first→long(cont→OR.H)',
        'L_swept_first→short(fade)',
        'H_swept_first→short(cont→OR.L)',
        'H_swept_first→long(fade)',
        'baseline',
    ]
    for play in plays:
        sub = df[df['play'] == play]
        s = cell_stats(sub)
        if s is None:
            print(f"  {play:40s} {'0':>4s} {'—':>4s} {'—':>4s} {'—':>6s} {'—':>6s} "
                  f"{'—':>6s} {'—':>4s} {'—':>7s}")
            continue
        pf_str = f"{s['pf']:5.2f}x" if s['pf'] != float('inf') else '   inf'
        print(f"  {play:40s} {s['n']:>4d} {s['wins']:>4d} {s['losses']:>4d} "
              f"{s['wr']:5.1f}% {pf_str:>6s} {s['mean_mfe_r']:>5.2f} "
              f"{s['op_n']:>4d} {s['op_hit_rate']:>6.1f}%")

    # Direction within baseline (sanity)
    base = df[df['play'] == 'baseline']
    if len(base) > 0:
        for d in ('long', 'short'):
            sub = base[base['direction'] == d]
            s = cell_stats(sub)
            if s is None:
                continue
            pf_str = f"{s['pf']:5.2f}x" if s['pf'] != float('inf') else '   inf'
            print(f"  {f'baseline·{d}':40s} {s['n']:>4d} {s['wins']:>4d} {s['losses']:>4d} "
                  f"{s['wr']:5.1f}% {pf_str:>6s} {s['mean_mfe_r']:>5.2f} "
                  f"{s['op_n']:>4d} {s['op_hit_rate']:>6.1f}%")


def print_part_b(df: pd.DataFrame, tf_label: str, mode: str):
    print(f"\n{'=' * 70}")
    print(f"  PART B — FVGC by sweep state × direction ({tf_label}, {mode} sweep)")
    print(f"{'=' * 70}")
    print(f"\n  Total post-9:45 entries (≤11:00): {len(df)}")
    if len(df) == 0:
        return
    print(f"  Of which entered before 10:15: {df['before_1015'].sum()}")

    # Sweep state composition at entry
    print(f"\n  --- Sweep state at entry (full window) ---")
    for state in ('neither', 'only_H_swept', 'only_L_swept', 'both_swept'):
        c = (df['sweep_state'] == state).sum()
        print(f"    {state:16s}: {c:4d}")

    print_cell_table(df[df['before_1015']],
                     f'Entries 9:45–10:15  (primary)')
    print_cell_table(df, f'Entries 9:45–11:00  (extended)')


# ===================================================================
# Pipeline
# ===================================================================

def run_timeframe(tf_label: str, data_path: Path):
    print(f"\n{'#' * 70}")
    print(f"  TIMEFRAME: {tf_label}")
    print(f"{'#' * 70}")

    candles = load_candles(data_path)
    print(f"  Data: {candles['timestamp_ny'].min()} → {candles['timestamp_ny'].max()}  "
          f"({len(candles):,} bars)")

    or_df = compute_or_and_sweeps(candles)
    print(f"  OR + sweep computed for {len(or_df)} days")

    print_part_a(or_df, tf_label)

    print("\n  Generating FVGC signals + simulating trades ...")
    signals, _fvgs = generate_signals(candles)
    print(f"  {len(signals)} signals")
    results = simulate_trades(signals, candles)

    for mode in ('loose', 'strict'):
        df = tag_trades_with_sweep_state(results, or_df, mode=mode)
        print_part_b(df, tf_label, mode)

        csv_path = RESULTS_DIR / f'or_sweep_state_{tf_label}_{mode}.csv'
        df.to_csv(csv_path, index=False)
        print(f"\n  Wrote {csv_path} ({len(df)} rows)")

    # Save Part A days table once per TF
    or_path = RESULTS_DIR / f'or_sweep_days_{tf_label}.csv'
    or_df.to_csv(or_path, index=False)
    print(f"  Wrote {or_path} ({len(or_df)} days)")


def main():
    print("=" * 70)
    print("FVGC — OR Sweep State Study")
    print("Sweep window 9:45–10:15 ET; entries tagged by sweep state at entry")
    print("=" * 70)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    for tf_label, data_path in TIMEFRAMES.items():
        if not data_path.exists():
            print(f"\n  Skipping {tf_label}: {data_path} missing")
            continue
        run_timeframe(tf_label, data_path)

    print("\nDone.")


if __name__ == '__main__':
    main()
