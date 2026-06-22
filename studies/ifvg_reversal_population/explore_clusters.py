#!/usr/bin/env python3
"""Explore FVG clustering — merge same-direction FVGs whose combined zone
(merged_span + HARD_STOP_BUFFER) fits within MAX_MERGED_SL.

Goal: validate the user's mental model on 5/20:
  - Two 30s bullish gaps near each other, single candle inverted both.
  - With MAX_MERGED_SL = 40 they stay separate (since their merged SL = 53.5pt).
  - Still want to flag "multi-gap inversion" as a high-conviction event:
    when one candle close inverts >=2 same-direction FVGs in the same TF or
    across TFs, that's a stronger signal than a single-gap inversion.

This is a diagnostic script, not a population overwrite. Output is a per-day
view of cluster events + multi-gap inversion events for the recent 3 weeks.
"""

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Set

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pandas as pd

from fvgc.data import load_candles
from ifvg_reversal.constants import HARD_STOP_BUFFER
from ifvg_reversal.detectors.multi_tf_fvg import (
    MultiTFGap, build_fvg_inventory, mark_inversions,
)

DATA_PATH = Path('data/consolidated/nq-front-month.ohlcv-30s.csv')

# ---- Merge config ----
MAX_MERGED_SL = 40.0   # max (merged_span + HARD_STOP_BUFFER), per user
BUILD_MIN_SIZE = 6.0   # loose population floor


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
        # Treat entry ≈ outer bound (close that crosses); SL = inner extreme + buffer
        return self.span + HARD_STOP_BUFFER

    @property
    def tfs(self) -> Set[str]:
        return {g.tf for g in self.source}

    @property
    def is_merged(self) -> bool:
        return len(self.source) > 1


def cluster_fvgs(gaps: List[MultiTFGap], max_sl: float = MAX_MERGED_SL) -> List[FVGCluster]:
    """Greedy merge: start with each FVG as a singleton, then merge adjacent
    same-direction clusters whose union still satisfies the SL cap.

    Order-independent property is approximated; we sort by (direction, bottom)
    and walk left→right, merging only if the resulting cluster sl ≤ max_sl.
    """
    if not gaps:
        return []
    clusters: List[FVGCluster] = [
        FVGCluster(direction=g.direction, bottom=g.bottom, top=g.top, source=[g])
        for g in gaps
    ]
    # Sort by (direction, bottom) so same-direction clusters are adjacent.
    clusters.sort(key=lambda c: (c.direction, c.bottom))

    merged: List[FVGCluster] = []
    for c in clusters:
        if merged and merged[-1].direction == c.direction:
            cand_top = max(merged[-1].top, c.top)
            cand_bot = min(merged[-1].bottom, c.bottom)
            cand_sl = (cand_top - cand_bot) + HARD_STOP_BUFFER
            if cand_sl <= max_sl:
                merged[-1].top = cand_top
                merged[-1].bottom = cand_bot
                merged[-1].source.extend(c.source)
                continue
        merged.append(c)
    return merged


def find_multi_gap_inversions(gaps: List[MultiTFGap]):
    """Group FVGs by their inversion candle. >=2 gaps inverted by the same
    candle = high-conviction event (regardless of merging).
    """
    out = {}
    for g in gaps:
        if not g.is_inverted:
            continue
        key = (g.inverted_at, 'short' if g.direction == 'bullish' else 'long')
        out.setdefault(key, []).append(g)
    return {k: v for k, v in out.items() if len(v) >= 2}


def analyze_day(date_str: str, candles: pd.DataFrame, focus_window=('09:30','11:00')):
    day = candles[candles['date_ny'] == date_str].copy()
    if day.empty:
        return None
    gaps = build_fvg_inventory(day, min_size=BUILD_MIN_SIZE)
    mark_inversions(gaps, day)
    clusters = cluster_fvgs(gaps)
    merged_only = [c for c in clusters if c.is_merged]
    multi_inv = find_multi_gap_inversions(gaps)

    # Filter multi_inv to killzone hours — convert to NY tz first then format
    def _ny_hhmm(ts):
        if ts.tz is None:
            return ts.strftime('%H:%M')
        return ts.tz_convert('America/New_York').strftime('%H:%M')
    multi_inv_kz = {
        k: v for k, v in multi_inv.items()
        if focus_window[0] <= _ny_hhmm(k[0]) <= focus_window[1]
    }
    return {
        'date': date_str,
        'n_gaps': len(gaps),
        'n_clusters': len(clusters),
        'n_merged_clusters': len(merged_only),
        'merged_clusters': merged_only,
        'multi_inv_killzone': multi_inv_kz,
    }


def print_day(res):
    d = res['date']
    print(f"\n=== {d} ===")
    print(f"  FVGs: {res['n_gaps']}   Clusters: {res['n_clusters']}   "
          f"Merged clusters: {res['n_merged_clusters']}")

    if res['merged_clusters']:
        print(f"  --- Merged clusters (SL ≤ {MAX_MERGED_SL}) ---")
        for c in res['merged_clusters']:
            tfs = ','.join(sorted(c.tfs))
            print(f"    {c.direction:8} [{c.bottom:.2f}, {c.top:.2f}]  "
                  f"span={c.span:.1f}pt  SL={c.sl_distance:.1f}pt  "
                  f"n_gaps={len(c.source)}  TFs={tfs}")

    if res['multi_inv_killzone']:
        print(f"  --- Multi-gap inversion events (killzone) ---")
        for (ts, side), gs in sorted(res['multi_inv_killzone'].items()):
            tfs = ','.join(sorted({g.tf for g in gs}))
            bodies = ', '.join(f"{g.tf}[{g.bottom:.1f},{g.top:.1f}]" for g in gs)
            print(f"    {ts.strftime('%H:%M:%S')}  reverse={side}  "
                  f"N={len(gs)} gaps  TFs={tfs}")
            print(f"      bodies: {bodies}")


def main():
    print(f"=== FVG cluster + multi-gap inversion explorer ===")
    print(f"Rules: merge same-dir gaps if merged_span+buffer ≤ {MAX_MERGED_SL}pt; "
          f"flag multi-gap inversion when ≥2 same-dir FVGs share inversion candle\n")

    candles = load_candles(DATA_PATH)
    candles['date_ny'] = candles['timestamp_ny'].dt.date.astype(str)

    # Last 3 weeks
    cohort = sorted(candles['date_ny'].unique())
    cohort = [d for d in cohort if d >= '2026-05-04']
    print(f"Cohort: {len(cohort)} sessions ({cohort[0]} → {cohort[-1]})")

    for d in cohort:
        res = analyze_day(d, candles)
        if res is None:
            continue
        # Only print days with something interesting (merge or multi-inv)
        if res['merged_clusters'] or res['multi_inv_killzone']:
            print_day(res)
        else:
            print(f"\n=== {d} ===  (nothing merged, no multi-gap inversion in killzone)")


if __name__ == '__main__':
    main()
