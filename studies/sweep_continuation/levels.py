"""Liquidity level construction.

Builds a DataFrame of liquidity levels keyed by the 30s bar index at
which each level becomes "active" (i.e. known to the market and
eligible to be swept). Level types included in v1:

  PDH / PDL         Prior RTH (09:30-16:00 ET) session high/low
  ONH / ONL         Globex session high/low (18:00 ET prior -> 09:29:59 ET)
  ORH_5 / ORL_5     Opening range high/low over 5 minutes from 09:30 ET
  ORH_15 / ORL_15   Opening range high/low over 15 minutes from 09:30 ET
  ORH_30 / ORL_30   Opening range high/low over 30 minutes from 09:30 ET
  H1_SH / H1_SL     1H fractal swing high/low (n=2)
  H4_SH / H4_SL     4H fractal swing high/low (n=2)
  PWH / PWL         Prior week (Mon-Fri RTH) high/low

Each row: {level_id, type, side, price, created_idx, created_ts}
where side in {'high','low'} tells us which wick direction would
constitute a sweep.

v1 deliberately skips:
  - Equal-highs clustering (documented gap)
  - 4H FVG boundaries (documented gap)
"""

from __future__ import annotations

import pandas as pd
from datetime import time as dtime
from typing import List, Dict

from fvgc.constants import NY_TZ  # noqa: F401 — already applied on load


RTH_START = dtime(9, 30)
RTH_END = dtime(16, 0)
GLOBEX_START = dtime(18, 0)


def _time(ts: pd.Timestamp) -> dtime:
    return ts.time()


def _first_idx_at_or_after(candles: pd.DataFrame, day_col: pd.Series,
                            day, t_start: dtime) -> int | None:
    """First bar index on `day` with ts_ny.time() >= t_start."""
    mask = (day_col == day) & (candles['_time_ny'] >= t_start)
    if not mask.any():
        return None
    return int(mask.idxmax())


def _prepare(candles: pd.DataFrame) -> pd.DataFrame:
    """Attach helper columns used by all level builders."""
    c = candles.copy()
    c['_date_ny'] = c['timestamp_ny'].dt.date
    c['_time_ny'] = c['timestamp_ny'].dt.time
    c['_dow'] = c['timestamp_ny'].dt.dayofweek
    # iso week for weekly grouping; use Mon-Sun weeks
    c['_iso_year'] = c['timestamp_ny'].dt.isocalendar().year
    c['_iso_week'] = c['timestamp_ny'].dt.isocalendar().week
    return c


# -------------------------------------------------------------------
# Daily levels: PDH/PDL, ONH/ONL, ORH/ORL
# -------------------------------------------------------------------

def _build_daily_levels(c: pd.DataFrame) -> List[Dict]:
    out: List[Dict] = []

    # Masks
    rth_mask = (c['_time_ny'] >= RTH_START) & (c['_time_ny'] < RTH_END)
    # Globex: 18:00 ET on day D through 09:30 ET on day D+1.
    # We bucket each Globex session by the *RTH date it precedes*.
    # Build globex_date = date+1 if time >= 18:00 else date.
    eve = c['_time_ny'] >= GLOBEX_START
    globex_date = c['_date_ny'].where(~eve,
        (c['timestamp_ny'] + pd.Timedelta(days=1)).dt.date)
    # Only rows before RTH on the target day belong to overnight:
    is_overnight = (c['_time_ny'] >= GLOBEX_START) | (c['_time_ny'] < RTH_START)

    # --- Per-RTH-day aggregates ---
    rth = c[rth_mask]
    for day, grp in rth.groupby('_date_ny', sort=True):
        day_hi = float(grp['high'].max())
        day_lo = float(grp['low'].min())
        last_bar = grp.iloc[-1]
        # PDH/PDL become active at the *next* day's first bar.
        next_day_mask = c['_date_ny'] > day
        if next_day_mask.any():
            next_idx = int(next_day_mask.idxmax())
            next_ts = c.iloc[next_idx]['timestamp_ny']
            out.append({
                'type': 'PDH', 'side': 'high', 'price': day_hi,
                'created_idx': next_idx, 'created_ts': next_ts,
                'ref_date': day,
            })
            out.append({
                'type': 'PDL', 'side': 'low', 'price': day_lo,
                'created_idx': next_idx, 'created_ts': next_ts,
                'ref_date': day,
            })

    # --- Per-Globex-session aggregates ---
    on_mask = is_overnight & c['_date_ny'].notna()
    on = c[on_mask].copy()
    on['_globex_date'] = globex_date[on.index]
    for gd, grp in on.groupby('_globex_date', sort=True):
        if len(grp) < 5:
            continue
        onh = float(grp['high'].max())
        onl = float(grp['low'].min())
        # ON levels become active at the first bar on RTH day gd at/after 09:30.
        first_rth_mask = (c['_date_ny'] == gd) & (c['_time_ny'] >= RTH_START)
        if not first_rth_mask.any():
            continue
        first_rth_idx = int(first_rth_mask.idxmax())
        ts = c.iloc[first_rth_idx]['timestamp_ny']
        out.append({
            'type': 'ONH', 'side': 'high', 'price': onh,
            'created_idx': first_rth_idx, 'created_ts': ts, 'ref_date': gd,
        })
        out.append({
            'type': 'ONL', 'side': 'low', 'price': onl,
            'created_idx': first_rth_idx, 'created_ts': ts, 'ref_date': gd,
        })

    # --- Opening range levels (5/15/30 min) ---
    for minutes in (5, 15, 30):
        end_time = (pd.Timestamp('1970-01-01') +
                    pd.Timedelta(hours=9, minutes=30 + minutes)).time()
        for day, grp in rth.groupby('_date_ny', sort=True):
            or_grp = grp[grp['_time_ny'] < end_time]
            if len(or_grp) < 2:
                continue
            orh = float(or_grp['high'].max())
            orl = float(or_grp['low'].min())
            # active from the first bar whose time >= end_time
            mask = (c['_date_ny'] == day) & (c['_time_ny'] >= end_time)
            if not mask.any():
                continue
            active_idx = int(mask.idxmax())
            ts = c.iloc[active_idx]['timestamp_ny']
            out.append({
                'type': f'ORH_{minutes}', 'side': 'high', 'price': orh,
                'created_idx': active_idx, 'created_ts': ts, 'ref_date': day,
            })
            out.append({
                'type': f'ORL_{minutes}', 'side': 'low', 'price': orl,
                'created_idx': active_idx, 'created_ts': ts, 'ref_date': day,
            })
    return out


# -------------------------------------------------------------------
# Weekly levels: PWH/PWL
# -------------------------------------------------------------------

def _build_weekly_levels(c: pd.DataFrame) -> List[Dict]:
    out: List[Dict] = []
    rth_mask = (c['_time_ny'] >= RTH_START) & (c['_time_ny'] < RTH_END)
    rth = c[rth_mask]
    weekly = rth.groupby(['_iso_year', '_iso_week']).agg(
        high=('high', 'max'), low=('low', 'min'),
        end_date=('_date_ny', 'max'),
    ).reset_index().sort_values(['_iso_year', '_iso_week'])

    for _, row in weekly.iterrows():
        end_date = row['end_date']
        # PWH/PWL become active at the first bar strictly after `end_date`.
        next_day_mask = c['_date_ny'] > end_date
        if not next_day_mask.any():
            continue
        active_idx = int(next_day_mask.idxmax())
        ts = c.iloc[active_idx]['timestamp_ny']
        out.append({'type': 'PWH', 'side': 'high', 'price': float(row['high']),
                    'created_idx': active_idx, 'created_ts': ts,
                    'ref_date': end_date})
        out.append({'type': 'PWL', 'side': 'low', 'price': float(row['low']),
                    'created_idx': active_idx, 'created_ts': ts,
                    'ref_date': end_date})
    return out


# -------------------------------------------------------------------
# Fractal swings on resampled timeframes
# -------------------------------------------------------------------

def _resample(c: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Resample 30s candles to a higher TF, preserving UTC timestamps."""
    idx = pd.DatetimeIndex(c['timestamp_utc'])
    agg = pd.DataFrame({
        'open': c['open'].values,
        'high': c['high'].values,
        'low': c['low'].values,
        'close': c['close'].values,
    }, index=idx)
    r = agg.resample(rule, label='left', closed='left').agg(
        {'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'}
    ).dropna()
    r = r.reset_index().rename(columns={'index': 'timestamp_utc'})
    # Ensure tz is preserved (some pandas versions drop it on reset_index)
    if r['timestamp_utc'].dt.tz is None:
        r['timestamp_utc'] = r['timestamp_utc'].dt.tz_localize('UTC')
    return r


def _fractal_swings(bars: pd.DataFrame, n: int = 2) -> List[Dict]:
    """n=2 fractal. Confirmation happens n bars after the swing bar."""
    out = []
    highs = bars['high'].values
    lows = bars['low'].values
    ts = bars['timestamp_utc'].values
    for i in range(n, len(bars) - n):
        h, l = highs[i], lows[i]
        is_high = all(h > highs[i - k] and h > highs[i + k]
                      for k in range(1, n + 1))
        is_low = all(l < lows[i - k] and l < lows[i + k]
                     for k in range(1, n + 1))
        confirm_ts = ts[i + n]
        if is_high:
            out.append({'side': 'high', 'price': float(h),
                        'confirm_utc': pd.Timestamp(confirm_ts)})
        if is_low:
            out.append({'side': 'low', 'price': float(l),
                        'confirm_utc': pd.Timestamp(confirm_ts)})
    return out


def _build_swing_levels(c: pd.DataFrame, rule: str, tag: str) -> List[Dict]:
    bars = _resample(c, rule)
    if len(bars) < 5:
        return []
    swings = _fractal_swings(bars, n=2)
    if not swings:
        return []
    # Map each swing's confirmation UTC to the 30s bar that confirms it
    ts_30s = pd.DatetimeIndex(c['timestamp_utc'])
    out = []
    for s in swings:
        confirm_utc = pd.Timestamp(s['confirm_utc'])
        if confirm_utc.tzinfo is None:
            confirm_utc = confirm_utc.tz_localize('UTC')
        pos = int(ts_30s.searchsorted(confirm_utc, side='left'))
        if pos >= len(c):
            continue
        active_idx = int(pos)
        ts_ny = c.iloc[active_idx]['timestamp_ny']
        out.append({
            'type': f'{tag}_S{"H" if s["side"] == "high" else "L"}',
            'side': s['side'], 'price': s['price'],
            'created_idx': active_idx, 'created_ts': ts_ny,
            'ref_date': ts_ny.date(),
        })
    return out


# -------------------------------------------------------------------
# Public API
# -------------------------------------------------------------------

def build_levels(candles: pd.DataFrame) -> pd.DataFrame:
    """Return a DataFrame of liquidity levels for the full candle history.

    Columns: level_id, type, side, price, created_idx, created_ts, ref_date
    Levels are ordered by created_idx.
    """
    c = _prepare(candles)
    rows: List[Dict] = []
    rows.extend(_build_daily_levels(c))
    rows.extend(_build_weekly_levels(c))
    rows.extend(_build_swing_levels(c, '1h', 'H1'))
    rows.extend(_build_swing_levels(c, '4h', 'H4'))
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df.sort_values('created_idx').reset_index(drop=True)
    df.insert(0, 'level_id', range(1, len(df) + 1))
    return df
