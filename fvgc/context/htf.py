"""Higher-timeframe machinery: resampling, HTF FVG inventory, swing structure.

Point-in-time contract:
  - An HTF FVG "exists" only from the close of its third bar (created_ts_known).
  - Touch/fill times are detected on 30s bars, so unmitigated-at-entry checks
    are precise to 30 seconds.
  - A swing point is "known" only once SWING_CONFIRM bars have printed after it.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

SWING_CONFIRM = 2  # bars each side, mirrors fvgc.model SWING_LOOKBACK
TOUCH_SCAN_DAYS = 10  # cap forward scan for FVG touch detection (trading days)


def load_bars_30s(path: str | Path) -> pd.DataFrame:
    """Load consolidated 30s bars; timestamps naive NY for joinability."""
    bars = pd.read_parquet(path, columns=["timestamp_ny", "open", "high", "low",
                                          "close", "volume"])
    ts = bars["timestamp_ny"]
    if ts.dt.tz is not None:
        bars["timestamp_ny"] = ts.dt.tz_localize(None)
    return bars.sort_values("timestamp_ny").reset_index(drop=True)


def resample(bars: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Resample 30s bars to an HTF frame (label=left; bar [t, t+rule))."""
    g = bars.set_index("timestamp_ny").resample(rule, label="left", closed="left")
    out = pd.DataFrame({
        "open": g["open"].first(), "high": g["high"].max(),
        "low": g["low"].min(), "close": g["close"].last(),
    }).dropna(subset=["open"]).reset_index()
    # known_ts: the moment this bar's values are final (its right edge)
    out["known_ts"] = out["timestamp_ny"] + pd.Timedelta(rule)
    return out


def detect_htf_fvgs(htf: pd.DataFrame, min_size: float = 0.0) -> pd.DataFrame:
    """Vectorized 3-bar FVG detection on an HTF frame.

    created_ts_known = close time of bar 3 (the first moment the gap exists).
    """
    c1h = htf["high"].shift(2)
    c1l = htf["low"].shift(2)
    c3h = htf["high"]
    c3l = htf["low"]

    bull = c1h < c3l
    bear = c1l > c3h
    rows = []
    for mask, direction in ((bull, "bullish"), (bear, "bearish")):
        idx = np.flatnonzero(mask.values)
        if len(idx) == 0:
            continue
        if direction == "bullish":
            top = c3l.values[idx]
            bottom = c1h.values[idx]
        else:
            top = c1l.values[idx]
            bottom = c3h.values[idx]
        size = top - bottom
        keep = size >= min_size
        rows.append(pd.DataFrame({
            "direction": direction,
            "top": top[keep], "bottom": bottom[keep],
            "created_ts_known": htf["known_ts"].values[idx[keep]],
        }))
    if not rows:
        return pd.DataFrame(columns=["direction", "top", "bottom",
                                     "created_ts_known", "touch_ts", "invert_ts"])
    fvgs = pd.concat(rows).sort_values("created_ts_known").reset_index(drop=True)
    fvgs["mid"] = (fvgs["top"] + fvgs["bottom"]) / 2
    return fvgs


def mark_touch_and_inversion(fvgs: pd.DataFrame, bars: pd.DataFrame) -> pd.DataFrame:
    """First 30s touch (price re-enters gap) and inversion (close through far
    edge) strictly AFTER created_ts_known. Forward scan capped at
    TOUCH_SCAN_DAYS trading days (~27,600 30s bars); FVGs untouched within the
    cap are treated as never-touched (logged by caller).
    """
    ts = bars["timestamp_ny"].values
    highs = bars["high"].values
    lows = bars["low"].values
    closes = bars["close"].values
    cap = TOUCH_SCAN_DAYS * 2760  # ~2,760 30s bars per full futures day

    touch = np.full(len(fvgs), np.datetime64("NaT"), dtype="datetime64[ns]")
    invert = np.full(len(fvgs), np.datetime64("NaT"), dtype="datetime64[ns]")
    starts = np.searchsorted(ts, fvgs["created_ts_known"].values, side="left")

    for i, (s, d, top, bottom) in enumerate(zip(
            starts, fvgs["direction"].values, fvgs["top"].values,
            fvgs["bottom"].values)):
        e = min(s + cap, len(ts))
        if s >= e:
            continue
        if d == "bullish":
            t_hits = lows[s:e] <= top
            v_hits = closes[s:e] < bottom
        else:
            t_hits = highs[s:e] >= bottom
            v_hits = closes[s:e] > top
        j = int(np.argmax(t_hits))
        if t_hits[j]:
            touch[i] = ts[s + j]
        k = int(np.argmax(v_hits))
        if v_hits[k]:
            invert[i] = ts[s + k]

    out = fvgs.copy()
    out["touch_ts"] = touch
    out["invert_ts"] = invert
    return out


def compute_swings(htf: pd.DataFrame, n: int = SWING_CONFIRM) -> pd.DataFrame:
    """Confirmed swing highs/lows; a swing is usable only from confirm_ts
    (the close time of the n-th bar after the pivot)."""
    h = htf["high"].values
    l = htf["low"].values
    rows = []
    for i in range(n, len(htf) - n):
        if all(h[i] > h[i - j] and h[i] > h[i + j] for j in range(1, n + 1)):
            rows.append((htf["timestamp_ny"].iloc[i], "high", h[i],
                         htf["known_ts"].iloc[i + n]))
        if all(l[i] < l[i - j] and l[i] < l[i + j] for j in range(1, n + 1)):
            rows.append((htf["timestamp_ny"].iloc[i], "low", l[i],
                         htf["known_ts"].iloc[i + n]))
    return pd.DataFrame(rows, columns=["bar_ts", "type", "price", "confirm_ts"])


def structure_at(swings: pd.DataFrame, ts: pd.Timestamp, k: int = 4) -> str:
    """HH/HL vs LH/LL read over the last k CONFIRMED swings as of ts.

    Returns 'up', 'down', or 'mixed'. Point-in-time: only swings with
    confirm_ts <= ts are visible.
    """
    vis = swings[swings["confirm_ts"] <= ts]
    if len(vis) < 4:
        return "mixed"
    last = vis.tail(k * 2)
    his = last[last["type"] == "high"]["price"].values
    los = last[last["type"] == "low"]["price"].values
    up = len(his) >= 2 and len(los) >= 2 and his[-1] > his[-2] and los[-1] > los[-2]
    dn = len(his) >= 2 and len(los) >= 2 and his[-1] < his[-2] and los[-1] < los[-2]
    if up:
        return "up"
    if dn:
        return "down"
    return "mixed"
