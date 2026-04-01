#!/usr/bin/env python3
"""
Compare win rates on red-folder news days vs not, and split red days by pre-RTH vs not.
Also: event calendar with weekday / week-of-month, WR by event_type × DOW, and day-structure
profiles (gap, ranges) per bucket.

Uses baseline trades joined to trading_days (same as analysis/permutation_test.load_data).

Run from repo root:
  python studies/red_folder_news_compare/run.py
"""

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd

from analysis.permutation_test import load_data

EVENTS_PATH = ROOT / 'data' / 'raw' / 'market_high_volume_events_2020_2025.csv'
TRADING_DAYS_PATH = ROOT / 'data' / 'trading_days' / 'trading_days.csv'
STUDY_DIR = Path(__file__).resolve().parent
RESULTS_DIR = STUDY_DIR / 'results'

DAY_STRUCTURE_COLS = [
    'gap_from_prior_close_pct',
    'or_5min_range',
    'or_45min_range',
    'candle_930_range',
    'rth_range',
]


def week_of_month(d: date) -> int:
    """1-based index: days 1–7 → week 1, 8–14 → week 2, … capped at 5."""
    return min((d.day - 1) // 7 + 1, 5)


def segment_stats(df: pd.DataFrame) -> dict:
    wins = (df['outcome'] == 'win').sum()
    losses = (df['outcome'] == 'loss').sum()
    n = len(df)
    wr = wins / (wins + losses) * 100 if (wins + losses) else 0.0
    pnl = pd.to_numeric(df['pnl'], errors='coerce')
    total = float(pnl.sum())
    return {
        'n': n,
        'wins': int(wins),
        'losses': int(losses),
        'win_rate_pct': round(wr, 2),
        'total_pnl': round(total, 2),
        'avg_pnl': round(float(pnl.mean()), 4) if n else 0.0,
    }


def load_events_calendar() -> pd.DataFrame:
    """Events CSV with date, weekday (Monday=0 in day_of_week), week_of_month."""
    ev = pd.read_csv(EVENTS_PATH)
    ev = ev.dropna(subset=['date', 'event_type'])
    ev['date'] = pd.to_datetime(ev['date']).dt.date
    ts = pd.to_datetime(ev['date'].astype(str))
    ev['day_of_week_name'] = ts.dt.day_name()
    ev['day_of_week'] = ts.dt.weekday
    ev['week_of_month'] = ev['date'].apply(week_of_month)
    return ev


def write_event_type_overall(ev: pd.DataFrame, df: pd.DataFrame) -> None:
    event_rows = []
    for et in sorted(ev['event_type'].unique()):
        dates = set(ev.loc[ev['event_type'] == et, 'date'].tolist())
        sub = df[df['date'].isin(dates)]
        st = segment_stats(sub)
        del st['avg_pnl']
        event_rows.append({'event_type': et, **st})

    if not event_rows:
        return
    ev_summary = pd.DataFrame(event_rows).sort_values('n', ascending=False)
    print('\n--- By event_type (trade on a day with that type; rows are not mutually exclusive) ---')
    print(ev_summary.to_string(index=False))
    ev_path = RESULTS_DIR / 'summary_by_event_type.csv'
    ev_summary.to_csv(ev_path, index=False)
    print(f"\n  Wrote {ev_path.relative_to(ROOT)}")


def write_calendar_with_dow(ev: pd.DataFrame) -> pd.DataFrame:
    cal_cols = ['date', 'event_type', 'event', 'day_of_week', 'day_of_week_name', 'week_of_month']
    cal_out = ev[cal_cols].sort_values(['date', 'event_type']).reset_index(drop=True)
    cal_path = RESULTS_DIR / 'red_folder_calendar_with_dow.csv'
    cal_out.to_csv(cal_path, index=False)
    print('\n--- Calendar: event rows with weekday / week_of_month ---')
    g = cal_out.groupby(['event_type', 'day_of_week_name']).size().reset_index(name='n_event_rows')
    print(g.to_string(index=False))
    print(f"\n  Wrote {cal_path.relative_to(ROOT)}")
    return cal_out


def event_dow_trade_summary(ev: pd.DataFrame, df: pd.DataFrame) -> pd.DataFrame:
    et_dow_rows = []
    pairs = ev[['event_type', 'day_of_week_name']].drop_duplicates()
    for _, row in pairs.iterrows():
        et, dow = row['event_type'], row['day_of_week_name']
        dates_et_dow = set(
            ev.loc[(ev['event_type'] == et) & (ev['day_of_week_name'] == dow), 'date'].tolist()
        )
        if not dates_et_dow:
            continue
        sub = df[df['date'].isin(dates_et_dow) & (df['day_of_week_name'] == dow)]
        if sub.empty:
            st = {
                'n': 0,
                'wins': 0,
                'losses': 0,
                'win_rate_pct': 0.0,
                'total_pnl': 0.0,
                'avg_pnl': 0.0,
                'long_n': 0,
                'short_n': 0,
            }
        else:
            base = segment_stats(sub)
            st = {
                **base,
                'long_n': int((sub['direction'] == 'long').sum()),
                'short_n': int((sub['direction'] == 'short').sum()),
            }
        et_dow_rows.append({'event_type': et, 'day_of_week_name': dow, **st})
    return pd.DataFrame(et_dow_rows).sort_values(['event_type', 'day_of_week_name'])


def day_structure_profile(ev: pd.DataFrame, pairs: pd.DataFrame, td: pd.DataFrame) -> pd.DataFrame:
    prof_rows = []
    for _, row in pairs.iterrows():
        et, dow = row['event_type'], row['day_of_week_name']
        dates_et_dow = set(
            ev.loc[(ev['event_type'] == et) & (ev['day_of_week_name'] == dow), 'date'].tolist()
        )
        sub_td = td[td['date'].isin(dates_et_dow)]
        if 'day_of_week_name' in sub_td.columns:
            sub_td = sub_td[sub_td['day_of_week_name'] == dow]
        n_dates = sub_td['date'].nunique()
        rec = {
            'event_type': et,
            'day_of_week_name': dow,
            'n_session_dates': n_dates,
        }
        if n_dates == 0:
            for c in DAY_STRUCTURE_COLS:
                rec[f'mean_{c}'] = float('nan')
        else:
            for c in DAY_STRUCTURE_COLS:
                if c not in sub_td.columns:
                    rec[f'mean_{c}'] = float('nan')
                else:
                    rec[f'mean_{c}'] = round(float(pd.to_numeric(sub_td[c], errors='coerce').mean()), 6)
        prof_rows.append(rec)
    return pd.DataFrame(prof_rows).sort_values(['event_type', 'day_of_week_name'])


def main():
    print('=' * 60)
    print('Red folder news — win rate comparison (baseline trades)')
    print('=' * 60)

    df = load_data()
    if df['has_red_folder_news'].isna().any():
        n_bad = int(df['has_red_folder_news'].isna().sum())
        print(
            f"\nNote: {n_bad} tradeable trades have no trading_days row (date outside "
            f"build range); excluded from no_red / red segments below. "
            f"'all_tradeable' still includes them."
        )

    rows = []

    def add_row(segment: str, sub: pd.DataFrame):
        st = segment_stats(sub)
        del st['avg_pnl']
        rows.append({'segment': segment, **st})

    add_row('all_tradeable', df)
    add_row('no_red_folder', df[df['has_red_folder_news'] == False])
    add_row('red_folder_all', df[df['has_red_folder_news'] == True])
    add_row(
        'red_folder_pre_rth_news',
        df[(df['has_red_folder_news'] == True) & (df['has_pre_rth_news'] == True)],
    )
    add_row(
        'red_folder_no_pre_rth_news',
        df[(df['has_red_folder_news'] == True) & (df['has_pre_rth_news'] == False)],
    )

    summary = pd.DataFrame(rows)
    print('\n--- All directions (primary segments) ---')
    print(summary.to_string(index=False))

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    summary_path = RESULTS_DIR / 'summary_by_red_folder.csv'
    summary.to_csv(summary_path, index=False)
    print(f"\n  Wrote {summary_path.relative_to(ROOT)}")

    dir_rows = []
    for direction in ['long', 'short']:
        d = df[df['direction'] == direction]
        for seg_name, sub in [
            ('all_tradeable', d),
            ('no_red_folder', d[d['has_red_folder_news'] == False]),
            ('red_folder_all', d[d['has_red_folder_news'] == True]),
            (
                'red_folder_pre_rth_news',
                d[(d['has_red_folder_news'] == True) & (d['has_pre_rth_news'] == True)],
            ),
            (
                'red_folder_no_pre_rth_news',
                d[(d['has_red_folder_news'] == True) & (d['has_pre_rth_news'] == False)],
            ),
        ]:
            st = segment_stats(sub)
            del st['avg_pnl']
            dir_rows.append({'direction': direction, 'segment': seg_name, **st})

    by_dir = pd.DataFrame(dir_rows)
    print('\n--- By direction (same segments) ---')
    for direction in ['long', 'short']:
        sub = by_dir[by_dir['direction'] == direction]
        print(f"\n  {direction.upper()}")
        print(sub[['segment', 'n', 'wins', 'losses', 'win_rate_pct', 'total_pnl']].to_string(index=False))

    by_dir_path = RESULTS_DIR / 'summary_by_red_folder_by_direction.csv'
    by_dir.to_csv(by_dir_path, index=False)
    print(f"\n  Wrote {by_dir_path.relative_to(ROOT)}")

    ev = load_events_calendar()
    write_event_type_overall(ev, df)

    write_calendar_with_dow(ev)
    pairs = ev[['event_type', 'day_of_week_name']].drop_duplicates()

    et_dow = event_dow_trade_summary(ev, df)
    et_dow_path = RESULTS_DIR / 'summary_event_type_by_dow.csv'
    et_dow.to_csv(et_dow_path, index=False)
    print('\n--- Trades: event_type × day_of_week (session DOW must match event row) ---')
    print(et_dow.to_string(index=False))
    print(f"\n  Wrote {et_dow_path.relative_to(ROOT)}")

    td = pd.read_csv(TRADING_DAYS_PATH)
    td['date'] = pd.to_datetime(td['date']).dt.date
    prof = day_structure_profile(ev, pairs, td)
    prof_path = RESULTS_DIR / 'profile_day_structure_by_event_dow.csv'
    prof.to_csv(prof_path, index=False)
    print('\n--- Day structure (mean over distinct session dates in bucket; from trading_days) ---')
    print(prof.to_string(index=False))
    print(f"\n  Wrote {prof_path.relative_to(ROOT)}")

    print('\nDone.')


if __name__ == '__main__':
    main()
