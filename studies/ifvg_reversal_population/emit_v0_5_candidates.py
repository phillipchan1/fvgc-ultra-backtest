#!/usr/bin/env python3
"""v0.5 candidate emitter — proactive gap combining + explicit tagging.

Difference from v0.4:
  - Drops per-TF min-size pre-filter. Instead:
    1. Cluster same-direction FVGs by proximity (greedy merge, combined SL ≤ 40pt)
    2. A cluster is tradeable if span ≥ MIN_TRADEABLE_SPAN (8pt)
    3. Tiny gaps that wouldn't fire individually CAN combine into tradeable zones
       → MORE candidates than v0.4 (user request 2026-05-25)
  - Each candidate explicitly tagged:
      is_combined           — True if cluster has >1 source FVG
      n_source_gaps         — total FVGs in the cluster
      multi_tf_count        — distinct TFs represented
      combined_span_pts     — width of the merged zone
      largest_source_size   — biggest underlying gap (sanity check)

Carries forward from v0.4:
  - Stop = outermost bound + buffer (Option B)
  - Sweep required (drop "(no sweep)" rows downstream)
  - Sweep-level dedup within DEDUPE_TOLERANCE_PTS

Output: studies/ifvg_reversal_population/results/v0_5/candidates_3wk.csv
"""

import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pandas as pd

from fvgc.data import load_candles
from ifvg_reversal.constants import (
    HARD_STOP_BUFFER, MOMENTUM_BODY_FRACTION,
    TRADING_WINDOW_END, TRADING_WINDOW_START,
)
from ifvg_reversal.detectors.multi_tf_fvg import (
    MultiTFGap, build_fvg_inventory, mark_inversions,
)
from ifvg_reversal.detectors.sweep import detect_sweeps

DATA_PATH = Path('data/consolidated/nq-front-month.ohlcv-30s.csv')
LEVELS_PATH = Path('data/levels/session_levels.csv')
OUT_DIR = Path(__file__).resolve().parent / 'results' / 'v0_5'
OUT_DIR.mkdir(parents=True, exist_ok=True)

MAX_MERGED_SL = 40.0          # cap on (combined_span + HARD_STOP_BUFFER) for proactive merging
MIN_TRADEABLE_SPAN = 8.0      # cluster span must be ≥ this to be tradeable
BUILD_MIN_SIZE = 3.0          # loose raw-FVG floor (lets tiny gaps in for combining)
DEDUPE_TOLERANCE_PTS = 5.0
SWEEP_VALIDITY_MIN = 40


@dataclass
class FVGCluster:
    direction: str
    bottom: float
    top: float
    source: List[MultiTFGap] = field(default_factory=list)

    @property
    def span(self) -> float:
        return self.top - self.bottom

    @property
    def sl_distance(self) -> float:
        return self.span + HARD_STOP_BUFFER

    @property
    def tfs(self) -> Set[str]:
        return {g.tf for g in self.source}

    @property
    def is_combined(self) -> bool:
        return len(self.source) > 1


def cluster_fvgs(gaps: List[MultiTFGap], max_sl: float = MAX_MERGED_SL) -> List[FVGCluster]:
    """Greedy merge same-direction FVGs (regardless of TF), capped at max_sl.

    Order-independent approximation: sort by (direction, bottom), walk L→R,
    merge into prev cluster if resulting SL ≤ cap.
    """
    if not gaps:
        return []
    singletons = [
        FVGCluster(direction=g.direction, bottom=g.bottom, top=g.top, source=[g])
        for g in gaps
    ]
    singletons.sort(key=lambda c: (c.direction, c.bottom))

    out: List[FVGCluster] = []
    for c in singletons:
        if out and out[-1].direction == c.direction:
            cand_top = max(out[-1].top, c.top)
            cand_bot = min(out[-1].bottom, c.bottom)
            if (cand_top - cand_bot) + HARD_STOP_BUFFER <= max_sl:
                out[-1].top = cand_top
                out[-1].bottom = cand_bot
                out[-1].source.extend(c.source)
                continue
        out.append(c)
    return out


def mark_cluster_inversions(clusters: List[FVGCluster], candles_day: pd.DataFrame):
    """For each cluster, find the FIRST candle whose close crosses the outer bound.

    Returns list of (cluster, inversion_ts, inversion_close, body_fraction).
    """
    bars = candles_day[['timestamp_ny', 'open', 'high', 'low', 'close']].sort_values(
        'timestamp_ny').reset_index(drop=True)
    out = []
    for c in clusters:
        # Need to start looking AFTER the latest source-FVG creation time
        earliest_valid_ts = max(g.created_at for g in c.source)
        if c.direction == 'bullish':
            mask = (bars['timestamp_ny'] > earliest_valid_ts) & (bars['close'] < c.bottom)
        else:
            mask = (bars['timestamp_ny'] > earliest_valid_ts) & (bars['close'] > c.top)
        hits = bars[mask]
        if hits.empty:
            continue
        first = hits.iloc[0]
        rng = first['high'] - first['low']
        body = abs(first['close'] - first['open'])
        body_frac = (body / rng) if rng > 0 else 0.0
        out.append((c, first['timestamp_ny'], float(first['close']), body_frac))
    return out


def find_opposing_in_path(
    gaps: List[MultiTFGap],
    entry_price: float,
    entry_ts: pd.Timestamp,
    direction: str,
    scan_distance: float,
):
    """For a LONG entry, find UNINVERTED bearish FVGs above entry within scan_distance.
    For a SHORT, find UNINVERTED bullish FVGs below.

    Returns (path_clear: bool, nearest_pts: Optional[float], n_in_path: int).
    """
    opposing_dir = 'bearish' if direction == 'long' else 'bullish'
    in_path = []
    for g in gaps:
        if g.direction != opposing_dir:
            continue
        if g.created_at >= entry_ts:
            continue
        # Treat as "still fresh" if it has NOT been inverted by entry_ts
        already_inverted = g.is_inverted and g.inverted_at < entry_ts
        if already_inverted:
            continue
        # Is the body within the path?
        if direction == 'long':
            # opposing bearish above: body bottom should be in [entry, entry+scan]
            if entry_price < g.bottom <= entry_price + scan_distance:
                in_path.append((g.bottom - entry_price, g))
            # Or body straddles entry from above (bottom below entry, top above)
            elif g.bottom <= entry_price <= g.top and g.top <= entry_price + scan_distance:
                in_path.append((0.0, g))
        else:
            # opposing bullish below: body top in [entry-scan, entry]
            if entry_price - scan_distance <= g.top < entry_price:
                in_path.append((entry_price - g.top, g))
            elif g.bottom <= entry_price <= g.top and g.bottom >= entry_price - scan_distance:
                in_path.append((0.0, g))

    if not in_path:
        return (True, None, 0)
    in_path.sort(key=lambda x: x[0])
    return (False, in_path[0][0], len(in_path))


def emit_for_day(date_str: str, candles_day: pd.DataFrame, levels: pd.DataFrame):
    gaps = build_fvg_inventory(candles_day, min_size=BUILD_MIN_SIZE)
    mark_inversions(gaps, candles_day)
    clusters = cluster_fvgs(gaps)

    # Drop clusters that are too narrow to trade
    tradeable_clusters = [c for c in clusters if c.span >= MIN_TRADEABLE_SPAN]

    cluster_inv = mark_cluster_inversions(tradeable_clusters, candles_day)

    sweeps = detect_sweeps(candles_day, levels)

    candidates = []
    for c, inv_ts, inv_close, body_frac in cluster_inv:
        if body_frac < MOMENTUM_BODY_FRACTION:
            continue
        ny_t = inv_ts.tz_convert('America/New_York') if inv_ts.tz else inv_ts
        ny_hhmm = ny_t.strftime('%H:%M')
        if ny_hhmm < TRADING_WINDOW_START.strftime('%H:%M'):
            continue
        if ny_hhmm > TRADING_WINDOW_END.strftime('%H:%M'):
            continue

        direction = 'short' if c.direction == 'bullish' else 'long'

        if direction == 'short':
            stop_price = c.top + HARD_STOP_BUFFER
        else:
            stop_price = c.bottom - HARD_STOP_BUFFER
        stop_distance = abs(stop_price - inv_close)

        # Recent sweeps qualifying
        valid_sweeps = [
            s for s in sweeps
            if s.reversal_direction == direction
            and s.timestamp_ny <= inv_ts
            and s.timestamp_ny >= inv_ts - pd.Timedelta(minutes=SWEEP_VALIDITY_MIN)
        ]
        if valid_sweeps:
            valid_sweeps.sort(key=lambda s: s.timestamp_ny, reverse=True)
            primary = valid_sweeps[0]
            sweep_level = primary.level_name
            sweep_tier = primary.tier
            sweep_ts = primary.timestamp_ny
            others = [s for s in valid_sweeps
                      if s is not primary and abs(s.level_price - primary.level_price) <= DEDUPE_TOLERANCE_PTS]
            stacked_count = 1 + len(others)
            stacked_levels = '+'.join([primary.level_name] + [s.level_name for s in others])
        else:
            sweep_level = '(no sweep)'
            sweep_tier = 0
            sweep_ts = None
            stacked_count = 0
            stacked_levels = ''

        # Opposite-FVG path-clear (Phil 2026-05-25): scan 1R above (long) or below (short)
        path_clear, nearest_opp_pts, n_opp_in_path = find_opposing_in_path(
            gaps, inv_close, inv_ts, direction, scan_distance=stop_distance,
        )

        candidates.append({
            'date': date_str,
            'entry_ts_ny': ny_t.strftime('%Y-%m-%d %H:%M:%S'),
            'direction': direction,
            'entry_price': inv_close,
            'stop_price': stop_price,
            'stop_distance_pts': stop_distance,
            'is_combined': c.is_combined,
            'n_source_gaps': len(c.source),
            'multi_tf_count': len(c.tfs),
            'tfs_in_cluster': '+'.join(sorted(c.tfs)),
            'combined_span_pts': c.span,
            'largest_source_size': max(g.size_pts for g in c.source),
            'cluster_top': c.top,
            'cluster_bottom': c.bottom,
            'path_clear': path_clear,
            'nearest_opp_fvg_pts': nearest_opp_pts,
            'n_opp_in_path': n_opp_in_path,
            'sweep_level': sweep_level,
            'sweep_tier': sweep_tier,
            'sweep_ts_ny': sweep_ts.tz_convert('America/New_York').strftime('%H:%M:%S') if sweep_ts is not None else '',
            'stacked_levels_count': stacked_count,
            'stacked_levels': stacked_levels,
            'inversion_body_fraction': body_frac,
        })

    return sorted(candidates, key=lambda c: c['entry_ts_ny'])


def main():
    print("=== v0.5 emitter — proactive combining + is_combined tag ===")
    print(f"MAX_MERGED_SL={MAX_MERGED_SL}pt  MIN_TRADEABLE_SPAN={MIN_TRADEABLE_SPAN}pt  "
          f"BUILD_MIN_SIZE={BUILD_MIN_SIZE}pt")
    print()

    candles = load_candles(DATA_PATH)
    candles['date_ny'] = candles['timestamp_ny'].dt.date.astype(str)
    levels = pd.read_csv(LEVELS_PATH, low_memory=False)

    cohort = sorted(candles['date_ny'].unique())
    cohort = [d for d in cohort if d >= '2026-05-04']
    print(f"Cohort: {len(cohort)} sessions ({cohort[0]} → {cohort[-1]})")

    all_cands = []
    for d in cohort:
        day = candles[candles['date_ny'] == d].reset_index(drop=True)
        if day.empty:
            continue
        all_cands.extend(emit_for_day(d, day, levels))

    df = pd.DataFrame(all_cands)
    out_csv = OUT_DIR / 'candidates_3wk.csv'
    df.to_csv(out_csv, index=False)

    print(f"\nEmitted {len(df)} cluster-based candidates")
    print(f"  combined (is_combined=True):     {df['is_combined'].sum()}")
    print(f"  singleton (is_combined=False):   {(~df['is_combined']).sum()}")
    print(f"  with valid sweep:                {(df['sweep_level']!='(no sweep)').sum()}")
    print(f"  combined AND with sweep:         {((df['is_combined']) & (df['sweep_level']!='(no sweep)')).sum()}")

    # Show swept-only, sorted
    sub = df[df['sweep_level']!='(no sweep)'].copy().sort_values(['date','entry_ts_ny'])
    out2 = OUT_DIR / 'candidates_3wk_swept.csv'
    sub.to_csv(out2, index=False)
    print(f"\nSwept-only list → {out2}  ({len(sub)} rows)")

    cols = ['date','entry_ts_ny','direction','is_combined','n_source_gaps','multi_tf_count',
            'tfs_in_cluster','combined_span_pts','largest_source_size','stop_distance_pts',
            'sweep_level','sweep_tier']
    print(f"\n=== SWEPT CANDIDATES (sorted) ===")
    with pd.option_context('display.width', 240, 'display.max_columns', None):
        print(sub[cols].to_string(index=False))


if __name__ == '__main__':
    main()
