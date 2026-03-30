#!/usr/bin/env python3
"""
Build trading_days.csv — one row per RTH trading day with ~50 properties
computed from NQ 1-minute bars, VIXY daily closes, and news/event data.

Usage:
    python data/trading_days/build_trading_days.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import numpy as np
import pytz
from datetime import time as dtime, timedelta

NY_TZ = pytz.timezone('America/New_York')

NQ_1M_PATH = ROOT / 'data' / 'raw' / 'glbx-mdp3-20200927-20260221.ohlcv-1m.csv'
VIXY_PATH = ROOT / 'data' / 'raw' / 'xnas-itch-20201203-20251203.ohlcv-1m.csv'
EVENTS_PATH = ROOT / 'data' / 'raw' / 'market_high_volume_events_2020_2025.csv'
OUTPUT_PATH = ROOT / 'data' / 'trading_days' / 'trading_days.csv'

RTH_START = dtime(9, 30)
RTH_END = dtime(16, 0)
OVERNIGHT_START = dtime(18, 0)
MIN_FVG_SIZE = 3.0

NQ_QUARTERLY_ORDER = ['H', 'M', 'U', 'Z']
PRICE_FLOOR = 10_000

# Known event times (ET) for pre-RTH / during-session classification
EVENT_TIMES = {
    'NFP': dtime(8, 30),
    'CPI': dtime(8, 30),
    'FOMC Statement': dtime(14, 0),
    'FOMC Minutes': dtime(14, 0),
    'OPEX': None,
    'Triple/Quadruple Witching': None,
}


# ===================================================================
# Data loading
# ===================================================================

def load_nq_1m() -> pd.DataFrame:
    print("Loading NQ 1-minute bars...")
    df = pd.read_csv(NQ_1M_PATH, dtype={'symbol': str})
    print(f"  {len(df):,} raw rows")

    df = df[~df['symbol'].str.contains('-', na=False)].copy()
    print(f"  {len(df):,} after dropping spreads")

    df['ts_event'] = pd.to_datetime(df['ts_event'], utc=True)
    df['ts_ny'] = df['ts_event'].dt.tz_convert(NY_TZ)
    df['date_ny'] = df['ts_ny'].dt.date

    df = select_front_month(df)

    mask = (df['open'] >= PRICE_FLOOR) & (df['close'] >= PRICE_FLOOR) & \
           (df['low'] >= PRICE_FLOOR) & (df['high'] >= PRICE_FLOOR)
    n_dropped = (~mask).sum()
    if n_dropped:
        print(f"  Dropped {n_dropped:,} sub-floor rows")
    df = df[mask].copy()

    df = df.sort_values('ts_ny').reset_index(drop=True)
    print(f"  {len(df):,} clean 1-min bars, {df['date_ny'].nunique()} calendar dates")
    return df


def select_front_month(df: pd.DataFrame) -> pd.DataFrame:
    daily_vol = (
        df.groupby(['date_ny', 'symbol'])['volume']
        .sum()
        .reset_index()
        .sort_values(['date_ny', 'volume'], ascending=[True, False])
    )
    front = daily_vol.drop_duplicates(subset='date_ny', keep='first')[['date_ny', 'symbol']]
    front = front.rename(columns={'symbol': 'front_month'})

    fm = front.sort_values('date_ny').reset_index(drop=True)
    for i in range(1, len(fm) - 1):
        if fm.loc[i - 1, 'front_month'] == fm.loc[i + 1, 'front_month'] and \
           fm.loc[i, 'front_month'] != fm.loc[i - 1, 'front_month']:
            fm.loc[i, 'front_month'] = fm.loc[i - 1, 'front_month']

    df = df.merge(fm, on='date_ny', how='left')
    n_back = (df['symbol'] != df['front_month']).sum()
    df = df[df['symbol'] == df['front_month']].copy()
    print(f"  Dropped {n_back:,} back-month rows")
    df = df.drop(columns=['front_month'])
    return df


def load_vixy() -> pd.DataFrame:
    print("Loading VIXY 1-minute bars...")
    df = pd.read_csv(VIXY_PATH)
    df['ts_event'] = pd.to_datetime(df['ts_event'], utc=True)
    df['ts_ny'] = df['ts_event'].dt.tz_convert(NY_TZ)
    df['date_ny'] = df['ts_ny'].dt.date

    rth = df[(df['ts_ny'].dt.time >= RTH_START) & (df['ts_ny'].dt.time < RTH_END)]
    daily = rth.groupby('date_ny').agg(
        vixy_close=('close', 'last'),
        vixy_high=('high', 'max'),
        vixy_low=('low', 'min'),
    ).reset_index()

    print(f"  {len(daily)} VIXY trading days")
    return daily


def load_events() -> pd.DataFrame:
    print("Loading market events...")
    df = pd.read_csv(EVENTS_PATH)
    df['date'] = pd.to_datetime(df['date']).dt.date
    print(f"  {len(df)} events loaded")
    return df


# ===================================================================
# FVG counting on 1-min bars
# ===================================================================

def count_fvgs_in_slice(bars: pd.DataFrame) -> dict:
    """Count bullish, bearish, and total FVGs in a slice of 1-min bars."""
    bullish = 0
    bearish = 0
    highs = bars['high'].values
    lows = bars['low'].values

    for i in range(2, len(bars)):
        if lows[i] > highs[i - 2]:
            gap = lows[i] - highs[i - 2]
            if gap >= MIN_FVG_SIZE:
                bullish += 1
        if highs[i] < lows[i - 2]:
            gap = lows[i - 2] - highs[i]
            if gap >= MIN_FVG_SIZE:
                bearish += 1

    return {'bullish': bullish, 'bearish': bearish, 'total': bullish + bearish}


# ===================================================================
# Per-day computation
# ===================================================================

def compute_day_properties(day_bars: pd.DataFrame, prior_day: dict | None,
                           overnight_bars: pd.DataFrame) -> dict:
    """Compute all properties for a single trading day."""
    date = day_bars.iloc[0]['date_ny']
    times = day_bars['ts_ny'].dt.time

    # RTH session bars
    rth = day_bars[(times >= RTH_START) & (times < RTH_END)]
    if rth.empty:
        return None

    row = {'date': date}

    # --- RTH session stats ---
    row['rth_open'] = rth.iloc[0]['open']
    row['rth_close'] = rth.iloc[-1]['close']
    row['rth_high'] = rth['high'].max()
    row['rth_low'] = rth['low'].min()
    row['rth_range'] = row['rth_high'] - row['rth_low']

    # --- Opening ranges ---
    for label, end_time in [('5min', dtime(9, 35)), ('15min', dtime(9, 45)), ('45min', dtime(10, 15))]:
        orng = rth[(rth['ts_ny'].dt.time >= RTH_START) & (rth['ts_ny'].dt.time < end_time)]
        if orng.empty:
            row[f'or_{label}_high'] = np.nan
            row[f'or_{label}_low'] = np.nan
            row[f'or_{label}_range'] = np.nan
        else:
            row[f'or_{label}_high'] = orng['high'].max()
            row[f'or_{label}_low'] = orng['low'].min()
            row[f'or_{label}_range'] = row[f'or_{label}_high'] - row[f'or_{label}_low']

    # --- Overnight session ---
    if not overnight_bars.empty:
        row['overnight_high'] = overnight_bars['high'].max()
        row['overnight_low'] = overnight_bars['low'].min()
        row['overnight_range'] = row['overnight_high'] - row['overnight_low']
        on_open = overnight_bars.iloc[0]['open']
        on_close = overnight_bars.iloc[-1]['close']
        pct_move = (on_close - on_open) / on_open * 100 if on_open != 0 else 0
        if pct_move > 0.1:
            row['overnight_direction'] = 'up'
        elif pct_move < -0.1:
            row['overnight_direction'] = 'down'
        else:
            row['overnight_direction'] = 'flat'
    else:
        row['overnight_high'] = np.nan
        row['overnight_low'] = np.nan
        row['overnight_range'] = np.nan
        row['overnight_direction'] = np.nan

    # --- Gap from prior close ---
    if prior_day is not None:
        row['gap_from_prior_close'] = row['rth_open'] - prior_day['rth_close']
        if prior_day['rth_close'] != 0:
            row['gap_from_prior_close_pct'] = row['gap_from_prior_close'] / prior_day['rth_close'] * 100
        else:
            row['gap_from_prior_close_pct'] = np.nan
    else:
        row['gap_from_prior_close'] = np.nan
        row['gap_from_prior_close_pct'] = np.nan

    # --- Prior day context ---
    if prior_day is not None:
        row['prior_day_range'] = prior_day['rth_range']
        denom = prior_day['rth_high'] - prior_day['rth_low']
        if denom > 0:
            row['prior_day_close_position'] = (prior_day['rth_close'] - prior_day['rth_low']) / denom
        else:
            row['prior_day_close_position'] = np.nan
    else:
        row['prior_day_range'] = np.nan
        row['prior_day_close_position'] = np.nan

    # --- 15-min macro windows ---
    macro_windows = [
        (1, dtime(9, 30), dtime(9, 45)),
        (2, dtime(9, 45), dtime(10, 0)),
        (3, dtime(10, 0), dtime(10, 15)),
        (4, dtime(10, 15), dtime(10, 30)),
    ]
    for n, wstart, wend in macro_windows:
        w = rth[(rth['ts_ny'].dt.time >= wstart) & (rth['ts_ny'].dt.time < wend)]
        if w.empty:
            row[f'macro_{n}_range'] = np.nan
            row[f'macro_{n}_num_fvgs'] = 0
        else:
            row[f'macro_{n}_range'] = w['high'].max() - w['low'].min()
            fvgs = count_fvgs_in_slice(w.reset_index(drop=True))
            row[f'macro_{n}_num_fvgs'] = fvgs['total']

    # --- 9:30 candle ---
    candle_930 = rth[rth['ts_ny'].dt.time == RTH_START]
    if not candle_930.empty:
        c = candle_930.iloc[0]
        row['candle_930_range'] = c['high'] - c['low']
        row['candle_930_body'] = abs(c['close'] - c['open'])
        row['candle_930_direction'] = 'bullish' if c['close'] > c['open'] else 'bearish'
    else:
        row['candle_930_range'] = np.nan
        row['candle_930_body'] = np.nan
        row['candle_930_direction'] = np.nan

    # --- FVG counts ---
    first_5 = rth[(rth['ts_ny'].dt.time >= RTH_START) & (rth['ts_ny'].dt.time < dtime(9, 35))]
    first_15 = rth[(rth['ts_ny'].dt.time >= RTH_START) & (rth['ts_ny'].dt.time < dtime(9, 45))]

    fvg5 = count_fvgs_in_slice(first_5.reset_index(drop=True)) if len(first_5) >= 3 else {'bullish': 0, 'bearish': 0, 'total': 0}
    fvg15 = count_fvgs_in_slice(first_15.reset_index(drop=True)) if len(first_15) >= 3 else {'bullish': 0, 'bearish': 0, 'total': 0}

    row['fvgs_first_5min'] = fvg5['total']
    row['fvgs_first_5min_bullish'] = fvg5['bullish']
    row['fvgs_first_5min_bearish'] = fvg5['bearish']
    row['fvgs_first_15min'] = fvg15['total']
    row['fvgs_first_15min_bullish'] = fvg15['bullish']
    row['fvgs_first_15min_bearish'] = fvg15['bearish']

    # --- Calendar ---
    from datetime import date as dt_date
    d = date if isinstance(date, dt_date) else pd.Timestamp(date).date()
    row['day_of_week'] = d.weekday()
    row['day_of_week_name'] = d.strftime('%A')
    row['month'] = d.month
    row['month_name'] = d.strftime('%B')
    row['day_of_month'] = d.day

    return row


# ===================================================================
# Calendar flags (need full list of trading dates)
# ===================================================================

def add_calendar_flags(df: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    dates = pd.to_datetime(df['date'])
    df = df.copy()

    # Month start / end: first/last 3 trading days of each month
    df['_ym'] = dates.dt.to_period('M')
    df['is_month_start'] = False
    df['is_month_end'] = False
    for ym, grp in df.groupby('_ym'):
        idxs = grp.index.tolist()
        for i in idxs[:3]:
            df.loc[i, 'is_month_start'] = True
        for i in idxs[-3:]:
            df.loc[i, 'is_month_end'] = True
    df = df.drop(columns=['_ym'])

    # FOMC week: week containing an FOMC Statement
    fomc_dates = set(events[events['event_type'] == 'FOMC Statement']['date'].values)
    fomc_weeks = {
        pd.Timestamp(fd) - timedelta(days=pd.Timestamp(fd).weekday())
        for fd in fomc_dates
    }
    df['is_fomc_week'] = dates.apply(
        lambda d: (d - timedelta(days=d.weekday())) in fomc_weeks
    )

    # OpEx week: week containing OPEX event or third Friday
    opex_dates = set(events[events['event_type'] == 'OPEX']['date'].values)
    witching_dates = set(events[events['event_type'] == 'Triple/Quadruple Witching']['date'].values)
    opex_all = opex_dates | witching_dates
    opex_weeks = set()
    for od in opex_all:
        od_ts = pd.Timestamp(od)
        week_start = od_ts - timedelta(days=od_ts.weekday())
        opex_weeks.add(week_start)
    df['is_opex_week'] = dates.apply(
        lambda d: (d - timedelta(days=d.weekday())) in opex_weeks
    )

    # Quad witching: third Friday of Mar, Jun, Sep, Dec
    witching_set = set(pd.Timestamp(d) for d in witching_dates)
    df['is_quad_witching'] = dates.isin(witching_set)

    return df


def add_news_flags(df: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    events_by_date = events.groupby('date').agg(
        event_types=('event_type', list),
        event_names=('event', list),
    ).to_dict('index')

    has_red = []
    has_pre_rth = []
    has_during = []
    event_names_col = []

    for _, row in df.iterrows():
        d = row['date']
        if d in events_by_date:
            info = events_by_date[d]
            has_red.append(True)
            event_names_col.append(', '.join(info['event_names']))

            pre_rth = False
            during = False
            for et in info['event_types']:
                t = EVENT_TIMES.get(et)
                if t is not None:
                    if t < dtime(10, 0):
                        pre_rth = True
                    if RTH_START <= t <= dtime(11, 0):
                        during = True
            has_pre_rth.append(pre_rth)
            has_during.append(during)
        else:
            has_red.append(False)
            has_pre_rth.append(False)
            has_during.append(False)
            event_names_col.append('')

    df['has_red_folder_news'] = has_red
    df['has_pre_rth_news'] = has_pre_rth
    df['has_during_session_news'] = has_during
    df['red_folder_event_names'] = event_names_col

    return df


def add_vixy_regime(df: pd.DataFrame, vixy: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    vixy = vixy.copy()
    vixy['date_ny'] = pd.to_datetime(vixy['date_ny']).dt.date

    vixy_sorted = vixy.sort_values('date_ny').reset_index(drop=True)
    vixy_sorted['vixy_prior_close'] = vixy_sorted['vixy_close'].shift(1)

    vixy_map = dict(zip(vixy_sorted['date_ny'].values, vixy_sorted['vixy_prior_close'].values))

    df['vixy_prior_close'] = df['date'].map(vixy_map)

    valid = df['vixy_prior_close'].dropna()
    if len(valid) > 0:
        q25, q50, q75 = valid.quantile([0.25, 0.5, 0.75])

        def regime(v):
            if pd.isna(v):
                return np.nan
            if v <= q25:
                return 'low'
            elif v <= q50:
                return 'normal'
            elif v <= q75:
                return 'elevated'
            else:
                return 'high'

        df['vixy_regime'] = df['vixy_prior_close'].apply(regime)
    else:
        df['vixy_regime'] = np.nan

    return df


# ===================================================================
# Main
# ===================================================================

def main():
    print("=" * 60)
    print("Building trading_days.csv")
    print("=" * 60)

    nq = load_nq_1m()
    vixy = load_vixy()
    events = load_events()

    all_dates = sorted(nq['date_ny'].unique())
    print(f"\nProcessing {len(all_dates)} calendar dates...")

    # Pre-group for faster access
    by_date = {d: g for d, g in nq.groupby('date_ny')}

    rows = []
    prior_day_info = None
    processed = 0

    for i, date in enumerate(all_dates):
        day_bars = by_date[date]

        # Identify RTH bars to decide if this is a trading day
        rth_bars = day_bars[
            (day_bars['ts_ny'].dt.time >= RTH_START) &
            (day_bars['ts_ny'].dt.time < RTH_END)
        ]
        if rth_bars.empty:
            continue

        # Overnight: from prior date 18:00 to current date 09:30
        if i > 0:
            prior_date = all_dates[i - 1]
            prior_bars = by_date.get(prior_date, pd.DataFrame())
            # Bars from prior day 18:00+ plus current day before 9:30
            on_prior = prior_bars[prior_bars['ts_ny'].dt.time >= OVERNIGHT_START] if not prior_bars.empty else pd.DataFrame()
            on_current = day_bars[day_bars['ts_ny'].dt.time < RTH_START]
            overnight = pd.concat([on_prior, on_current]).sort_values('ts_ny')
        else:
            overnight = day_bars[day_bars['ts_ny'].dt.time < RTH_START]

        props = compute_day_properties(day_bars, prior_day_info, overnight)
        if props is not None:
            rows.append(props)
            prior_day_info = props
            processed += 1

        if processed % 200 == 0 and processed > 0:
            print(f"  ... {processed} trading days processed")

    print(f"  Total: {processed} trading days")

    df = pd.DataFrame(rows)

    # Add calendar / news / VIXY flags
    print("Adding calendar flags...")
    df = add_calendar_flags(df, events)
    print("Adding news flags...")
    df = add_news_flags(df, events)
    print("Adding VIXY regime...")
    df = add_vixy_regime(df, vixy)

    # Sort and write
    df = df.sort_values('date').reset_index(drop=True)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_PATH, index=False)
    print(f"\nWrote {len(df)} rows to {OUTPUT_PATH}")
    print(f"Columns ({len(df.columns)}): {list(df.columns)}")

    # Quick stats
    print(f"\nDate range: {df['date'].iloc[0]} to {df['date'].iloc[-1]}")
    print(f"Days with red folder news: {df['has_red_folder_news'].sum()}")
    print(f"FOMC weeks: {df['is_fomc_week'].sum()}")
    vixy_coverage = df['vixy_prior_close'].notna().sum()
    print(f"VIXY coverage: {vixy_coverage}/{len(df)} days")


if __name__ == '__main__':
    main()
