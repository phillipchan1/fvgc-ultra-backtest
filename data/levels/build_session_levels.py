#!/usr/bin/env python3
"""
Build session H/L rows for liquidity_levels.csv (consolidated NQ 30s), resampled where needed.

Use `build_liquidity_levels.py` for the single output file; run this module with `--write`
only for debugging. Returns a DataFrame with the unified liquidity schema (HTF columns NaN).
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, time as dtime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytz

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from fvgc.model import compute_swing_points  # noqa: E402

from data.levels.level_registry import LEVEL_REGISTRY, iter_registry  # noqa: E402
from data.levels.nq_1m_front import load_nq_1m  # noqa: E402

NY_TZ = pytz.timezone('America/New_York')
RTH_START = dtime(9, 30)
RTH_END = dtime(16, 0)
OVERNIGHT_START = dtime(18, 0)

TRADING_DAYS_PATH = ROOT / 'data' / 'trading_days' / 'trading_days.csv'
OUTPUT_PATH = ROOT / 'data' / 'levels' / 'session_levels.csv'  # optional --write debug output

REG_BY_NAME = {e.name: e for e in iter_registry() if e.builder == 'build_session_levels'}

# Pre-RTH sweep applies to these level names only (not overnight_*, or_*, stubs).
def _session_fvg_na() -> dict:
    """Unified liquidity_levels schema: HTF fields empty for session rows."""
    return {
        'timeframe': np.nan,
        'fvg_direction': np.nan,
        'fvg_top': np.nan,
        'fvg_bottom': np.nan,
        'fvg_mid': np.nan,
        'created_date': np.nan,
        'bars_old': np.nan,
    }


PRE_RTH_SWEEP_LEVEL_NAMES = frozenset({
    'prev_day_high', 'prev_day_low', 'london_high', 'london_low',
    'asia_high', 'asia_low', '6am_high', '6am_low',
    'nwog_high', 'nwog_low', 'bsl_level', 'ssl_level',
})


def _finalize_pre_rth_sweep(rows: list[dict], overnight: pd.DataFrame) -> None:
    """Mutate rows with swept_pre_rth / swept_pre_rth_time using overnight window only."""
    on = overnight.sort_values('ts_ny').reset_index(drop=True) if not overnight.empty else overnight
    for row in rows:
        row['swept_pre_rth'] = ''
        row['swept_pre_rth_time'] = ''
        nm = row['level_name']
        if nm not in PRE_RTH_SWEEP_LEVEL_NAMES:
            continue
        px = row.get('price')
        if px is None or (isinstance(px, float) and np.isnan(px)):
            continue
        price = float(px)
        side = REG_BY_NAME[nm].side
        if on.empty:
            row['swept_pre_rth'] = False
            continue
        if side == 'resistance':
            mask = on['high'] >= price
        elif side == 'support':
            mask = on['low'] <= price
        else:
            mask = (on['high'] >= price) | (on['low'] <= price)
        hit = on[mask]
        if hit.empty:
            row['swept_pre_rth'] = False
        else:
            row['swept_pre_rth'] = True
            first_ts = hit.sort_values('ts_ny').iloc[0]['ts_ny']
            ts = pd.Timestamp(first_ts)
            row['swept_pre_rth_time'] = ts.isoformat()


def _mask_rth(ts: pd.Series) -> pd.Series:
    t = ts.dt.time
    return (t >= RTH_START) & (t < RTH_END)


def _prior_trading_date(d: date, trading_dates: list[date]) -> date | None:
    normalized = [t.date() if hasattr(t, 'date') else t for t in trading_dates]
    d_norm = d.date() if hasattr(d, 'date') else d
    try:
        idx = normalized.index(d_norm)
    except ValueError:
        return None
    return normalized[idx - 1] if idx > 0 else None


def _friday_before(d: date) -> date | None:
    wd = d.weekday()  # Mon=0
    if wd != 0:
        return None
    prev = d - timedelta(days=1)
    while prev.weekday() != 4:  # Friday
        prev -= timedelta(days=1)
    return prev


def build_15m_with_ts(nq: pd.DataFrame) -> pd.DataFrame:
    """15m OHLCV with timestamp_ny at bar end (right label)."""
    x = nq[['ts_ny', 'open', 'high', 'low', 'close', 'volume']].copy()
    x = x.set_index('ts_ny')
    g = x.resample('15min', label='right', closed='right').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
    }).dropna(how='all')
    g = g.reset_index()
    g.rename(columns={'ts_ny': 'timestamp_ny'}, inplace=True)
    return g


def london_swing_levels(day_15m: pd.DataFrame, session_date: date) -> tuple[float | None, float | None, str]:
    """BSL = highest confirmed swing high in London 02:00–08:00; SSL = lowest swing low."""
    if day_15m.empty or len(day_15m) < 5:
        return None, None, 'insufficient_15m_bars'
    m = compute_swing_points(day_15m)
    if m.empty:
        return None, None, 'no_swings'
    lo = dtime(2, 0)
    hi = dtime(8, 0)
    highs = []
    lows = []
    for _, row in m.iterrows():
        ts = day_15m.iloc[int(row['idx'])]['timestamp_ny']
        if not isinstance(ts, pd.Timestamp):
            ts = pd.Timestamp(ts)
        if ts.tzinfo is None:
            ts = NY_TZ.localize(ts)
        t = ts.timetz().replace(tzinfo=None)
        if ts.date() != session_date:
            continue
        if lo <= t < hi:
            if row['type'] == 'high':
                highs.append(float(row['price']))
            elif row['type'] == 'low':
                lows.append(float(row['price']))
    if not highs and not lows:
        return None, None, 'no_swings_in_london_window'
    bsl = max(highs) if highs else None
    ssl = min(lows) if lows else None
    return bsl, ssl, ''


def compute_day_levels(
    d: date,
    by_date: dict[date, pd.DataFrame],
    trading_dates: list[date],
    nq_15m_full: pd.DataFrame,
) -> list[dict]:
    rows: list[dict] = []
    day = by_date.get(d)
    if day is None or day.empty:
        return rows

    def add_row(level_name: str, price: float | None, notes: str = '') -> None:
        reg = REG_BY_NAME[level_name]
        rows.append({
            'date': d,
            'level_name': level_name,
            'group': reg.group,
            'side': reg.side,
            'price': price,
            'available_time': reg.available_time,
            **_session_fvg_na(),
            'notes': notes,
        })

    # --- prev day ---
    pd_prev = _prior_trading_date(d, trading_dates)
    if pd_prev is not None and pd_prev in by_date:
        pr = by_date[pd_prev]
        pr_rth = pr[_mask_rth(pr['ts_ny'])]
        if not pr_rth.empty:
            add_row('prev_day_high', float(pr_rth['high'].max()))
            add_row('prev_day_low', float(pr_rth['low'].min()))
        else:
            add_row('prev_day_high', None, 'no_prior_rth')
            add_row('prev_day_low', None, 'no_prior_rth')
    else:
        add_row('prev_day_high', None, 'no_prior_trading_day')
        add_row('prev_day_low', None, 'no_prior_trading_day')

    times = day['ts_ny'].dt.time
    # London 02:00–08:00 same calendar date as session
    lon = day[(times >= dtime(2, 0)) & (times < dtime(8, 0))]
    if not lon.empty:
        add_row('london_high', float(lon['high'].max()))
        add_row('london_low', float(lon['low'].min()))
    else:
        add_row('london_high', None, 'no_bars')
        add_row('london_low', None, 'no_bars')

    # Asia: prior calendar day 19:00 through session date 02:00
    d_prev_cal = d - timedelta(days=1)
    asia_parts = []
    if d_prev_cal in by_date:
        p = by_date[d_prev_cal]
        asia_parts.append(p[p['ts_ny'].dt.time >= dtime(19, 0)])
    asia_parts.append(day[day['ts_ny'].dt.time < dtime(2, 0)])
    asia = pd.concat(asia_parts, ignore_index=True).sort_values('ts_ny') if asia_parts else pd.DataFrame()
    if not asia.empty:
        add_row('asia_high', float(asia['high'].max()))
        add_row('asia_low', float(asia['low'].min()))
    else:
        add_row('asia_high', None, 'no_bars')
        add_row('asia_low', None, 'no_bars')

    # Overnight: prior calendar day 18:00+ and session day before 09:30
    on_parts = []
    if d_prev_cal in by_date:
        p = by_date[d_prev_cal]
        on_parts.append(p[p['ts_ny'].dt.time >= OVERNIGHT_START])
    on_parts.append(day[day['ts_ny'].dt.time < RTH_START])
    overnight = pd.concat(on_parts, ignore_index=True).sort_values('ts_ny') if on_parts else pd.DataFrame()
    if not overnight.empty:
        add_row('overnight_high', float(overnight['high'].max()))
        add_row('overnight_low', float(overnight['low'].min()))
    else:
        add_row('overnight_high', None, 'no_bars')
        add_row('overnight_low', None, 'no_bars')

    # 6am window 04:00–08:00
    six = day[(times >= dtime(4, 0)) & (times < dtime(8, 0))]
    if not six.empty:
        add_row('6am_high', float(six['high'].max()))
        add_row('6am_low', float(six['low'].min()))
    else:
        add_row('6am_high', None, 'no_bars')
        add_row('6am_low', None, 'no_bars')

    # NWOG: Monday only
    fri = _friday_before(d)
    if fri is not None and fri in by_date:
        fri_rth = by_date[fri][_mask_rth(by_date[fri]['ts_ny'])]
        cur_rth = day[_mask_rth(day['ts_ny'])]
        if not fri_rth.empty and not cur_rth.empty:
            fri_close = float(fri_rth.iloc[-1]['close'])
            mon_open = float(cur_rth.iloc[0]['open'])
            add_row('nwog_high', max(fri_close, mon_open))
            add_row('nwog_low', min(fri_close, mon_open))
        else:
            add_row('nwog_high', None, 'missing_friday_or_monday_rth')
            add_row('nwog_low', None, 'missing_friday_or_monday_rth')
    else:
        add_row('nwog_high', np.nan, 'not_monday_or_no_friday')
        add_row('nwog_low', np.nan, 'not_monday_or_no_friday')

    # BSL / SSL on 15m — use all 15m bars for session_date d (wide context for swing)
    d15 = nq_15m_full[nq_15m_full['timestamp_ny'].dt.date == d].copy()
    if not d15.empty:
        bsl, ssl, note = london_swing_levels(d15, d)
        add_row('bsl_level', bsl, note)
        add_row('ssl_level', ssl, note)
    else:
        add_row('bsl_level', None, 'no_15m')
        add_row('ssl_level', None, 'no_15m')

    # OR stub
    add_row('or_high', np.nan, 'stub_not_implemented')
    add_row('or_low', np.nan, 'stub_not_implemented')

    _finalize_pre_rth_sweep(rows, overnight)

    return rows


LIQUIDITY_COLUMN_ORDER = (
    'date', 'level_name', 'group', 'side', 'price', 'available_time',
    'swept_pre_rth', 'swept_pre_rth_time',
    'timeframe', 'fvg_direction', 'fvg_top', 'fvg_bottom', 'fvg_mid',
    'created_date', 'bars_old', 'notes',
)


def build_session_dataframe() -> pd.DataFrame:
    td = pd.read_csv(TRADING_DAYS_PATH)
    td['date'] = pd.to_datetime(td['date']).dt.date
    trading_dates = sorted(td['date'].unique())

    nq = load_nq_1m()
    by_date = {d: g for d, g in nq.groupby('date_ny', sort=False)}
    nq_15m_full = build_15m_with_ts(nq)

    all_rows: list[dict] = []
    for d in trading_dates:
        if d not in by_date:
            continue
        all_rows.extend(compute_day_levels(d, by_date, trading_dates, nq_15m_full))

    out = pd.DataFrame(all_rows)
    for c in LIQUIDITY_COLUMN_ORDER:
        if c not in out.columns:
            out[c] = np.nan
    return out[list(LIQUIDITY_COLUMN_ORDER)]


def main(write: bool = False) -> pd.DataFrame:
    print('=' * 60)
    print('Building session level rows (liquidity schema)')
    print('=' * 60)

    out = build_session_dataframe()
    if write:
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        out.to_csv(OUTPUT_PATH, index=False)
        print(f'Wrote {len(out)} rows to {OUTPUT_PATH}')
    else:
        print(f'Built {len(out)} session rows (no file write)')
    return out


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description='Session levels builder (use build_liquidity_levels.py for production).')
    ap.add_argument('--write', action='store_true', help=f'Write debug CSV to {OUTPUT_PATH}')
    args = ap.parse_args()
    df = main(write=args.write)
    print(df.head(3).to_string())
