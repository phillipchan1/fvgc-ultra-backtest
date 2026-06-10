"""Per-trade point-in-time market-state snapshot at the entry bar.

build_snapshots(trades, ...) returns one row per trade with feature groups:

  A. Draw map        — named-level distances/status, HTF FVG proximity,
                       draw-count asymmetry, target alignment
  B. Need proxies    — v1 impulse-toward-draw (grid), v2 last-FVG-in-leg,
                       v3 rejection grade of last taken draw (grid)
  C. Session state   — sweep order, first-sweep identity, OR state,
                       HTF inversion state, macro window
  D. HTF alignment   — 15m/1h swing structure, prior-day range position,
                       gap context

Causality: every feature uses only bars/levels/events with timestamp <= the
trade's entry bar label. HTF bars must be fully closed (known_ts <= entry);
swings must be confirmed; levels must have available_mod <= entry mod;
post-sweep reversal grades are NaN unless the full grading window pre-dates
entry. Conservative by construction: an event in the entry bar's own 30s
window counts as known (entry fires at that bar's close).
"""
from __future__ import annotations

from datetime import time as dtime

import numpy as np
import pandas as pd

from .htf import (load_bars_30s, resample, detect_htf_fvgs,
                  mark_touch_and_inversion, compute_swings, structure_at)
from .draws import (load_level_table, daily_atr14_lagged, rth_slices,
                    intra_rth_sweeps)

IMPULSE_X = (20, 30, 40)      # points
IMPULSE_Y = (5, 10)           # minutes
REJECT_Z = (10, 15, 20)       # points
REJECT_N = (4, 10)            # bars
MIN_FVG_30S = 3.0             # mirrors frozen model min size

CORE_LEVELS = ["prev_day_high", "prev_day_low", "prev_close",
               "overnight_high", "overnight_low", "asia_high", "asia_low",
               "london_high", "london_low", "6am_high", "6am_low",
               "or_high", "or_low"]


def _mod(ts: pd.Timestamp) -> int:
    return ts.hour * 60 + ts.minute


def _detect_30s_fvgs(high: np.ndarray, low: np.ndarray, ts: np.ndarray):
    """Vectorized 3-bar FVGs on a session slice. Returns list of dicts with
    created_ts (= label of 3rd bar; values final at its close), direction,
    top, bottom."""
    out = []
    if len(high) < 3:
        return out
    c1h, c3l = high[:-2], low[2:]
    c1l, c3h = low[:-2], high[2:]
    bull = np.flatnonzero(c1h < c3l)
    bear = np.flatnonzero(c1l > c3h)
    for i in bull:
        if c3l[i] - c1h[i] >= MIN_FVG_30S:
            out.append(dict(created_ts=ts[i + 2], direction="bullish",
                            top=c3l[i], bottom=c1h[i]))
    for i in bear:
        if c1l[i] - c3h[i] >= MIN_FVG_30S:
            out.append(dict(created_ts=ts[i + 2], direction="bearish",
                            top=c1l[i], bottom=c3h[i]))
    return out


def build_context(bars_path, session_levels_csv, trading_days_csv,
                  cache_dir=None):
    """Precompute all shared tables. Returns a dict of context objects.
    Caches HTF FVG inventories under cache_dir if given."""
    import pickle
    from pathlib import Path

    bars = load_bars_30s(bars_path)

    cache_file = Path(cache_dir) / "htf_context.pkl" if cache_dir else None
    if cache_file and cache_file.exists():
        with open(cache_file, "rb") as f:
            htf_ctx = pickle.load(f)
    else:
        htf15 = resample(bars, "15min")
        htf60 = resample(bars, "1h")
        fvgs15 = mark_touch_and_inversion(detect_htf_fvgs(htf15), bars)
        fvgs60 = mark_touch_and_inversion(detect_htf_fvgs(htf60), bars)
        swings15 = compute_swings(htf15)
        swings60 = compute_swings(htf60)
        htf_ctx = dict(fvgs15=fvgs15, fvgs60=fvgs60,
                       swings15=swings15, swings60=swings60)
        if cache_file:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            with open(cache_file, "wb") as f:
                pickle.dump(htf_ctx, f)

    levels = load_level_table(session_levels_csv, trading_days_csv)
    slices = rth_slices(bars)
    sweeps = intra_rth_sweeps(levels, slices)
    atr = daily_atr14_lagged(trading_days_csv)

    td = pd.read_csv(trading_days_csv, parse_dates=["date"])
    gap = td.set_index("date")["gap_from_prior_close"]

    return dict(bars=bars, slices=slices, levels=levels, sweeps=sweeps,
                atr=atr, gap=gap, **htf_ctx)


def _nearest_unfilled(fvgs: pd.DataFrame, entry_ts, entry_price):
    """(dist_above, dist_below, n_above, n_below) among unmitigated FVGs
    visible at entry (created & not touched as of entry)."""
    created = fvgs["created_ts_known"].values
    lo = np.searchsorted(created, entry_ts - np.timedelta64(14, "D"))
    hi = np.searchsorted(created, entry_ts, side="right")
    w = fvgs.iloc[lo:hi]
    untouched = w["touch_ts"].isna() | (w["touch_ts"] > entry_ts)
    w = w[untouched]
    above = w[w["bottom"] > entry_price]
    below = w[w["top"] < entry_price]
    d_above = float((above["bottom"] - entry_price).min()) if len(above) else np.nan
    d_below = float((entry_price - below["top"]).min()) if len(below) else np.nan
    return d_above, d_below, len(above), len(below), w


def build_snapshots(trades: pd.DataFrame, ctx: dict) -> pd.DataFrame:
    """One snapshot row per trade. trades needs: timestamp, direction, variant,
    entry_price, sl_dist, fvg_created_at, fvg_top, fvg_bottom, fvg_mid."""
    levels_by_date = {d: g for d, g in ctx["levels"].groupby("date")}
    sweeps_by_date = {d: g.sort_values("sweep_ts")
                      for d, g in ctx["sweeps"].groupby("date")}
    rows = []

    for tr in trades.itertuples():
        entry_ts = tr.timestamp
        entry_np = np.datetime64(entry_ts)
        d = entry_ts.normalize()
        price = tr.entry_price
        is_long = tr.direction == "long"
        sgn = 1.0 if is_long else -1.0
        mod = _mod(entry_ts)
        atr = ctx["atr"].get(d, np.nan)
        row = dict(timestamp=entry_ts, direction=tr.direction,
                   variant=tr.variant, session_date=d)

        # ---------------- pre-entry session slice ----------------
        lv = levels_by_date.get(d)
        sw = sweeps_by_date.get(d)
        sl_bars = ctx["slices"].get(d)
        lv_vis = (lv[lv["available_mod"] <= mod] if lv is not None
                  else pd.DataFrame(columns=["level_name", "price",
                                             "swept_pre_rth", "side"]))
        sweep_map = ({r.level_name: r for r in sw.itertuples()}
                     if sw is not None else {})

        last_close = np.nan
        if sl_bars is not None:
            ts_a, hi_a, lo_a, cl_a = sl_bars
            kend = np.searchsorted(ts_a, entry_np, side="right")
            pre_ts, pre_hi, pre_lo, pre_cl = (ts_a[:kend], hi_a[:kend],
                                              lo_a[:kend], cl_a[:kend])
            if kend > 0:
                last_close = cl_a[kend - 1]
        else:
            pre_ts = pre_hi = pre_lo = pre_cl = np.array([])

        # Opening range (9:30-9:45), computed live from bars — session_levels
        # carries or_high/or_low rows but with NaN prices (live-only levels).
        # Point-in-time: only known from 9:45 (mod 585).
        orh = orl = np.nan
        j45 = 0
        if mod >= 585 and len(pre_ts):
            t945 = np.datetime64(d + pd.Timedelta(hours=9, minutes=45))
            j45 = int(np.searchsorted(pre_ts, t945))
            if j45 > 0:
                orh = float(pre_hi[:j45].max())
                orl = float(pre_lo[:j45].min())

        # ---------------- A. Draw map: named levels ----------------

        n_unt_above = n_unt_below = 0
        n_unt_above_1atr = n_unt_below_1atr = 0
        untaken_dists_dir = []           # untaken draws in trade direction
        for r in lv_vis.itertuples():
            lvl_price = r.price
            srec = sweep_map.get(r.level_name)
            swept_intra = (srec is not None
                           and srec.sweep_ts <= entry_np)
            swept_pre = bool(r.swept_pre_rth)
            untaken = not swept_pre and not swept_intra
            reclaimed = False
            if swept_intra and not np.isnan(last_close):
                reclaimed = (last_close < lvl_price if srec.swept_up
                             else last_close > lvl_price)
            status = ("untaken" if untaken
                      else ("swept_reclaimed" if reclaimed else "swept"))
            dist = lvl_price - price
            if r.level_name in CORE_LEVELS:
                key = r.level_name
                row[f"lvl_{key}_dist"] = dist
                row[f"lvl_{key}_dist_atr"] = dist / atr if atr else np.nan
                row[f"lvl_{key}_status"] = status
            if untaken:
                if dist > 0:
                    n_unt_above += 1
                    if atr and dist <= atr:
                        n_unt_above_1atr += 1
                elif dist < 0:
                    n_unt_below += 1
                    if atr and -dist <= atr:
                        n_unt_below_1atr += 1
                if dist * sgn > 0:
                    untaken_dists_dir.append(abs(dist))

        # OR H/L as live-computed draws (post-formation only). Sweep = strict
        # break beyond the OR boundary by a post-9:45 pre-entry bar.
        for name, lvl_price, is_res in (("or_high", orh, True),
                                        ("or_low", orl, False)):
            if np.isnan(lvl_price):
                row[f"lvl_{name}_dist"] = np.nan
                row[f"lvl_{name}_dist_atr"] = np.nan
                row[f"lvl_{name}_status"] = "unavailable"
                continue
            post = (pre_hi[j45:] > lvl_price if is_res
                    else pre_lo[j45:] < lvl_price)
            swept_intra = bool(post.any())
            reclaimed = False
            if swept_intra and not np.isnan(last_close):
                reclaimed = (last_close < lvl_price if is_res
                             else last_close > lvl_price)
            status = ("untaken" if not swept_intra
                      else ("swept_reclaimed" if reclaimed else "swept"))
            dist = lvl_price - price
            row[f"lvl_{name}_dist"] = dist
            row[f"lvl_{name}_dist_atr"] = dist / atr if atr else np.nan
            row[f"lvl_{name}_status"] = status
            if not swept_intra:
                if dist > 0:
                    n_unt_above += 1
                    if atr and dist <= atr:
                        n_unt_above_1atr += 1
                elif dist < 0:
                    n_unt_below += 1
                    if atr and -dist <= atr:
                        n_unt_below_1atr += 1
                if dist * sgn > 0:
                    untaken_dists_dir.append(abs(dist))

        row["n_untaken_above"] = n_unt_above
        row["n_untaken_below"] = n_unt_below
        row["draw_asym_dir"] = ((n_unt_above - n_unt_below) * (1 if is_long else -1))
        row["draw_asym_dir_1atr"] = ((n_unt_above_1atr - n_unt_below_1atr)
                                     * (1 if is_long else -1))
        nearest_dir = min(untaken_dists_dir) if untaken_dists_dir else np.nan
        row["nearest_untaken_dir_dist"] = nearest_dir
        row["nearest_untaken_dir_dist_R"] = (nearest_dir / tr.sl_dist
                                             if tr.sl_dist else np.nan)
        # target alignment: nearest untaken draw in trade direction sits AT or
        # BEYOND the 1R target -> the draw pulls price through the TP.
        row["target_aligned"] = (bool(nearest_dir >= tr.sl_dist)
                                 if not np.isnan(nearest_dir) else False)

        # ---------------- A. Draw map: HTF FVGs ----------------
        for tf, fkey in (("15m", "fvgs15"), ("1h", "fvgs60")):
            da, db, na, nb, vis = _nearest_unfilled(ctx[fkey], entry_np, price)
            row[f"htf{tf}_nearest_above"] = da
            row[f"htf{tf}_nearest_below"] = db
            row[f"htf{tf}_n_above"] = na
            row[f"htf{tf}_n_below"] = nb
            if tf == "15m":
                # Nesting: entry FVG mid inside a same-direction 15m FVG that
                # was created before entry and NOT inverted before entry.
                # (Touched-but-not-inverted is allowed: a nested entry is by
                # definition inside the zone, so price has touched it.)
                same_dir = "bullish" if is_long else "bearish"
                f15 = ctx["fvgs15"]
                created = f15["created_ts_known"].values
                lo_i = np.searchsorted(created, entry_np - np.timedelta64(14, "D"))
                hi_i = np.searchsorted(created, entry_np, side="right")
                w14 = f15.iloc[lo_i:hi_i]
                not_inv = w14["invert_ts"].isna() | (w14["invert_ts"] > entry_np)
                nest = w14[not_inv & (w14["direction"] == same_dir)
                           & (w14["bottom"] <= tr.fvg_mid)
                           & (w14["top"] >= tr.fvg_mid)]
                row["nested_15m"] = len(nest) > 0
                # inversion state: opposing-to-trade HTF FVG inverted today
                opp_dir = "bearish" if is_long else "bullish"
                f15 = ctx["fvgs15"]
                sess_start = np.datetime64(d + pd.Timedelta(hours=9, minutes=30))
                inv = f15[(f15["direction"] == opp_dir)
                          & f15["invert_ts"].notna()
                          & (f15["invert_ts"].values >= sess_start)
                          & (f15["invert_ts"].values <= entry_np)]
                row["opp_htf_inverted_today"] = len(inv) > 0

        # ---------------- B. Need proxies ----------------
        has_untaken_above = n_unt_above > 0
        has_untaken_below = n_unt_below > 0
        for X in IMPULSE_X:
            for Y in IMPULSE_Y:
                w = Y * 2  # 30s bars per minute
                flag = False
                if len(pre_cl) > w:
                    moves = pre_cl[w:] - pre_cl[:-w]
                    up_ok = (moves >= X).any() and has_untaken_above
                    dn_ok = (moves <= -X).any() and has_untaken_below
                    flag = up_ok if is_long else dn_ok
                row[f"need_v1_x{X}_y{Y}"] = flag

        # v2: entry FVG is the last unmitigated same-direction 30s FVG in leg
        need_v2 = np.nan
        if len(pre_cl) > 4:
            origin_idx = int(np.argmin(pre_lo)) if is_long else int(np.argmax(pre_hi))
            sess_fvgs = _detect_30s_fvgs(pre_hi, pre_lo, pre_ts)
            same_dir = "bullish" if is_long else "bearish"
            others = 0
            for f in sess_fvgs:
                if f["direction"] != same_dir:
                    continue
                if f["created_ts"] <= pre_ts[origin_idx]:
                    continue
                if f["created_ts"] == np.datetime64(tr.fvg_created_at):
                    continue  # the entry FVG itself
                # mitigated before entry? any later pre-entry bar re-enters gap
                j0 = np.searchsorted(pre_ts, f["created_ts"], side="right")
                if f["direction"] == "bullish":
                    mit = (pre_lo[j0:] <= f["top"]).any()
                else:
                    mit = (pre_hi[j0:] >= f["bottom"]).any()
                if not mit:
                    others += 1
            need_v2 = others == 0
        row["need_v2_last_fvg"] = need_v2

        # v3: rejection grade of most recent TAKEN draw (grading window must
        # fully pre-date entry, else NaN — no peeking)
        last_sweep = None
        if sw is not None:
            pre_sw = sw[sw["sweep_ts"].values <= entry_np]
            if len(pre_sw):
                last_sweep = pre_sw.iloc[-1]
        for Z in REJECT_Z:
            for N in REJECT_N:
                val = np.nan
                if last_sweep is not None:
                    window_end = last_sweep["sweep_ts"] + np.timedelta64(30 * N, "s")
                    if window_end <= entry_np:
                        rev = (last_sweep["rev4_pts"] if N == 4
                               else last_sweep["rev10_pts"])
                        if not pd.isna(rev):
                            val = bool(rev >= Z)
                row[f"need_v3_z{Z}_n{N}"] = val

        # ---------------- C. Session state ----------------
        if sw is not None:
            pre_sw = sw[sw["sweep_ts"].values <= entry_np]
            row["n_swept_so_far"] = len(pre_sw)
            row["first_sweep_name"] = (pre_sw.iloc[0]["level_name"]
                                       if len(pre_sw) else "none")
        else:
            row["n_swept_so_far"] = 0
            row["first_sweep_name"] = "none"

        # OR state (OR = 9:30-9:45, computed live; only known from 9:45)
        if mod < 585:
            row["or_state"] = "forming"
        elif np.isnan(orh) or np.isnan(orl):
            row["or_state"] = "unknown"
        else:
            bh = bool((pre_hi[j45:] > orh).any())
            bl = bool((pre_lo[j45:] < orl).any())
            row["or_state"] = ("broke_both" if bh and bl else
                               "broke_high" if bh else
                               "broke_low" if bl else "inside")

        row["macro_window"] = ("W1" if mod < 585 else
                               "W2" if mod < 600 else "W3")

        # ---------------- D. HTF alignment ----------------
        s15 = structure_at(ctx["swings15"], entry_ts)
        s60 = structure_at(ctx["swings60"], entry_ts)
        row["struct_15m"] = s15
        row["struct_1h"] = s60
        row["struct_15m_aligned"] = (s15 == ("up" if is_long else "down"))
        row["struct_1h_aligned"] = (s60 == ("up" if is_long else "down"))

        pdh = row.get("lvl_prev_day_high_dist")
        pdl = row.get("lvl_prev_day_low_dist")
        if pdh is not None and pdl is not None and not (
                pd.isna(pdh) or pd.isna(pdl)) and (pdh - pdl) != 0:
            pos = -pdl / (pdh - pdl)  # 0 at pd_low, 1 at pd_high
            row["pd_range_pos"] = pos
            zone = ("above" if pos > 1 else "below" if pos < 0
                    else "premium" if pos >= 0.5 else "discount")
            row["pd_zone"] = zone
            row["pd_zone_aligned"] = (zone == ("discount" if is_long else "premium"))
        else:
            row["pd_range_pos"] = np.nan
            row["pd_zone"] = "unknown"
            row["pd_zone_aligned"] = False

        gap = ctx["gap"].get(d, np.nan)
        row["gap_pts"] = gap
        row["gap_atr"] = gap / atr if atr and not pd.isna(gap) else np.nan
        if pd.isna(gap) or not atr or pd.isna(atr):
            gc = "unknown"
        elif abs(gap) < 0.2 * atr:
            gc = "flat"
        else:
            gc = "gap_up" if gap > 0 else "gap_down"
        row["gap_class"] = gc
        row["atr14_lag1"] = atr

        rows.append(row)

    return pd.DataFrame(rows)
