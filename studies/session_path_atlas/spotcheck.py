"""Spot-check the session table.

1. Full-table cross-check of OR5/OR15 H/L vs trading_days.csv (independent
   pipeline that built those columns from raw data).
2. 10 random sessions (seed 7): recompute break facts / level touches / W1 /
   archetype inputs with independent straight-line pandas code and diff.
Writes results/spotcheck.md.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from fvgc.context.htf import load_bars_30s

HERE = Path(__file__).resolve().parent
ST = pd.read_parquet(HERE / "results/cache/session_table.parquet")
TD = pd.read_csv("data/trading_days/trading_days.csv", parse_dates=["date"])

lines = ["# Session table spot-check", ""]

# ---- 1. full cross-check of OR values vs trading_days ----
m = ST.merge(TD[["date", "or_5min_high", "or_5min_low",
                 "or_15min_high", "or_15min_low", "rth_open"]], on="date")
checks = {
    "or5_high": "or_5min_high", "or5_low": "or_5min_low",
    "or15_high": "or_15min_high", "or15_low": "or_15min_low",
    "open_930": "rth_open",
}
lines.append("## Full-table cross-check vs trading_days.csv (independent pipeline)")
lines.append("")
lines.append("| field | n compared | max |diff| | mismatches (>0.25 pt) |")
lines.append("|---|---|---|---|")
for a, b in checks.items():
    d = (m[a] - m[b]).abs()
    n_bad = int((d > 0.25).sum())
    lines.append(f"| {a} vs {b} | {d.notna().sum()} | {d.max():.2f} | {n_bad} |")
    if n_bad:
        bad = m.loc[d > 0.25, ["date", a, b]].head(8)
        lines.append("")
        lines.append(bad.to_markdown(index=False))
        lines.append("")

# ---- 2. ten random sessions, independent recompute ----
print("loading bars for detailed check ...")
bars = load_bars_30s("data/consolidated/nq-front-month.ohlcv-30s.parquet")
bars["d"] = bars["timestamp_ny"].dt.normalize()
bars["t"] = bars["timestamp_ny"].dt.time

rng = np.random.default_rng(7)
sample = ST.sample(10, random_state=7).sort_values("date")

lines += ["", "## 10 random sessions — independent recompute", ""]
n_diffs = 0
for _, r in sample.iterrows():
    d = r["date"]
    g = bars[(bars["d"] == d)
             & (bars["t"] >= pd.Timestamp("1970-01-01 09:30").time())
             & (bars["t"] < pd.Timestamp("1970-01-01 10:15").time())].reset_index(drop=True)
    w1 = g[g["t"] < pd.Timestamp("1970-01-01 09:45").time()]
    post = g[g["t"] >= pd.Timestamp("1970-01-01 09:45").time()]
    orh, orl = w1["high"].max(), w1["low"].min()
    hb = post[post["high"] > orh]
    lb = post[post["low"] < orl]
    t_hi = hb["timestamp_ny"].iloc[0] if len(hb) else None
    t_lo = lb["timestamp_ny"].iloc[0] if len(lb) else None
    if t_hi is not None and (t_lo is None or t_hi < t_lo):
        first = "high"
    elif t_lo is not None:
        first = "low"
    else:
        first = "none"
    diffs = []

    def ck(name, mine, theirs, tol=1e-6):
        global n_diffs
        ok = (pd.isna(mine) and pd.isna(theirs)) or (
            not pd.isna(mine) and not pd.isna(theirs)
            and (mine == theirs if isinstance(mine, str)
                 else abs(float(mine) - float(theirs)) <= tol))
        if not ok:
            diffs.append(f"{name}: table={theirs} recompute={mine}")
            n_diffs += 1

    ck("or15_high", orh, r["or15_high"], 0.01)
    ck("or15_low", orl, r["or15_low"], 0.01)
    ck("or15_first_side", first, r["or15_first_side"])
    if first != "none":
        tsec = (t_hi if first == "high" else t_lo)
        ck("or15_t_first", tsec.hour * 3600 + tsec.minute * 60 + tsec.second,
           r["or15_t_first"], 0.5)
    ck("w1_close", w1["close"].iloc[-1], r["w1_close"], 0.01)
    ck("close_1015", g["close"].iloc[-1], r["close_1015"], 0.01)
    ck("hi_1015", g["high"].max(), r["hi_1015"], 0.01)
    ck("lo_1015", g["low"].min(), r["lo_1015"], 0.01)
    # one level touch recompute: PDH (if present)
    L = r.get("lv_prev_day_high_price", np.nan)
    if not pd.isna(L):
        O = r["open_930"]
        hits = g[g["high"] >= L] if L >= O else g[g["low"] <= L]
        t = (hits["timestamp_ny"].iloc[0].hour * 3600
             + hits["timestamp_ny"].iloc[0].minute * 60
             + hits["timestamp_ny"].iloc[0].second) if len(hits) else np.nan
        ck("pdh_touch_t", t, r["lv_prev_day_high_touch_t"], 0.5)
    status = "OK" if not diffs else "DIFFS: " + "; ".join(diffs)
    lines.append(f"- **{d.date()}** arch={r['archetype']} or15_first={r['or15_first_side']} → {status}")

lines += ["", f"Total field mismatches across 10 sessions: **{n_diffs}**", ""]
out = "\n".join(lines)
(HERE / "results/spotcheck.md").write_text(out)
print(out)
