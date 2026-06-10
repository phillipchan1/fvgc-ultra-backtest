"""Draw map: named liquidity levels, their sweep state, and intra-RTH sweep times.

Point-in-time contract:
  - Level prices come from data/levels/session_levels.csv which carries an
    available_time column ('open' = known at 9:30; '09:45' = OR levels known
    only once the opening range completes). Features must respect it.
  - swept_pre_rth is an overnight fact, known by 9:30.
  - Intra-RTH sweep times are detected on 30s bars; a sweep "exists" for a
    trade only if its sweep bar closed at or before the trade's entry bar.
"""
from __future__ import annotations

from datetime import time as dtime
from pathlib import Path

import numpy as np
import pandas as pd

RTH_START = dtime(9, 30)
RTH_SCAN_END = dtime(10, 35)  # entries end 10:15; +20m covers post-sweep reversal scans


def load_level_table(csv_path: str | Path,
                     trading_days_csv: str | Path) -> pd.DataFrame:
    """Per (date, level_name) rows: price, side, available_mod, swept_pre_rth.

    Adds a derived 'prev_close' level (prior RTH close = today's open minus the
    gap, both known at 9:30; settlement proxied by prior close — documented).
    """
    lv = pd.read_csv(csv_path, low_memory=False,
                     parse_dates=["date"])
    lv = lv[["date", "level_name", "group", "side", "price", "available_time",
             "swept_pre_rth", "swept_pre_rth_time"]].copy()
    lv["available_mod"] = np.where(lv["available_time"].astype(str) == "open", 570,
                                   585)
    lv["swept_pre_rth"] = lv["swept_pre_rth"].fillna(False).astype(bool)

    td = pd.read_csv(trading_days_csv, parse_dates=["date"])
    prev_close = (td["rth_open"] - td["gap_from_prior_close"])
    pc = pd.DataFrame({
        "date": td["date"], "level_name": "prev_close", "group": "prev_day",
        "side": "either", "price": prev_close, "available_time": "open",
        "swept_pre_rth": False, "swept_pre_rth_time": pd.NaT,
        "available_mod": 570,
    })
    # side 'either': acts as resistance if above the 9:30 open, support if below;
    # resolved per-trade at snapshot time against entry price.
    out = pd.concat([lv, pc], ignore_index=True)
    return out.dropna(subset=["price"])


def daily_atr14_lagged(trading_days_csv: str | Path) -> pd.Series:
    """ATR(14) of RTH daily bars, lagged one day (only prior days used)."""
    td = pd.read_csv(trading_days_csv, parse_dates=["date"]).sort_values("date")
    hi, lo, cl = td["rth_high"], td["rth_low"], td["rth_close"]
    prev_cl = cl.shift(1)
    tr = pd.concat([hi - lo, (hi - prev_cl).abs(), (lo - prev_cl).abs()],
                   axis=1).max(axis=1)
    atr = tr.rolling(14, min_periods=5).mean().shift(1)  # shift(1): yesterday's ATR
    return pd.Series(atr.values, index=td["date"].values, name="atr14_lag1")


def rth_slices(bars: pd.DataFrame) -> dict:
    """{session_date(np.datetime64[D]): (ts, high, low, close) numpy arrays}
    for 09:30 <= t < RTH_SCAN_END."""
    tod = bars["timestamp_ny"].dt.time
    m = (tod >= RTH_START) & (tod < RTH_SCAN_END)
    sub = bars[m]
    out = {}
    for day, g in sub.groupby(sub["timestamp_ny"].dt.normalize()):
        out[day] = (g["timestamp_ny"].values, g["high"].values,
                    g["low"].values, g["close"].values)
    return out


def intra_rth_sweeps(level_table: pd.DataFrame, slices: dict) -> pd.DataFrame:
    """First intra-RTH sweep time per (date, level_name).

    Sweep: any 30s bar with high >= level (resistance) or low <= level
    (support). 'either'-side levels are swept by either touch (first one).
    Also records the immediate reversal magnitude within 4 and 10 bars after
    the sweep bar (for need_v3 rejection grading) and whether the latest close
    before +10 bars reclaimed the level.
    """
    rows = []
    for date, g in level_table.groupby("date"):
        sl = slices.get(pd.Timestamp(date))
        if sl is None:
            continue
        ts, high, low, close = sl
        for r in g.itertuples():
            price = r.price
            if r.side == "resistance":
                hits = high >= price
            elif r.side == "support":
                hits = low <= price
            else:  # either
                hits = (high >= price) | (low <= price)
            j = int(np.argmax(hits))
            if not hits[j]:
                continue
            # direction of the sweep at bar j
            swept_up = high[j] >= price if r.side != "support" else False
            if r.side == "either":
                swept_up = high[j] >= price
            rev4 = rev10 = np.nan
            reclaimed = False
            for nb, name in ((4, "rev4"), (10, "rev10")):
                seg_end = min(j + 1 + nb, len(ts))
                if seg_end > j + 1:
                    if swept_up:
                        rev = price - low[j + 1:seg_end].min()
                    else:
                        rev = high[j + 1:seg_end].max() - price
                    if name == "rev4":
                        rev4 = rev
                    else:
                        rev10 = rev
            k = min(j + 10, len(ts) - 1)
            reclaimed = close[k] < price if swept_up else close[k] > price
            rows.append((pd.Timestamp(date), r.level_name, ts[j], swept_up,
                         rev4, rev10, reclaimed))
    return pd.DataFrame(rows, columns=["date", "level_name", "sweep_ts",
                                       "swept_up", "rev4_pts", "rev10_pts",
                                       "reclaimed_by_10b"])
