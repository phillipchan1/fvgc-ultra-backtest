"""Null model (DEFINITIONS §8): per-session bar shuffle, 500 resamples.

Each session's 90 30s bars are decomposed into (dh, dl, dc) offsets, the bar
order is shuffled, and the path is rebuilt chained on closes from the real
9:30 open. Every Tier-1 statistic is recomputed per resample.

Outputs results/cache/null_summary.npz:
  dates                (S,)        session dates (ns epoch)
  U, D                 (S, R)      max up/down excursion from open (pts)
  t_first15            (S, R)      OR15 first-break sec-of-day (NaN if none)
  acc_*                (R,)        per-resample numerator sums over sessions
  den_*                (R,)        per-resample denominator sums (conditional stats)
  ses_*                (S,)        per-session null means (for per-session join)

Run with python3.13 from repo root. Deterministic (seed 20260609).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from fvgc.context.htf import load_bars_30s

HERE = Path(__file__).resolve().parent
CACHE = HERE / "results/cache"
R = 500
T930, T945, T935, T1015 = 34200, 35100, 34500, 36900

ACC_KEYS = ["or5_any", "or5_both", "or15_any", "or15_both",
            "or15_first_high", "or15_break", "or15_ret_mid",
            "or15_ext10", "or15_ext20", "or15_ext30", "or15_ext50",
            "or15_ext025atr", "w1_match", "w1_valid", "w1_extreme_holds",
            "bba_below_first", "bba_valid"]


def main():
    st = pd.read_parquet(CACHE / "session_table.parquet")
    st = st.set_index("date")
    bars = load_bars_30s("data/consolidated/nq-front-month.ohlcv-30s.parquet")
    ts = bars["timestamp_ny"]
    secs_all = (ts.dt.hour * 3600 + ts.dt.minute * 60 + ts.dt.second).values
    date_all = ts.dt.normalize().values
    hi_all, lo_all = bars["high"].values, bars["low"].values
    op_all, cl_all = bars["open"].values, bars["close"].values

    rng = np.random.default_rng(20260609)
    S = len(st)
    U = np.full((S, R), np.nan, dtype=np.float32)
    D = np.full((S, R), np.nan, dtype=np.float32)
    TF = np.full((S, R), np.nan, dtype=np.float32)
    acc = {k: np.zeros(R) for k in ACC_KEYS}
    ses = {k: np.full(S, np.nan) for k in
           ["or15_any", "or15_both", "or15_first_high", "or15_ret_mid",
            "w1_match", "bba_below_first"]}

    dates = st.index.values
    for si, d in enumerate(dates):
        m = (date_all == d) & (secs_all >= T930) & (secs_all < T1015)
        idx = np.flatnonzero(m)
        secs = secs_all[idx]
        o = op_all[idx]; h = hi_all[idx]; l = lo_all[idx]; c = cl_all[idx]
        nb = len(idx)
        O = o[0]
        dh, dl, dc = h - o, l - o, c - o
        k45 = int((secs < T945).sum())
        k35 = int((secs < T935).sum())
        atr = st.iloc[si]["atr"]

        # (R, nb) permutations
        perm = np.argsort(rng.random((R, nb)), axis=1)
        dcp = dc[perm]
        closes = O + np.cumsum(dcp, axis=1)
        opens = closes - dcp
        highs = opens + dh[perm]
        lows = opens + dl[perm]

        U[si] = (highs.max(axis=1) - O).astype(np.float32)
        D[si] = (O - lows.min(axis=1)).astype(np.float32)

        # ---- OR variants ----
        for tag, k in (("or5", k35), ("or15", k45)):
            orh = highs[:, :k].max(axis=1)
            orl = lows[:, :k].min(axis=1)
            ph = highs[:, k:]; pl = lows[:, k:]
            hb = ph > orh[:, None]
            lb = pl < orl[:, None]
            any_h = hb.any(axis=1); any_l = lb.any(axis=1)
            acc[f"{tag}_any"] += (any_h | any_l)
            acc[f"{tag}_both"] += (any_h & any_l)
            if tag == "or5":
                continue
            ses["or15_any"][si] = (any_h | any_l).mean()
            ses["or15_both"][si] = (any_h & any_l).mean()
            fh = np.where(any_h, hb.argmax(axis=1), nb + 1)
            fl = np.where(any_l, lb.argmax(axis=1), nb + 1)
            brk = any_h | any_l
            first_high = brk & (fh <= fl)
            acc["or15_break"] += brk
            acc["or15_first_high"] += first_high
            ses["or15_first_high"][si] = (first_high[brk].mean()
                                          if brk.any() else np.nan)
            fidx = np.where(first_high, fh, fl)
            post_secs = secs[k:] if k < nb else np.array([])
            tf = np.where(brk, post_secs[np.clip(fidx, 0, len(post_secs) - 1)],
                          np.nan)
            TF[si] = tf.astype(np.float32)
            # extension beyond first-broken boundary (max post-bar suffices:
            # pre-break post-bars never exceed the boundary by construction)
            ext = np.where(first_high, ph.max(axis=1) - orh,
                           orl - pl.min(axis=1))
            ext = np.where(brk, ext, np.nan)
            for X in (10, 20, 30, 50):
                acc[f"or15_ext{X}"] += ((ext >= X) & brk)
            acc["or15_ext025atr"] += ((ext >= 0.25 * atr) & brk)
            # return to mid after first break: last cross index > first break
            mid = (orh + orl) / 2.0
            cross = np.where(first_high[:, None], pl <= mid[:, None],
                             ph >= mid[:, None])
            anyc = cross.any(axis=1)
            last_cross = cross.shape[1] - 1 - cross[:, ::-1].argmax(axis=1)
            ret = brk & anyc & (last_cross > fidx)
            acc["or15_ret_mid"] += ret
            ses["or15_ret_mid"][si] = ret[brk].mean() if brk.any() else np.nan

        # ---- W1 direction match + W1 extreme holds ----
        w1c = closes[:, k45 - 1]
        net = closes[:, -1] - O
        w1s = np.sign(w1c - O); ns = np.sign(net)
        valid = (w1s != 0) & (ns != 0)
        match = valid & (w1s == ns)
        acc["w1_match"] += match
        acc["w1_valid"] += valid
        ses["w1_match"][si] = match[valid].mean() if valid.any() else np.nan
        w1h = highs[:, :k45].max(axis=1); w1l = lows[:, :k45].min(axis=1)
        acc["w1_extreme_holds"] += ((w1h >= highs.max(axis=1))
                                    | (w1l <= lows.min(axis=1)))

        # ---- below-before-above (T9), using the session's real distances ----
        row = st.iloc[si]
        da = dbb = np.nan
        if row["nearest_above_name"] != "none":
            da = row[f"lv_{row['nearest_above_name']}_price"] - O
        if row["nearest_below_name"] != "none":
            dbb = O - row[f"lv_{row['nearest_below_name']}_price"]
        if not (np.isnan(da) or np.isnan(dbb)):
            cmh = np.maximum.accumulate(highs, axis=1)
            cml = np.minimum.accumulate(lows, axis=1)
            hit_a = cmh >= O + da
            hit_b = cml <= O - dbb
            ia = np.where(hit_a.any(axis=1), hit_a.argmax(axis=1), nb + 1)
            ib = np.where(hit_b.any(axis=1), hit_b.argmax(axis=1), nb + 1)
            either = (ia <= nb) | (ib <= nb)
            below_first = either & (ib < ia) | (ib <= nb) & (ia > nb)
            acc["bba_below_first"] += below_first
            acc["bba_valid"] += either
            ses["bba_below_first"][si] = (below_first[either].mean()
                                          if either.any() else np.nan)
        if (si + 1) % 250 == 0:
            print(f"  {si + 1}/{S}")

    np.savez_compressed(
        CACHE / "null_summary.npz",
        dates=dates.astype("datetime64[ns]").astype(np.int64),
        U=U, D=D, t_first15=TF,
        **{f"acc_{k}": v for k, v in acc.items()},
        **{f"ses_{k}": v for k, v in ses.items()},
        n_sessions=np.array([S]), n_resamples=np.array([R]))
    print("null model done:", S, "sessions x", R, "resamples")
    print("null P(or15 any break) =", acc["or15_any"].sum() / (S * R))
    print("null P(or15 both) =", acc["or15_both"].sum() / (S * R))


if __name__ == "__main__":
    main()
