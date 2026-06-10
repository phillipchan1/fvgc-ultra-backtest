"""Phase 2 — spot-check 10 random trades by independently recomputing features
from raw data with simple brute-force code (catches wiring/sign/tz bugs and,
critically, look-ahead: every checked event must pre-date entry).

Writes results/phase2_spotcheck.md with PASS/FAIL per check.
"""
import sys
from datetime import time as dtime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"

snaps = pd.read_csv(RESULTS / "phase2_snapshots.csv",
                    parse_dates=["timestamp", "session_date", "fvg_created_at"])
bars = pd.read_parquet(ROOT / "data/consolidated/nq-front-month.ohlcv-30s.parquet")
bars["timestamp_ny"] = bars["timestamp_ny"].dt.tz_localize(None)
levels = pd.read_csv(ROOT / "data/levels/session_levels.csv", low_memory=False,
                     parse_dates=["date"])
td = pd.read_csv(ROOT / "data/trading_days/trading_days.csv", parse_dates=["date"])

rng = np.random.default_rng(42)
sample = snaps.sample(10, random_state=42).sort_values("timestamp")

lines = ["# Phase 2 — 10-trade spot check (seed 42)\n"]
n_pass = n_fail = 0


def check(name, ok, detail=""):
    global n_pass, n_fail
    n_pass += ok
    n_fail += (not ok)
    lines.append(f"- {'PASS' if ok else '**FAIL**'} {name} {detail}")


for tr in sample.itertuples():
    d = tr.session_date
    entry = tr.timestamp
    lines.append(f"\n## {entry} {tr.direction} {tr.variant} @ {tr.entry_price}")
    day_bars = bars[(bars.timestamp_ny >= d + pd.Timedelta(hours=9, minutes=30))
                    & (bars.timestamp_ny <= entry)]
    lv = levels[levels.date == d]

    # 1) prev_day_high distance + status
    r = lv[lv.level_name == "prev_day_high"]
    if len(r) and not pd.isna(r.price.iloc[0]):
        price = float(r.price.iloc[0])
        want = price - tr.entry_price
        got = tr.lvl_prev_day_high_dist
        check("pdh_dist", abs(want - got) < 1e-6, f"want {want:.2f} got {got:.2f}")
        swept_pre = bool(r.swept_pre_rth.fillna(False).iloc[0])
        swept_intra = bool((day_bars.high >= price).any())
        want_status = "untaken" if not swept_pre and not swept_intra else "swept*"
        got_status = tr.lvl_prev_day_high_status
        ok = (want_status == "untaken") == (got_status == "untaken")
        check("pdh_status", ok, f"want {want_status} got {got_status} "
              f"(pre={swept_pre} intra={swept_intra})")

    # 2) recount untaken above/below across ALL levels available at entry
    mod = entry.hour * 60 + entry.minute
    n_above = n_below = 0
    for r2 in lv.itertuples():
        if pd.isna(r2.price):
            continue
        avail = 570 if str(r2.available_time) == "open" else 585
        if avail > mod:
            continue
        p2 = float(r2.price)
        if bool(pd.Series([r2.swept_pre_rth]).fillna(False).iloc[0]):
            continue
        if r2.side == "resistance":
            swept = (day_bars.high >= p2).any()
        elif r2.side == "support":
            swept = (day_bars.low <= p2).any()
        else:
            swept = ((day_bars.high >= p2) | (day_bars.low <= p2)).any()
        if swept:
            continue
        if p2 > tr.entry_price:
            n_above += 1
        elif p2 < tr.entry_price:
            n_below += 1
    # prev_close derived level: add it
    g = td[td.date == d]
    if len(g):
        pc = float(g.rth_open.iloc[0] - g.gap_from_prior_close.iloc[0])
        swept = ((day_bars.high >= pc) | (day_bars.low <= pc)).any()
        if not swept:
            if pc > tr.entry_price:
                n_above += 1
            elif pc < tr.entry_price:
                n_below += 1
    # OR levels (live-computed, only for entries >= 9:45)
    or_bars = day_bars[day_bars.timestamp_ny
                       < d + pd.Timedelta(hours=9, minutes=45)]
    post_or = day_bars[day_bars.timestamp_ny
                       >= d + pd.Timedelta(hours=9, minutes=45)]
    if mod >= 585 and len(or_bars):
        orh_v, orl_v = float(or_bars.high.max()), float(or_bars.low.min())
        if not (post_or.high > orh_v).any():
            if orh_v > tr.entry_price:
                n_above += 1
            elif orh_v < tr.entry_price:
                n_below += 1
        if not (post_or.low < orl_v).any():
            if orl_v > tr.entry_price:
                n_above += 1
            elif orl_v < tr.entry_price:
                n_below += 1
    check("n_untaken_above", n_above == tr.n_untaken_above,
          f"want {n_above} got {tr.n_untaken_above}")
    check("n_untaken_below", n_below == tr.n_untaken_below,
          f"want {n_below} got {tr.n_untaken_below}")

    # 3) macro window + or_state
    want_w = "W1" if mod < 585 else ("W2" if mod < 600 else "W3")
    check("macro_window", want_w == tr.macro_window,
          f"want {want_w} got {tr.macro_window}")
    if mod < 585:
        check("or_state_forming", tr.or_state == "forming", f"got {tr.or_state}")
    elif len(or_bars):
        orh_v, orl_v = float(or_bars.high.max()), float(or_bars.low.min())
        bh = (post_or.high > orh_v).any()
        bl = (post_or.low < orl_v).any()
        want_or = ("broke_both" if bh and bl else "broke_high" if bh
                   else "broke_low" if bl else "inside")
        check("or_state", want_or == tr.or_state,
              f"want {want_or} got {tr.or_state}")

    # 4) gap pts
    if len(g):
        want_gap = float(g.gap_from_prior_close.iloc[0])
        check("gap_pts", abs(want_gap - tr.gap_pts) < 1e-6,
              f"want {want_gap:.2f} got {tr.gap_pts:.2f}")

    # 5) need_v1 x20 y5 brute force
    cl = day_bars.close.values
    w = 10
    has_above = tr.n_untaken_above > 0
    has_below = tr.n_untaken_below > 0
    flag = False
    if len(cl) > w:
        mv = cl[w:] - cl[:-w]
        if tr.direction == "long":
            flag = bool((mv >= 20).any()) and has_above
        else:
            flag = bool((mv <= -20).any()) and has_below
    check("need_v1_x20_y5", flag == tr.need_v1_x20_y5,
          f"want {flag} got {tr.need_v1_x20_y5}")

    # 6) LOOKAHEAD check on htf15m nearest-above: re-derive 15m FVGs for the
    # 14 days before entry and confirm the reported distance corresponds to an
    # FVG that (a) was created before entry, (b) untouched before entry.
    if not pd.isna(tr.htf15m_nearest_above):
        win = bars[(bars.timestamp_ny >= entry - pd.Timedelta(days=14))
                   & (bars.timestamp_ny <= entry)]
        g15 = win.set_index("timestamp_ny").resample("15min", label="left",
                                                     closed="left").agg(
            high=("high", "max"), low=("low", "min")).dropna()
        found = False
        arr_h, arr_l, idx15 = g15.high.values, g15.low.values, g15.index
        for i in range(2, len(g15)):
            known = idx15[i] + pd.Timedelta(minutes=15)
            if known > entry:
                continue
            top = bottom = direction = None
            if arr_h[i - 2] < arr_l[i]:
                top, bottom, direction = arr_l[i], arr_h[i - 2], "bullish"
            elif arr_l[i - 2] > arr_h[i]:
                top, bottom, direction = arr_l[i - 2], arr_h[i], "bearish"
            if top is None or bottom <= tr.entry_price:
                continue
            seg = win[(win.timestamp_ny >= known)]
            # touch = price retraces INTO the gap, direction-dependent
            touched = ((seg.low <= top).any() if direction == "bullish"
                       else (seg.high >= bottom).any())
            if not touched and abs((bottom - tr.entry_price)
                                   - tr.htf15m_nearest_above) < 1e-6:
                found = True
                break
        check("htf15m_nearest_above causal", found,
              f"reported {tr.htf15m_nearest_above:.2f}")

    # 7) pd zone
    if tr.pd_zone in ("premium", "discount", "above", "below"):
        pdh_ = lv[lv.level_name == "prev_day_high"].price
        pdl_ = lv[lv.level_name == "prev_day_low"].price
        if len(pdh_) and not pd.isna(pdh_.iloc[0]):
            pos = (tr.entry_price - float(pdl_.iloc[0])) / (
                float(pdh_.iloc[0]) - float(pdl_.iloc[0]))
            want_zone = ("above" if pos > 1 else "below" if pos < 0
                         else "premium" if pos >= 0.5 else "discount")
            check("pd_zone", want_zone == tr.pd_zone,
                  f"want {want_zone} got {tr.pd_zone} (pos {pos:.3f})")

lines.insert(1, f"\n**{n_pass} PASS / {n_fail} FAIL**\n")
(RESULTS / "phase2_spotcheck.md").write_text("\n".join(lines))
print(f"{n_pass} PASS / {n_fail} FAIL -> results/phase2_spotcheck.md")
