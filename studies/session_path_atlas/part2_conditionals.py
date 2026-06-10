"""Part 2 — conditional layer (the narrative layer).

10 Tier-1 events x 7 pre-registered single conditioners + 4 pre-registered
two-way pairs ONLY: (gap x pd_type), (gap x open_pos), (pd_type x streak),
(open_pos x draw_asym). BH FDR q=0.10 across ALL cell tests in this file;
material = |cell - marginal| >= 5pp. Cells n<30 suppressed, n<100 LOW-N.

Output: results/part2_conditionals.csv (long format) + ledger rows.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from atlas_stats import wilson, ledger_append, binom_vs_marginal, bh_fdr

CACHE = HERE / "results/cache"
RESULTS = HERE / "results"

st = pd.read_parquet(CACHE / "session_table.parquet").reset_index(drop=True)

# ---- Tier-1 events: (success, valid) boolean series ----
brk = st["or15_any_break"].fillna(False).astype(bool)
EVENTS = {
    "T1_or15_any": (brk, pd.Series(True, index=st.index)),
    "T2_or15_both": (st["or15_both_break"] == True, pd.Series(True, index=st.index)),
    "T3_first_high": (st["or15_first_side"] == "high", brk),
    "T4_ret_mid": (st["or15_ret_mid"] == True, brk),
    "T5_ext_025atr": (st["or15_ext_atr"] >= 0.25, brk),
    "T6_pd_touch": ((st["lv_prev_day_high_touch_t"].notna()
                     | st["lv_prev_day_low_touch_t"].notna()),
                    st["lv_prev_day_high_price"].notna()
                    & st["lv_prev_day_low_price"].notna()),
    "T7_on_touch": ((st["lv_overnight_high_touch_t"].notna()
                     | st["lv_overnight_low_touch_t"].notna()),
                    pd.Series(True, index=st.index)),
    "T8_nearest_touch": (st["nearest_untaken_touched"] == True,
                         st["nearest_untaken_name"] != "none"),
    "T9_below_first": (st["below_before_above"] == True,
                       (st["nearest_above_name"] != "none")
                       & (st["nearest_below_name"] != "none")
                       & st["below_before_above"].notna()),
    "T10_w1_match": (st["w1_matches_net"] == True, st["w1_matches_net"].notna()),
}

CONDS = ["gap_cat", "pd_type", "streak2", "open_pos_cat", "draw_asym_cat",
         "on_bucket", "dow"]
PAIRS = [("gap_cat", "pd_type"), ("gap_cat", "open_pos_cat"),
         ("pd_type", "streak2"), ("open_pos_cat", "draw_asym_cat")]

rows = []


def run_cells(event_id, success, valid, cond_name, cells: pd.Series):
    known = cells.notna() & (cells != "unknown") & valid
    pool_s = success & known
    n_m = int(known.sum())
    p_m = float(pool_s.sum()) / n_m if n_m else np.nan
    for cell in sorted(cells[known].unique()):
        m = known & (cells == cell)
        n = int(m.sum())
        if n < 30:
            rows.append(dict(event=event_id, conditioner=cond_name, cell=cell,
                             n=n, suppressed=True))
            continue
        k = int((success & m).sum())
        p = k / n
        lo, hi = wilson(k, n)
        pv = binom_vs_marginal(k, n, p_m)
        rows.append(dict(event=event_id, conditioner=cond_name, cell=cell,
                         n=n, k=k, p=round(p, 4), ci_lo=round(lo, 4),
                         ci_hi=round(hi, 4), marginal_p=round(p_m, 4),
                         delta_pp=round((p - p_m) * 100, 2), p_value=pv,
                         low_n=n < 100, suppressed=False))


for ev, (succ, val) in EVENTS.items():
    succ = succ.fillna(False).astype(bool)
    val = val.fillna(False).astype(bool)
    for c in CONDS:
        run_cells(ev, succ, val, c, st[c])
    for c1, c2 in PAIRS:
        combo = st[c1].astype(str) + " & " + st[c2].astype(str)
        combo[(st[c1] == "unknown") | (st[c2] == "unknown")] = "unknown"
        run_cells(ev, succ, val, f"{c1}*{c2}", combo)

df = pd.DataFrame(rows)
tested = df[~df["suppressed"].fillna(False)].copy()
tested["q_value"] = bh_fdr(tested["p_value"].values.astype(float))


def verdict(r):
    sig = r["q_value"] <= 0.10
    mat = abs(r["delta_pp"]) >= 5.0
    if sig and mat:
        return "MOVES" + ("|LOW-N" if r["low_n"] else "")
    if sig or mat:
        return "WEAK" + ("|LOW-N" if r["low_n"] else "")
    return "NO_MOVE"


tested["verdict"] = tested.apply(verdict, axis=1)
df = df.merge(tested[["event", "conditioner", "cell", "q_value", "verdict"]],
              on=["event", "conditioner", "cell"], how="left")
df.loc[df["suppressed"] == True, "verdict"] = "SUPPRESSED"
df.to_csv(RESULTS / "part2_conditionals.csv", index=False)

for _, r in tested.iterrows():
    ledger_append(dict(test_id=f"P2_{r['event']}_{r['conditioner']}_{r['cell']}"[:80],
                       part=2, statistic=r["event"], conditioner=r["conditioner"],
                       cell=r["cell"], as_of="9:30", n=r["n"], p_hat=r["p"],
                       ci_lo=r["ci_lo"], ci_hi=r["ci_hi"],
                       marginal_p=r["marginal_p"], delta_pp=r["delta_pp"],
                       p_value=r["p_value"], q_value=round(r["q_value"], 4),
                       verdict=r["verdict"], notes=""))

print(f"cells: {len(df)}  tested: {len(tested)}  suppressed: {(df['suppressed']==True).sum()}")
print("\nverdict counts:")
print(tested["verdict"].value_counts())
mv = tested[tested["verdict"].str.startswith(("MOVES", "WEAK"))].sort_values("q_value")
cols = ["event", "conditioner", "cell", "n", "p", "marginal_p", "delta_pp", "q_value", "verdict"]
print("\n=== MOVES + WEAK (by q) ===")
print(mv[cols].to_string(index=False))
print("\n=== conditioners that move nothing (folk-belief killers) ===")
for c in CONDS:
    sub = tested[tested["conditioner"] == c]
    n_moves = sub["verdict"].str.startswith("MOVES").sum()
    print(f"  {c}: {n_moves} MOVES cells of {len(sub)} tested")
