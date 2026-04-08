#!/usr/bin/env python3
"""
HTF FVG rows for liquidity_levels.csv.

Gap math mirrors fvgc.model.detect_fvg (see model.py) without FVG_START_TIME.
MIN_FVG_SIZE from fvgc.constants.

Mitigation (wick touch, universal in this pipeline):
  - Bullish FVG: mitigated when a later bar's low <= bottom (price wicks into gap from above).
  - Bearish FVG: mitigated when a later bar's high >= top (wick into gap from below).

Use build_liquidity_levels.py for the single output; run with --write for debug CSV only.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd
import pytz

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from fvgc.constants import MIN_FVG_SIZE  # noqa: E402

from data.levels.level_registry import iter_registry  # noqa: E402
from data.levels.nq_1m_front import load_nq_1m  # noqa: E402

NY_TZ = pytz.timezone('America/New_York')
RTH_OPEN = dtime(9, 30)
RTH_END = dtime(16, 0)
OVERNIGHT_START = dtime(18, 0)

TRADING_DAYS_PATH = ROOT / 'data' / 'trading_days' / 'trading_days.csv'
OUTPUT_PATH = ROOT / 'data' / 'levels' / 'htf_fvgs_active.csv'

TF_SPECS: tuple[tuple[str, str], ...] = (
    ('15m', '15min'),
    ('1H', '1h'),
    ('4H', '4h'),
    ('Daily', '1D'),
)


def _tf_to_group_map() -> dict[str, str]:
    m: dict[str, str] = {}
    for e in iter_registry():
        if e.builder == 'build_htf_fvgs' and e.timeframe is not None:
            m[e.timeframe] = e.group
    return m


TF_TO_GROUP = _tf_to_group_map()


def _ny_ts(ts: Any) -> pd.Timestamp:
    t = pd.Timestamp(ts)
    if t.tzinfo is None:
        return NY_TZ.localize(t.replace(tzinfo=None))
    return t.tz_convert(NY_TZ)


def detect_fvg_htf(candles: pd.DataFrame, idx: int) -> Optional[dict[str, Any]]:
    """
    Same gap math as fvgc.model.detect_fvg; no FVG_START_TIME filter (HTF bars).
    See fvgc/model.py detect_fvg.
    """
    if idx < 2:
        return None
    c1 = candles.iloc[idx - 2]
    c3 = candles.iloc[idx]

    if c1['high'] < c3['low']:
        gap_size = c3['low'] - c1['high']
        if gap_size < MIN_FVG_SIZE:
            return None
        return {
            'direction': 'bullish',
            'top': float(c3['low']),
            'bottom': float(c1['high']),
            'mid': float((c3['low'] + c1['high']) / 2),
        }

    if c1['low'] > c3['high']:
        gap_size = c1['low'] - c3['high']
        if gap_size < MIN_FVG_SIZE:
            return None
        return {
            'direction': 'bearish',
            'top': float(c1['low']),
            'bottom': float(c3['high']),
            'mid': float((c1['low'] + c3['high']) / 2),
        }
    return None


def aggregate_ohlc_grouper(nq: pd.DataFrame, rule: str) -> pd.DataFrame:
    x = nq[['ts_ny', 'open', 'high', 'low', 'close', 'volume']].copy()
    x = x.set_index('ts_ny')
    g = x.groupby(pd.Grouper(freq=rule, label='right', closed='right')).agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
    }).dropna(how='all')
    g = g.reset_index()
    g.rename(columns={'ts_ny': 'timestamp_ny'}, inplace=True)
    return g


def aggregate_daily(nq: pd.DataFrame) -> pd.DataFrame:
    x = nq.copy()
    x['d'] = x['ts_ny'].dt.date
    g = x.groupby('d', sort=True).agg(
        open=('open', 'first'),
        high=('high', 'max'),
        low=('low', 'min'),
        close=('close', 'last'),
        volume=('volume', 'sum'),
    ).reset_index()
    g.rename(columns={'d': 'date_only'}, inplace=True)
    g['timestamp_ny'] = g['date_only'].apply(
        lambda d: NY_TZ.localize(datetime.combine(d, dtime(16, 0)))
    )
    return g[['timestamp_ny', 'open', 'high', 'low', 'close', 'volume']]


def cutoff_ts(d: date) -> pd.Timestamp:
    return NY_TZ.localize(datetime.combine(d, RTH_OPEN))


def snapshot_include(fvg: dict[str, Any], cut: pd.Timestamp) -> bool:
    """Morning snapshot: formed at/before open; still active at open (wick mitigated only after open)."""
    ct = _ny_ts(fvg['created_ts'])
    if ct > cut:
        return False
    if not fvg['mitigated']:
        return True
    mt = _ny_ts(fvg['mitigated_ts'])
    return mt >= cut


def overnight_window(by_date: dict[date, pd.DataFrame], d: date) -> pd.DataFrame:
    """18:00 prior calendar day through 09:29 session day (same as session_levels)."""
    d_prev_cal = d - timedelta(days=1)
    on_parts: list[pd.DataFrame] = []
    if d_prev_cal in by_date:
        p = by_date[d_prev_cal]
        on_parts.append(p[p['ts_ny'].dt.time >= OVERNIGHT_START])
    day = by_date.get(d)
    if day is not None and not day.empty:
        on_parts.append(day[day['ts_ny'].dt.time < RTH_OPEN])
    if not on_parts:
        return pd.DataFrame()
    return pd.concat(on_parts, ignore_index=True).sort_values('ts_ny')


def fvg_swept_pre_rth(
    direction: str,
    top: float,
    bottom: float,
    overnight: pd.DataFrame,
) -> tuple[bool, str]:
    if overnight.empty:
        return False, ''
    if direction == 'bullish':
        mask = overnight['low'] <= bottom
    else:
        mask = overnight['high'] >= top
    hit = overnight[mask]
    if hit.empty:
        return False, ''
    first_ts = hit.sort_values('ts_ny').iloc[0]['ts_ny']
    return True, pd.Timestamp(first_ts).isoformat()


def direction_to_side(direction: str) -> str:
    return 'support' if direction == 'bullish' else 'resistance'


def walk_timeframe(
    candles: pd.DataFrame,
    tf_label: str,
) -> list[dict[str, Any]]:
    """Chronological walk: mitigate existing FVGs (wick rule), then detect new FVG at i."""
    candles = candles.sort_values('timestamp_ny').reset_index(drop=True)
    if len(candles) < 3:
        return []

    all_fvgs: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []  # not yet mitigated — O(active) per bar, not O(all)

    for i in range(len(candles)):
        row = candles.iloc[i]
        still: list[dict[str, Any]] = []
        for fvg in pending:
            if fvg['direction'] == 'bullish' and float(row['low']) <= fvg['bottom']:
                fvg['mitigated'] = True
                fvg['mitigated_ts'] = row['timestamp_ny']
            elif fvg['direction'] == 'bearish' and float(row['high']) >= fvg['top']:
                fvg['mitigated'] = True
                fvg['mitigated_ts'] = row['timestamp_ny']
            else:
                still.append(fvg)
        pending = still

        nf = detect_fvg_htf(candles, i)
        if nf:
            rec = {
                'created_idx': i,
                'created_ts': candles.iloc[i]['timestamp_ny'],
                'direction': nf['direction'],
                'top': nf['top'],
                'bottom': nf['bottom'],
                'mid': nf['mid'],
                'mitigated': False,
                'mitigated_ts': None,
                'timeframe': tf_label,
            }
            all_fvgs.append(rec)
            pending.append(rec)
    return all_fvgs


def bars_old_count(candles: pd.DataFrame, created_ts: Any, cut: pd.Timestamp) -> int:
    ts = candles['timestamp_ny']
    ct = _ny_ts(created_ts)
    return int(((ts < cut) & (ts > ct)).sum())


def build_htf_rows(
    all_fvgs: list[dict[str, Any]],
    candles: pd.DataFrame,
    tf_label: str,
    trading_dates: list[date],
    by_date: dict[date, pd.DataFrame],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    grp = TF_TO_GROUP.get(tf_label)
    if grp is None:
        return rows

    for D in trading_dates:
        cut = cutoff_ts(D)
        on = overnight_window(by_date, D)
        for fvg in all_fvgs:
            if not snapshot_include(fvg, cut):
                continue
            ct = _ny_ts(fvg['created_ts'])
            cdate = ct.date()
            bo = bars_old_count(candles, fvg['created_ts'], cut)
            direction = str(fvg['direction'])
            spr, spr_t = fvg_swept_pre_rth(direction, fvg['top'], fvg['bottom'], on)
            level_name = f"htf_fvg_{tf_label}_{direction}_{fvg['created_idx']}"
            rows.append({
                'date': D,
                'level_name': level_name,
                'group': grp,
                'side': direction_to_side(direction),
                'price': fvg['mid'],
                'available_time': 'open',
                'swept_pre_rth': spr,
                'swept_pre_rth_time': spr_t,
                'timeframe': tf_label,
                'fvg_direction': direction,
                'fvg_top': fvg['top'],
                'fvg_bottom': fvg['bottom'],
                'fvg_mid': fvg['mid'],
                'created_date': cdate,
                'bars_old': bo,
                'notes': '',
            })
    return rows


# Must match data/levels/build_session_levels.py LIQUIDITY_COLUMN_ORDER
LIQUIDITY_COLUMN_ORDER = (
    'date', 'level_name', 'group', 'side', 'price', 'available_time',
    'swept_pre_rth', 'swept_pre_rth_time',
    'timeframe', 'fvg_direction', 'fvg_top', 'fvg_bottom', 'fvg_mid',
    'created_date', 'bars_old', 'notes',
)


def build_htf_dataframe() -> pd.DataFrame:
    td = pd.read_csv(TRADING_DAYS_PATH)
    td['date'] = pd.to_datetime(td['date']).dt.date
    trading_dates = sorted(td['date'].unique())

    nq = load_nq_1m()
    by_date = {d: g for d, g in nq.groupby('date_ny', sort=False)}

    all_out: list[dict[str, Any]] = []

    for tf_label, rule in TF_SPECS:
        if tf_label == 'Daily':
            candles = aggregate_daily(nq)
        else:
            candles = aggregate_ohlc_grouper(nq, rule)
        print(f'  {tf_label}: {len(candles)} bars')
        fvgs = walk_timeframe(candles, tf_label)
        all_out.extend(build_htf_rows(fvgs, candles, tf_label, trading_dates, by_date))

    out = pd.DataFrame(all_out)
    for c in LIQUIDITY_COLUMN_ORDER:
        if c not in out.columns:
            out[c] = np.nan
    return out[list(LIQUIDITY_COLUMN_ORDER)]


def main(write: bool = False) -> pd.DataFrame:
    print('=' * 60)
    print('Building HTF FVG rows (liquidity schema)')
    print('=' * 60)

    out = build_htf_dataframe()
    if write:
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        out.to_csv(OUTPUT_PATH, index=False)
        print(f'Wrote {len(out)} rows to {OUTPUT_PATH}')
    else:
        print(f'Built {len(out)} HTF rows (no file write)')
    return out


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description='HTF FVG builder (use build_liquidity_levels.py for production).')
    ap.add_argument('--write', action='store_true', help=f'Write debug CSV to {OUTPUT_PATH}')
    args = ap.parse_args()
    df = main(write=args.write)
    print(df.head(3).to_string())

