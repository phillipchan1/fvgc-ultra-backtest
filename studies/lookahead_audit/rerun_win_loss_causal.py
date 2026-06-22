"""Pass-2 causal re-run of the win/loss discriminator OOS survivors.

The win/loss study (claude/elegant-heyrovsky-2f8815) joined trading_days.csv
on date in loader.py:84. Three of its OOS survivors reference `or_45min_range`,
which is only observable at 10:15. The study's tradeable pool (1572 trades)
fires 99% pre-10:15, so the filter is structurally lookahead for almost every
trade it was applied to.

This script reproduces the OOS WR/PF/lift under strict causal masking, and
prints the impact on the headline numbers.
"""
from __future__ import annotations

from pathlib import Path
import sys

import polars as pl

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.causal_features import load_causal_features  # noqa: E402

LEVELS = ROOT / 'data' / 'levels' / 'trades_with_levels.csv'
CUTOFF = '2025-05-14'  # IS/OOS split from loader.split_is_oos(frac_is=0.70)


def _load_trades() -> pl.DataFrame:
    """Recreate the win/loss tradeable frame using polars + causal features."""
    df = pl.read_csv(LEVELS, try_parse_dates=True)
    df = df.filter(pl.col('outcome').is_in(['win', 'loss']))
    df = df.with_columns([
        (pl.col('outcome') == 'win').cast(pl.Int8).alias('win'),
        pl.col('pnl').cast(pl.Float64, strict=False).alias('pnl'),
    ])
    # Join causal trading_days features (gated where appropriate).
    df = load_causal_features(df, include=[
        'or_45min_range', 'candle_930_range', 'prior_day_close_position',
        'is_fomc_week',
    ])
    return df


def _wr_pf(df: pl.DataFrame) -> dict:
    if df.is_empty():
        return {'n': 0, 'wr': float('nan'), 'pf': float('nan')}
    wins = df.filter(pl.col('win') == 1)
    losses = df.filter(pl.col('win') == 0)
    sum_w = float(wins['pnl'].sum() or 0.0)
    sum_l = abs(float(losses['pnl'].sum() or 0.0))
    pf = (sum_w / sum_l) if sum_l > 0 else float('inf')
    return {
        'n': len(df),
        'wr': float(df['win'].mean()),
        'pf': pf,
    }


def evaluate_rule(name: str, oos: pl.DataFrame, mask: pl.Expr,
                  base_wr: float) -> dict:
    """Evaluate one filter rule on the OOS slice."""
    filtered = oos.filter(mask)
    # Pool stats: rows where mask is determinable (not null) and True.
    # Under causal masking, rows where the feature is NaN cannot fire the
    # filter at all — they're effectively skipped (filter returns False).
    s = _wr_pf(filtered)
    s['lift'] = (s['wr'] - base_wr) if s['n'] > 0 else float('nan')
    return {'rule': name, **s}


def main() -> None:
    df = _load_trades()
    oos = df.filter(pl.col('date') >= pl.lit(CUTOFF).str.to_date())
    base = _wr_pf(oos)
    print(f"OOS pool: n={base['n']}, baseline WR={base['wr']:.3f}, PF={base['pf']:.2f}")
    print(f"OOS cutoff: {CUTOFF}\n")

    # Diagnostics: how many OOS trades fire when each gated feature is required?
    mod_check = oos.with_columns(
        (pl.col('timestamp').dt.hour() * 60 + pl.col('timestamp').dt.minute())
        .alias('mod')
    )
    post_1015 = mod_check.filter(pl.col('mod') >= 615).height
    print(f"OOS trades with or_45min_range CAUSALLY KNOWN (mod>=615): {post_1015}")
    print(f"OOS trades with or_45min_range UNKNOWN at trade time   : {base['n'] - post_1015}\n")

    print("=== Original (lookahead) headline survivors ===")
    print("  or_45min_range_ge_q50 (>=138): WR 61.1%, PF 1.57, n=221, lift +7.7pp")
    print("  or_45min_range_le_q20 (<=93) : WR 40.7%, PF 0.75, n=59,  lift -12.7pp")
    print("  pd_close_pos<=0.3832 AND or_45min_range>=110.8: WR 64.8%, PF 1.81, n=105, lift +11.4pp\n")

    print("=== Causal OOS evaluation (or_45min_range NaN for mod<615) ===")
    rules = [
        ('or_45min_range >= 138 (causal)', pl.col('or_45min_range') >= 138),
        ('or_45min_range <= 93  (causal)', pl.col('or_45min_range') <= 93),
        ('pd_close_pos<=0.3832 AND or_45min_range>=110.8 (causal)',
         (pl.col('prior_day_close_position') <= 0.3832)
         & (pl.col('or_45min_range') >= 110.8)),
        # Sanity: a fully safe rule should be unchanged.
        ('is_fomc_week == True (safe)', pl.col('is_fomc_week') == True),  # noqa: E712
    ]
    results = []
    for name, expr in rules:
        r = evaluate_rule(name, oos, expr, base['wr'])
        results.append(r)
        n, wr, pf, lift = r['n'], r['wr'], r['pf'], r['lift']
        if n == 0:
            print(f"  {name:<60s}  n=0 (no trades fire causally)")
        else:
            print(f"  {name:<60s}  n={n:>4d}  WR={wr*100:5.1f}%  PF={pf:5.2f}  lift={lift*100:+6.2f}pp")

    # Write CSV for results bundle.
    out_path = ROOT / 'studies' / 'lookahead_audit' / 'results' / 'rerun_win_loss_causal.csv'
    out_path.parent.mkdir(exist_ok=True)
    pl.DataFrame(results).write_csv(out_path)
    print(f"\nWrote {out_path.relative_to(ROOT)}")


if __name__ == '__main__':
    main()
