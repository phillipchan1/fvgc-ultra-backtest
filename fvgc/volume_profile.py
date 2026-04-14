"""
Volume Profile calculation from OHLCV candles.

Computes POC (Point of Control), VAH (Value Area High), and VAL (Value Area Low)
from candle data by distributing volume into price buckets.
"""

from __future__ import annotations

from datetime import time as dtime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import pytz

NY_TZ = pytz.timezone('America/New_York')
RTH_START = dtime(9, 30)
RTH_END = dtime(16, 0)


def compute_volume_profile(
    candles: pd.DataFrame,
    bucket_size: float = 1.0,
    value_area_pct: float = 0.70,
) -> Optional[dict]:
    """
    Compute volume profile from OHLCV candles for a single session.

    Distributes each candle's volume uniformly across price buckets spanning
    its high-low range. Returns POC, VAH, VAL, and total volume.

    Parameters
    ----------
    candles : DataFrame with columns: high, low, volume
    bucket_size : price bucket width in points (default 1.0)
    value_area_pct : fraction of total volume for value area (default 0.70)

    Returns
    -------
    dict with keys: poc, vah, val, total_volume, va_width
    None if candles is empty or has no volume.
    """
    if candles.empty:
        return None

    session_low = candles['low'].min()
    session_high = candles['high'].max()
    total_volume = candles['volume'].sum()

    if total_volume == 0 or np.isnan(session_low) or np.isnan(session_high):
        return None

    # Build bucket edges from session low to high
    bucket_start = np.floor(session_low / bucket_size) * bucket_size
    bucket_end = np.ceil(session_high / bucket_size) * bucket_size + bucket_size
    edges = np.arange(bucket_start, bucket_end, bucket_size)

    if len(edges) < 2:
        return None

    # Bucket midpoints
    mids = (edges[:-1] + edges[1:]) / 2.0
    n_buckets = len(mids)
    vol_hist = np.zeros(n_buckets, dtype=np.float64)

    # Distribute each candle's volume across the buckets it spans
    for _, row in candles.iterrows():
        h, l, v = row['high'], row['low'], row['volume']
        if v <= 0 or np.isnan(v):
            continue

        if h == l:
            # Doji — all volume in one bucket
            idx = int((h - bucket_start) / bucket_size)
            idx = min(max(idx, 0), n_buckets - 1)
            vol_hist[idx] += v
        else:
            # Uniform distribution across spanned buckets
            lo_idx = int((l - bucket_start) / bucket_size)
            hi_idx = int((h - bucket_start) / bucket_size)
            lo_idx = max(lo_idx, 0)
            hi_idx = min(hi_idx, n_buckets - 1)
            n_span = hi_idx - lo_idx + 1
            per_bucket = v / n_span
            vol_hist[lo_idx:hi_idx + 1] += per_bucket

    # POC: bucket with maximum volume
    poc_idx = int(np.argmax(vol_hist))
    poc = float(mids[poc_idx])

    # Value Area: expand from POC until value_area_pct of total volume captured
    va_vol = vol_hist[poc_idx]
    target_vol = total_volume * value_area_pct
    lo = poc_idx
    hi = poc_idx

    while va_vol < target_vol and (lo > 0 or hi < n_buckets - 1):
        vol_above = vol_hist[hi + 1] if hi + 1 < n_buckets else 0.0
        vol_below = vol_hist[lo - 1] if lo > 0 else 0.0

        if vol_above >= vol_below:
            hi += 1
            va_vol += vol_hist[hi]
        else:
            lo -= 1
            va_vol += vol_hist[lo]

    val = float(edges[lo])          # bottom of lowest VA bucket
    vah = float(edges[hi + 1])      # top of highest VA bucket

    return {
        'poc': poc,
        'vah': vah,
        'val': val,
        'total_volume': int(total_volume),
        'va_width': vah - val,
    }


def build_daily_vp(candles: pd.DataFrame, output_path: Optional[Path] = None) -> pd.DataFrame:
    """
    Build daily volume profiles from consolidated OHLCV candles.

    Parameters
    ----------
    candles : DataFrame with columns: ts_ny, date_ny, high, low, close, volume
              (as returned by load_nq_consolidated)
    output_path : if provided, write CSV

    Returns
    -------
    DataFrame with columns: date, poc, vah, val, rth_volume, va_width
    """
    # Filter to RTH only (9:30-16:00 ET)
    times = candles['ts_ny'].dt.time
    rth = candles[(times >= RTH_START) & (times < RTH_END)].copy()

    rows = []
    for d, group in rth.groupby('date_ny'):
        vp = compute_volume_profile(group)
        if vp is None:
            continue
        rows.append({
            'date': d,
            'poc': vp['poc'],
            'vah': vp['vah'],
            'val': vp['val'],
            'rth_volume': vp['total_volume'],
            'va_width': vp['va_width'],
        })

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values('date').reset_index(drop=True)

    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(output_path, index=False)
        print(f'Wrote {len(df)} daily VP rows to {output_path}')

    return df
