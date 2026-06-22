"""
Build rolling-window composite Volume Profiles (POC/VAH/VAL) per day.

Construction method
-------------------
Volume-weighted aggregation. For each date d and window W in {5, 10, 20}:
  - Collect all 30s RTH bars (9:30-16:00 ET) from the W trading days
    that strictly PRECEDE d (i.e. date_ny in the W most recent trading
    days before d).
  - Run the same TPO-volume distribution as the single-day VP
    (fvgc/volume_profile.py) on the unioned bars.
  - This is a true cross-day composite — each price bucket accumulates
    volume from every session in the window.

Look-ahead guard: composite for d uses only bars with date_ny < d.

Output: studies/composite_vp/results/composite_vp_levels.csv
  date, poc_5d, vah_5d, val_5d, va_width_5d, vol_5d,
        poc_10d, ..., poc_20d, ...
"""

from __future__ import annotations

from datetime import time as dtime
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / 'results'
OUT.mkdir(parents=True, exist_ok=True)

RTH_START = dtime(9, 30)
RTH_END = dtime(16, 0)
BUCKET_SIZE = 1.0
VA_PCT = 0.70
WINDOWS = (5, 10, 20)


def compute_vp_fast(highs, lows, vols, bucket_size=BUCKET_SIZE, va_pct=VA_PCT):
    """Vectorised TPO-volume VP on numpy arrays."""
    if highs.size == 0:
        return None
    total_vol = float(vols.sum())
    if total_vol <= 0:
        return None

    lo_all = float(lows.min())
    hi_all = float(highs.max())
    if not np.isfinite(lo_all) or not np.isfinite(hi_all):
        return None

    bucket_start = np.floor(lo_all / bucket_size) * bucket_size
    bucket_end = np.ceil(hi_all / bucket_size) * bucket_size + bucket_size
    n_buckets = int(round((bucket_end - bucket_start) / bucket_size))
    if n_buckets < 2:
        return None

    edges = bucket_start + np.arange(n_buckets + 1) * bucket_size
    mids = (edges[:-1] + edges[1:]) / 2.0

    lo_idx = np.clip(((lows - bucket_start) / bucket_size).astype(np.int64), 0, n_buckets - 1)
    hi_idx = np.clip(((highs - bucket_start) / bucket_size).astype(np.int64), 0, n_buckets - 1)
    n_span = (hi_idx - lo_idx + 1).astype(np.float64)
    per_bucket = vols.astype(np.float64) / n_span

    vol_hist = np.zeros(n_buckets, dtype=np.float64)
    # Tight loop; n_buckets typically <2000 and n_bars per window <30k.
    for i in range(highs.size):
        vol_hist[lo_idx[i]:hi_idx[i] + 1] += per_bucket[i]

    poc_idx = int(np.argmax(vol_hist))
    poc = float(mids[poc_idx])
    va_vol = vol_hist[poc_idx]
    target_vol = total_vol * va_pct
    lo = poc_idx
    hi = poc_idx
    while va_vol < target_vol and (lo > 0 or hi < n_buckets - 1):
        can_up = hi < n_buckets - 1
        can_dn = lo > 0
        vol_above = vol_hist[hi + 1] if can_up else -np.inf
        vol_below = vol_hist[lo - 1] if can_dn else -np.inf
        if can_up and (not can_dn or vol_above >= vol_below):
            hi += 1
            va_vol += vol_hist[hi]
        elif can_dn:
            lo -= 1
            va_vol += vol_hist[lo]
        else:
            break

    val = float(edges[lo])
    vah = float(edges[hi + 1])
    return {
        'poc': poc,
        'vah': vah,
        'val': val,
        'vol': total_vol,
        'va_width': vah - val,
    }


def main():
    print('=== build composite VP ===')
    bars = pl.read_parquet(ROOT / 'data/consolidated/nq-front-month.ohlcv-30s.parquet')
    print(f'30s bars: {bars.height:,}')

    # Filter to RTH (9:30-16:00 ET).
    bars = bars.with_columns([
        pl.col('timestamp_ny').dt.date().alias('date_ny'),
        pl.col('timestamp_ny').dt.time().alias('time_ny'),
    ])
    bars = bars.filter(
        (pl.col('time_ny') >= RTH_START) & (pl.col('time_ny') < RTH_END)
    )
    print(f'RTH 30s bars: {bars.height:,}')

    # Pre-arrays per session.
    per_day = {}
    for d, group in bars.group_by('date_ny'):
        d_val = d[0] if isinstance(d, tuple) else d
        h = group['high'].to_numpy()
        l = group['low'].to_numpy()
        v = group['volume'].to_numpy()
        per_day[d_val] = (h, l, v)

    dates_sorted = sorted(per_day.keys())
    print(f'sessions: {len(dates_sorted)} ({dates_sorted[0]} → {dates_sorted[-1]})')

    rows = []
    for i, d in enumerate(dates_sorted):
        row = {'date': d}
        for W in WINDOWS:
            if i < W:
                # Insufficient prior history.
                row[f'poc_{W}d'] = None
                row[f'vah_{W}d'] = None
                row[f'val_{W}d'] = None
                row[f'va_width_{W}d'] = None
                row[f'vol_{W}d'] = None
                continue
            window_dates = dates_sorted[i - W:i]  # strictly prior W sessions
            hs = np.concatenate([per_day[wd][0] for wd in window_dates])
            ls = np.concatenate([per_day[wd][1] for wd in window_dates])
            vs = np.concatenate([per_day[wd][2] for wd in window_dates])
            vp = compute_vp_fast(hs, ls, vs)
            if vp is None:
                row[f'poc_{W}d'] = None
                row[f'vah_{W}d'] = None
                row[f'val_{W}d'] = None
                row[f'va_width_{W}d'] = None
                row[f'vol_{W}d'] = None
            else:
                row[f'poc_{W}d'] = vp['poc']
                row[f'vah_{W}d'] = vp['vah']
                row[f'val_{W}d'] = vp['val']
                row[f'va_width_{W}d'] = vp['va_width']
                row[f'vol_{W}d'] = vp['vol']
        rows.append(row)
        if (i + 1) % 200 == 0:
            print(f'  {i+1}/{len(dates_sorted)} ({d})')

    df = pl.DataFrame(rows)
    out_path = OUT / 'composite_vp_levels.csv'
    df.write_csv(out_path)
    print(f'\nWrote {df.height} rows to {out_path}')

    # Quick sanity stats
    for W in WINDOWS:
        vw = df[f'va_width_{W}d'].drop_nulls()
        if vw.len():
            print(f'  W={W}d: VA-width mean={vw.mean():.1f} median={vw.median():.1f} (n={vw.len()})')


if __name__ == '__main__':
    main()
