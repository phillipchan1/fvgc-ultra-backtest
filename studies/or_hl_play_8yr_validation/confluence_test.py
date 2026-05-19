#!/usr/bin/env python3
"""
Test a stupid-simple confluence model for the OR H/L play.

HARD VETOS (any one -> SKIP):
  V1. OR range > 150 pts
  V2. ifvg variant
  V3. R-to-OR > 1.5

CONFLUENCE COUNT (after passing vetos, 0-3):
  C1. Long direction       +1
  C2. OR range 30-100 pts  +1
  C3. R-to-OR 0.25-1.0     +1

TIERS:
  0-1 confluences: SKIP
  2 confluences:   TAKE at 1x size
  3 confluences:   TAKE at 1.5x size

Run: python studies/or_hl_play_8yr_validation/confluence_test.py
"""

import sys
from pathlib import Path
from datetime import date

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd

STUDY_DIR = Path(__file__).resolve().parent
RESULTS_DIR = STUDY_DIR / 'results'

IS_START = date(2023, 10, 1)
IS_END   = date(2025, 10, 31)


def load(tf: str = '1m') -> pd.DataFrame:
    df = pd.read_csv(RESULTS_DIR / f'core_play_{tf}.csv')
    df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True).dt.tz_convert('America/New_York')
    df['date'] = pd.to_datetime(df['date']).dt.date
    df['or_range'] = df['or_high'] - df['or_low']
    df['pnl_r'] = df['outcome_2r'].map({'WIN': 2.0, 'LOSS': -1.0, 'PARTIAL': 0.0})
    return df


def apply_model(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    # vetos
    df['veto_or_wide']   = df['or_range'] > 150
    df['veto_ifvg']      = df['variant'] == 'ifvg'
    df['veto_far_entry'] = df['r_to_or'] > 1.5
    df['vetoed'] = df['veto_or_wide'] | df['veto_ifvg'] | df['veto_far_entry']
    # confluence count
    df['c_long']    = (df['direction'] == 'long').astype(int)
    df['c_or_band'] = ((df['or_range'] >= 30) & (df['or_range'] <= 100)).astype(int)
    df['c_rto_sweet'] = ((df['r_to_or'] >= 0.25) & (df['r_to_or'] <= 1.0)).astype(int)
    df['conf_count'] = df['c_long'] + df['c_or_band'] + df['c_rto_sweet']
    df['tier'] = 'SKIP'
    df.loc[(~df['vetoed']) & (df['conf_count'] == 2), 'tier'] = 'TIER B (1x)'
    df.loc[(~df['vetoed']) & (df['conf_count'] == 3), 'tier'] = 'TIER A (1.5x)'
    return df


def stats(df: pd.DataFrame) -> dict:
    n = len(df)
    if n == 0:
        return {'n': 0, 'wr': float('nan'), 'pf': float('nan'), 'ev': float('nan')}
    wins   = int((df['outcome_2r'] == 'WIN').sum())
    losses = int((df['outcome_2r'] == 'LOSS').sum())
    dec = wins + losses
    wr  = wins / dec * 100 if dec else float('nan')
    pf  = (wins * 2.0 / losses) if losses else float('inf')
    ev  = df['pnl_r'].sum() / n
    return {'n': n, 'wins': wins, 'losses': losses, 'wr': wr, 'pf': pf, 'ev': ev}


def fmt(s):
    if s['n'] == 0: return "n=0"
    pf = f"{s['pf']:5.2f}" if s['pf'] != float('inf') else "  inf"
    return f"n={s['n']:3d}  W={s['wins']:3d} L={s['losses']:3d}  WR={s['wr']:5.1f}%  PF={pf}  EV={s['ev']:+.3f}R"


def report(label: str, df: pd.DataFrame):
    is_m = (df['date'] >= IS_START) & (df['date'] <= IS_END)
    is_df, oos_df = df[is_m], df[~is_m]
    print(f"\n  ── {label} ──")
    print(f"  IS   {fmt(stats(is_df))}")
    print(f"  OOS  {fmt(stats(oos_df))}")
    print(f"  ALL  {fmt(stats(df))}")


def run_one_tf(tf: str):
    df = apply_model(load(tf))
    print(f"\n\n{'#'*72}")
    print(f"  TIMEFRAME: {tf}  ({len(df)} core trades)")
    print(f"{'#'*72}")
    print(f"\n{'='*70}")
    print(f"  Confluence model validation")
    print(f"  Vetos: OR>150pt, ifvg variant, R-to-OR>1.5")
    print(f"  Conf:  long(+1), OR 30-100pt(+1), R-to-OR 0.25-1.0(+1)")
    print(f"{'='*70}")

    # Vetos
    vetoed = df[df['vetoed']]
    kept   = df[~df['vetoed']]
    print(f"\n  Veto-filtered:  {len(vetoed)} trades vetoed, {len(kept)} kept")
    print(f"  Veto reasons:   OR>150={df['veto_or_wide'].sum()}, "
          f"ifvg={df['veto_ifvg'].sum()}, R-to-OR>1.5={df['veto_far_entry'].sum()}")
    report('Vetoed trades (proof of veto value)', vetoed)
    report('Non-vetoed trades (post-veto universe)', kept)

    # Confluence tiers
    for cc in (0, 1, 2, 3):
        sub = kept[kept['conf_count'] == cc]
        report(f'Confluence count = {cc}  ({len(sub)} trades)', sub)

    # Tier groupings
    skip_set = kept[kept['conf_count'].isin([0, 1])]
    tier_b   = kept[kept['conf_count'] == 2]
    tier_a   = kept[kept['conf_count'] == 3]
    print(f"\n{'='*70}")
    print(f"  Tier summary (post-veto)")
    print(f"{'='*70}")
    report('SKIP    (conf 0-1)', skip_set)
    report('TIER B  (conf 2,   1x)', tier_b)
    report('TIER A  (conf 3,   1.5x)', tier_a)

    # Trades-per-year frequency
    n_years = 8.4
    print(f"\n  Frequency (per year, ~{n_years:.1f}yr sample):")
    print(f"    Tier B fires: {len(tier_b)/n_years:.1f}/yr")
    print(f"    Tier A fires: {len(tier_a)/n_years:.1f}/yr")

    # Combined EV at 1x base, 1.5x premium
    tb = stats(tier_b)
    ta = stats(tier_a)
    if tb['n'] and ta['n']:
        combined_r_per_yr = (tb['ev'] * len(tier_b) + 1.5 * ta['ev'] * len(tier_a)) / n_years
        print(f"\n  Combined model: {combined_r_per_yr:+.1f} R/yr  "
              f"(equivalent to ${combined_r_per_yr * 30 * 20:+,.0f}/yr at $20/pt × 30pt SL)")

    # Save annotated trades for execution lookup
    out = df[['timestamp', 'date', 'direction', 'variant', 'entry_price',
              'sl_dist', 'or_high', 'or_low', 'or_range', 'r_to_or',
              'outcome_2r', 'vetoed', 'conf_count', 'tier']].copy()
    out.to_csv(RESULTS_DIR / f'confluence_annotated_{tf}.csv', index=False)
    print(f"\n  Wrote results/confluence_annotated_{tf}.csv")


if __name__ == '__main__':
    for tf in ('1m', '30s'):
        run_one_tf(tf)
