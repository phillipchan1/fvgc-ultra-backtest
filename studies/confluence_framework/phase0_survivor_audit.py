"""Phase 0 — Survivor audit.

Re-derive headline results of prior studies from the canonical 8-yr baseline
(results/cache/baseline_trades_8yr.csv == logs/baseline_trades.csv.preserve,
generated under frozen v2.0.5 / 9:30-10:15 window) with consistent standards:
  - tradeable = outcome in {win, loss}
  - WR tested two-sided binomial vs the canonical baseline WR
  - PF = gross win pnl / gross loss pnl
  - BH FDR q=0.10 across the full re-derived set

Outputs: results/phase0_survivor_audit.csv and appends to results/test_ledger.csv
"""
from datetime import time as dtime
from pathlib import Path

import numpy as np
import pandas as pd
from math import lgamma, log


def binom_pvalue_two_sided(k: int, n: int, p0: float) -> float:
    """Exact two-sided binomial test (sum of outcomes with pmf <= pmf(k))."""
    ks = np.arange(n + 1)
    logpmf = (np.array([lgamma(n + 1) - lgamma(x + 1) - lgamma(n - x + 1) for x in ks])
              + ks * log(p0) + (n - ks) * log(1 - p0))
    pmf = np.exp(logpmf)
    return float(pmf[pmf <= pmf[k] * (1 + 1e-7)].sum())

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
RESULTS.mkdir(exist_ok=True)

df = pd.read_csv(RESULTS / "cache" / "baseline_trades_8yr.csv",
                 parse_dates=["timestamp", "fvg_created_at"])
t = df[df["outcome"].isin(["win", "loss"])].copy()
t["win"] = (t["outcome"] == "win").astype(int)
t["dow"] = t["timestamp"].dt.day_name()
t["fvg_tod"] = t["fvg_created_at"].dt.time
t["entry_tod"] = t["timestamp"].dt.time

BASE_WR = t["win"].mean()
BASE_N = len(t)


def pf(sub: pd.DataFrame) -> float:
    gp = sub.loc[sub["pnl"] > 0, "pnl"].sum()
    gl = -sub.loc[sub["pnl"] < 0, "pnl"].sum()
    return gp / gl if gl > 0 else np.nan


def avg_r(sub: pd.DataFrame) -> float:
    ok = sub["sl_dist"] > 0
    return (sub.loc[ok, "pnl"] / sub.loc[ok, "sl_dist"]).mean()


rows = []


def test(test_id: str, hypothesis: str, sub: pd.DataFrame, claim: str, notes: str = ""):
    n = len(sub)
    if n == 0:
        rows.append(dict(test_id=test_id, hypothesis=hypothesis, n=0, wr=np.nan,
                         pf=np.nan, avg_r=np.nan, p_value=np.nan, claim=claim, notes="empty"))
        return
    wins = int(sub["win"].sum())
    p = binom_pvalue_two_sided(wins, n, BASE_WR)
    rows.append(dict(test_id=test_id, hypothesis=hypothesis, n=n,
                     wr=round(100 * wins / n, 1), pf=round(pf(sub), 2),
                     avg_r=round(avg_r(sub), 3), p_value=p, claim=claim, notes=notes))


# --- Opening-window FVG cohort (benchmark candidate) ---------------------
ow = t[(t["fvg_tod"] >= dtime(9, 29, 30)) & (t["fvg_tod"] <= dtime(9, 31, 0))]
test("ow_all", "FVG created 09:29:30-09:31:00, all dirs", ow,
     "61.0% n=100 (30mo era)")
test("ow_short", "Opening-window FVG, shorts", ow[ow["direction"] == "short"],
     "74.1% n=54 (30mo era)")
test("ow_long", "Opening-window FVG, longs", ow[ow["direction"] == "long"],
     "45.7% n=46 (30mo era)")
test("ow_short_noPS", "Opening-window shorts excl protected_swing",
     ow[(ow["direction"] == "short") & (ow["variant"] != "protected_swing")],
     "70% WR / PF 2.3 n=83 (8yr study memory)")
test("ow_long_smallfvg", "Opening-window longs, FVG size <=10pt",
     ow[(ow["direction"] == "long") & ((ow["fvg_top"] - ow["fvg_bottom"]) <= 10)],
     "63% WR / PF 1.73 (8yr study)")
test("ow_long_largefvg", "Opening-window longs, FVG size >10pt",
     ow[(ow["direction"] == "long") & ((ow["fvg_top"] - ow["fvg_bottom"]) > 10)],
     "knife-catch PF 0.48 (8yr study)")

# --- Day of week ----------------------------------------------------------
for d in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]:
    test(f"dow_{d.lower()}", f"{d} all trades", t[t["dow"] == d],
         "Thu 55.8% best / Tue 49.2% worst (1572-era)")
test("dow_thursday_short", "Thursday shorts",
     t[(t["dow"] == "Thursday") & (t["direction"] == "short")],
     "short Thursday drives edge (1572-era)")

# --- Macro windows (context) ---------------------------------------------
for label, lo, hi in [("w1", dtime(9, 30), dtime(9, 45)),
                      ("w2", dtime(9, 45), dtime(10, 0)),
                      ("w3", dtime(10, 0), dtime(10, 15, 0, 1))]:
    test(f"macro_{label}", f"entry in {label.upper()}",
         t[(t["entry_tod"] >= lo) & (t["entry_tod"] < hi)], "context split")

# --- Variants / direction (sanity context) --------------------------------
for v in ["no_fvg", "bos", "protected_swing", "ifvg"]:
    test(f"variant_{v}", f"variant={v}", t[t["variant"] == v], "context split")
for d in ["long", "short"]:
    test(f"dir_{d}", f"direction={d}", t[t["direction"] == d], "context split")

res = pd.DataFrame(rows)

# --- BH FDR q=0.10 across the full set ------------------------------------
valid = res["p_value"].notna()
pvals = res.loc[valid, "p_value"].values
m = len(pvals)
order = np.argsort(pvals)
bh = np.empty(m)
prev = 1.0
for rank_idx in range(m - 1, -1, -1):
    i = order[rank_idx]
    q = pvals[i] * m / (rank_idx + 1)
    prev = min(prev, q)
    bh[i] = prev
res.loc[valid, "q_value"] = bh
res["fdr_survives_q10"] = res["q_value"] < 0.10

res.insert(1, "phase", 0)
res.to_csv(RESULTS / "phase0_survivor_audit.csv", index=False)

# --- append to test ledger -------------------------------------------------
ledger_path = RESULTS / "test_ledger.csv"
ledger = res.rename(columns={"wr": "WR", "pf": "PF"})[
    ["test_id", "phase", "hypothesis", "n", "WR", "PF", "p_value", "q_value", "notes"]]
ledger["cohort"] = "8yr canonical baseline"
ledger = ledger[["test_id", "phase", "hypothesis", "cohort", "n", "WR", "PF",
                 "p_value", "q_value", "notes"]]
header = not ledger_path.exists()
ledger.to_csv(ledger_path, mode="a", header=header, index=False)

print(f"Canonical baseline: n={BASE_N}, WR={100*BASE_WR:.2f}%, PF={pf(t):.3f}")
print(res.to_string(index=False))
