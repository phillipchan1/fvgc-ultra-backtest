"""Multi-timeframe FVG inventory — §6.

Builds a list of qualifying FVGs across 30s/1m/2m/3m timeframes
(TARGET_GAP_TIMEFRAMES). Each FVG is tagged with its source TF, and
inversion is attributed using bars on the *same* TF (a 3m FVG is inverted
by a 3m close, not a 30s close — matches Tempo's "wait for candle close"
semantics on the FVG's own timeframe).

Per-day scoping: FVGs are detected within each NY trading date up through
the killzone end (11:00 NY). This avoids cross-session false gaps (Friday
close → Sunday open) and keeps inversion attribution local to the session.

Selection between candidate gaps happens in model.py (§6.3) — this module
just produces the inventory.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import time as dtime
from typing import Dict, List, Optional

import pandas as pd

from shared.fvg import detect_fvg, inverts_fvg

from ..constants import MIN_FVG_SIZE, TARGET_GAP_TIMEFRAMES, TRADING_WINDOW_END


# Pandas resample frequencies. Map our TF labels to pandas freq strings.
_TF_FREQ = {
    '30s':  '30s',
    '1min': '1min',
    '2min': '2min',
    '3min': '3min',
}


@dataclass
class MultiTFGap:
    """§6 v0.3.1 candidate FVG."""
    created_at: pd.Timestamp
    tf: str                              # '30s' | '1min' | '2min' | '3min'
    direction: str                       # 'bullish' or 'bearish'
    top: float
    bottom: float
    size_pts: float
    inverted_at: Optional[pd.Timestamp] = None
    inversion_candle_ts: Optional[pd.Timestamp] = None
    inversion_close_price: Optional[float] = None    # close of the inverting bar
    inversion_body_fraction: Optional[float] = None  # §7.2 momentum check

    @property
    def is_inverted(self) -> bool:
        return self.inverted_at is not None


def build_fvg_inventory(
    candles_30s: pd.DataFrame,
    min_size: float = MIN_FVG_SIZE,
) -> List[MultiTFGap]:
    """Build the multi-TF FVG inventory across all sessions in `candles_30s`.

    Scans each NY date up through TRADING_WINDOW_END (11:00 NY). For each TF
    in TARGET_GAP_TIMEFRAMES, resamples 30s base bars to that TF, scans
    consecutive triplets, and emits MultiTFGap records that pass `min_size`.

    `min_size` defaults to MIN_FVG_SIZE (the v0.3.x baseline). Population /
    permutation studies override with a looser threshold.

    Inversion fields are unset on emission — call `mark_inversions` after.
    """
    if candles_30s.empty:
        return []

    base = candles_30s[['timestamp_ny', 'open', 'high', 'low', 'close']].copy()
    base['date_ny'] = base['timestamp_ny'].dt.date.astype(str)

    gaps: List[MultiTFGap] = []
    for _, day in base.groupby('date_ny', sort=True):
        day = day[day['timestamp_ny'].dt.time <= TRADING_WINDOW_END]
        if len(day) < 3:
            continue

        for tf in TARGET_GAP_TIMEFRAMES:
            bars = day if tf == '30s' else _resample_ohlc(day, _TF_FREQ[tf])
            if len(bars) < 3:
                continue
            gaps.extend(_detect_on_tf(bars, tf, min_size=min_size))

    gaps.sort(key=lambda g: (g.created_at, g.tf))
    return gaps


def mark_inversions(gaps: List[MultiTFGap], candles_30s: pd.DataFrame) -> None:
    """Mark each FVG's inversion in-place using bars on its own TF.

    A gap is inverted by the first same-TF bar (after its creation) whose
    close passes through it in the opposite direction. Body fraction of that
    bar is recorded for §7.2 momentum checks downstream.

    Scoped per-session (NY date) so an FVG created on day D cannot be
    inverted by a bar from day D+1.
    """
    if not gaps or candles_30s.empty:
        return

    base = candles_30s[['timestamp_ny', 'open', 'high', 'low', 'close']].copy()
    base['date_ny'] = base['timestamp_ny'].dt.date.astype(str)
    # Pre-group by date once — O(1) lookup per session below.
    by_date = {d: g for d, g in base.groupby('date_ny', sort=False)}

    by_session_tf: Dict[tuple, List[MultiTFGap]] = defaultdict(list)
    for g in gaps:
        date_str = str(g.created_at.date())
        by_session_tf[(date_str, g.tf)].append(g)

    for (date_str, tf), session_gaps in by_session_tf.items():
        day = by_date.get(date_str)
        if day is None or day.empty:
            continue
        day = day[day['timestamp_ny'].dt.time <= TRADING_WINDOW_END]
        if day.empty:
            continue
        bars = day if tf == '30s' else _resample_ohlc(day, _TF_FREQ[tf])
        _mark_on_tf(session_gaps, bars)


# ---------- internals ----------

def _resample_ohlc(day: pd.DataFrame, freq: str) -> pd.DataFrame:
    """Resample a single NY date's 30s bars to a coarser TF."""
    df = day.set_index('timestamp_ny')
    out = df.resample(freq, label='left', closed='left').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
    }).dropna(how='any').reset_index()
    return out


def _detect_on_tf(bars: pd.DataFrame, tf: str, min_size: float) -> List[MultiTFGap]:
    """Scan consecutive triplets, emit MultiTFGap records that pass min_size."""
    out: List[MultiTFGap] = []
    if len(bars) < 3:
        return out
    for i in range(2, len(bars)):
        c1 = bars.iloc[i - 2]
        c2 = bars.iloc[i - 1]
        c3 = bars.iloc[i]
        fvg = detect_fvg(c1, c2, c3, min_size=min_size)
        if fvg is None:
            continue
        out.append(MultiTFGap(
            created_at=fvg.created_ts,
            tf=tf,
            direction=fvg.direction,
            top=fvg.top,
            bottom=fvg.bottom,
            size_pts=fvg.size,
        ))
    return out


def _mark_on_tf(gaps: List[MultiTFGap], bars: pd.DataFrame) -> None:
    """Walk bars forward; mark the first close that inverts each open gap.

    Linear in (bars × open_gaps), with open_gaps shrinking as inversions
    resolve. Acceptable for v0.3.1 cohort sizes.
    """
    open_gaps = sorted(gaps, key=lambda g: g.created_at)
    if not open_gaps:
        return

    for _, c in bars.iterrows():
        if not open_gaps:
            break
        ts = c['timestamp_ny']
        # Only consider gaps already created (strict-before this bar's close).
        still_open: List[MultiTFGap] = []
        rng = c['high'] - c['low']
        body = abs(c['close'] - c['open'])
        body_frac = (body / rng) if rng > 0 else 0.0

        for g in open_gaps:
            if g.created_at >= ts:
                still_open.append(g)
                continue
            if inverts_fvg(g.direction, g.top, g.bottom, c['close']):
                g.inverted_at = ts
                g.inversion_candle_ts = ts
                g.inversion_close_price = float(c['close'])
                g.inversion_body_fraction = body_frac
            else:
                still_open.append(g)
        open_gaps = still_open
