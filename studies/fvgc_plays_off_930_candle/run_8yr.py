#!/usr/bin/env python3
"""
8yr redo of the FVGC 9:30-opening-FVG study.

Filter: trades whose FVG was created during 09:29:30-09:31:00 ET (default window)
on the 8yr ES baseline_trades.csv. Adds an IS / OOS split vs the original
~30mo sample (2018-01-02 -> ~2021-05-21 covered the original 1572-trade run on
NQ; we approximate that cutoff here on ES baseline).

Run from repo root:
  python studies/fvgc_plays_off_930_candle/run_8yr.py
  python studies/fvgc_plays_off_930_candle/run_8yr.py --window tight
"""

import argparse
import sys
from datetime import time as dtime, date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from fvgc.constants import NY_TZ

TRADES_PATH = ROOT / 'logs' / 'baseline_trades.csv'
STUDY_DIR = Path(__file__).resolve().parent
RESULTS_DIR = STUDY_DIR / 'results'

WINDOW_DEFAULT = (dtime(9, 29, 30), dtime(9, 31, 0))
WINDOW_TIGHT = (dtime(9, 29, 30), dtime(9, 30, 30))

# Original NQ study had n=1572 tradeable over ~30mo. Use a comparable cutoff
# on the 8yr ES baseline so IS roughly matches the original headline window.
# Pick 2020-12-31 as a clean split (gives ~3yr IS, ~5yr OOS).
IS_END = date(2020, 12, 31)


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument('--window', choices=['default', 'tight'], default='default')
    p.add_argument('--is-end', default=IS_END.isoformat(),
                   help='IS cutoff date inclusive (YYYY-MM-DD)')
    return p.parse_args()


def stats(df: pd.DataFrame) -> dict:
    sub = df[df['outcome'].isin(['win', 'loss'])]
    if sub.empty:
        return {'n': 0, 'wins': 0, 'losses': 0, 'wr': float('nan'),
                'pnl': 0.0, 'pf': float('nan'), 'exp_r': float('nan')}
    wins = int((sub['outcome'] == 'win').sum())
    losses = int((sub['outcome'] == 'loss').sum())
    pnl = pd.to_numeric(sub['pnl'], errors='coerce')
    sl_dist = pd.to_numeric(sub['sl_dist'], errors='coerce')
    r = pnl / sl_dist
    gross_win = pnl[pnl > 0].sum()
    gross_loss = -pnl[pnl < 0].sum()
    pf = (gross_win / gross_loss) if gross_loss > 0 else float('inf')
    return {
        'n': len(sub), 'wins': wins, 'losses': losses,
        'wr': wins / (wins + losses) * 100 if (wins + losses) else float('nan'),
        'pnl': float(pnl.sum()),
        'pf': float(pf),
        'exp_r': float(r.mean()) if len(r) else float('nan'),
    }


def fmt(label: str, s: dict) -> str:
    if s['n'] == 0:
        return f'  {label:48s}  n=0'
    return (f'  {label:48s}  n={s["n"]:5d}  W={s["wins"]:4d} L={s["losses"]:4d}  '
            f'WR={s["wr"]:5.1f}%  PF={s["pf"]:5.2f}  exp={s["exp_r"]:+.3f}R  '
            f'PnL={s["pnl"]:+8.1f}')


def main():
    args = parse_args()
    wstart, wend = WINDOW_TIGHT if args.window == 'tight' else WINDOW_DEFAULT
    is_end = date.fromisoformat(args.is_end)

    print('=' * 100)
    print(f'FVGC 9:30 opening-FVG study (8yr ES)  window={wstart}-{wend} ET  IS<= {is_end}')
    print('=' * 100)

    t = pd.read_csv(TRADES_PATH)
    t['timestamp'] = pd.to_datetime(t['timestamp'])
    t['fvg_created_at'] = pd.to_datetime(t['fvg_created_at'], errors='coerce')
    if t['fvg_created_at'].dt.tz is None:
        t['fvg_created_ny'] = t['fvg_created_at'].dt.tz_localize(
            NY_TZ, ambiguous='infer', nonexistent='shift_forward'
        )
    else:
        t['fvg_created_ny'] = t['fvg_created_at'].dt.tz_convert(NY_TZ)
    t['date'] = t['timestamp'].dt.date
    t['t_of_day'] = t['fvg_created_ny'].dt.time
    t['in_open_win'] = t['t_of_day'].between(wstart, wend, inclusive='both') & t['fvg_created_ny'].notna()

    base = t[t['outcome'].isin(['win', 'loss'])].copy()

    print('\n--- FULL 8yr sample ---')
    print(f'Date range: {base.timestamp.min().date()} -> {base.timestamp.max().date()}')
    print(fmt('All tradeable baseline', stats(base)))

    cohort = base[base['in_open_win']]
    print('\n--- FVG created in opening window (all 8yr) ---')
    print(fmt('Opening-window FVG (all directions)', stats(cohort)))
    for d in ['long', 'short']:
        print(fmt(f'  {d} only', stats(cohort[cohort['direction'] == d])))

    is_mask = base['date'] <= is_end
    base_is = base[is_mask]
    base_oos = base[~is_mask]
    coh_is = cohort[cohort['date'] <= is_end]
    coh_oos = cohort[cohort['date'] > is_end]

    print(f'\n--- IS  (<= {is_end})  ---')
    print(fmt('All baseline', stats(base_is)))
    print(fmt('Opening-window FVG (all dir)', stats(coh_is)))
    for d in ['long', 'short']:
        print(fmt(f'  {d} only', stats(coh_is[coh_is['direction'] == d])))

    print(f'\n--- OOS (>  {is_end})  ---')
    print(fmt('All baseline', stats(base_oos)))
    print(fmt('Opening-window FVG (all dir)', stats(coh_oos)))
    for d in ['long', 'short']:
        print(fmt(f'  {d} only', stats(coh_oos[coh_oos['direction'] == d])))

    print('\n--- Opening-window SHORTS by calendar year ---')
    sh = cohort[cohort['direction'] == 'short'].copy()
    sh['year'] = sh['timestamp'].dt.year
    for y, g in sh.groupby('year'):
        print(fmt(f'  {y}', stats(g)))

    # Save the full cohort for inspection
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    window_tag = 'tight' if args.window == 'tight' else 'default'
    out = cohort.copy()
    out['fvg_created_ny'] = out['fvg_created_ny'].astype(str)
    out_path = RESULTS_DIR / f'trades_opening_fvg_8yr_{window_tag}.csv'
    out.to_csv(out_path, index=False)
    print(f'\nWrote {out_path.relative_to(ROOT)} ({len(out)} rows)')


if __name__ == '__main__':
    main()
