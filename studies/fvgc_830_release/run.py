#!/usr/bin/env python3
"""
8:30 ET data-release candle continuation — analysis-only.

Heavier study: requires the backtester to be re-run with FVG_START_TIME and
TRADING_WINDOW_START widened to 08:30 in fvgc/constants.py. The regenerated
trade log is stored in logs/baseline_trades_830scope.csv (not the canonical
baseline_trades.csv).

Hypothesis: on scheduled-data days (CPI, NFP) the 8:30 ET release candle
creates a high-information FVG that continues into RTH. Test cohorts:
  (A) FVG created 08:29:30-08:31:00 AND has_830_release=True
  (B) Same time window, has_830_release=False (control)
  (C) FVG created 09:29:30-09:31:00 AND has_830_release=True (does
      pre-knowledge of a release boost the 9:30 cohort?)

Keyword universe (trading_days.csv `red_folder_event_names` text):
  - "Payroll"         -> NFP / Employment Situation (08:30 release)
  - "Consumer Price"  -> CPI (08:30 release)
NOTE: trading_days.csv does NOT carry PPI / jobless claims / retail sales /
GDP / PCE / ISM / etc., so the 8:30 release universe is narrower than ideal
(~99 days over 8yr). FOMC events are at 14:00 ET and explicitly excluded.

IS/OOS: year<=2022 / year>=2023.

Liquidity caveat: pre-9:30 CME futures liquidity is thinner than RTH;
slippage on simulated fills may be optimistic. Flag this in any verdict.

Run from repo root:
  python studies/fvgc_830_release/run.py
"""

import sys
from datetime import time as dtime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from fvgc.constants import NY_TZ

TRADES_PATH = ROOT / 'logs' / 'baseline_trades_830scope.csv'
TRADING_DAYS_PATH = ROOT / 'data' / 'trading_days' / 'trading_days.csv'
STUDY_DIR = Path(__file__).resolve().parent
RESULTS_DIR = STUDY_DIR / 'results'

WIN_830 = (dtime(8, 29, 30), dtime(8, 31, 0))
WIN_930 = (dtime(9, 29, 30), dtime(9, 31, 0))

# Keywords identifying an 08:30 ET scheduled data release in
# trading_days.csv:red_folder_event_names (case-insensitive substring match)
RELEASE_KEYWORDS_830 = ['Payroll', 'Consumer Price']

IS_MAX_YEAR = 2022
OOS_MIN_YEAR = 2023


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
        return f'  {label:54s}  n=0'
    small = ' (SMALL-N)' if s['n'] < 30 else ''
    return (f'  {label:54s}  n={s["n"]:5d}  W={s["wins"]:4d} L={s["losses"]:4d}  '
            f'WR={s["wr"]:5.1f}%  PF={s["pf"]:5.2f}  exp={s["exp_r"]:+.3f}R  '
            f'PnL={s["pnl"]:+8.1f}{small}')


def build_release_flags() -> pd.DataFrame:
    td = pd.read_csv(TRADING_DAYS_PATH,
                      usecols=['date', 'has_pre_rth_news', 'red_folder_event_names'])
    td['date'] = pd.to_datetime(td['date']).dt.date
    events = td['red_folder_event_names'].fillna('').astype(str)
    pat = '|'.join(RELEASE_KEYWORDS_830)
    td['has_830_release'] = events.str.contains(pat, case=False, regex=True, na=False)
    # individual flags for diagnostics
    for kw in RELEASE_KEYWORDS_830:
        td[f'has_{kw.replace(" ", "_").lower()}'] = events.str.contains(
            kw, case=False, regex=False, na=False
        )
    return td


def main():
    if not TRADES_PATH.exists():
        print(f'ERROR: {TRADES_PATH.relative_to(ROOT)} not found.')
        print('       Generate it by:')
        print('         1. Edit fvgc/constants.py: '
              'FVG_START_TIME / TRADING_WINDOW_START -> 8:30')
        print('         2. Backup logs/baseline_trades.csv')
        print('         3. Run: python tools/run_backtest.py --baseline')
        print('         4. Move logs/baseline_trades.csv -> logs/baseline_trades_830scope.csv')
        print('         5. Restore the canonical baseline_trades.csv and constants.py')
        sys.exit(1)

    print('=' * 110)
    print(f'FVGC 8:30 ET data-release candle  '
          f'IS<={IS_MAX_YEAR}  OOS>={OOS_MIN_YEAR}')
    print('=' * 110)

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
    t['year'] = t['timestamp'].dt.year
    t['t_of_day'] = t['fvg_created_ny'].dt.time

    # Release flag join
    td = build_release_flags()
    t = t.merge(td, on='date', how='left')
    t['has_pre_rth_news'] = t['has_pre_rth_news'].fillna(False).astype(bool)
    t['has_830_release'] = t['has_830_release'].fillna(False).astype(bool)
    t['has_payroll'] = t['has_payroll'].fillna(False).astype(bool)
    t['has_consumer_price'] = t['has_consumer_price'].fillna(False).astype(bool)

    # Time-window flags
    t['in_830_win'] = (
        t['t_of_day'].between(WIN_830[0], WIN_830[1], inclusive='both')
        & t['fvg_created_ny'].notna()
    )
    t['in_930_win'] = (
        t['t_of_day'].between(WIN_930[0], WIN_930[1], inclusive='both')
        & t['fvg_created_ny'].notna()
    )

    base = t[t['outcome'].isin(['win', 'loss'])].copy()

    n_release_days = base.loc[base['has_830_release'], 'date'].nunique()
    print(f'\nDate range: {base.timestamp.min().date()} -> {base.timestamp.max().date()}')
    print(f'Distinct 8:30 release days (Payroll or CPI): {n_release_days}')
    print(f'Distinct days in trade log: {base["date"].nunique()}')

    print('\n--- FULL widened-scope baseline (8:30 - 10:15 entries) ---')
    print(fmt('All tradeable baseline', stats(base)))
    print(fmt('  long', stats(base[base['direction'] == 'long'])))
    print(fmt('  short', stats(base[base['direction'] == 'short'])))

    def report(label: str, df: pd.DataFrame) -> None:
        print(fmt(label, stats(df)))
        for d in ['long', 'short']:
            print(fmt(f'    {d}', stats(df[df['direction'] == d])))
        is_ = df[df['year'] <= IS_MAX_YEAR]
        oos = df[df['year'] >= OOS_MIN_YEAR]
        print(fmt(f'    IS  (<= {IS_MAX_YEAR})', stats(is_)))
        print(fmt(f'    OOS (>= {OOS_MIN_YEAR})', stats(oos)))
        for d in ['long', 'short']:
            print(fmt(f'      OOS {d}', stats(oos[oos['direction'] == d])))

    cohort_830 = base[base['in_830_win']]
    print(f'\n--- 8:30 candle cohort sizes ---')
    print(f'  all 8:30 window trades:           n={len(cohort_830)}')
    print(f'  on release days:                  n={len(cohort_830[cohort_830["has_830_release"]])}')
    print(f'  on non-release days (control):    n={len(cohort_830[~cohort_830["has_830_release"]])}')

    print('\n=== (A) 8:30 candle × has_830_release=True ===')
    print()
    report('8:30 candle on release day', cohort_830[cohort_830['has_830_release']])

    print('\n=== (A) 8:30 candle × Payroll-only (NFP-style) ===')
    print()
    report('8:30 candle × Payroll', cohort_830[cohort_830['has_payroll']])

    print('\n=== (A) 8:30 candle × CPI-only ===')
    print()
    report('8:30 candle × CPI', cohort_830[cohort_830['has_consumer_price']])

    print('\n=== (B) 8:30 candle on NON-release days (control) ===')
    print()
    report('8:30 candle on NON-release day', cohort_830[~cohort_830['has_830_release']])

    print('\n=== (C) 9:30 candle × has_830_release=True (does 8:30 release set up 9:30?) ===')
    cohort_930 = base[base['in_930_win']]
    print()
    report('9:30 cohort × release day', cohort_930[cohort_930['has_830_release']])
    print()
    report('9:30 cohort × NON-release day (control)', cohort_930[~cohort_930['has_830_release']])

    print('\n=== (A) gap-aligned split (8:30 cohort × release × gap sign) ===')
    # gap_from_prior_close is in trading_days.csv; we have it indirectly via has_pre_rth_news only.
    # We didn't load gap col — quick re-load
    gap_td = pd.read_csv(
        TRADING_DAYS_PATH,
        usecols=['date', 'gap_from_prior_close'],
    )
    gap_td['date'] = pd.to_datetime(gap_td['date']).dt.date
    rel_830 = cohort_830[cohort_830['has_830_release']].merge(
        gap_td, on='date', how='left'
    )
    rel_830['gap_dir'] = rel_830['gap_from_prior_close'].apply(
        lambda x: 'up' if pd.notna(x) and x > 0 else ('down' if pd.notna(x) and x < 0 else 'flat')
    )
    for gd in ['up', 'down', 'flat']:
        print(fmt(f'release × gap_{gd}', stats(rel_830[rel_830['gap_dir'] == gd])))

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    cohort_830.assign(
        fvg_created_ny=cohort_830['fvg_created_ny'].astype(str)
    ).to_csv(RESULTS_DIR / 'trades_830_release.csv', index=False)
    cohort_930.assign(
        fvg_created_ny=cohort_930['fvg_created_ny'].astype(str)
    ).to_csv(RESULTS_DIR / 'trades_930_release_aware.csv', index=False)
    print(f'\nWrote results/trades_830_release.csv ({len(cohort_830)} rows)')
    print(f'Wrote results/trades_930_release_aware.csv ({len(cohort_930)} rows)')


if __name__ == '__main__':
    main()
