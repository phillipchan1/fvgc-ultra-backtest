#!/usr/bin/env python3
"""v0.6 candidate emitter — Phase B bug fixes from SPEC.md v2.0.

Fixes from v0.5 (Phil manual review 2026-05-25, applied 2026-05-26):

  #43 BUG: Cluster inversion must use the LARGEST-TF candle close, not the 30s
       stream. Phil noted 5/13 9:54:30 3m gap was 'not inversed' on its own TF.
       Fix: resample candles to the largest TF in cluster, check close on THAT.

  #44 LABEL SPLIT: 'is_combined' was ambiguous. Now two flags:
       - is_multi_tf:   same body detected across multiple TFs (1 visual gap)
       - is_zone_merge: distinct zones at different price levels merged
       Heuristic: zone_merge = True if span > 1.5 * largest_source_size.

  #39 TIME-WINDOW DEDUP: within DEDUPE_WINDOW_SEC of (direction, sweep_level),
       keep only the BEST candidate. 'Best' = tightest SL (rank 1) then most
       multi-gap conviction (rank 2). Eliminates 5/13 firing 5 candidates.

  #40 ABS SL CEILING: skip any candidate with stop_distance_pts > 60.0.
       Multi-gap-validated zones don't override this hard ceiling.

  §2.2 PREMIUM/DISCOUNT FILTER: compute pd_position at inversion time from
       running session H/L; skip if 0.45 <= pd_position <= 0.55 (mid-range).
       SHORT requires pd_position >= 0.50; LONG requires <= 0.50.

Carried forward from v0.5:
  - Proactive cluster merging with 40pt SL cap
  - MIN_TRADEABLE_SPAN = 8pt
  - Path-clear factor (any opposing FVG within 1R)
  - Sweep validity 40 min
  - Sweep-level co-location dedup

Output: studies/ifvg_reversal_population/results/v0_6/candidates_3wk.csv
"""

import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pandas as pd

from fvgc.data import load_candles
from ifvg_reversal.constants import (
    HARD_STOP_BUFFER, MOMENTUM_BODY_FRACTION,
    TRADING_WINDOW_END, TRADING_WINDOW_START,
)
from ifvg_reversal.detectors.multi_tf_fvg import (
    MultiTFGap, build_fvg_inventory, mark_inversions, _resample_ohlc, _TF_FREQ,
)
from ifvg_reversal.detectors.sweep import detect_sweeps

DATA_PATH = Path('data/consolidated/nq-front-month.ohlcv-30s.csv')
LEVELS_PATH = Path('data/levels/session_levels.csv')
OUT_DIR = Path(__file__).resolve().parent / 'results' / 'v0_6'
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ---- Clustering ----
MAX_MERGED_SL = 40.0
MIN_TRADEABLE_SPAN = 8.0
BUILD_MIN_SIZE = 3.0

# ---- Label split ----
ZONE_MERGE_SPAN_RATIO = 1.5  # span > 1.5 * largest_source_size = true zone merge

# ---- Time-window dedup ----
DEDUPE_WINDOW_SEC = 300  # 5 min — collapse same-setup re-firings

# ---- Absolute SL ceiling ----
MAX_SL_CEILING = 60.0

# ---- Premium/Discount filter ----
MID_RANGE_LO = 0.45
MID_RANGE_HI = 0.55

# ---- Other ----
DEDUPE_TOLERANCE_PTS = 5.0
SWEEP_VALIDITY_MIN = 40

# TF size ordering (smallest → largest) for "largest TF in cluster"
_TF_ORDER = {'30s': 0, '1min': 1, '2min': 2, '3min': 3}

# Bar duration in seconds — used to compute bar CLOSE time from bar START label
_TF_SECONDS = {'30s': 30, '1min': 60, '2min': 120, '3min': 180}


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
    def is_multi_tf(self) -> bool:
        return len(self.tfs) > 1

    @property
    def is_zone_merge(self) -> bool:
        """True if the cluster spans substantially more than its largest source.

        If largest gap is 19pt and cluster span is 20pt, this is just multi-TF detection
        of the same body (not_zone_merge). If span is 35pt with largest 19pt, the cluster
        merged distinct zones (is_zone_merge=True).
        """
        if not self.source:
            return False
        largest = max(g.size_pts for g in self.source)
        return self.span > ZONE_MERGE_SPAN_RATIO * largest

    @property
    def largest_tf(self) -> str:
        return max(self.tfs, key=lambda tf: _TF_ORDER.get(tf, 0))


def cluster_fvgs(gaps: List[MultiTFGap], max_sl: float = MAX_MERGED_SL) -> List[FVGCluster]:
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


def mark_cluster_inversions_fixed(
    clusters: List[FVGCluster], candles_day: pd.DataFrame
):
    """v0.6 fix (#43): use the cluster's LARGEST TF candle stream for inversion check.

    For a cluster containing only 30s gaps, use 30s bars.
    For a cluster containing 30s + 1m + 2m, use 2m bars (largest).
    A 3m gap can ONLY be inverted by a 3m close.

    Returns list of (cluster, inversion_ts, inversion_close, body_fraction, used_tf).
    """
    out = []
    # Pre-build TF-resampled bar streams (cache per TF)
    by_tf: Dict[str, pd.DataFrame] = {'30s': candles_day[['timestamp_ny','open','high','low','close']].sort_values('timestamp_ny').reset_index(drop=True)}
    for c in clusters:
        tf = c.largest_tf
        if tf not in by_tf:
            by_tf[tf] = _resample_ohlc(candles_day, _TF_FREQ[tf])
        bars = by_tf[tf]

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
        out.append((c, first['timestamp_ny'], float(first['close']), body_frac, tf))
    return out


def find_opposing_in_path(
    gaps: List[MultiTFGap], entry_price: float, entry_ts: pd.Timestamp,
    direction: str, scan_distance: float,
):
    opposing_dir = 'bearish' if direction == 'long' else 'bullish'
    in_path = []
    for g in gaps:
        if g.direction != opposing_dir:
            continue
        if g.created_at >= entry_ts:
            continue
        already_inverted = g.is_inverted and g.inverted_at < entry_ts
        if already_inverted:
            continue
        if direction == 'long':
            if entry_price < g.bottom <= entry_price + scan_distance:
                in_path.append((g.bottom - entry_price, g))
            elif g.bottom <= entry_price <= g.top and g.top <= entry_price + scan_distance:
                in_path.append((0.0, g))
        else:
            if entry_price - scan_distance <= g.top < entry_price:
                in_path.append((entry_price - g.top, g))
            elif g.bottom <= entry_price <= g.top and g.bottom >= entry_price - scan_distance:
                in_path.append((0.0, g))
    if not in_path:
        return (True, None, 0)
    in_path.sort(key=lambda x: x[0])
    return (False, in_path[0][0], len(in_path))


def compute_pd_position(candles_day: pd.DataFrame, at_ts: pd.Timestamp, current_price: float) -> Optional[float]:
    """§2.2: pd_position = (price - day_low) / (day_high - day_low) using RTH bars 9:30 → at_ts."""
    rth = candles_day[
        (candles_day['timestamp_ny'].dt.time >= TRADING_WINDOW_START) &
        (candles_day['timestamp_ny'] <= at_ts)
    ]
    if rth.empty:
        return None
    dl = float(rth['low'].min())
    dh = float(rth['high'].max())
    if dh <= dl:
        return None
    return (current_price - dl) / (dh - dl)


def time_window_dedupe(candidates: List[dict], window_sec: int = DEDUPE_WINDOW_SEC) -> List[dict]:
    """Within (direction, sweep_level) and time window, keep BEST candidate.

    'Best' = (smallest stop_distance_pts, most multi_gap_count).
    """
    if not candidates:
        return []
    # Sort by entry time
    cands = sorted(candidates, key=lambda c: c['entry_ts_ny'])
    kept: List[dict] = []
    for c in cands:
        c_ts = pd.Timestamp(c['entry_ts_ny'])
        c_key = (c['direction'], c['sweep_level'])
        # See if there's a recently-kept candidate in same window with same key
        duplicate = None
        for k in kept:
            k_ts = pd.Timestamp(k['entry_ts_ny'])
            if (c['direction'], k['sweep_level']) != c_key:
                continue
            if abs((c_ts - k_ts).total_seconds()) <= window_sec:
                duplicate = k
                break
        if duplicate is None:
            kept.append(c)
            continue
        # Decide which is better
        def score(x):
            return (x['stop_distance_pts'], -x.get('n_source_gaps', 0))
        if score(c) < score(duplicate):
            kept.remove(duplicate)
            kept.append(c)
    return sorted(kept, key=lambda x: x['entry_ts_ny'])


def emit_for_day(date_str: str, candles_day: pd.DataFrame, levels: pd.DataFrame):
    gaps = build_fvg_inventory(candles_day, min_size=BUILD_MIN_SIZE)
    mark_inversions(gaps, candles_day)
    clusters = cluster_fvgs(gaps)
    tradeable = [c for c in clusters if c.span >= MIN_TRADEABLE_SPAN]
    cluster_inv = mark_cluster_inversions_fixed(tradeable, candles_day)
    sweeps = detect_sweeps(candles_day, levels)

    candidates = []
    for c, inv_ts, inv_close, body_frac, used_tf in cluster_inv:
        if body_frac < MOMENTUM_BODY_FRACTION:
            continue
        # Bar-close time = bar start + TF duration. Used for sweep matching
        # so that a sweep happening DURING a 1m+ bar is correctly visible to
        # that bar's inversion confirmation at its close.
        bar_close_ts = inv_ts + pd.Timedelta(seconds=_TF_SECONDS.get(used_tf, 30))
        ny_t = bar_close_ts.tz_convert('America/New_York') if bar_close_ts.tz else bar_close_ts
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

        # #40 Absolute SL ceiling
        if stop_distance > MAX_SL_CEILING:
            continue

        # §2.2 Premium/Discount — exposed as TAG, not filter
        # (Hard filter killed valid setups on fast-mover days like 5/20 where
        # the entry happens after price has swept then moved decisively away
        # from the sweep level. Keep as a score factor for downstream gating.)
        pd_pos = compute_pd_position(candles_day, inv_ts, inv_close)
        pd_aligned = None
        if pd_pos is not None:
            if direction == 'short':
                pd_aligned = pd_pos >= 0.50
            else:
                pd_aligned = pd_pos <= 0.50

        # Path-clear
        path_clear, nearest_opp_pts, n_opp_in_path = find_opposing_in_path(
            gaps, inv_close, inv_ts, direction, scan_distance=stop_distance,
        )

        # Sweep matching uses BAR-CLOSE time (when inversion is realized),
        # not bar-start label. Lets a 1m+ inversion see a sweep that
        # happened mid-bar.
        valid_sweeps = [
            s for s in sweeps
            if s.reversal_direction == direction
            and s.timestamp_ny <= bar_close_ts
            and s.timestamp_ny >= bar_close_ts - pd.Timedelta(minutes=SWEEP_VALIDITY_MIN)
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
        else:
            sweep_level = '(no sweep)'
            sweep_tier = 0
            sweep_ts = None
            stacked_count = 0

        candidates.append({
            'date': date_str,
            'entry_ts_ny': ny_t.strftime('%Y-%m-%d %H:%M:%S'),
            'direction': direction,
            'entry_price': inv_close,
            'stop_price': stop_price,
            'stop_distance_pts': stop_distance,
            'used_tf_for_inversion': used_tf,    # #43 transparency
            'is_multi_tf': c.is_multi_tf,        # #44
            'is_zone_merge': c.is_zone_merge,    # #44
            'n_source_gaps': len(c.source),
            'multi_tf_count': len(c.tfs),
            'tfs_in_cluster': '+'.join(sorted(c.tfs)),
            'combined_span_pts': c.span,
            'largest_source_size': max(g.size_pts for g in c.source),
            'cluster_top': c.top,
            'cluster_bottom': c.bottom,
            'pd_position': pd_pos,
            'pd_aligned': pd_aligned,
            'path_clear': path_clear,
            'nearest_opp_fvg_pts': nearest_opp_pts,
            'n_opp_in_path': n_opp_in_path,
            'sweep_level': sweep_level,
            'sweep_tier': sweep_tier,
            'sweep_ts_ny': sweep_ts.tz_convert('America/New_York').strftime('%H:%M:%S') if sweep_ts is not None else '',
            'stacked_levels_count': stacked_count,
            'inversion_body_fraction': body_frac,
        })

    # #39 Time-window dedup
    candidates = time_window_dedupe(candidates)
    return candidates


def main():
    print("=== v0.6 emitter — Phase B bug fixes ===")
    print(f"Fixes: cluster-inv-TF (#43), label split (#44), time-window dedup (#39),")
    print(f"       SL ceiling {MAX_SL_CEILING}pt (#40), premium/discount filter (§2.2)")
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
    if df.empty:
        print("No candidates emitted.")
        return

    out_csv = OUT_DIR / 'candidates_3wk.csv'
    df.to_csv(out_csv, index=False)

    print(f"\nEmitted {len(df)} candidates")
    print(f"  is_multi_tf:    {df['is_multi_tf'].sum()}")
    print(f"  is_zone_merge:  {df['is_zone_merge'].sum()}")
    print(f"  with sweep:     {(df['sweep_level']!='(no sweep)').sum()}")
    print(f"  path_clear:     {df['path_clear'].sum()}")
    print(f"  pd_position direction-aligned: implicit (mid-range pre-filtered)")

    sub = df[df['sweep_level']!='(no sweep)'].copy().sort_values(['date','entry_ts_ny'])
    out2 = OUT_DIR / 'candidates_3wk_swept.csv'
    sub.to_csv(out2, index=False)
    print(f"\nSwept-only → {out2}  ({len(sub)} rows)")

    cols = ['date','entry_ts_ny','direction','used_tf_for_inversion',
            'is_multi_tf','is_zone_merge','n_source_gaps',
            'tfs_in_cluster','combined_span_pts','largest_source_size',
            'stop_distance_pts','pd_position','path_clear','nearest_opp_fvg_pts',
            'sweep_level','sweep_tier']
    print(f"\n=== SWEPT CANDIDATES ===")
    with pd.option_context('display.width', 240, 'display.max_columns', None):
        print(sub[cols].to_string(index=False))


if __name__ == '__main__':
    main()
