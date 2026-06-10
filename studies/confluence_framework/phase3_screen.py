"""Phase 3 — IS-only single-factor screen.

Pre-registered factor registry (every bucketing choice is explicit here and
logged to the ledger). Cohorts per brief: longs, shorts, benchmark
(opening-window short no-PS). Selection: BH FDR q=0.10 across THIS screen
family + same-sign effect in >=3/4 walk-forward folds + n>=30.

Then a marginal-value pass: does each survivor add lift ON TOP of the IS
benchmark cohort (n=41 — descriptive, small-n caveats reported, not promoted)?

Outputs: results/phase3_screen.csv, results/phase3_survivors.csv,
results/phase3_marginal_benchmark.csv. All tests appended to test_ledger.csv.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from harness import evaluate, RESULTS  # noqa: E402

snaps = pd.read_csv(RESULTS / "phase2_snapshots.csv",
                    parse_dates=["timestamp", "session_date", "fvg_created_at"])
snaps = snaps.sort_values("timestamp").reset_index(drop=True)
IS = snaps[snaps["split"] == "IS"]

# IS-only quantile cuts (recorded; reused as fixed constants for OOS later)
ATR_P80 = float(IS["atr14_lag1"].quantile(0.80))
ATR_P20 = float(IS["atr14_lag1"].quantile(0.20))
print(f"IS ATR cuts: p20={ATR_P20:.1f} p80={ATR_P80:.1f}")

long_m = snaps["direction"] == "long"
short_m = snaps["direction"] == "short"


def _toward(col_above, col_below):
    return np.where(long_m, snaps[col_above], snaps[col_below])


def _against(col_above, col_below):
    return np.where(long_m, snaps[col_below], snaps[col_above])


htf15_toward = pd.Series(_toward("htf15m_nearest_above", "htf15m_nearest_below"))
htf15_against = pd.Series(_against("htf15m_nearest_above", "htf15m_nearest_below"))
htf60_toward = pd.Series(_toward("htf1h_nearest_above", "htf1h_nearest_below"))
atr = snaps["atr14_lag1"]

# prior-day level toward trade & untaken (long -> pdh above; short -> pdl below)
pd_toward_untaken = np.where(
    long_m,
    (snaps["lvl_prev_day_high_status"] == "untaken")
    & (snaps["lvl_prev_day_high_dist"] > 0),
    (snaps["lvl_prev_day_low_status"] == "untaken")
    & (snaps["lvl_prev_day_low_dist"] < 0))

FIRST_SWEEP_SIDE = {  # resistance-type vs support-type level names
    "prev_day_high": "res", "asia_high": "res", "london_high": "res",
    "6am_high": "res", "overnight_high": "res", "nwog_high": "res",
    "daily_50pct_high": "res", "bsl_level": "res",
    "prev_day_low": "sup", "asia_low": "sup", "london_low": "sup",
    "6am_low": "sup", "overnight_low": "sup", "nwog_low": "sup",
    "daily_50pct_low": "sup", "ssl_level": "sup",
}
fs_side = snaps["first_sweep_name"].map(FIRST_SWEEP_SIDE)
fade_first_sweep = ((fs_side == "res") & short_m) | ((fs_side == "sup") & long_m)
cont_first_sweep = ((fs_side == "res") & long_m) | ((fs_side == "sup") & short_m)

gap_aligned = ((snaps["gap_class"] == "gap_up") & long_m) | \
              ((snaps["gap_class"] == "gap_down") & short_m)
gap_against = ((snaps["gap_class"] == "gap_down") & long_m) | \
              ((snaps["gap_class"] == "gap_up") & short_m)
or_break_aligned = (snaps["or_state"].isin(["broke_high", "broke_both"]) & long_m) | \
                   (snaps["or_state"].isin(["broke_low", "broke_both"]) & short_m)
or_break_against = (snaps["or_state"].isin(["broke_low", "broke_both"]) & long_m) | \
                   (snaps["or_state"].isin(["broke_high", "broke_both"]) & short_m)
pd_outside_aligned = ((snaps["pd_zone"] == "above") & long_m) | \
                     ((snaps["pd_zone"] == "below") & short_m)

ndr = snaps["nearest_untaken_dir_dist_R"]

FACTORS = [
    # --- A. draw map ---
    ("asym_pos", "A", "draw_asym_dir > 0 (more untaken draws toward trade)",
     snaps["draw_asym_dir"] > 0),
    ("asym_ge2", "A", "draw_asym_dir >= 2", snaps["draw_asym_dir"] >= 2),
    ("asym_le_m2", "A", "draw_asym_dir <= -2 (anti)", snaps["draw_asym_dir"] <= -2),
    ("asym_1atr_pos", "A", "draw_asym within 1 ATR > 0",
     snaps["draw_asym_dir_1atr"] > 0),
    ("target_aligned", "A", "nearest untaken draw at/beyond 1R target",
     snaps["target_aligned"] == True),  # noqa: E712
    ("ndr_le1", "A", "nearest untaken draw toward trade <= 1R (stall risk)",
     ndr <= 1),
    ("ndr_1_3", "A", "nearest untaken draw toward trade in (1,3]R",
     (ndr > 1) & (ndr <= 3)),
    ("ndr_gt3", "A", "nearest untaken draw toward trade > 3R", ndr > 3),
    ("no_draw_dir", "A", "no untaken draw in trade direction", ndr.isna()),
    ("nested_15m", "A", "entry FVG nested in not-inverted 15m FVG",
     snaps["nested_15m"] == True),  # noqa: E712
    ("htf15_toward_1atr", "A", "unfilled 15m FVG toward trade within 1 ATR",
     htf15_toward <= atr),
    ("htf15_toward_none", "A", "no unfilled 15m FVG toward trade (14d)",
     htf15_toward.isna()),
    ("htf15_against_halfatr", "A", "unfilled 15m FVG against trade within 0.5 ATR",
     htf15_against <= 0.5 * atr),
    ("htf60_toward_1atr", "A", "unfilled 1h FVG toward trade within 1 ATR",
     htf60_toward <= atr),
    ("opp_htf_inverted", "A", "opposing 15m FVG inverted this session",
     snaps["opp_htf_inverted_today"] == True),  # noqa: E712
    ("pd_toward_untaken", "A", "prior-day level toward trade still untaken",
     pd.Series(pd_toward_untaken)),
    # --- B. need proxies ---
    *[(f"need_v1_x{X}_y{Y}", "B", f"impulse >={X}pt/{Y}min toward untaken draw",
       snaps[f"need_v1_x{X}_y{Y}"] == True)  # noqa: E712
      for X in (20, 30, 40) for Y in (5, 10)],
    ("need_v2", "B", "entry FVG is last unmitigated FVG in leg",
     snaps["need_v2_last_fvg"] == True),  # noqa: E712
    *[(f"need_v3_z{Z}_n{N}", "B", f"last taken draw rejected >={Z}pt in {N} bars",
       snaps[f"need_v3_z{Z}_n{N}"] == True)  # noqa: E712
      for Z in (10, 15, 20) for N in (4, 10)],
    # --- C. session state ---
    ("or_inside", "C", "entry with OR intact (>=9:45)",
     snaps["or_state"] == "inside"),
    ("or_break_aligned", "C", "OR broken in trade direction", or_break_aligned),
    ("or_break_against", "C", "OR broken against trade", or_break_against),
    ("macro_w1", "C", "entry in W1", snaps["macro_window"] == "W1"),
    ("macro_w2", "C", "entry in W2", snaps["macro_window"] == "W2"),
    ("macro_w3", "C", "entry in W3", snaps["macro_window"] == "W3"),
    ("near_miss_c1", "C", "confirmed near-miss aligned (going back for it)",
     snaps["near_miss_c1"] == True),  # noqa: E712
    ("near_miss_fade", "C", "confirmed near-miss, trade fades it",
     snaps["near_miss_fade"] == True),  # noqa: E712
    ("no_sweeps_yet", "C", "no named level swept yet",
     snaps["n_swept_so_far"] == 0),
    ("many_sweeps", "C", ">=3 named levels swept already",
     snaps["n_swept_so_far"] >= 3),
    ("fade_first_sweep", "C", "trade fades the first swept level",
     fade_first_sweep),
    ("cont_first_sweep", "C", "trade continues through first swept level",
     cont_first_sweep),
    # --- D. HTF alignment ---
    ("struct15_aligned", "D", "15m structure aligned", snaps["struct_15m_aligned"] == True),  # noqa: E712
    ("struct15_mixed", "D", "15m structure mixed", snaps["struct_15m"] == "mixed"),
    ("struct1h_aligned", "D", "1h structure aligned", snaps["struct_1h_aligned"] == True),  # noqa: E712
    ("struct1h_mixed", "D", "1h structure mixed", snaps["struct_1h"] == "mixed"),
    ("pd_zone_aligned", "D", "long-in-discount / short-in-premium",
     snaps["pd_zone_aligned"] == True),  # noqa: E712
    ("pd_outside", "D", "entry outside prior-day range",
     snaps["pd_zone"].isin(["above", "below"])),
    ("pd_outside_aligned", "D", "outside prior-day range in trade direction",
     pd_outside_aligned),
    ("gap_aligned", "D", "overnight gap in trade direction", gap_aligned),
    ("gap_against", "D", "overnight gap against trade", gap_against),
    ("gap_flat", "D", "flat gap (<0.2 ATR)", snaps["gap_class"] == "flat"),
    ("gap_large_against", "D", "large gap (>=0.5 ATR) against trade",
     gap_against & (snaps["gap_atr"].abs() >= 0.5)),
    # --- E. trade geometry / regime (pre-registered from prior studies) ---
    ("fvg_small", "E", "entry FVG size <= 10pt", snaps["fvg_size"] <= 10),
    ("fvg_large", "E", "entry FVG size > 20pt", snaps["fvg_size"] > 20),
    ("fvg_fresh", "E", "FVG age <= 5 min", snaps["fvg_age_min"] <= 5),
    ("fvg_stale", "E", "FVG age > 15 min", snaps["fvg_age_min"] > 15),
    ("atr_high", "E", f"ATR14 >= IS p80 ({ATR_P80:.0f})", atr >= ATR_P80),
    ("atr_low", "E", f"ATR14 <= IS p20 ({ATR_P20:.0f})", atr <= ATR_P20),
]
print(f"registered factors: {len(FACTORS)}")

COHORTS = {
    "longs": snaps["direction"] == "long",
    "shorts": snaps["direction"] == "short",
    "benchmark": snaps["is_benchmark"] == True,  # noqa: E712
}

rows = []
for cname, cmask in COHORTS.items():
    dfc = snaps[cmask]
    for fid, grp, desc, fmask in FACTORS:
        fmask = pd.Series(np.asarray(fmask), index=snaps.index).fillna(False)
        r = evaluate(dfc, fmask, test_id=f"p3_{cname}_{fid}", phase=3,
                     hypothesis=desc, cohort=cname, split="IS",
                     notes=f"group={grp}")
        rows.append(dict(factor=fid, group=grp, cohort=cname, n=r["n"],
                         WR=r["WR"], PF=r["PF"], avg_r=r["avg_r"],
                         p=r["p_value"], folds_same_sign=r["folds_same_sign"],
                         base_wr=r["base_wr"], desc=desc))

res = pd.DataFrame(rows)

# screen-family BH FDR (q across all phase-3 tests)
valid = res["p"].notna() & (res["n"] > 0)
p = res.loc[valid, "p"].values
m = len(p)
order = np.argsort(p)
qv = np.empty(m)
prev = 1.0
for rank in range(m - 1, -1, -1):
    i = order[rank]
    prev = min(prev, p[i] * m / (rank + 1))
    qv[i] = prev
res.loc[valid, "q"] = qv

res["survives"] = (res["q"] < 0.10) & (res["folds_same_sign"] >= 3) & (res["n"] >= 30)
res = res.sort_values(["survives", "q"], ascending=[False, True])
res.to_csv(RESULTS / "phase3_screen.csv", index=False)

surv = res[res["survives"]]
surv.to_csv(RESULTS / "phase3_survivors.csv", index=False)
print(f"\ntests run: {len(res)} | survivors (q<0.10, folds>=3/4, n>=30): {len(surv)}")
print(surv[["factor", "cohort", "n", "WR", "base_wr", "PF", "avg_r", "p", "q",
            "folds_same_sign"]].to_string(index=False))

# --- marginal value over the IS benchmark cohort (descriptive, small n) ----
bench = snaps[snaps["is_benchmark"] == True]  # noqa: E712
mrows = []
for fid in surv["factor"].unique():
    fmask = dict((f[0], f[3]) for f in FACTORS)[fid]
    fmask = pd.Series(np.asarray(fmask), index=snaps.index).fillna(False)
    r = evaluate(bench, fmask, test_id=f"p3_marginal_bench_{fid}", phase=3,
                 hypothesis=f"marginal lift of {fid} on benchmark", cohort="benchmark",
                 split="IS", notes="marginal-value pass; small n, descriptive")
    # overlap with benchmark within shorts cohort (is the factor just re-finding it?)
    sh = snaps[(snaps["direction"] == "short") & (snaps["split"] == "IS")]
    fm_sh = fmask.reindex(sh.index, fill_value=False)
    overlap = (sh["is_benchmark"] & fm_sh).sum() / max(int(fm_sh.sum()), 1)
    mrows.append(dict(factor=fid, n=r["n"], WR=r["WR"], PF=r["PF"],
                      base_wr=r["base_wr"], p=r["p_value"],
                      bench_overlap_in_shorts=round(float(overlap), 3)))
marg = pd.DataFrame(mrows)
marg.to_csv(RESULTS / "phase3_marginal_benchmark.csv", index=False)
print("\nmarginal on IS benchmark (n=41 total, descriptive):")
print(marg.to_string(index=False))
