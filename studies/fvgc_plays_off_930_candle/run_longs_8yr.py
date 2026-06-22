#!/usr/bin/env python3
"""
Long-side redo of the Opening-FVG (9:30 candle) study on the FULL 8yr baseline.

Motivation: the short side is 8yr-validated (63-70% WR, PF 2.3). The long side
was only ever studied on 2-3yr (W1 Long Confluence, 2026-04) and found no edge,
BUT that study flagged that bullish-9:30 / strong-prior-day HURT longs while
gap-up / clean-news HELPED. Now we have 8yr -> re-mine a LONG-oriented
confluence set and see whether a genuinely tradeable cell exists.

IMPORTANT: the live logs/baseline_trades.csv is clobbered to 2024-2026 by the
daily fly runs. The real 8yr file is logs/baseline_trades.csv.preserve.

Run from repo root:
  python studies/fvgc_plays_off_930_candle/run_longs_8yr.py
"""

import sys
from datetime import time as dtime, date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
from fvgc.constants import NY_TZ

TRADES_PATH = ROOT / 'logs' / 'baseline_trades.csv.preserve'   # the real 8yr file
DAYS_PATH   = ROOT / 'data' / 'trading_days' / 'trading_days.csv'
RESULTS_DIR = Path(__file__).resolve().parent / 'results'

WIN_START = dtime(9, 29, 30)
WIN_END   = dtime(9, 31, 0)
IS_END    = date(2022, 12, 31)   # ~5yr IS / ~3yr OOS on the 8yr sample
SEED      = 12345


# -----------------------------------------------------------------------------
# Per-day LONG-oriented confluence factors (all causally observable by ~9:31)
# -----------------------------------------------------------------------------

def compute_long_factors(d: pd.DataFrame) -> pd.DataFrame:
    d = d.sort_values('date').reset_index(drop=True).copy()
    # rolling quantiles use only PRIOR days (shift 1) -> causal
    for col, q, name in [
        ('vixy_prior_close', 0.75, 'vixy_q75'),
        ('vixy_prior_close', 0.25, 'vixy_q25'),
        ('candle_930_body',  0.75, 'c930_body_q75'),
        ('or_5min_range',    0.75, 'or5_q75'),
    ]:
        d[name] = d[col].rolling(90, min_periods=30).quantile(q).shift(1)

    gap = d['gap_from_prior_close']
    d['c_gap_up']         = (gap >= 10).astype(int)
    d['c_gap_up_large']   = (gap >= 100).astype(int)
    d['c_gap_down']       = (gap <= -10).astype(int)
    # W1 finding: bullish 9:30 HURT longs -> test the INVERSE (fade a red open)
    d['c_bear_930']       = (d['candle_930_direction'] == 'bearish').astype(int)
    d['c_bull_930']       = (d['candle_930_direction'] == 'bullish').astype(int)
    # W1 finding: strong prior-day close HURT longs -> test weak prior day
    d['c_prior_day_weak'] = (d['prior_day_close_position'] <= 0.333).astype(int)
    d['c_prior_day_strong'] = (d['prior_day_close_position'] >= 0.667).astype(int)
    d['c_no_news']        = (d['has_red_folder_news'] == False).astype(int) \
        if d['has_red_folder_news'].dtype == bool else (~d['has_red_folder_news'].astype(bool)).astype(int)
    d['c_wide_930']       = (d['candle_930_body'] >= d['c930_body_q75']).astype(int)
    d['c_or5_top_q']      = (d['or_5min_range'] >= d['or5_q75']).astype(int)
    d['c_vixy_high']      = (d['vixy_prior_close'] >= d['vixy_q75']).astype(int)
    d['c_vixy_low']       = (d['vixy_prior_close'] <= d['vixy_q25']).astype(int)
    d['c_dow_friday']     = (d['day_of_week_name'] == 'Friday').astype(int)
    d['c_dow_monday']     = (d['day_of_week_name'] == 'Monday').astype(int)
    d['c_fomc_week']      = d['is_fomc_week'].astype(int)
    return d


# Factors that ENTER the confluence count (long-thesis-aligned only).
COUNT_FACTORS = ['c_gap_up', 'c_no_news', 'c_bear_930', 'c_prior_day_weak',
                 'c_wide_930', 'c_or5_top_q']

# Wider set we also report per-factor lift for (incl. the "anti" hypotheses).
ALL_FACTORS = COUNT_FACTORS + ['c_gap_up_large', 'c_gap_down', 'c_bull_930',
                               'c_prior_day_strong', 'c_vixy_high', 'c_vixy_low',
                               'c_dow_friday', 'c_dow_monday', 'c_fomc_week']


# -----------------------------------------------------------------------------
# Stats helpers
# -----------------------------------------------------------------------------

def stats(df: pd.DataFrame) -> dict:
    s = df[df['outcome'].isin(['win', 'loss'])]
    if s.empty:
        return dict(n=0)
    wins = int((s['outcome'] == 'win').sum())
    losses = int((s['outcome'] == 'loss').sum())
    pnl = pd.to_numeric(s['pnl'], errors='coerce')
    sl = pd.to_numeric(s['sl_dist'], errors='coerce')
    r = pnl / sl
    gw = pnl[pnl > 0].sum(); gl = -pnl[pnl < 0].sum()
    pf = (gw / gl) if gl > 0 else float('inf')
    return dict(n=len(s), wins=wins, losses=losses,
                wr=wins / (wins + losses) * 100 if wins + losses else float('nan'),
                pf=pf, exp_r=float(r.mean()))


def fmt(label, s):
    if not s or s.get('n', 0) == 0:
        return f'  {label:50s}  n=0'
    return (f'  {label:50s}  n={s["n"]:4d}  W={s["wins"]:3d} L={s["losses"]:3d}  '
            f'WR={s["wr"]:5.1f}%  PF={s["pf"]:5.2f}  exp={s["exp_r"]:+.3f}R')


def perm_test(cohort: pd.DataFrame, mask: pd.Series, n_perm=5000) -> float:
    """One-sided permutation p-value: is the masked subset's WR higher than
    chance, given the cohort's overall win rate? Shuffles outcome labels."""
    s = cohort[cohort['outcome'].isin(['win', 'loss'])].copy()
    y = (s['outcome'] == 'win').values.astype(int)
    m = mask.loc[s.index].values.astype(bool)
    k = m.sum()
    if k == 0:
        return float('nan')
    obs = y[m].mean()
    rng = np.random.default_rng(SEED)
    ge = 0
    for _ in range(n_perm):
        if rng.permutation(y)[:k].mean() >= obs:   # crude: sample-without-replacement equiv
            ge += 1
    # proper: shuffle assignment of m each time
    ge = 0
    for _ in range(n_perm):
        mm = rng.permutation(m)
        if y[mm].mean() >= obs:
            ge += 1
    return (ge + 1) / (n_perm + 1)


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

def main():
    print('=' * 100)
    print('Opening-FVG LONGS — 8yr confluence mine')
    print('=' * 100)

    t = pd.read_csv(TRADES_PATH)
    t['timestamp'] = pd.to_datetime(t['timestamp'])
    fc = pd.to_datetime(t['fvg_created_at'], errors='coerce')
    t['fvg_ny'] = (fc.dt.tz_localize(NY_TZ, ambiguous='infer', nonexistent='shift_forward')
                   if fc.dt.tz is None else fc.dt.tz_convert(NY_TZ))
    t['date'] = t['timestamp'].dt.normalize()
    t['ft'] = t['fvg_ny'].dt.time
    t['in_win'] = t['fvg_ny'].notna() & t['ft'].between(WIN_START, WIN_END)
    t['year'] = t['timestamp'].dt.year

    base = t[t['outcome'].isin(['win', 'loss'])].copy()
    longs = base[(base['direction'] == 'long') & base['in_win']].copy()
    print(f'\nDate range: {base.timestamp.min().date()} -> {base.timestamp.max().date()}')
    print(fmt('All opening-FVG LONGS (all variants)', stats(longs)))
    print(f'  variants: {longs.variant.value_counts().to_dict()}')
    nops = longs[longs.variant != 'protected_swing'].copy()
    print(fmt('  no-PS', stats(nops)))

    print('\n--- LONGS by calendar year (all variants) ---')
    for y, g in longs.groupby('year'):
        print(fmt(f'  {y}', stats(g)))

    # merge day factors
    days = pd.read_csv(DAYS_PATH)
    days['date'] = pd.to_datetime(days['date'])
    days = compute_long_factors(days)
    keep = ['date'] + ALL_FACTORS
    longs = longs.merge(days[keep], on='date', how='left')
    longs['conf_count'] = longs[COUNT_FACTORS].sum(axis=1)

    # ------------------------------------------------------------------
    # Per-factor lift (all variants — more n)
    # ------------------------------------------------------------------
    print('\n' + '=' * 100)
    print('Per-factor lift on opening-FVG LONGS (factor ON vs OFF, all variants)')
    print('=' * 100)
    rows = []
    for f in ALL_FACTORS:
        on = longs[longs[f] == 1]; off = longs[longs[f] == 0]
        son, soff = stats(on), stats(off)
        rows.append(dict(factor=f.replace('c_', ''),
                         n_on=son.get('n', 0), wr_on=son.get('wr', np.nan), pf_on=son.get('pf', np.nan),
                         n_off=soff.get('n', 0), wr_off=soff.get('wr', np.nan),
                         lift_pp=son.get('wr', np.nan) - soff.get('wr', np.nan)))
    lift = pd.DataFrame(rows).sort_values('lift_pp', ascending=False)
    with pd.option_context('display.width', 200, 'display.float_format', '{:.1f}'.format):
        print(lift.to_string(index=False))

    # ------------------------------------------------------------------
    # Confluence-tier stacking (thesis-aligned count factors only)
    # ------------------------------------------------------------------
    print('\n' + '=' * 100)
    print(f'Confluence tiers (count of {COUNT_FACTORS})')
    print('=' * 100)
    print('\n-- all variants --')
    for lo, hi, lbl in [(0, 0, '0'), (1, 1, '1'), (2, 2, '2'), (3, 3, '3'),
                        (4, 6, '4+'), (2, 6, '2+'), (3, 6, '3+')]:
        sub = longs[(longs.conf_count >= lo) & (longs.conf_count <= hi)]
        print(fmt(f'tier {lbl}', stats(sub)))
    print('\n-- no-PS --')
    nops2 = longs[longs.variant != 'protected_swing']
    for lo, hi, lbl in [(0, 1, '0-1'), (2, 2, '2'), (3, 6, '3+'), (2, 6, '2+')]:
        sub = nops2[(nops2.conf_count >= lo) & (nops2.conf_count <= hi)]
        print(fmt(f'tier {lbl}', stats(sub)))

    # ------------------------------------------------------------------
    # IS / OOS on the best-looking tier
    # ------------------------------------------------------------------
    print('\n' + '=' * 100)
    print(f'IS (<= {IS_END}) / OOS split — tier 2+ and tier 3+')
    print('=' * 100)
    for lbl, lo in [('2+', 2), ('3+', 3)]:
        cell = longs[longs.conf_count >= lo]
        is_c = cell[cell['date'].dt.date <= IS_END]
        oos_c = cell[cell['date'].dt.date > IS_END]
        print(f'\n  tier {lbl}:')
        print(fmt('    IS ', stats(is_c)))
        print(fmt('    OOS', stats(oos_c)))

    # ------------------------------------------------------------------
    # Permutation test on the best tier (all variants)
    # ------------------------------------------------------------------
    print('\n' + '=' * 100)
    print('Permutation test (WR of tier vs shuffled labels within the long cohort)')
    print('=' * 100)
    for lbl, lo in [('2+', 2), ('3+', 3)]:
        mask = longs['conf_count'] >= lo
        p = perm_test(longs, mask)
        s = stats(longs[mask])
        print(f'  tier {lbl}: WR={s.get("wr", float("nan")):.1f}%  n={s.get("n",0)}  perm p={p:.4f}')

    # ------------------------------------------------------------------
    # Best single-factor pair scan (top lifters combined)
    # ------------------------------------------------------------------
    print('\n' + '=' * 100)
    print('Pairwise factor combos (both ON) — n>=20 only, sorted by WR')
    print('=' * 100)
    combo_rows = []
    for i in range(len(ALL_FACTORS)):
        for j in range(i + 1, len(ALL_FACTORS)):
            f1, f2 = ALL_FACTORS[i], ALL_FACTORS[j]
            sub = longs[(longs[f1] == 1) & (longs[f2] == 1)]
            s = stats(sub)
            if s.get('n', 0) >= 20:
                combo_rows.append(dict(pair=f'{f1.replace("c_","")}+{f2.replace("c_","")}',
                                       n=s['n'], wr=s['wr'], pf=s['pf'], exp_r=s['exp_r']))
    if combo_rows:
        cdf = pd.DataFrame(combo_rows).sort_values('wr', ascending=False)
        with pd.option_context('display.width', 200, 'display.float_format', '{:.2f}'.format):
            print(cdf.head(15).to_string(index=False))

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = longs.copy()
    out['fvg_ny'] = out['fvg_ny'].astype(str)
    out.to_csv(RESULTS_DIR / 'trades_opening_fvg_LONGS_8yr.csv', index=False)
    print(f'\nWrote results/trades_opening_fvg_LONGS_8yr.csv ({len(out)} rows)')


if __name__ == '__main__':
    main()
