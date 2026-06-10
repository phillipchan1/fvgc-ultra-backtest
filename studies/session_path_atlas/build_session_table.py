"""Session Path Atlas — per-session feature table builder.

One row per RTH session with: conditioners (as-of 9:30), OR5/OR15 break facts,
named-level touch times/distances, first-sweep identity, ping-pong pairs,
W1 facts + W2/W3 transition outcome, path stats, archetype label.

All definitions per results/DEFINITIONS.md (frozen 2026-06-09).
Run with python3.13 from repo root.
"""
from __future__ import annotations

import sys
from datetime import time as dtime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fvgc.context.htf import load_bars_30s
from fvgc.context.draws import load_level_table, daily_atr14_lagged

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
CACHE = RESULTS / "cache"

BARS_PATH = "data/consolidated/nq-front-month.ohlcv-30s.parquet"
LEVELS_CSV = "data/levels/session_levels.csv"
TDAYS_CSV = "data/trading_days/trading_days.csv"

ATLAS_LEVELS = ["prev_day_high", "prev_day_low", "prev_close",
                "overnight_high", "overnight_low", "asia_high", "asia_low",
                "london_high", "london_low", "6am_high", "6am_low"]
PAIRS = [("prev_day_high", "prev_day_low"), ("overnight_high", "overnight_low"),
         ("asia_high", "asia_low"), ("london_high", "london_low"),
         ("6am_high", "6am_low")]
DIST_EDGES = [0.0, 0.10, 0.25, 0.50, 1.00, np.inf]
DIST_LABELS = ["d00_10", "d10_25", "d25_50", "d50_100", "d100p"]

T930 = 9 * 3600 + 30 * 60     # seconds-of-day anchors
T935 = 9 * 3600 + 35 * 60
T945 = 9 * 3600 + 45 * 60
T1000 = 10 * 3600
T1015 = 10 * 3600 + 15 * 60


def sod(ts_arr):
    """Seconds-of-day for a datetime64 array."""
    t = pd.DatetimeIndex(ts_arr)
    return (t.hour * 3600 + t.minute * 60 + t.second).values


def or_break_facts(hi, lo, secs, or_end, orh, orl):
    """Break facts for one OR variant. Returns dict (times = seconds-of-day,
    NaN if no break). Strict > / < per DEFINITIONS §4."""
    post = secs >= or_end
    ph, pl, ps = hi[post], lo[post], secs[post]
    hb = ph > orh
    lb = pl < orl
    t_hi = float(ps[hb][0]) if hb.any() else np.nan
    t_lo = float(ps[lb][0]) if lb.any() else np.nan
    out = dict(t_hi=t_hi, t_lo=t_lo)
    out["any"] = not (np.isnan(t_hi) and np.isnan(t_lo))
    out["both"] = not np.isnan(t_hi) and not np.isnan(t_lo)
    if out["any"]:
        first_hi = (not np.isnan(t_hi)) and (np.isnan(t_lo) or t_hi < t_lo)
        # exact tie (same bar through both): label by larger penetration
        if (not np.isnan(t_hi)) and (not np.isnan(t_lo)) and t_hi == t_lo:
            j = int(np.searchsorted(ps, t_hi))
            first_hi = (ph[j] - orh) >= (orl - pl[j])
        out["first_side"] = "high" if first_hi else "low"
        out["t_first"] = t_hi if first_hi else t_lo
        b = orh if first_hi else orl
        mid = (orh + orl) / 2.0
        after = ps > out["t_first"]
        if first_hi:
            out["ext_pts"] = float((ph[ps >= out["t_first"]] - b).max())
            out["ret_mid"] = bool((pl[after] <= mid).any())
        else:
            out["ext_pts"] = float((b - pl[ps >= out["t_first"]]).max())
            out["ret_mid"] = bool((ph[after] >= mid).any())
    else:
        out.update(first_side="none", t_first=np.nan, ext_pts=np.nan,
                   ret_mid=np.nan)
    return out


def main():
    CACHE.mkdir(parents=True, exist_ok=True)
    print("loading bars ...")
    bars = load_bars_30s(BARS_PATH)
    ts_all = bars["timestamp_ny"]
    secs_all = sod(ts_all.values)
    date_all = ts_all.dt.normalize().values
    # session date for ON attribution: bars from 18:00 belong to NEXT calendar day
    # (sufficient for ON coverage + six2 since both windows end before 16:00)
    hi_all = bars["high"].values
    lo_all = bars["low"].values
    op_all = bars["open"].values
    cl_all = bars["close"].values

    td = pd.read_csv(TDAYS_CSV, parse_dates=["date"]).sort_values("date")
    atr_s = daily_atr14_lagged(TDAYS_CSV)
    levels = load_level_table(LEVELS_CSV, TDAYS_CSV)
    levels = levels[levels["level_name"].isin(ATLAS_LEVELS)]
    lv_by_date = {d: g.set_index("level_name") for d, g in levels.groupby("date")}

    # prior-day taxonomy inputs (all lagged)
    td = td.reset_index(drop=True)
    td["range_med20"] = td["rth_range"].rolling(20, min_periods=10).median()
    td["bull"] = td["rth_close"] > td["rth_open"]
    td["on_med20_lag"] = (td["overnight_range"].rolling(20, min_periods=10)
                          .median().shift(1))

    rows, excluded = [], []
    dates = td["date"].tolist()

    for i, d in enumerate(dates):
        drec = td.iloc[i]
        d64 = np.datetime64(d)
        # ---- slice today's RTH analysis window and the ON window ----
        day_mask = date_all == d64
        if not day_mask.any():
            excluded.append((d, "no_bars"))
            continue
        idx = np.flatnonzero(day_mask)
        s_day = secs_all[idx]
        rth_sel = idx[(s_day >= T930) & (s_day < T1015)]
        if len(rth_sel) < 85:
            excluded.append((d, f"rth_coverage_{len(rth_sel)}"))
            continue
        # ON window: 18:00 prior calendar day -> 9:30 today (expected 1860 bars)
        prev_cal = d64 - np.timedelta64(1, "D")
        on_sel = np.flatnonzero(
            ((date_all == prev_cal) & (secs_all >= 18 * 3600))
            | ((date_all == d64) & (secs_all < T930)))
        on_cov = len(on_sel) / 1860.0
        if on_cov < 0.90:
            excluded.append((d, f"on_coverage_{on_cov:.2f}"))
            continue
        atr = atr_s.get(pd.Timestamp(d), np.nan)
        if pd.isna(atr):
            excluded.append((d, "no_atr"))
            continue
        lv = lv_by_date.get(pd.Timestamp(d))
        if lv is None or len(lv) < 4:
            excluded.append((d, "no_levels"))
            continue

        hi = hi_all[rth_sel]; lo = lo_all[rth_sel]
        op = op_all[rth_sel]; cl = cl_all[rth_sel]
        secs = s_day[(s_day >= T930) & (s_day < T1015)]
        O = float(op[0])
        C = float(cl[-1])
        row = dict(date=pd.Timestamp(d), year=pd.Timestamp(d).year,
                   open_930=O, close_1015=C, atr=float(atr),
                   n_rth_bars=len(rth_sel), on_cov=round(on_cov, 3))

        # ---- path stats ----
        row["hi_1015"] = float(hi.max()); row["lo_1015"] = float(lo.min())
        row["net_move"] = C - O
        row["net_range"] = row["hi_1015"] - row["lo_1015"]
        row["mfe"] = row["hi_1015"] - O
        row["mae"] = O - row["lo_1015"]
        for k in ("net_move", "net_range", "mfe", "mae"):
            row[f"{k}_atr"] = row[k] / atr

        # ---- W1 facts ----
        w1m = secs < T945
        w1_hi = float(hi[w1m].max()); w1_lo = float(lo[w1m].min())
        w1_cl = float(cl[w1m][-1])
        row.update(w1_high=w1_hi, w1_low=w1_lo, w1_close=w1_cl)
        row["w1_dir"] = ("up" if w1_cl > O else "down" if w1_cl < O else "flat")
        row["w1_extreme_holds"] = (row["hi_1015"] == w1_hi) or (row["lo_1015"] == w1_lo)
        net_sign = np.sign(C - O)
        w1_sign = np.sign(w1_cl - O)
        row["w1_matches_net"] = (bool(w1_sign == net_sign)
                                 if (w1_sign != 0 and net_sign != 0) else np.nan)
        # W2/W3 transition outcome (close-based, DEFINITIONS §11)
        if row["w1_dir"] == "up":
            row["w23_outcome"] = ("continuation" if C > w1_hi
                                  else "reversal" if C < w1_lo else "chop")
        elif row["w1_dir"] == "down":
            row["w23_outcome"] = ("continuation" if C < w1_lo
                                  else "reversal" if C > w1_hi else "chop")
        else:
            row["w23_outcome"] = np.nan

        # ---- OR variants ----
        for tag, or_end in (("or5", T935), ("or15", T945)):
            wm = secs < or_end
            orh = float(hi[wm].max()); orl = float(lo[wm].min())
            f = or_break_facts(hi, lo, secs, or_end, orh, orl)
            row[f"{tag}_high"] = orh; row[f"{tag}_low"] = orl
            row[f"{tag}_range"] = orh - orl
            row[f"{tag}_any_break"] = f["any"]
            row[f"{tag}_both_break"] = f["both"]
            row[f"{tag}_first_side"] = f["first_side"]
            row[f"{tag}_t_first"] = f["t_first"]
            row[f"{tag}_t_hi"] = f["t_hi"]; row[f"{tag}_t_lo"] = f["t_lo"]
            row[f"{tag}_ext_pts"] = f["ext_pts"]
            row[f"{tag}_ext_atr"] = (f["ext_pts"] / atr
                                     if not np.isnan(f["ext_pts"]) else np.nan)
            row[f"{tag}_ret_mid"] = f["ret_mid"]
            for X in (10, 20, 30, 50):
                row[f"{tag}_ext_ge{X}"] = (f["ext_pts"] >= X
                                           if not np.isnan(f["ext_pts"]) else np.nan)
            tf = f["t_first"]
            row[f"{tag}_break_by_1000"] = (tf < T1000) if not np.isnan(tf) else False
            row[f"{tag}_break_in_w2w3"] = ((T945 <= tf < T1015)
                                           if not np.isnan(tf) else False)
        # >= sensitivity for the headline 94% claim (touch counts as taken)
        wm = secs < T945
        post = secs >= T945
        row["or15_any_break_touch"] = bool(
            (hi[post] >= row["or15_high"]).any() or (lo[post] <= row["or15_low"]).any())

        # ---- named levels ----
        onh = float(lv.loc["overnight_high", "price"]) if "overnight_high" in lv.index else np.nan
        onl = float(lv.loc["overnight_low", "price"]) if "overnight_low" in lv.index else np.nan
        first_name, first_t = "none", np.nan
        n_above = n_below = 0
        touch_t = {}
        for name in ATLAS_LEVELS:
            if name not in lv.index:
                row[f"lv_{name}_price"] = np.nan
                row[f"lv_{name}_untaken"] = np.nan
                row[f"lv_{name}_dist_atr"] = np.nan
                row[f"lv_{name}_bucket"] = ""
                row[f"lv_{name}_touch_t"] = np.nan
                continue
            L = float(lv.loc[name, "price"])
            if name == "prev_close":
                untaken = not (onl <= L <= onh) if not np.isnan(onh) else np.nan
            elif name in ("overnight_high", "overnight_low"):
                untaken = True
            else:
                untaken = not bool(lv.loc[name, "swept_pre_rth"])
            dist = L - O
            above = L >= O
            hitm = (hi >= L) if above else (lo <= L)
            t = float(secs[hitm][0]) if hitm.any() else np.nan
            touch_t[name] = t
            row[f"lv_{name}_price"] = L
            row[f"lv_{name}_untaken"] = untaken
            row[f"lv_{name}_dist_atr"] = abs(dist) / atr
            row[f"lv_{name}_bucket"] = DIST_LABELS[
                int(np.searchsorted(DIST_EDGES, abs(dist) / atr, side="right")) - 1]
            row[f"lv_{name}_touch_t"] = t
            if untaken is True:
                if L > O:
                    n_above += 1
                elif L < O:
                    n_below += 1
                if not np.isnan(t) and (np.isnan(first_t) or t < first_t):
                    first_t, first_name = t, name
        row["first_sweep_name"] = first_name
        row["first_sweep_t"] = first_t
        row["n_untaken_above"] = n_above
        row["n_untaken_below"] = n_below

        # nearest untaken draw each side + cross-side ordering (T8/T9)
        cand = [(name, row[f"lv_{name}_price"]) for name in ATLAS_LEVELS
                if row.get(f"lv_{name}_untaken") is True]
        ab = [(p - O, name) for name, p in cand if p > O]
        be = [(O - p, name) for name, p in cand if p < O]
        na = min(ab)[1] if ab else None
        nb = min(be)[1] if be else None
        row["nearest_above_name"] = na or "none"
        row["nearest_below_name"] = nb or "none"
        ta = touch_t.get(na, np.nan) if na else np.nan
        tb = touch_t.get(nb, np.nan) if nb else np.nan
        row["nearest_above_touch_t"] = ta
        row["nearest_below_touch_t"] = tb
        nearest = (min([x for x in (ab + be)])[1] if (ab or be) else None)
        row["nearest_untaken_name"] = nearest or "none"
        row["nearest_untaken_dist_atr"] = (min([x[0] for x in ab + be]) / atr
                                           if (ab or be) else np.nan)
        row["nearest_untaken_touched"] = (not np.isnan(touch_t.get(nearest, np.nan))
                                          if nearest else np.nan)
        if na and nb:
            row["below_before_above"] = (tb < ta if not np.isnan(tb) and not np.isnan(ta)
                                         else True if not np.isnan(tb)
                                         else False if not np.isnan(ta) else np.nan)
        else:
            row["below_before_above"] = np.nan

        # ping-pong pairs
        for hn, ln in PAIRS:
            tag = hn.replace("_high", "").replace("prev_day", "pd")
            th, tl = touch_t.get(hn, np.nan), touch_t.get(ln, np.nan)
            uh = row.get(f"lv_{hn}_untaken") is True
            ul = row.get(f"lv_{ln}_untaken") is True
            if not (uh and ul):
                row[f"pp_{tag}_first"] = "na"
                row[f"pp_{tag}_opposite"] = np.nan
                continue
            if np.isnan(th) and np.isnan(tl):
                row[f"pp_{tag}_first"] = "none"
                row[f"pp_{tag}_opposite"] = np.nan
            elif np.isnan(tl) or (not np.isnan(th) and th <= tl):
                row[f"pp_{tag}_first"] = "high"
                row[f"pp_{tag}_opposite"] = not np.isnan(tl)
            else:
                row[f"pp_{tag}_first"] = "low"
                row[f"pp_{tag}_opposite"] = not np.isnan(th)

        # six2 literal variant: H/L of [06:00, 09:29:30]
        six_sel = on_sel[(date_all[on_sel] == d64) & (secs_all[on_sel] >= 6 * 3600)]
        if len(six_sel) >= 300:  # ~84% of 420 expected bars
            s2h = float(hi_all[six_sel].max()); s2l = float(lo_all[six_sel].min())
            hh = hi >= s2h
            ll = lo <= s2l
            row["six2_high"] = s2h; row["six2_low"] = s2l
            row["six2_h_touch_t"] = float(secs[hh][0]) if hh.any() else np.nan
            row["six2_l_touch_t"] = float(secs[ll][0]) if ll.any() else np.nan
        else:
            row["six2_high"] = row["six2_low"] = np.nan
            row["six2_h_touch_t"] = row["six2_l_touch_t"] = np.nan

        # repo-6am claim bookkeeping (pre-RTH sweeps count as taken)
        for nm, key in (("6am_high", "h"), ("6am_low", "l")):
            pre = (not (row.get(f"lv_{nm}_untaken") is True)
                   if nm in lv.index else np.nan)
            row[f"six_repo_{key}_preswept"] = pre

        # w1_sweep: any untaken named level touched during W1
        row["w1_sweep"] = any(
            (row.get(f"lv_{n}_untaken") is True)
            and not np.isnan(touch_t.get(n, np.nan))
            and touch_t[n] < T945 for n in ATLAS_LEVELS)
        # OR5 state by 9:45 (for W1 transition state)
        th5, tl5 = row["or5_t_hi"], row["or5_t_lo"]
        bh5 = (not np.isnan(th5)) and th5 < T945
        bl5 = (not np.isnan(tl5)) and tl5 < T945
        row["w1_or5"] = ("both" if bh5 and bl5 else "high" if bh5
                         else "low" if bl5 else "none")

        # ---- archetype (DEFINITIONS §10) ----
        if not row["or15_any_break"]:
            arch = "BALANCE_CHOP"
        elif row["or15_both_break"]:
            arch = "TWO_WAY_SWEEP"
        else:
            mid = (row["or15_high"] + row["or15_low"]) / 2.0
            broke_high = row["or15_first_side"] == "high"
            beyond = C > row["or15_high"] if broke_high else C < row["or15_low"]
            crossed = row["or15_ret_mid"]  # post-break mid cross == same rule
            if beyond and not crossed:
                arch = "STRAIGHT_RUN"
            elif beyond:
                arch = "BREAK_RETEST_GO"
            elif (C >= mid) == broke_high:
                arch = "FAILED_BREAK"
            else:
                arch = "SWEEP_AND_REVERSE"
        row["archetype"] = arch

        # ---- conditioners (as-of 9:30) ----
        gap = drec["gap_from_prior_close"]
        ga = abs(gap) / atr if not pd.isna(gap) else np.nan
        row["gap_pts"] = gap; row["gap_atr_abs"] = ga
        row["gap_bucket"] = ("unknown" if pd.isna(ga) else
                             "flat" if ga < 0.10 else
                             "small" if ga < 0.30 else
                             "medium" if ga < 0.60 else "large")
        row["gap_dir"] = ("none" if pd.isna(gap) or row["gap_bucket"] == "flat"
                          else "up" if gap > 0 else "down")
        row["gap_cat"] = (row["gap_bucket"] if row["gap_bucket"] in ("flat", "unknown")
                          else f"{row['gap_bucket']}_{row['gap_dir']}")

        # prior-day type (needs i-1 and i-2)
        if i >= 2:
            P, PP = td.iloc[i - 1], td.iloc[i - 2]
            med = td["range_med20"].iloc[i - 1]
            rng = P["rth_high"] - P["rth_low"]
            cpos = (P["rth_close"] - P["rth_low"]) / rng if rng > 0 else 0.5
            if P["rth_high"] > PP["rth_high"] and P["rth_low"] < PP["rth_low"]:
                pdt = "outside"
            elif P["rth_high"] < PP["rth_high"] and P["rth_low"] > PP["rth_low"]:
                pdt = "inside"
            elif not pd.isna(med) and rng >= med and cpos >= 0.75:
                pdt = "trend_up"
            elif not pd.isna(med) and rng >= med and cpos <= 0.25:
                pdt = "trend_down"
            else:
                pdt = "neutral"
            row["pd_type"] = pdt
            b1, b2 = bool(P["bull"]), bool(PP["bull"])
            row["streak2"] = ("up-up" if b1 and b2
                              else "down-down" if not b1 and not b2 else "mixed")
        else:
            row["pd_type"] = "unknown"; row["streak2"] = "unknown"

        pdh = row.get("lv_prev_day_high_price", np.nan)
        pdl = row.get("lv_prev_day_low_price", np.nan)
        if not (np.isnan(pdh) or np.isnan(pdl)) and pdh > pdl:
            pos = (O - pdl) / (pdh - pdl)
            row["open_pos"] = pos
            row["open_pos_cat"] = ("above_range" if pos > 1 else
                                   "premium" if pos >= 0.5 else
                                   "discount" if pos >= 0 else "below_range")
        else:
            row["open_pos"] = np.nan; row["open_pos_cat"] = "unknown"

        diff = n_above - n_below
        row["draw_asym_cat"] = ("above_heavy" if diff >= 2
                                else "below_heavy" if diff <= -2 else "balanced")

        onr = drec["overnight_range"]; onm = drec["on_med20_lag"]
        if pd.isna(onr) or pd.isna(onm) or onm <= 0:
            row["on_bucket"] = "unknown"
        else:
            r = onr / onm
            row["on_ratio"] = r
            row["on_bucket"] = ("compressed" if r < 0.80
                                else "expanded" if r > 1.25 else "normal")
        row["dow"] = pd.Timestamp(d).day_name()

        rows.append(row)
        if (i + 1) % 250 == 0:
            print(f"  {i + 1}/{len(dates)} sessions")

    out = pd.DataFrame(rows)
    out.to_parquet(CACHE / "session_table.parquet", index=False)
    pd.DataFrame(excluded, columns=["date", "reason"]).to_csv(
        CACHE / "excluded_sessions.csv", index=False)
    print(f"\nwrote {len(out)} sessions, excluded {len(excluded)}")
    print(out["archetype"].value_counts())
    print(out[["gap_bucket", "pd_type", "streak2", "open_pos_cat",
               "draw_asym_cat", "on_bucket"]].describe(include="all").T[["count", "unique", "top", "freq"]])


if __name__ == "__main__":
    main()
