#!/usr/bin/env python3
"""
Thursday Inside Value Area — Retest with enlarged sample and targeted hardening.

Re-validates the Notion-page play (Thu + entry inside prior-day VA) on the
refreshed dataset, then tests five pre-registered hardening hypotheses with
permutation tests and an OOS partition.

Pre-registered (committed before data was seen):
  H1  va_width <= 500 pts                    (page flagged wide VA dilutes)
  H2  macro window MW2 (9:45-10:00)          (best window in original)
  H3  bearish 9:30 candle                    (strongest sub-filter)
  H4  no red folder news + normal VIXY       (clean context)
  H5  va_width in 100..500 pts (band)        (novel)

OOS split: trades dated <= 2026-04-15 = IS; > 2026-04-15 = OOS.
Acceptance per filter: permutation p < 0.05 vs Thu+InsideVA base AND OOS
direction matches IS direction.

Outputs are written to studies/thu_inside_va_retest/results/.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

STUDY_DIR = Path(__file__).resolve().parent
RESULTS_DIR = STUDY_DIR / 'results'

VP_TRADES = ROOT / 'data' / 'levels' / 'trades_with_vp.csv'
VP_DAILY = ROOT / 'data' / 'levels' / 'daily_volume_profile.csv'
TRADING_DAYS = ROOT / 'data' / 'trading_days' / 'trading_days.csv'

ORIGINAL_CUTOFF = date(2026, 4, 15)   # Notion page creation date


def cohort_stats(df: pd.DataFrame, label: str) -> dict:
    n = len(df)
    if n == 0:
        return {'cohort': label, 'n': 0, 'wins': 0, 'losses': 0,
                'wr': None, 'pf': None, 'avg_pnl_R': None, 'sum_pnl_R': None}
    wins = int((df['outcome'] == 'win').sum())
    losses = int((df['outcome'] == 'loss').sum())
    # express PnL in R-multiples so different sl_dist days are comparable
    sl = pd.to_numeric(df['sl_dist'], errors='coerce')
    pnl = pd.to_numeric(df['pnl'], errors='coerce')
    pnl_R = pnl / sl
    gp = pnl_R[pnl_R > 0].sum()
    gl = abs(pnl_R[pnl_R < 0].sum())
    pf = gp / gl if gl > 0 else (np.inf if gp > 0 else np.nan)
    wr = wins / (wins + losses) * 100 if (wins + losses) > 0 else None
    return {
        'cohort': label,
        'n': n,
        'wins': wins,
        'losses': losses,
        'wr': round(wr, 1) if wr is not None else None,
        'pf': round(pf, 2) if np.isfinite(pf) else pf,
        'avg_pnl_R': round(pnl_R.mean(), 3),
        'sum_pnl_R': round(pnl_R.sum(), 2),
    }


def perm_test_wr(parent: pd.DataFrame, child_mask: pd.Series,
                 n_perms: int = 10_000, seed: int = 42) -> dict:
    """Permutation test: is child WR significantly different from parent WR?

    Null: child trades are a random subsample of parent. Shuffle outcomes
    across parent, recompute WR for a same-size subsample. Two-sided p.
    """
    rng = np.random.default_rng(seed)
    parent = parent[parent['outcome'].isin(['win', 'loss'])].reset_index(drop=True)
    cmask = child_mask.loc[parent.index] if isinstance(child_mask, pd.Series) else child_mask
    child = parent[cmask]
    n_child = len(child)
    if n_child < 5:
        return {'n_child': n_child, 'actual_wr': None, 'p': None,
                'parent_wr': None, 'n_parent': len(parent)}

    actual_wr = (child['outcome'] == 'win').mean() * 100
    parent_outcomes = (parent['outcome'] == 'win').values
    parent_wr = parent_outcomes.mean() * 100

    n_parent = len(parent)
    perms = np.empty(n_perms)
    for i in range(n_perms):
        idx = rng.choice(n_parent, size=n_child, replace=False)
        perms[i] = parent_outcomes[idx].mean() * 100

    # two-sided p
    diff = abs(actual_wr - parent_wr)
    perm_diffs = np.abs(perms - parent_wr)
    p = (perm_diffs >= diff).mean()
    return {
        'n_parent': n_parent,
        'n_child': n_child,
        'parent_wr': round(parent_wr, 2),
        'actual_wr': round(actual_wr, 2),
        'mean_perm_wr': round(perms.mean(), 2),
        'p': round(float(p), 4),
        'significant_05': p < 0.05,
    }


def main():
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    log_lines = []

    def log(s=''):
        print(s)
        log_lines.append(s)

    log('=' * 72)
    log('  THURSDAY INSIDE VALUE AREA — RETEST WITH HARDENING')
    log('=' * 72)

    # ------ load ------
    trades = pd.read_csv(VP_TRADES)
    trades['timestamp'] = pd.to_datetime(trades['timestamp'])
    trades['date'] = trades['timestamp'].dt.date

    vp_daily = pd.read_csv(VP_DAILY)
    vp_daily['date'] = pd.to_datetime(vp_daily['date']).dt.date
    # va_width is computed on prior-day daily VP. We need to join prior_vp_date -> va_width.
    vp_width = vp_daily.set_index('date')['va_width']

    td = pd.read_csv(TRADING_DAYS)
    td['date'] = pd.to_datetime(td['date']).dt.date

    # tradeable + has VP
    df = trades[
        trades['outcome'].isin(['win', 'loss']) &
        trades['prior_vp_poc'].notna()
    ].copy()

    df['prior_vp_date'] = pd.to_datetime(df['prior_vp_date']).dt.date
    df['prior_va_width'] = df['prior_vp_date'].map(vp_width)

    # context join on TRADE date (not prior — but day_of_week / 9:30 / news /
    # vixy / macro time-of-entry are all known by entry, not lookahead)
    ctx_cols = [
        'date', 'day_of_week', 'day_of_week_name',
        'candle_930_direction', 'has_red_folder_news',
        'vixy_regime', 'overnight_direction',
    ]
    df = df.merge(td[ctx_cols], on='date', how='left')

    # macro window from entry timestamp
    t = df['timestamp']
    minute = t.dt.hour * 60 + t.dt.minute
    df['macro_window'] = pd.cut(
        minute,
        bins=[570, 585, 600, 615, 630, 1000],   # 9:30, 9:45, 10:00, 10:15, 10:30, ...
        labels=['MW1', 'MW2', 'MW3', 'MW4', 'after'],
        include_lowest=True, right=False,
    ).astype(str)

    log(f'\nLoaded {len(df)} tradeable trades (win/loss, VP present)')
    log(f'  Date range: {df["date"].min()} .. {df["date"].max()}')

    # ------ base cuts ------
    log('\n' + '-' * 72)
    log('BASE CUTS — full enlarged sample')
    log('-' * 72)

    base_all = cohort_stats(df, 'ALL tradeable')
    thu = df[df['day_of_week_name'] == 'Thursday']
    inside_va = df[df['entry_in_value_area'] == True]
    thu_inside = df[(df['day_of_week_name'] == 'Thursday') &
                    (df['entry_in_value_area'] == True)]

    base_rows = [
        base_all,
        cohort_stats(thu, 'Thursday alone'),
        cohort_stats(inside_va, 'Inside VA alone'),
        cohort_stats(thu_inside, 'Thursday + Inside VA'),
    ]
    base_df = pd.DataFrame(base_rows)
    log('\n' + base_df.to_string(index=False))

    # Permutation test: is Thu+InsideVA WR significantly above ALL baseline?
    log('\n--- Permutation: Thu+InsideVA vs ALL tradeable ---')
    pt = perm_test_wr(df, (df['day_of_week_name'] == 'Thursday') &
                          (df['entry_in_value_area'] == True))
    log(f'  n_parent={pt["n_parent"]}, n_child={pt["n_child"]}, '
        f'parent_WR={pt["parent_wr"]}%, actual_WR={pt["actual_wr"]}%, '
        f'mean_perm_WR={pt["mean_perm_wr"]}%, p={pt["p"]}')

    # ------ Time-slice breakdown ------
    # The original Notion study used trades starting Oct 2023. The retest
    # expanded back to 2018. Slice to see if the headline 73.7% was a
    # regime-specific phenomenon or just an arbitrary cutoff artifact.
    log('\n' + '-' * 72)
    log('TIME-SLICE BREAKDOWN (Thu + Inside VA)')
    log('-' * 72)
    slices = [
        ('2018-02..2020-12 (pre-COVID + COVID)',
            (date(2018, 1, 1), date(2020, 12, 31))),
        ('2021-01..2023-09 (post-COVID range)',
            (date(2021, 1, 1), date(2023, 9, 30))),
        ('2023-10..2026-04 (Notion study window)',
            (date(2023, 10, 1), date(2026, 4, 15))),
        ('2026-04-16..end (pure OOS)',
            (date(2026, 4, 16), date(2030, 1, 1))),
    ]
    slice_rows = []
    for label, (lo, hi) in slices:
        sl = thu_inside[(thu_inside['date'] >= lo) & (thu_inside['date'] <= hi)]
        slice_rows.append(cohort_stats(sl, label))
    log('\n' + pd.DataFrame(slice_rows).to_string(index=False))
    pd.DataFrame(slice_rows).to_csv(RESULTS_DIR / 'time_slices.csv', index=False)

    # Compare ALL baseline by the same slices for reference
    log('\nFor reference, ALL tradeable WR by same slices:')
    ref_rows = []
    for label, (lo, hi) in slices:
        sl = df[(df['date'] >= lo) & (df['date'] <= hi)]
        ref_rows.append(cohort_stats(sl, 'ALL ' + label))
    log('\n' + pd.DataFrame(ref_rows).to_string(index=False))

    # ------ Targeted hardening hypotheses ------
    log('\n' + '=' * 72)
    log('PRE-REGISTERED HARDENING HYPOTHESES (parent = Thu+InsideVA)')
    log('=' * 72)

    parent = thu_inside.reset_index(drop=True)

    hypos = {
        'H1: va_width <= 500':
            parent['prior_va_width'] <= 500,
        'H2: MW2 (9:45-10:00)':
            parent['macro_window'] == 'MW2',
        'H3: bearish 9:30':
            parent['candle_930_direction'] == 'bearish',
        'H4: no_news + vixy normal':
            (parent['has_red_folder_news'] == False) &
            (parent['vixy_regime'].isin(['low', 'normal'])),
        'H5: va_width 100..500':
            (parent['prior_va_width'] >= 100) & (parent['prior_va_width'] <= 500),
    }

    rows = [cohort_stats(parent, 'PARENT: Thu+InsideVA (full)')]
    for name, mask in hypos.items():
        rows.append(cohort_stats(parent[mask], name + ' (full)'))
    log('\n' + pd.DataFrame(rows).to_string(index=False))

    # Permutation tests on full sample
    log('\n--- Permutation: each hypothesis vs PARENT Thu+InsideVA ---')
    perm_rows = []
    for name, mask in hypos.items():
        pt = perm_test_wr(parent, mask)
        perm_rows.append({'hypothesis': name, **pt})
        sig = '***' if pt.get('significant_05') else ''
        log(f'  {name:35s}  n_child={pt["n_child"]:>3}  '
            f'WR={pt["actual_wr"]}% (parent {pt["parent_wr"]}%)  '
            f'p={pt["p"]}  {sig}')

    perm_df = pd.DataFrame(perm_rows)
    perm_df.to_csv(RESULTS_DIR / 'hypothesis_permutations.csv', index=False)

    # IS/OOS for each hypothesis
    log('\n--- IS vs OOS for each hypothesis (acceptance gate) ---')
    is_oos_rows = []
    for name, mask in hypos.items():
        h_full = parent[mask]
        h_is = h_full[h_full['date'] <= ORIGINAL_CUTOFF]
        h_oos = h_full[h_full['date'] > ORIGINAL_CUTOFF]
        is_oos_rows.append({**cohort_stats(h_is, name + ' IS'),
                             'partition': 'IS'})
        is_oos_rows.append({**cohort_stats(h_oos, name + ' OOS'),
                             'partition': 'OOS'})
    is_oos_df = pd.DataFrame(is_oos_rows)
    log('\n' + is_oos_df.to_string(index=False))
    is_oos_df.to_csv(RESULTS_DIR / 'hypothesis_is_oos.csv', index=False)

    # Save full enriched parent for follow-up
    parent_out_cols = [
        'timestamp', 'date', 'direction', 'variant', 'entry_price',
        'outcome', 'pnl', 'sl_dist',
        'prior_vp_poc', 'prior_vp_vah', 'prior_vp_val', 'prior_va_width',
        'entry_in_value_area', 'day_of_week_name',
        'candle_930_direction', 'has_red_folder_news', 'vixy_regime',
        'overnight_direction', 'macro_window',
        'hit_1_0R', 'hit_1_5R', 'hit_2_0R', 'hit_2_5R', 'hit_3_0R',
        'mfe_pts', 'mae_pts', 'mfe_r', 'mae_r',
    ]
    parent_out_cols = [c for c in parent_out_cols if c in parent.columns]
    parent[parent_out_cols].to_csv(RESULTS_DIR / 'thu_inside_va_trades.csv', index=False)

    # Persist log
    (RESULTS_DIR / 'run.log').write_text('\n'.join(log_lines))
    log(f'\nResults written to {RESULTS_DIR}/')


if __name__ == '__main__':
    main()
