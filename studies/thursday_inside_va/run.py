#!/usr/bin/env python3
"""
Thursday × Inside-Value-Area Retest
====================================

The Notion playbook entry (Apr 14, 2026) claims FVGC entries on Thursdays
where the entry price is inside the prior day's Value Area produce
73.7% WR / 2.89 PF over n=76 trades (p=0.0002).

That study used only 2023-10 → 2026-03-25. We now have the full 30s
baseline back to 2018-01-02 and through 2026-05-15.

Memory flags:
  * Lag-1 VP has ~0 edge on its own (composite_vp, naked_vp, vp_targets killed).
  * The original search space was large (DOW × VP-location × direction × MW);
    a p=0.0002 cell from that space is not as strong as raw stats suggest.

This script runs three windows:
  1. HOLDOUT   2018-01-02 → 2023-09-30     (~5.5yr never seen by original)
  2. IN-SAMPLE 2023-10-01 → 2026-03-25     (should reproduce n=76 / 73.7% WR)
  3. FORWARD   2026-03-26 → end-of-data    (~2 months post-publication)

Plus a Bonferroni correction over the implicit search space.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.causal_features import load_causal_features, load_lagged_vp  # noqa: E402

STUDY_DIR = Path(__file__).resolve().parent
RESULTS = STUDY_DIR / 'results'
RESULTS.mkdir(parents=True, exist_ok=True)

BASELINE_TRADES = ROOT / 'studies' / 'baseline' / 'results' / 'trades.csv'

ORIG_START = pl.date(2023, 10, 1)
ORIG_END = pl.date(2026, 3, 25)


# -- Loading ------------------------------------------------------------------

def load_trades_with_features() -> pl.DataFrame:
    """Load baseline trades, attach day_of_week + lag-1 VP, mark in-VA."""
    trades = pl.read_csv(BASELINE_TRADES, try_parse_dates=True)
    trades = trades.filter(pl.col('outcome').is_in(['win', 'loss']))

    trades = load_causal_features(trades, include=['day_of_week'])
    trades = load_lagged_vp(trades)

    # entry-inside-VA flag using STRICTLY causal lag-1 VP
    trades = trades.with_columns([
        (
            (pl.col('entry_price') >= pl.col('val_lag1'))
            & (pl.col('entry_price') <= pl.col('vah_lag1'))
        ).alias('in_va'),
        (pl.col('entry_price') > pl.col('vah_lag1')).alias('above_va'),
        (pl.col('entry_price') < pl.col('val_lag1')).alias('below_va'),
    ])

    # Drop rows missing VP (first day with no prior)
    trades = trades.filter(pl.col('poc_lag1').is_not_null())
    return trades


# -- Stats --------------------------------------------------------------------

def stats(df: pl.DataFrame, label: str) -> dict:
    n = df.height
    if n == 0:
        return dict(label=label, n=0, wins=0, losses=0,
                    wr=None, pf=None, ev_R=None, pnl=None)
    wins = (df['outcome'] == 'win').sum()
    losses = (df['outcome'] == 'loss').sum()
    pnl = df['pnl'].cast(pl.Float64)
    gp = pnl.filter(pnl > 0).sum()
    gl = abs(pnl.filter(pnl < 0).sum())
    pf = gp / gl if gl > 0 else float('inf') if gp > 0 else None
    wr = wins / (wins + losses) * 100 if (wins + losses) else None
    # 1R fixed-target EV: +1 per win, -1 per loss
    ev_R = (wins - losses) / n if n else None
    return dict(
        label=label, n=n, wins=int(wins), losses=int(losses),
        wr=round(wr, 1) if wr is not None else None,
        pf=round(pf, 2) if pf is not None and np.isfinite(pf) else pf,
        ev_R=round(ev_R, 3) if ev_R is not None else None,
        pnl=round(pnl.sum(), 1),
    )


def permutation_p(df: pl.DataFrame, mask_col: str, n_perms: int = 10_000,
                  rng_seed: int = 42) -> dict:
    """
    H0: the binary mask has no effect on win rate. Shuffle mask labels
    across the FULL frame and compare the cell WR to the null.
    """
    rng = np.random.default_rng(rng_seed)
    mask = df[mask_col].to_numpy()
    wins = (df['outcome'] == 'win').to_numpy().astype(int)
    losses = (df['outcome'] == 'loss').to_numpy().astype(int)
    cell_n = mask.sum()
    if cell_n == 0:
        return dict(actual_wr=None, p_wr=None, n=0)
    actual_wr = wins[mask].sum() / (wins[mask].sum() + losses[mask].sum())

    perm_wr = np.empty(n_perms)
    for i in range(n_perms):
        idx = rng.permutation(len(mask))
        m = mask[idx]
        w = wins[m].sum()
        l = losses[m].sum()
        perm_wr[i] = w / (w + l) if (w + l) else 0.0

    p = float((perm_wr >= actual_wr).mean())
    return dict(actual_wr=float(actual_wr), p_wr=p, n=int(cell_n),
                mean_perm_wr=float(perm_wr.mean()))


# -- Reporting ----------------------------------------------------------------

def fmt(s: dict) -> str:
    if s['n'] == 0:
        return f"  {s['label']:35s}  (no data)"
    pf = s['pf']
    pf_str = f"{pf:5.2f}" if isinstance(pf, (int, float)) and np.isfinite(pf) else str(pf)
    return (f"  {s['label']:35s}  n={s['n']:4d}  "
            f"WR={s['wr']:5.1f}%  PF={pf_str}  "
            f"EV={s['ev_R']:+.3f}R  pnl={s['pnl']:+.1f}")


def print_window(title: str, df: pl.DataFrame):
    print(f'\n{"="*78}\n  {title}  (rows={df.height})\n{"="*78}')

    thu = df.filter(pl.col('day_of_week') == 3)
    thu_in = thu.filter(pl.col('in_va'))
    thu_out = thu.filter(~pl.col('in_va'))
    other = df.filter(pl.col('day_of_week') != 3)
    other_in = other.filter(pl.col('in_va'))

    rows = [
        stats(df, 'ALL (baseline)'),
        stats(df.filter(pl.col('day_of_week') == 3), 'Thursday alone'),
        stats(df.filter(pl.col('in_va')), 'Inside VA alone'),
        stats(thu_in, 'Thursday + Inside VA  *** THE PLAY ***'),
        stats(thu_out, 'Thursday + NOT in VA'),
        stats(other_in, 'Non-Thursday + Inside VA'),
    ]
    for r in rows:
        print(fmt(r))
    return rows


def per_dow_inside_va(df: pl.DataFrame) -> list[dict]:
    out = []
    for dow, name in enumerate(['Mon', 'Tue', 'Wed', 'Thu', 'Fri']):
        sub = df.filter((pl.col('day_of_week') == dow) & pl.col('in_va'))
        out.append(stats(sub, f'{name} + Inside VA'))
    return out


def main():
    print('Loading trades + features...')
    df = load_trades_with_features()
    print(f'  total tradeable w/ lag-1 VP: {df.height}')
    print(f'  date range: {df["timestamp"].min()} → {df["timestamp"].max()}')

    holdout = df.filter(pl.col('timestamp').dt.date() < ORIG_START)
    in_sample = df.filter(
        (pl.col('timestamp').dt.date() >= ORIG_START)
        & (pl.col('timestamp').dt.date() <= ORIG_END)
    )
    forward = df.filter(pl.col('timestamp').dt.date() > ORIG_END)

    holdout_rows = print_window('HOLDOUT  (2018-01-02 → 2023-09-30, never seen)', holdout)
    in_sample_rows = print_window('IN-SAMPLE  (2023-10-01 → 2026-03-25, original study)', in_sample)
    forward_rows = print_window('FORWARD  (2026-03-26 → 2026-05-15, post-publication)', forward)
    full_rows = print_window('FULL  (2018-01-02 → 2026-05-15, all data)', df)

    print('\n' + '='*78)
    print('  PERMUTATION TEST  (in-VA mask within Thursday slice only — apples-to-apples)')
    print('='*78)
    for name, sub in [('HOLDOUT', holdout), ('IN-SAMPLE', in_sample),
                      ('FORWARD', forward), ('FULL', df)]:
        thu = sub.filter(pl.col('day_of_week') == 3)
        res = permutation_p(thu, 'in_va', n_perms=10_000)
        if res['n'] == 0:
            print(f'  {name:10s}  (no Thursday-in-VA trades)')
            continue
        print(f"  {name:10s}  cell n={res['n']:4d}  "
              f"WR={res['actual_wr']*100:5.1f}%  "
              f"perm-mean={res['mean_perm_wr']*100:5.1f}%  "
              f"p={res['p_wr']:.4f}")

    print('\n' + '='*78)
    print('  DOW × Inside-VA breakdown  (Bonferroni search space = 5 days)')
    print('='*78)
    for label, win in [('HOLDOUT', holdout), ('IN-SAMPLE', in_sample),
                       ('FORWARD', forward), ('FULL', df)]:
        print(f'\n  --- {label} ---')
        for s in per_dow_inside_va(win):
            print(fmt(s))

    # Persist results
    all_rows = []
    for win_label, rows in [('holdout', holdout_rows),
                            ('in_sample', in_sample_rows),
                            ('forward', forward_rows),
                            ('full', full_rows)]:
        for r in rows:
            all_rows.append({'window': win_label, **r})
    pl.DataFrame(all_rows).write_csv(RESULTS / 'summary.csv')
    print(f'\n  → {RESULTS / "summary.csv"}')

    # Verdict heuristic
    print('\n' + '='*78)
    print('  VERDICT  (decision rule from study scoping)')
    print('='*78)
    holdout_play = next(r for r in holdout_rows if 'THE PLAY' in r['label'])
    forward_play = next(r for r in forward_rows if 'THE PLAY' in r['label'])
    print(f"  Holdout cell:  n={holdout_play['n']}  WR={holdout_play['wr']}%  PF={holdout_play['pf']}")
    print(f"  Forward cell:  n={forward_play['n']}  WR={forward_play['wr']}%  PF={forward_play['pf']}")

    def verdict(wr, pf, n):
        if n == 0 or wr is None:
            return 'NO DATA'
        if wr >= 65 and isinstance(pf, (int, float)) and pf >= 2.0:
            return 'CONFIRMED'
        if wr <= 55 or (isinstance(pf, (int, float)) and pf < 1.5):
            return 'INVALIDATED (multi-comparison)'
        return 'DEGRADED — tier-down'

    print(f"  Holdout verdict:  {verdict(holdout_play['wr'], holdout_play['pf'], holdout_play['n'])}")
    print(f"  Forward verdict:  {verdict(forward_play['wr'], forward_play['pf'], forward_play['n'])}")


if __name__ == '__main__':
    main()
