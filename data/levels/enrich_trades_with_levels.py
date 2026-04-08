#!/usr/bin/env python3
"""
Join baseline trades with liquidity_levels.csv (session + HTF FVG rows); proximity metrics.
Session level names come from level_registry; HTF rows are iterated from the file by timeframe.

Option B: at load time, `filter_trade_date_levels` keeps only rows with
`swept_pre_rth == False`, valid `price`, non-stub `notes`, and (if present) HTF `still_active`.
Then 30s bars (9:30–entry) classify in-session vs available.
Per-group `{group}_swept` is pre_rth | in_session | available (pre_rth rare after filter).
"""

from __future__ import annotations

import sys
from datetime import datetime, time as dtime
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd
import pytz

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from data.levels.level_registry import (  # noqa: E402
    LEVEL_REGISTRY,
    groups_in_order,
    iter_registry,
)

NY_TZ = pytz.timezone('America/New_York')
RTH_START = dtime(9, 30)

BASELINE_PATH = ROOT / 'logs' / 'baseline_trades.csv'
LIQUIDITY_PATH = ROOT / 'data' / 'levels' / 'liquidity_levels.csv'
RAW_30S_PATH = ROOT / 'data' / 'raw' / 'glbx-mdp3-20231002-20251027.ohlcv-30s-trading-session.csv'
OUTPUT_PATH = ROOT / 'data' / 'levels' / 'trades_with_levels.csv'

HTF_TF_KEYS = ('15m', '1H', '4H', 'Daily')


def filter_trade_date_levels(levels: pd.DataFrame) -> pd.DataFrame:
    """
    Hard availability gate: only levels that are valid draws at trade time.
    Full liquidity_levels.csv is unchanged; this runs at enrichment time only.
    """
    if levels is None or levels.empty:
        return levels
    notes = levels['notes'] if 'notes' in levels.columns else pd.Series('', index=levels.index)
    notes = notes.fillna('')
    stub_ok = ~notes.str.contains('stub', case=False, na=False, regex=False)
    price_ok = levels['price'].notna()
    spr = levels['swept_pre_rth']
    spr_false = spr.eq(False) | (spr.astype(str).str.strip().str.lower() == 'false')
    mask = spr_false & price_ok & stub_ok
    if 'still_active' in levels.columns:
        tf = levels['timeframe']
        is_htf = tf.notna() & (tf.astype(str).str.strip() != '') & (tf.astype(str).str.lower() != 'nan')
        sa = levels['still_active']
        active_ok = sa.eq(True) | (sa.astype(str).str.strip().str.lower().isin(('true', '1')))
        mask = mask & (~is_htf | active_ok)
    return levels.loc[mask].copy()


def parse_avail(tstr: str) -> dtime | None:
    if tstr == 'open':
        return None
    h, m = tstr.split(':')
    return dtime(int(h), int(m))


def passes_time_gate(available_time: str, entry_ts: pd.Timestamp) -> bool:
    if available_time == 'open':
        return True
    t0 = parse_avail(available_time)
    if t0 is None:
        return True
    return entry_ts.time() >= t0


def session_date_ny(ts: pd.Timestamp) -> Any:
    if ts.tzinfo is None:
        ts = NY_TZ.localize(ts)
    else:
        ts = ts.tz_convert(NY_TZ)
    return ts.date()


def nearest_magnet_price(
    direction: str,
    entry_price: float,
    prices: list[float],
) -> tuple[Optional[float], Optional[float]]:
    if not prices:
        return None, None
    if direction == 'long':
        above = [p for p in prices if p > entry_price]
        if not above:
            return None, None
        p = min(above)
        return p, abs(p - entry_price)
    below = [p for p in prices if p < entry_price]
    if not below:
        return None, None
    p = max(below)
    return p, abs(p - entry_price)


def between(entry: float, tp: float, p: float) -> bool:
    lo, hi = (entry, tp) if entry < tp else (tp, entry)
    return lo < p < hi


def load_30s_session() -> pd.DataFrame:
    df = pd.read_csv(RAW_30S_PATH)
    df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
    df['ts_ny'] = df['timestamp'].dt.tz_convert(NY_TZ)
    df['date_ny'] = df['ts_ny'].dt.date
    return df


def session_bars_30(
    df30: pd.DataFrame,
    d: Any,
    entry_ts: pd.Timestamp,
) -> pd.DataFrame:
    open_ts = NY_TZ.localize(datetime.combine(d, RTH_START))
    return df30[(df30['date_ny'] == d) & (df30['ts_ny'] >= open_ts) & (df30['ts_ny'] <= entry_ts)]


def parse_swept_pre_rth(val: Any) -> bool | None:
    """True/False from liquidity_levels; None if empty / N/A (e.g. overnight session row)."""
    if val is None:
        return None
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        if pd.isna(val):
            return None
    s = str(val).strip().lower()
    if s in ('', 'nan', 'none'):
        return None
    if s in ('true', '1'):
        return True
    if s in ('false', '0'):
        return False
    return None


def classify_sweep(
    swept_pre_rth: bool | None,
    side: str,
    price: float,
    sub: pd.DataFrame,
) -> str:
    """pre_rth from build; else in_session vs available from 30s RTH window."""
    if swept_pre_rth is True:
        return 'pre_rth'
    if is_level_swept(side, price, sub):
        return 'in_session'
    return 'available'


def is_level_swept(side: str, price: float, sub: pd.DataFrame) -> bool:
    """Resistance: high >= price; support: low <= price; both: either."""
    if sub.empty:
        return False
    if side == 'resistance':
        return bool((sub['high'] >= price).any())
    if side == 'support':
        return bool((sub['low'] <= price).any())
    # both
    return bool((sub['high'] >= price).any() or (sub['low'] <= price).any())


def htf_direction_to_side(direction: str) -> str:
    d = str(direction).lower()
    if d == 'bullish':
        return 'support'
    if d == 'bearish':
        return 'resistance'
    return 'both'


def _is_session_liquidity_row(timeframe_val: Any) -> bool:
    if timeframe_val is None:
        return True
    if isinstance(timeframe_val, float) and np.isnan(timeframe_val):
        return True
    s = str(timeframe_val).strip().lower()
    return s in ('', 'nan', 'none')


def nearest_htf_alignment_pts(
    direction: str,
    entry: float,
    triples: list[tuple[float, str, str]],
    aligned_only: bool,
) -> Optional[float]:
    """Triples: (price, sweep_cat, fvg_direction). Nearest available FVG mid in trade direction."""
    avail = [(p, d) for p, cat, d in triples if cat == 'available']
    if not avail:
        return None
    if aligned_only:
        prices = [
            p for p, d in avail
            if (direction == 'long' and d == 'bullish')
            or (direction == 'short' and d == 'bearish')
        ]
    else:
        prices = [p for p, _ in avail]
    if not prices:
        return None
    _, pts = nearest_magnet_price(direction, entry, prices)
    return pts


def enrich_row(
    trade: pd.Series,
    liqu_by_date: dict[Any, pd.DataFrame],
    df30: pd.DataFrame,
    group_list: list[str],
) -> dict[str, Any]:
    ts = pd.to_datetime(trade['timestamp'])
    if ts.tzinfo is None:
        ts = NY_TZ.localize(ts)
    else:
        ts = ts.tz_convert(NY_TZ)
    d = session_date_ny(ts)
    entry = float(trade['entry_price'])
    direction = str(trade['direction'])
    sl_dist = trade.get('sl_dist')
    try:
        sl_f = float(sl_dist) if sl_dist is not None and not pd.isna(sl_dist) else None
    except (TypeError, ValueError):
        sl_f = None
    if sl_f is not None and sl_f <= 0:
        sl_f = None

    tp = trade.get('tp')
    try:
        tp_f = float(tp) if tp is not None and not pd.isna(tp) else None
    except (TypeError, ValueError):
        tp_f = None

    liqu_day = liqu_by_date.get(d)
    if liqu_day is not None and not liqu_day.empty:
        liqu_day = filter_trade_date_levels(liqu_day)

    sub = session_bars_30(df30, d, ts)

    if liqu_day is None or liqu_day.empty:
        rowmap = {}
        htf_by_tf: dict[str, list[tuple[float, str, str]]] = {tf: [] for tf in HTF_TF_KEYS}
    else:
        rowmap = {
            str(r['level_name']): r.to_dict()
            for _, r in liqu_day.iterrows()
            if _is_session_liquidity_row(r.get('timeframe'))
        }
        htf_by_tf = {tf: [] for tf in HTF_TF_KEYS}
    # --- Collect (group, price, side) with time gate; three-way sweep per level ---
    level_events: list[tuple[str, float, str, str]] = []  # group, price, side, sweep_cat

    for e in LEVEL_REGISTRY:
        if e.builder != 'build_session_levels':
            continue
        if e.name not in rowmap:
            continue
        r = rowmap[e.name]
        if not passes_time_gate(str(r['available_time']), ts):
            continue
        px = r['price']
        if px is None or (isinstance(px, float) and np.isnan(px)):
            continue
        price = float(px)
        spr = parse_swept_pre_rth(r.get('swept_pre_rth'))
        cat = classify_sweep(spr, e.side, price, sub)
        level_events.append((e.group, price, e.side, cat))

    if liqu_day is not None and not liqu_day.empty:
        for _, r in liqu_day.iterrows():
            if _is_session_liquidity_row(r.get('timeframe')):
                continue
            px = r['price']
            if px is None or (isinstance(px, float) and np.isnan(px)):
                continue
            price = float(px)
            spr = parse_swept_pre_rth(r.get('swept_pre_rth'))
            side = htf_direction_to_side(str(r['fvg_direction']))
            cat = classify_sweep(spr, side, price, sub)
            level_events.append((str(r['group']), price, side, cat))
            tf = str(r['timeframe'])
            if tf in htf_by_tf:
                htf_by_tf[tf].append((price, cat, str(r['fvg_direction'])))

    # Per group: lists of (price, sweep_cat)
    by_group: dict[str, list[tuple[float, str]]] = {g: [] for g in group_list}
    for g, price, _side, cat in level_events:
        by_group[g].append((price, cat))

    per_group: dict[str, dict[str, Any]] = {}
    candidates_R: list[tuple[float, str, float]] = []

    for g in group_list:
        pairs = by_group[g]
        if not pairs:
            per_group[g] = {
                f'{g}_nearest_price': None,
                f'{g}_nearest_pts': None,
                f'{g}_nearest_R': None,
                f'{g}_swept': None,
            }
            continue

        all_prices = [p for p, _ in pairs]
        # Nearest in direction among all candidates (for _swept categorical)
        des_p, _ = nearest_magnet_price(direction, entry, all_prices)
        if des_p is None:
            g_swept: Optional[str] = None
        else:
            cats_for_des = [c for p, c in pairs if abs(p - des_p) < 1e-9]
            g_swept = cats_for_des[0] if cats_for_des else None

        # Magnets / obstructions: only levels still available (not pre-RTH or in-session swept)
        unswept_prices = [p for p, c in pairs if c == 'available']
        np_price, np_pts = nearest_magnet_price(direction, entry, unswept_prices)
        r_val: Optional[float] = None
        if np_pts is not None and sl_f is not None:
            r_val = np_pts / sl_f
        per_group[g] = {
            f'{g}_nearest_price': np_price,
            f'{g}_nearest_pts': np_pts,
            f'{g}_nearest_R': r_val,
            f'{g}_swept': g_swept,
        }
        if r_val is not None:
            candidates_R.append((r_val, g, np_pts))

    if candidates_R:
        candidates_R.sort(key=lambda x: x[0])
        best_R, best_g, best_pts = candidates_R[0]
        nearest_magnet_R = best_R
        nearest_magnet_group = best_g
        nearest_magnet_pts = best_pts
    else:
        nearest_magnet_R = None
        nearest_magnet_group = None
        nearest_magnet_pts = None

    magnet_valid: Optional[bool] = None
    if nearest_magnet_R is not None:
        magnet_valid = nearest_magnet_R <= 3.0

    magnet_within_1R = nearest_magnet_R is not None and nearest_magnet_R <= 1.0
    magnet_within_2R = nearest_magnet_R is not None and nearest_magnet_R <= 2.0
    magnet_within_3R = nearest_magnet_R is not None and nearest_magnet_R <= 3.0

    # available_level_count: distinct groups with >=1 available level in trade direction within 3R
    available_level_count = 0
    for g in group_list:
        for price, cat in by_group[g]:
            if cat != 'available':
                continue
            if direction == 'long':
                if not (price > entry):
                    continue
            else:
                if not (price < entry):
                    continue
            pts_d = abs(price - entry)
            if sl_f is None:
                continue
            if pts_d / sl_f <= 3.0:
                available_level_count += 1
                break

    no_valid_levels = available_level_count == 0

    # Obstructions — available levels only
    all_pts: list[tuple[str, float]] = [
        (g, p) for g in group_list for p, cat in by_group[g] if cat == 'available'
    ]
    obstructions: list[tuple[str, float]] = []
    if tp_f is not None:
        for g, p in all_pts:
            if between(entry, tp_f, p):
                obstructions.append((g, p))

    obstruction_count = len(obstructions)
    path_clear = obstruction_count == 0

    nearest_obstruction_pts = None
    nearest_obstruction_R = None
    nearest_obstruction_group = None
    if obstructions and sl_f is not None:
        best_d = min(abs(p - entry) for _, p in obstructions)
        for g, p in obstructions:
            if abs(p - entry) == best_d or abs(abs(p - entry) - best_d) < 1e-9:
                nearest_obstruction_pts = abs(p - entry)
                nearest_obstruction_R = nearest_obstruction_pts / sl_f
                nearest_obstruction_group = g
                break

    magnet_level_price = None
    if nearest_magnet_group is not None:
        magnet_level_price = per_group[nearest_magnet_group][f'{nearest_magnet_group}_nearest_price']

    level_confluence_count = 0
    if magnet_level_price is not None:
        mlp = float(magnet_level_price)
        seen_g: set[str] = set()
        for g, p in all_pts:
            if abs(p - mlp) <= 10.0:
                seen_g.add(g)
        level_confluence_count = len(seen_g)

    swept_magnet_ref = swept_before_entry_unswept(df30, d, ts, direction, magnet_level_price)

    out = {**trade.to_dict()}
    out['nearest_magnet_pts'] = nearest_magnet_pts
    out['nearest_magnet_R'] = nearest_magnet_R
    out['nearest_magnet_group'] = nearest_magnet_group
    out['magnet_valid'] = magnet_valid
    out['magnet_within_1R'] = magnet_within_1R
    out['magnet_within_2R'] = magnet_within_2R
    out['magnet_within_3R'] = magnet_within_3R
    out['nearest_obstruction_pts'] = nearest_obstruction_pts
    out['nearest_obstruction_R'] = nearest_obstruction_R
    out['nearest_obstruction_group'] = nearest_obstruction_group
    out['obstruction_count'] = obstruction_count
    out['path_clear'] = path_clear
    out['level_confluence_count'] = level_confluence_count
    out['level_swept_before_entry'] = swept_magnet_ref
    out['available_level_count'] = available_level_count
    out['no_valid_levels'] = no_valid_levels

    for g in group_list:
        out.update(per_group[g])

    for tf in HTF_TF_KEYS:
        triples = htf_by_tf.get(tf, []) if liqu_day is not None and not liqu_day.empty else []
        out[f'htf_fvg_{tf}_aligned_nearest_pts'] = nearest_htf_alignment_pts(
            direction, entry, triples, aligned_only=True,
        )
        out[f'htf_fvg_{tf}_any_nearest_pts'] = nearest_htf_alignment_pts(
            direction, entry, triples, aligned_only=False,
        )

    return out


def swept_before_entry_unswept(
    df30: pd.DataFrame,
    d: Any,
    entry_ts: pd.Timestamp,
    direction: str,
    magnet_price: Optional[float],
) -> Optional[bool]:
    """Whether 30s range traded through the (unswept) magnet price — reference only."""
    if magnet_price is None:
        return None
    sub = session_bars_30(df30, d, entry_ts)
    if sub.empty:
        return None
    mp = float(magnet_price)
    if direction == 'long':
        return bool((sub['low'] <= mp).any())
    return bool((sub['high'] >= mp).any())


def main() -> None:
    print('Loading inputs...')
    trades = pd.read_csv(BASELINE_PATH)
    liqu = pd.read_csv(LIQUIDITY_PATH)
    liqu['date'] = pd.to_datetime(liqu['date']).dt.date
    liqu_by_date = {d: g for d, g in liqu.groupby('date')}

    print('Loading 30s session data...')
    df30 = load_30s_session()

    group_list = groups_in_order()
    rows = []
    for _, tr in trades.iterrows():
        rows.append(enrich_row(tr, liqu_by_date, df30, group_list))

    base_cols = list(trades.columns)
    agg_cols = [
        'nearest_magnet_pts', 'nearest_magnet_R', 'nearest_magnet_group', 'magnet_valid',
        'magnet_within_1R', 'magnet_within_2R', 'magnet_within_3R',
        'nearest_obstruction_pts', 'nearest_obstruction_R', 'nearest_obstruction_group',
        'obstruction_count', 'path_clear', 'level_confluence_count',
        'level_swept_before_entry', 'available_level_count', 'no_valid_levels',
    ]
    htf_align_cols: list[str] = []
    for tf in HTF_TF_KEYS:
        htf_align_cols.extend([
            f'htf_fvg_{tf}_aligned_nearest_pts',
            f'htf_fvg_{tf}_any_nearest_pts',
        ])
    detail_cols: list[str] = []
    for g in group_list:
        detail_cols.extend([
            f'{g}_nearest_price', f'{g}_nearest_pts', f'{g}_nearest_R', f'{g}_swept',
        ])

    out = pd.DataFrame(rows)
    out = out[base_cols + agg_cols + htf_align_cols + detail_cols]
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUTPUT_PATH, index=False)
    print(f'Wrote {len(out)} rows to {OUTPUT_PATH}')


if __name__ == '__main__':
    main()
