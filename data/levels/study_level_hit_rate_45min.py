#!/usr/bin/env python3
"""
Study: which liquidity levels get hit in the first 45 min of RTH (9:30–10:15)?

Includes ALL session and HTF levels with valid prices. Does NOT filter on
swept_pre_rth — that flag has a known pipeline issue where levels whose
formation window is inside the overnight window (Asia, London, 6am, overnight)
always register as swept, even though the levels are valid RTH references.

Availability overrides (per level definitions):
  6am_high / 6am_low  → available from 10:00 (close of the 6am 4H candle 6am-10am)
                         only checkable in the 10:00–10:15 window
  or_high / or_low    → stub (not computed); excluded

Distance scope: only levels within SCOPE_PTS of the RTH open are included.
Default SCOPE_PTS = 300 (adjustable via --scope).

Hit definitions:
  Resistance (session): rth_window_high >= price
  Support (session):    rth_window_low  <= price
  HTF FVG resistance:   rth_window_high >= fvg_bottom  (enters FVG from below)
  HTF FVG support:      rth_window_low  <= fvg_top     (enters FVG from above)
  Window for each level = [max(9:30, avail_time), 10:15)

Outputs (data/levels/results/):
  hit_rate_by_group.csv         — groups ranked by hit rate
  hit_rate_by_distance.csv      — hit rate by distance bucket from open
  hit_rate_group_x_gap.csv      — group × gap direction
  hit_rate_group_x_distance.csv — group × distance bucket
  hit_rate_by_930_candle.csv    — hit rate by 9:30 candle × gap direction
  hit_rate_group_x_930_candle.csv — group × 9:30 candle direction
  hit_rate_top_combos.csv       — top group × gap × candle combos (n≥30)

Run from repo root:
  python data/levels/study_level_hit_rate_45min.py
  python data/levels/study_level_hit_rate_45min.py --scope 200
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, time as dtime
from pathlib import Path

import numpy as np
import pandas as pd
import pytz

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

NY_TZ = pytz.timezone('America/New_York')

LEVELS_PATH   = ROOT / 'data' / 'levels' / 'liquidity_levels.csv'
BARS_30S_PATH = ROOT / 'data' / 'consolidated' / 'nq-front-month.ohlcv-30s.csv'
RESULTS_DIR   = ROOT / 'data' / 'levels' / 'results'

DEFAULT_SCOPE_PTS = 300

RTH_START = dtime(9, 30)
RTH_45_END = dtime(10, 15)

# 6am level forms at 10:00 (close of the 6am–10am 4H candle)
SIX_AM_AVAIL = dtime(10, 0)

# Gap thresholds (NQ points, prev RTH close → current RTH open)
GAP_UP_MIN   =  10.0
GAP_DOWN_MAX = -10.0

# Distance buckets (NQ points from RTH open)
DIST_BINS   = [0, 25, 50, 100, 200, float('inf')]
DIST_LABELS = ['0–25', '25–50', '50–100', '100–200', '200+']

# Level names whose available_time we override (pipeline definitions differ from
# the actual availability these levels have at RTH open).
AVAIL_OVERRIDES: dict[str, dtime] = {
    '6am_high': SIX_AM_AVAIL,
    '6am_low':  SIX_AM_AVAIL,
}


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_levels() -> pd.DataFrame:
    """Load all levels with valid prices. Exclude stubs only."""
    df = pd.read_csv(LEVELS_PATH, low_memory=False)
    df['date'] = pd.to_datetime(df['date']).dt.date

    # Require a valid price
    price_ok = df['price'].notna()

    # Exclude stubs (or_high / or_low — not yet computed in pipeline)
    notes    = df['notes'].fillna('')
    stub_ok  = ~notes.str.contains('stub', case=False, na=False, regex=False)

    # HTF FVGs: must still be active (if column present)
    mask = price_ok & stub_ok
    if 'still_active' in df.columns:
        tf        = df['timeframe']
        is_htf    = tf.notna() & (tf.astype(str).str.strip() != '') & (tf.astype(str).str.lower() != 'nan')
        sa        = df['still_active']
        active_ok = sa.eq(True) | (sa.astype(str).str.strip().str.lower().isin(('true', '1')))
        mask      = mask & (~is_htf | active_ok)

    df = df.loc[mask].copy()

    # Apply availability overrides
    for level_name, avail_time in AVAIL_OVERRIDES.items():
        df.loc[df['level_name'] == level_name, 'available_time'] = avail_time.strftime('%H:%M')

    return df


def load_bars() -> pd.DataFrame:
    df = pd.read_csv(BARS_30S_PATH, low_memory=False)
    df['ts']       = pd.to_datetime(df['timestamp_ny'], utc=True).dt.tz_convert(NY_TZ)
    df['date']     = df['ts'].dt.date
    df['bar_time'] = df['ts'].dt.time
    return df


# ---------------------------------------------------------------------------
# Per-day bar stats
# ---------------------------------------------------------------------------

def _parse_avail(avail_str: str) -> dtime:
    """Parse 'open', 'HH:MM' → dtime. 'open' → RTH_START."""
    s = str(avail_str).strip().lower()
    if s == 'open' or s == 'nan':
        return RTH_START
    h, m = s.split(':')
    return dtime(int(h), int(m))


def compute_day_stats(bars: pd.DataFrame) -> pd.DataFrame:
    """Return one row per trading day with open, gap, and windowed H/L."""

    # Prior RTH close map: date → last bar close between 15:50–16:01
    rth_close_map: dict[date, float] = {}
    for day, grp in bars.groupby('date'):
        cb = grp[(grp['bar_time'] >= dtime(15, 50)) & (grp['bar_time'] <= dtime(16, 1))]
        if not cb.empty:
            rth_close_map[day] = float(cb.sort_values('ts').iloc[-1]['close'])

    days_sorted = sorted(rth_close_map.keys())
    prev_close_by_day: dict[date, float] = {
        days_sorted[i]: rth_close_map[days_sorted[i - 1]]
        for i in range(1, len(days_sorted))
    }

    # Pre-compute windowed H/L per available_time we care about
    window_starts = [RTH_START, dtime(9, 45), SIX_AM_AVAIL]

    records = []
    for day, grp in bars.groupby('date'):
        grp = grp.sort_values('ts')

        rth_bars = grp[grp['bar_time'] >= RTH_START]
        if rth_bars.empty:
            continue
        rth_open = float(rth_bars.iloc[0]['open'])

        # Overnight gap
        prior_close = prev_close_by_day.get(day, np.nan)
        gap_pts = rth_open - prior_close if not np.isnan(prior_close) else np.nan
        if np.isnan(gap_pts):
            gap_dir = 'unknown'
        elif gap_pts >= GAP_UP_MIN:
            gap_dir = 'gap_up'
        elif gap_pts <= GAP_DOWN_MAX:
            gap_dir = 'gap_down'
        else:
            gap_dir = 'flat'

        # 9:30 candle direction (first 5-min window)
        c930 = rth_bars[rth_bars['bar_time'] < dtime(9, 35)]
        c930_dir = 'up' if (not c930.empty and c930.iloc[-1]['close'] >= c930.iloc[0]['open']) else 'down' if not c930.empty else 'unknown'

        # Windowed H/L for each possible available_time
        row: dict = {
            'date':        day,
            'rth_open':    rth_open,
            'prior_close': prior_close,
            'gap_pts':     gap_pts,
            'gap_dir':     gap_dir,
            'c930_dir':    c930_dir,
        }

        for ws in window_starts:
            window = rth_bars[(rth_bars['bar_time'] >= ws) & (rth_bars['bar_time'] < RTH_45_END)]
            key = ws.strftime('%H%M')
            row[f'hi_{key}'] = float(window['high'].max()) if not window.empty else np.nan
            row[f'lo_{key}'] = float(window['low'].min())  if not window.empty else np.nan

        records.append(row)

    return pd.DataFrame(records)


# ---------------------------------------------------------------------------
# Hit detection
# ---------------------------------------------------------------------------

def check_hit(row: pd.Series) -> bool:
    """Check if the level was touched within its eligible window (up to 10:15)."""
    price  = float(row['price'])
    side   = str(row['side']).lower()
    group  = str(row['group'])
    avail  = _parse_avail(str(row.get('available_time', 'open')))

    # If level only becomes available at 10:15 or after, no chance to hit it
    if avail >= RTH_45_END:
        return False

    # Select the pre-computed window H/L for this avail start
    key = avail.strftime('%H%M')
    hi = row.get(f'hi_{key}', np.nan)
    lo = row.get(f'lo_{key}', np.nan)

    # Fall back to 9:30 window if this avail_time wasn't pre-computed
    if pd.isna(hi) or pd.isna(lo):
        hi = row.get('hi_0930', np.nan)
        lo = row.get('lo_0930', np.nan)
    if pd.isna(hi) or pd.isna(lo):
        return False

    # HTF FVGs: check body edges
    if group.startswith('htf_fvg'):
        fvg_top    = row.get('fvg_top',    np.nan)
        fvg_bottom = row.get('fvg_bottom', np.nan)
        if side == 'resistance' and pd.notna(fvg_bottom):
            return bool(hi >= fvg_bottom)
        if side == 'support' and pd.notna(fvg_top):
            return bool(lo <= fvg_top)
        # Fallback: mid price
        return bool(hi >= price) if side == 'resistance' else bool(lo <= price)

    # Session levels
    if side == 'resistance':
        return bool(hi >= price)
    elif side == 'support':
        return bool(lo <= price)
    else:  # 'both'
        return bool(hi >= price or lo <= price)


# ---------------------------------------------------------------------------
# Summary helpers
# ---------------------------------------------------------------------------

def pct(hits: int | float, total: int | float) -> float:
    return round(100.0 * hits / total, 1) if total else float('nan')


def summarize(df: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    agg = (
        df.groupby(group_cols, observed=True)['hit']
        .agg(total='count', hits='sum')
        .reset_index()
    )
    agg['hit_rate_pct'] = [pct(h, t) for h, t in zip(agg['hits'], agg['total'])]
    return agg


def print_table(title: str, df: pd.DataFrame) -> None:
    print(f'\n{"="*65}')
    print(title)
    print('='*65)
    print(df.to_string(index=False))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(scope_pts: float = DEFAULT_SCOPE_PTS) -> None:
    print('Loading levels...')
    levels = load_levels()
    print(f'  {len(levels):,} level-day rows ({levels["date"].nunique()} days, '
          f'{levels["group"].nunique()} groups)')
    print(f'  Groups: {sorted(levels["group"].unique())}')

    print('Loading 30s bars...')
    bars = load_bars()
    print(f'  {bars["date"].nunique()} trading days in bar data')

    print('Computing per-day stats...')
    day_stats = compute_day_stats(bars)
    print(f'  {len(day_stats)} days with stats')

    # Join
    levels = levels.merge(day_stats, on='date', how='inner')
    print(f'  {len(levels):,} level-day rows after join')

    # Distance from open
    levels['distance_pts']    = (levels['price'] - levels['rth_open']).abs()
    levels['distance_bucket'] = pd.cut(
        levels['distance_pts'], bins=DIST_BINS, labels=DIST_LABELS, right=False,
    )
    levels['above_open'] = levels['price'] > levels['rth_open']

    # Scope filter
    in_scope = levels['distance_pts'] <= scope_pts
    print(f'  Scoping to within {scope_pts} pts of open: '
          f'{in_scope.sum():,} rows ({100*in_scope.mean():.1f}%)')
    levels = levels.loc[in_scope].copy()

    # Hit flag
    print('Checking hit in first 45 min...')
    levels['hit'] = levels.apply(check_hit, axis=1)
    n_hit  = int(levels['hit'].sum())
    n_tot  = len(levels)
    print(f'  Overall hit rate: {pct(n_hit, n_tot)}% ({n_hit:,}/{n_tot:,})')

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Table 1: Hit rate by group (ranked)
    # ------------------------------------------------------------------
    t1 = summarize(levels, ['group']).sort_values('hit_rate_pct', ascending=False).reset_index(drop=True)
    t1.insert(0, 'rank', range(1, len(t1) + 1))
    t1 = t1[['rank', 'group', 'hit_rate_pct', 'hits', 'total']]
    print_table(f'RANKING: Hit Rate by Level Group (first 45 min, ≤{scope_pts}pts from open)', t1)
    t1.to_csv(RESULTS_DIR / 'hit_rate_by_group.csv', index=False)

    # ------------------------------------------------------------------
    # Table 2: Hit rate by distance bucket
    # ------------------------------------------------------------------
    t2 = summarize(levels, ['distance_bucket'])
    print_table('Hit Rate by Distance from Open', t2)
    t2.to_csv(RESULTS_DIR / 'hit_rate_by_distance.csv', index=False)

    # ------------------------------------------------------------------
    # Table 3: Group × distance bucket
    # ------------------------------------------------------------------
    t3 = summarize(levels, ['group', 'distance_bucket'])
    t3_pivot = t3.pivot_table(
        index='group', columns='distance_bucket', values='hit_rate_pct', observed=True,
    ).reset_index()
    print_table('Hit Rate: Group × Distance Bucket (%)', t3_pivot)
    t3.to_csv(RESULTS_DIR / 'hit_rate_group_x_distance.csv', index=False)

    # ------------------------------------------------------------------
    # Table 4: Group × gap direction
    # ------------------------------------------------------------------
    t4      = summarize(levels, ['group', 'gap_dir'])
    t4_pivot = t4.pivot_table(
        index='group', columns='gap_dir', values='hit_rate_pct', observed=True,
    ).reset_index()
    print_table('Hit Rate: Group × Gap Direction (%)', t4_pivot)
    t4.to_csv(RESULTS_DIR / 'hit_rate_group_x_gap.csv', index=False)

    # ------------------------------------------------------------------
    # Table 5: Hit rate by 9:30 candle × gap direction
    # ------------------------------------------------------------------
    t5 = summarize(levels, ['c930_dir', 'gap_dir'])
    print_table('Hit Rate by 9:30 Candle Direction × Gap Direction', t5)
    t5.to_csv(RESULTS_DIR / 'hit_rate_by_930_candle.csv', index=False)

    # ------------------------------------------------------------------
    # Table 6: Group × 9:30 candle direction
    # ------------------------------------------------------------------
    t6       = summarize(levels, ['group', 'c930_dir'])
    t6_pivot = t6.pivot_table(
        index='group', columns='c930_dir', values='hit_rate_pct', observed=True,
    ).reset_index()
    print_table('Hit Rate: Group × 9:30 Candle Direction (%)', t6_pivot)
    t6.to_csv(RESULTS_DIR / 'hit_rate_group_x_930_candle.csv', index=False)

    # ------------------------------------------------------------------
    # Table 7: Top combos (n≥30)
    # ------------------------------------------------------------------
    t7 = summarize(levels, ['group', 'gap_dir', 'c930_dir'])
    t7 = t7[t7['total'] >= 30].sort_values('hit_rate_pct', ascending=False).head(20).reset_index(drop=True)
    t7.insert(0, 'rank', range(1, len(t7) + 1))
    print_table('TOP COMBOS: Group × Gap Direction × 9:30 Candle (n≥30)', t7)
    t7.to_csv(RESULTS_DIR / 'hit_rate_top_combos.csv', index=False)

    # ------------------------------------------------------------------
    # Verification export: one row per level-day with all context
    # ------------------------------------------------------------------
    verify_cols = [
        'date', 'group', 'level_name', 'side', 'price',
        'available_time', 'distance_pts', 'distance_bucket', 'above_open',
        'hit', 'rth_open', 'gap_pts', 'gap_dir', 'c930_dir',
        'rth_45_high', 'rth_45_low',
    ]
    # Add swept_pre_rth if present (useful for spot-checking)
    if 'swept_pre_rth' in levels.columns:
        verify_cols.insert(6, 'swept_pre_rth')
    verify_out = levels[[c for c in verify_cols if c in levels.columns]].copy()
    verify_out = verify_out.sort_values(['date', 'group', 'distance_pts']).reset_index(drop=True)
    verify_path = RESULTS_DIR / 'levels_hit_verified.csv'
    verify_out.to_csv(verify_path, index=False)
    print(f'  Verification export: {len(verify_out):,} rows → {verify_path.name}')

    print(f'\nResults written to {RESULTS_DIR}/')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--scope', type=float, default=DEFAULT_SCOPE_PTS,
                    help=f'Max distance from RTH open in NQ points (default: {DEFAULT_SCOPE_PTS})')
    args = ap.parse_args()
    main(scope_pts=args.scope)
