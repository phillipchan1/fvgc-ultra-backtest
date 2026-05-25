#!/usr/bin/env python3
"""
Study: Daily Markov-Regime Conditioning of FVGC Trades

Motivation
----------
The "hedge fund method" (a YouTube framing of Markov regime-switching) proposes
a daily bull/sideways/bear state from a trailing N-day return, claims the state
is "sticky", and trades the bull-minus-bear differential. That signal lives on a
DAILY timescale and cannot generate intraday entries — our edge is FVG
continuation in the 9:30–10:15 ET window on 30s bars.

The only defensible application is to use the daily regime as a PRE-MARKET BIAS
GATE on top of the existing FVGC baseline: known before the 9:30 open, it can
tell us which days / directions to take or size up. This study tests, on our own
trades, whether that conditioning carries real information or is noise.

Two caveats this study is built to expose:
  1. Mechanical stickiness. The trailing-N-day state is autocorrelated by
     construction (consecutive windows overlap N-1 days), so "persistence" alone
     proves nothing. We therefore test the trades, not the matrix.
  2. Look-ahead. The regime for trading day D uses only closes through D-1, so it
     is genuinely knowable at the open.

What it computes
----------------
  - Daily close-to-close series (RTH close anchor) from the candle data.
  - Regime label per trading day D from the trailing-N-day return as of D-1.
  - Tags every baseline FVGC trade with its day's regime.
  - Conditional expectancy table: regime x direction (win rate, expectancy in R,
    profit factor) vs the unconditional baseline.
  - Alignment test: "with regime" (long-in-bull + short-in-bear) vs
    "against regime", with a day-level permutation test for significance —
    this is the correlation-vs-noise check.
  - Sensitivity grid over (lookback, threshold) so the result doesn't hinge on
    the video's arbitrary 20-day / 5% choice.

Run from repo root:
  python studies/markov_regime/run.py
  python studies/markov_regime/run.py --lookback 20 --threshold 0.05 --perms 5000
"""

import sys
import argparse
from pathlib import Path
from datetime import time as dtime

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from fvgc.data import load_candles
from fvgc.model import generate_signals
from fvgc.engine import simulate_trades

STUDY_DIR = Path(__file__).resolve().parent
RESULTS_DIR = STUDY_DIR / 'results'
DATA_PATH = ROOT / 'data' / 'consolidated' / 'nq-front-month.ohlcv-30s.csv'

RTH_CLOSE = dtime(16, 0)          # daily-close anchor (last bar at/<= 16:00 ET)
DECIDED = ('win', 'loss', 'eod', 'ambiguous')
REGIMES = ('bull', 'sideways', 'bear')

# Sensitivity grid — probes robustness of the (arbitrary) regime definition.
LOOKBACKS = (10, 20, 40)
THRESHOLDS = (0.03, 0.05, 0.08)


# ===================================================================
# Regime construction (pure functions — unit-testable without market data)
# ===================================================================

def compute_daily_close(candles: pd.DataFrame, anchor: dtime = RTH_CLOSE) -> pd.Series:
    """Daily close series anchored at the last bar at/before `anchor` (16:00 ET).

    Returns a Series of close prices indexed by date, sorted ascending.
    """
    df = candles[['timestamp_ny', 'close']].copy()
    df['date'] = df['timestamp_ny'].dt.date
    df['time'] = df['timestamp_ny'].dt.time
    rth = df[df['time'] <= anchor]
    # last bar at/before the anchor on each date
    daily = rth.groupby('date')['close'].last()
    return daily.sort_index()


def _bucket(ret: float, threshold: float) -> str:
    if ret >= threshold:
        return 'bull'
    if ret <= -threshold:
        return 'bear'
    return 'sideways'


def compute_regimes(daily_close: pd.Series, lookback: int, threshold: float) -> dict:
    """Map each trading day D -> regime label, using ONLY closes through D-1.

    The trailing-N-day return is measured as of the close of day i
    (close[i]/close[i-lookback] - 1) and assigned as the regime for the NEXT
    trading day i+1. This guarantees the label is known before D's 9:30 open.
    """
    closes = daily_close.values
    dates = list(daily_close.index)
    regimes: dict = {}
    for i in range(lookback, len(closes) - 1):
        ret = closes[i] / closes[i - lookback] - 1.0
        regimes[dates[i + 1]] = _bucket(ret, threshold)
    return regimes


def tag_trades(results: list, regimes: dict) -> pd.DataFrame:
    """Flatten simulated trades into a frame with a per-day regime label."""
    rows = []
    for r in results:
        if r.get('outcome') not in DECIDED:
            continue
        sl_dist = r.get('sl_dist', 0) or 0
        pnl = r.get('pnl', '')
        if sl_dist <= 0 or pnl == '' or pnl is None:
            continue
        d = r['timestamp'].date()
        rows.append({
            'date': d,
            'direction': r['direction'],
            'variant': r.get('variant', ''),
            'outcome': r['outcome'],
            'pnl': float(pnl),
            'sl_dist': float(sl_dist),
            'r_realized': float(pnl) / float(sl_dist),
            'regime': regimes.get(d, 'unknown'),
        })
    return pd.DataFrame(rows)


# ===================================================================
# Conditional statistics
# ===================================================================

def cell_stats(df: pd.DataFrame) -> dict:
    """Win rate, expectancy (R), profit factor and counts for a trade subset."""
    n = len(df)
    if n == 0:
        return {'n': 0, 'win_rate': None, 'exp_r': None, 'pf': None,
                'wins': 0, 'losses': 0}
    wins = int((df['outcome'] == 'win').sum())
    losses = int((df['outcome'] == 'loss').sum())
    decided = wins + losses
    win_rate = wins / decided * 100 if decided else None
    exp_r = df['r_realized'].mean()
    gross_win = df.loc[df['pnl'] > 0, 'pnl'].sum()
    gross_loss = abs(df.loc[df['pnl'] < 0, 'pnl'].sum())
    pf = (gross_win / gross_loss) if gross_loss > 0 else float('inf')
    return {'n': n, 'win_rate': win_rate, 'exp_r': exp_r, 'pf': pf,
            'wins': wins, 'losses': losses}


def conditional_table(df: pd.DataFrame) -> pd.DataFrame:
    """regime x direction (+ALL / both-directions) expectancy grid."""
    rows = []
    for regime in REGIMES + ('unknown',):
        sub_r = df[df['regime'] == regime]
        if len(sub_r) == 0:
            continue
        for direction in ('long', 'short', 'both'):
            sub = sub_r if direction == 'both' else sub_r[sub_r['direction'] == direction]
            s = cell_stats(sub)
            if s['n'] == 0:
                continue
            rows.append({'regime': regime, 'direction': direction, **s})
    return pd.DataFrame(rows)


def alignment_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Tag each trade as with / against / neutral relative to the regime."""
    df = df.copy()

    def _align(row):
        reg, dr = row['regime'], row['direction']
        if reg == 'bull':
            return 'with' if dr == 'long' else 'against'
        if reg == 'bear':
            return 'with' if dr == 'short' else 'against'
        if reg == 'sideways':
            return 'neutral'
        return 'unknown'

    df['alignment'] = df.apply(_align, axis=1)
    return df


# ===================================================================
# Day-level permutation test (correlation vs. noise)
# ===================================================================

def _gap_from_regimes(trade_regime: np.ndarray, direction: np.ndarray,
                      r_realized: np.ndarray) -> float:
    """with-regime minus against-regime mean realized R.

    with    = (bull & long) | (bear & short)
    against = (bull & short) | (bear & long)
    """
    is_long = direction == 'long'
    is_bull = trade_regime == 'bull'
    is_bear = trade_regime == 'bear'
    with_mask = (is_bull & is_long) | (is_bear & ~is_long)
    against_mask = (is_bull & ~is_long) | (is_bear & is_long)
    if with_mask.sum() == 0 or against_mask.sum() == 0:
        return np.nan
    return r_realized[with_mask].mean() - r_realized[against_mask].mean()


def permutation_test(df: pd.DataFrame, n_perms: int, seed: int = 42) -> dict:
    """Shuffle regime labels at the DAY level and rebuild the with-against gap.

    Day-level (not per-trade) shuffling preserves intraday clustering — trades
    on the same day share a regime — so the null variance isn't understated.
    """
    work = df[df['regime'].isin(('bull', 'bear', 'sideways'))].copy()
    if len(work) == 0:
        return {'observed_gap': None, 'p_value': None, 'n': 0}

    direction = work['direction'].values
    r_realized = work['r_realized'].values
    dates = work['date'].values

    # day -> regime map, and the per-trade index into the unique-day array
    uniq_dates, inv = np.unique(dates, return_inverse=True)
    day_regime = (work.groupby('date')['regime'].first()
                  .reindex(uniq_dates).values)

    observed = _gap_from_regimes(day_regime[inv], direction, r_realized)

    rng = np.random.default_rng(seed)
    ge = 0
    valid = 0
    for _ in range(n_perms):
        shuffled = rng.permutation(day_regime)
        g = _gap_from_regimes(shuffled[inv], direction, r_realized)
        if np.isnan(g):
            continue
        valid += 1
        if g >= observed:
            ge += 1
    p_value = ge / valid if valid else None
    return {'observed_gap': observed, 'p_value': p_value, 'n': len(work),
            'n_perms_valid': valid}


# ===================================================================
# Reporting
# ===================================================================

def _fmt(v, spec):
    return format(v, spec) if v is not None and not (isinstance(v, float) and np.isnan(v)) else '—'


def print_conditional(df: pd.DataFrame, table: pd.DataFrame, lookback: int, threshold: float):
    base = cell_stats(df)
    base_long = cell_stats(df[df['direction'] == 'long'])
    base_short = cell_stats(df[df['direction'] == 'short'])

    print(f"\n{'=' * 72}")
    print(f"  MARKOV-REGIME CONDITIONING  (lookback={lookback}d, threshold=±{threshold:.0%})")
    print(f"{'=' * 72}")
    print(f"\n  Unconditional baseline: n={base['n']}  "
          f"WR={_fmt(base['win_rate'], '.1f')}%  "
          f"Exp={_fmt(base['exp_r'], '+.3f')}R  PF={_fmt(base['pf'], '.2f')}")
    print(f"    long : n={base_long['n']}  WR={_fmt(base_long['win_rate'], '.1f')}%  "
          f"Exp={_fmt(base_long['exp_r'], '+.3f')}R")
    print(f"    short: n={base_short['n']}  WR={_fmt(base_short['win_rate'], '.1f')}%  "
          f"Exp={_fmt(base_short['exp_r'], '+.3f')}R")

    print(f"\n  {'regime':>9s} {'dir':>6s} │ {'N':>5s} {'WR':>6s} {'Exp(R)':>8s} {'PF':>6s}")
    print(f"  {'─' * 52}")
    for _, row in table.iterrows():
        print(f"  {row['regime']:>9s} {row['direction']:>6s} │ {row['n']:>5d} "
              f"{_fmt(row['win_rate'], '5.1f')}% {_fmt(row['exp_r'], '+8.3f')} "
              f"{_fmt(row['pf'], '6.2f')}")
    print(f"  {'─' * 52}")


def print_alignment(adf: pd.DataFrame):
    print(f"\n  --- Alignment to regime ---")
    print(f"  {'group':>9s} │ {'N':>5s} {'WR':>6s} {'Exp(R)':>8s} {'PF':>6s}")
    print(f"  {'─' * 44}")
    for g in ('with', 'against', 'neutral'):
        s = cell_stats(adf[adf['alignment'] == g])
        if s['n'] == 0:
            continue
        print(f"  {g:>9s} │ {s['n']:>5d} {_fmt(s['win_rate'], '5.1f')}% "
              f"{_fmt(s['exp_r'], '+8.3f')} {_fmt(s['pf'], '6.2f')}")
    print(f"  {'─' * 44}")


def print_permutation(res: dict):
    print(f"\n  --- Day-level permutation test (with − against, Exp R) ---")
    if res['observed_gap'] is None:
        print("  insufficient data")
        return
    p = res['p_value']
    sig = ' **' if (p is not None and p < 0.01) else (' *' if (p is not None and p < 0.05) else '')
    print(f"  observed gap = {res['observed_gap']:+.4f}R   "
          f"p = {_fmt(p, '.4f')}{sig}   (n={res['n']}, perms={res.get('n_perms_valid')})")
    print("  p is the fraction of day-shuffled nulls with gap >= observed.")
    print("  Small p ⇒ the with/against split is unlikely under no-regime-info.")


def print_sensitivity(df_results: list, daily_close: pd.Series, perms: int):
    """Gap + permutation p across the (lookback, threshold) grid."""
    print(f"\n{'=' * 72}")
    print(f"  SENSITIVITY GRID — robustness of the regime definition")
    print(f"{'=' * 72}")
    print(f"  Reports with−against Exp(R) gap and permutation p for each combo.")
    print(f"\n  {'lookback':>8s} {'thresh':>7s} │ {'N':>5s} {'gap(R)':>8s} {'p':>7s}")
    print(f"  {'─' * 46}")
    for lookback in LOOKBACKS:
        for threshold in THRESHOLDS:
            regimes = compute_regimes(daily_close, lookback, threshold)
            tagged = tag_trades(df_results, regimes)
            res = permutation_test(tagged, perms)
            gap = res['observed_gap']
            p = res['p_value']
            sig = ' **' if (p is not None and p < 0.01) else (' *' if (p is not None and p < 0.05) else '')
            print(f"  {lookback:>8d} {threshold:>6.0%} │ {res['n']:>5d} "
                  f"{_fmt(gap, '+8.4f')} {_fmt(p, '7.4f')}{sig}")
    print(f"  {'─' * 46}")


# ===================================================================
# Main
# ===================================================================

def main():
    ap = argparse.ArgumentParser(description='Markov-regime conditioning of FVGC trades')
    ap.add_argument('--lookback', type=int, default=20, help='trailing days for regime (default 20)')
    ap.add_argument('--threshold', type=float, default=0.05, help='bull/bear cutoff (default 0.05 = 5%%)')
    ap.add_argument('--perms', type=int, default=5000, help='permutations for the significance test')
    ap.add_argument('--data', type=Path, default=DATA_PATH)
    ap.add_argument('--no-sensitivity', action='store_true', help='skip the (lookback,threshold) grid')
    args = ap.parse_args()

    print("=" * 72)
    print("FVGC — Daily Markov-Regime Conditioning Study")
    print("Regime is a PRE-MARKET BIAS GATE (known at the open), not a signal.")
    print("=" * 72)

    candles = load_candles(args.data)
    print(f"  bars: {len(candles):,}  "
          f"range: {candles['timestamp_ny'].min()} → {candles['timestamp_ny'].max()}")

    daily_close = compute_daily_close(candles)
    print(f"  daily closes: {len(daily_close)}")

    print("  detecting FVGs / entries ...")
    signals, _fvgs = generate_signals(candles)
    print(f"  {len(signals)} signals; simulating ...")
    results = simulate_trades(signals, candles)

    regimes = compute_regimes(daily_close, args.lookback, args.threshold)
    df = tag_trades(results, regimes)
    print(f"  tradeable trades tagged: {len(df)} "
          f"(unknown-regime: {(df['regime'] == 'unknown').sum()})")

    table = conditional_table(df)
    print_conditional(df, table, args.lookback, args.threshold)

    adf = alignment_frame(df)
    print_alignment(adf)

    perm = permutation_test(df, args.perms)
    print_permutation(perm)

    if not args.no_sensitivity:
        print_sensitivity(results, daily_close, args.perms)

    # --- Persist ---
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    adf.to_csv(RESULTS_DIR / 'trades_tagged.csv', index=False)
    table.to_csv(RESULTS_DIR / 'conditional_table.csv', index=False)
    pd.DataFrame([{
        'lookback': args.lookback, 'threshold': args.threshold,
        'observed_gap_R': perm['observed_gap'], 'p_value': perm['p_value'],
        'n_trades': perm['n'],
    }]).to_csv(RESULTS_DIR / 'permutation_summary.csv', index=False)
    print(f"\n  wrote {RESULTS_DIR}/ (trades_tagged, conditional_table, permutation_summary)")
    print("\nDone.")


if __name__ == '__main__':
    main()
