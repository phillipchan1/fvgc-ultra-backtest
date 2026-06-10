"""Part 3 — session path archetypes & intra-session transitions.

1. Unconditional archetype distribution (rule-based, DEFINITIONS §10) +
   per-year stationarity of the distribution itself.
2. P(archetype | each Part-2 conditioner) — single conditioning only,
   BH FDR q=0.10 within this file's family.
3. W1 -> W2/W3 transition table (as-of 9:45): outcome 3-way + remaining-draw
   touch probabilities by W1 state.

Outputs: results/part3_archetypes.csv, results/part3_transitions.csv.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as sps

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from atlas_stats import wilson, ledger_append, binom_vs_marginal, bh_fdr

CACHE = HERE / "results/cache"
RESULTS = HERE / "results"
T945, T1015 = 35100, 36900

st = pd.read_parquet(CACHE / "session_table.parquet").reset_index(drop=True)
S = len(st)
ARCHES = ["STRAIGHT_RUN", "FAILED_BREAK", "TWO_WAY_SWEEP", "SWEEP_AND_REVERSE",
          "BALANCE_CHOP", "BREAK_RETEST_GO"]
CONDS = ["gap_cat", "pd_type", "streak2", "open_pos_cat", "draw_asym_cat",
         "on_bucket", "dow"]
LEVELS = ["prev_day_high", "prev_day_low", "prev_close", "overnight_high",
          "overnight_low", "asia_high", "asia_low", "london_high",
          "london_low", "6am_high", "6am_low"]

rows = []

# ---------- 1. unconditional distribution + stationarity ----------
for a in ARCHES:
    m = st["archetype"] == a
    n, k = S, int(m.sum())
    p = k / n
    lo, hi = wilson(k, n)
    yearly = []
    for y in range(2018, 2027):
        my = st["year"] == y
        if my.sum():
            yearly.append(f"{y}:{(m & my).sum() / my.sum() * 100:.0f}%")
    rows.append(dict(kind="unconditional", archetype=a, conditioner="none",
                     cell="all", n=n, k=k, p=round(p, 4), ci_lo=round(lo, 4),
                     ci_hi=round(hi, 4), yearly=" ".join(yearly)))

# distribution-level stationarity: chi2 archetype x year
tbl = pd.crosstab(st["archetype"], st["year"])
tbl8 = tbl[[c for c in tbl.columns if c <= 2025]]
chi2, p_dist, dof, _ = sps.chi2_contingency(tbl8.values)
print(f"archetype x year chi2 p = {p_dist:.2e} (dof {dof})")

# ---------- 2. P(archetype | conditioner), single only ----------
cond_rows = []
for c in CONDS:
    known = st[c] != "unknown"
    for cell in sorted(st.loc[known, c].unique()):
        mcell = known & (st[c] == cell)
        n = int(mcell.sum())
        for a in ARCHES:
            succ = st["archetype"] == a
            p_m = float((succ & known).sum()) / int(known.sum())
            if n < 30:
                cond_rows.append(dict(kind="conditional", archetype=a,
                                      conditioner=c, cell=cell, n=n,
                                      suppressed=True))
                continue
            k = int((succ & mcell).sum())
            p = k / n
            lo, hi = wilson(k, n)
            pv = binom_vs_marginal(k, n, p_m)
            cond_rows.append(dict(kind="conditional", archetype=a,
                                  conditioner=c, cell=cell, n=n, k=k,
                                  p=round(p, 4), ci_lo=round(lo, 4),
                                  ci_hi=round(hi, 4), marginal_p=round(p_m, 4),
                                  delta_pp=round((p - p_m) * 100, 2),
                                  p_value=pv, low_n=n < 100, suppressed=False))

cdf = pd.DataFrame(cond_rows)
tested = cdf[cdf["suppressed"] != True].copy()
tested["q_value"] = bh_fdr(tested["p_value"].values.astype(float))
tested["verdict"] = np.where(
    (tested["q_value"] <= 0.10) & (tested["delta_pp"].abs() >= 5),
    "MOVES", np.where((tested["q_value"] <= 0.10)
                      | (tested["delta_pp"].abs() >= 5), "WEAK", "NO_MOVE"))
tested.loc[tested["low_n"] & tested["verdict"].isin(["MOVES", "WEAK"]),
           "verdict"] += "|LOW-N"
cdf = cdf.merge(tested[["archetype", "conditioner", "cell", "q_value",
                        "verdict"]], on=["archetype", "conditioner", "cell"],
                how="left")
cdf.loc[cdf["suppressed"] == True, "verdict"] = "SUPPRESSED"

out = pd.concat([pd.DataFrame(rows), cdf], ignore_index=True)
out.to_csv(RESULTS / "part3_archetypes.csv", index=False)
for _, r in tested.iterrows():
    ledger_append(dict(test_id=f"P3_arch_{r['archetype']}_{r['conditioner']}_{r['cell']}"[:80],
                       part=3, statistic=f"archetype={r['archetype']}",
                       conditioner=r["conditioner"], cell=r["cell"],
                       as_of="9:30", n=r["n"], p_hat=r["p"], ci_lo=r["ci_lo"],
                       ci_hi=r["ci_hi"], marginal_p=r["marginal_p"],
                       delta_pp=r["delta_pp"], p_value=r["p_value"],
                       q_value=round(r["q_value"], 4), verdict=r["verdict"],
                       notes=""))

print("\narchetype MOVES cells:")
mv = tested[tested["verdict"].str.startswith("MOVES")]
print(mv[["archetype", "conditioner", "cell", "n", "p", "marginal_p",
          "delta_pp", "q_value", "verdict"]].to_string(index=False))

# ---------- 3. W1 -> W2/W3 transition table (as-of 9:45) ----------
trows = []
valid = st["w23_outcome"].notna() & (st["w1_dir"] != "flat")

# full state: w1_dir x w1_or5 x w1_sweep
state = (st["w1_dir"] + "|or5_" + st["w1_or5"]
         + "|" + np.where(st["w1_sweep"], "swept", "nosweep"))
for grp_name, grp in (("full_state", state),
                      ("dir_only", st["w1_dir"]),
                      ("dir_x_or5", st["w1_dir"] + "|or5_" + st["w1_or5"]),
                      ("dir_x_sweep", st["w1_dir"] + "|"
                       + np.where(st["w1_sweep"], "swept", "nosweep"))):
    for cell in sorted(grp[valid].unique()):
        m = valid & (grp == cell)
        n = int(m.sum())
        if n < 30:
            continue
        for oc in ("continuation", "chop", "reversal"):
            k = int((m & (st["w23_outcome"] == oc)).sum())
            lo, hi = wilson(k, n)
            trows.append(dict(table=grp_name, w1_state=cell, outcome=oc,
                              n=n, k=k, p=round(k / n, 4),
                              ci_lo=round(lo, 4), ci_hi=round(hi, 4),
                              low_n=n < 100))

# remaining-draw touch probabilities by w1_dir (denominator: level untaken
# at 9:45 = untaken at 9:30 and not touched in W1; side vs w1_close)
for lvl in LEVELS:
    price = st[f"lv_{lvl}_price"]
    t = st[f"lv_{lvl}_touch_t"]
    unt945 = (st[f"lv_{lvl}_untaken"] == True) & (t.isna() | (t >= T945))
    touched_w23 = t.notna() & (t >= T945) & (t < T1015)
    above945 = price > st["w1_close"]
    for d in ("up", "down"):
        for side, sm in (("above", above945), ("below", ~above945)):
            v = unt945 & price.notna() & (st["w1_dir"] == d) & sm & valid
            n = int(v.sum())
            if n < 30:
                continue
            k = int((touched_w23 & v).sum())
            lo, hi = wilson(k, n)
            trows.append(dict(table="draw_touch_w23",
                              w1_state=f"{d}|{lvl}_{side}", outcome="touched",
                              n=n, k=k, p=round(k / n, 4), ci_lo=round(lo, 4),
                              ci_hi=round(hi, 4), low_n=n < 100))

tdf = pd.DataFrame(trows)
tdf.to_csv(RESULTS / "part3_transitions.csv", index=False)
print("\n=== dir_only transition table ===")
print(tdf[tdf["table"] == "dir_only"].to_string(index=False))
print("\n=== dir_x_or5 ===")
print(tdf[tdf["table"] == "dir_x_or5"].to_string(index=False))
print("\nunconditional archetype distribution:")
print(pd.DataFrame(rows)[["archetype", "p", "ci_lo", "ci_hi", "yearly"]].to_string(index=False))
