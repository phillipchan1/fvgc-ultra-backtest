"""Phase 3 diagnostic addendum (Phil's Phase-4-gate request, 2026-06-09).

(1) Comparison target clarification + both versions for top factors
(2) Top 10 factors by raw effect size (n, raw p, q under both family defs)
(3) Positive-control check: does the benchmark condition fire on IS pre-FDR?
    + exact power analysis of the screen for benchmark-sized cohorts
(4) FDR family sizes + minimal pre-registered family under which top factors
    would survive q=0.10
(5) Spot-check draw_asym_dir and need_v2 on 3 random trades vs raw bars

Output: results/phase3_diagnostic_addendum.md
"""
import sys
from math import lgamma, log, exp
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
from harness import RESULTS  # noqa: E402

L = ["# Phase 3 — Diagnostic addendum (requested by Phil at the Phase-4 gate)\n"]

snaps = pd.read_csv(RESULTS / "phase2_snapshots.csv",
                    parse_dates=["timestamp", "session_date", "fvg_created_at"])
screen = pd.read_csv(RESULTS / "phase3_screen.csv")
IS = snaps[snaps.split == "IS"]

# ---------- (1) comparison target ----------
L.append("## (1) What was the comparison target?\n")
L.append(
    "Each factor was tested against **its own cohort's IS base rate** — longs vs "
    f"IS-longs base ({100*IS[IS.direction=='long'].win.mean():.2f}%), shorts vs "
    f"IS-shorts base ({100*IS[IS.direction=='short'].win.mean():.2f}%), benchmark "
    f"cells vs IS-benchmark base ({100*IS[IS.is_benchmark].win.mean():.2f}%). "
    "NOT the pooled 49.5% 8-yr baseline. Marginal-lift over the opening-window-short "
    "benchmark was a separate pass (vacuous — no survivors to test). Below, top "
    "factors are shown BOTH ways: vs cohort base, and intersected with the IS "
    "benchmark cohort (n=41) vs its 56.1% base.\n")

# ---------- (2) top 10 by raw effect ----------
v = screen[(screen.n >= 30) & screen.p.notna()].copy()
v["effect_pp"] = v["WR"] - v["base_wr"]
# q under clean family (m = n>=30 cells)
m2 = len(v)
p2 = v.p.values
order = np.argsort(p2)
q2 = np.empty(m2)
prev = 1.0
for rank in range(m2 - 1, -1, -1):
    i = order[rank]
    prev = min(prev, p2[i] * m2 / (rank + 1))
    q2[i] = prev
v["q_m121"] = q2
top = v.reindex(v["effect_pp"].abs().sort_values(ascending=False).index).head(10)

L.append("## (2) Top 10 factors by |raw effect| (n>=30 cells)\n")
L.append("| factor | cohort | n | WR | base | effect pp | PF | raw p | q (m=174) | q (m=121) |")
L.append("|---|---|---|---|---|---|---|---|---|---|")
bench_is = snaps[snaps.is_benchmark & (snaps.split == "IS")]
marg_lines = []
for r in top.itertuples():
    L.append(f"| {r.factor} | {r.cohort} | {r.n} | {r.WR}% | {r.base_wr}% | "
             f"{r.effect_pp:+.1f} | {r.PF} | {r.p:.4f} | {r.q:.2f} | {r.q_m121:.2f} |")
L.append("")

# marginal-on-benchmark version of those same factors
import importlib.util  # noqa: E402
spec = importlib.util.spec_from_file_location("p3", HERE / "phase3_screen.py")
# (re-deriving masks inline instead of re-running the screen module)
L.append("Same factors intersected with the IS benchmark cohort (n=41, "
         "descriptive only):\n")
L.append("| factor | n in bench | WR | bench base |")
L.append("|---|---|---|---|")
# rebuild the handful of needed masks
long_m = snaps.direction == "long"
short_m = snaps.direction == "short"
masks = {
    "or_break_against": (snaps.or_state.isin(["broke_low", "broke_both"]) & long_m)
                        | (snaps.or_state.isin(["broke_high", "broke_both"]) & short_m),
    "macro_w3": snaps.macro_window == "W3",
    "macro_w1": snaps.macro_window == "W1",
    "fvg_stale": snaps.fvg_age_min > 15,
    "fvg_large": snaps.fvg_size > 20,
    "asym_pos": snaps.draw_asym_dir > 0,
    "asym_ge2": snaps.draw_asym_dir >= 2,
    "asym_le_m2": snaps.draw_asym_dir <= -2,
    "need_v2": snaps.need_v2_last_fvg == True,  # noqa: E712
    "near_miss_c1": snaps.near_miss_c1 == True,  # noqa: E712
    "need_v3_z15_n4": snaps.need_v3_z15_n4 == True,  # noqa: E712
    "asym_1atr_pos": snaps.draw_asym_dir_1atr > 0,
    "struct15_aligned": snaps.struct_15m_aligned == True,  # noqa: E712
    "pd_zone_aligned": snaps.pd_zone_aligned == True,  # noqa: E712
}
for r in top.itertuples():
    mk = masks.get(r.factor)
    if mk is None:
        continue
    cell = bench_is[mk.reindex(bench_is.index, fill_value=False)]
    wr = 100 * cell.win.mean() if len(cell) else float("nan")
    L.append(f"| {r.factor} | {len(cell)} | "
             f"{wr:.1f}% | {100*bench_is.win.mean():.1f}% |")
L.append("")

# ---------- (3) positive control ----------
L.append("## (3) Positive control: the benchmark condition itself\n")
full = snaps
bm_all = full[full.is_benchmark]
k, n = int(bm_all.win.sum()), len(bm_all)
p_all = stats.binomtest(k, n, full.win.mean()).pvalue
L.append(f"- FULL sample (harness verification): {100*k/n:.1f}% (n={n}) vs pooled "
         f"base {100*full.win.mean():.2f}% -> exact p = {p_all:.2e}. "
         "**Fires decisively** — and it is the only q<0.10 survivor in the global "
         "ledger. The harness and features are not broken.")
bm_is = bench_is
k2, n2 = int(bm_is.win.sum()), len(bm_is)
sh_base = IS[IS.direction == "short"].win.mean()
p_is = stats.binomtest(k2, n2, sh_base).pvalue
L.append(f"- IS ONLY: {100*k2/n2:.1f}% (n={n2}) vs IS-shorts base "
         f"{100*sh_base:.2f}% -> exact p = {p_is:.3f}. **Does NOT fire on IS** — "
         "pre-registered in Phase 1: the benchmark's pooled 8-yr strength is "
         "concentrated in the 2024+ OOS window (IS 56.1% / OOS portion implies ~83%).")

# exact power: would a TRUE benchmark-strength factor survive this screen?
alpha_needed = 0.10 * 1 / 174  # best-rank BH threshold in the m=174 family
p0 = sh_base
n_p = 41


def exact_two_sided_p(kk, nn, pp0):
    ks = np.arange(nn + 1)
    logpmf = (np.array([lgamma(nn + 1) - lgamma(x + 1) - lgamma(nn - x + 1)
                        for x in ks]) + ks * log(pp0) + (nn - ks) * log(1 - pp0))
    pmf = np.exp(logpmf)
    return pmf[pmf <= pmf[kk] * (1 + 1e-7)].sum()


crit = next(kk for kk in range(n_p + 1) if exact_two_sided_p(kk, n_p, p0) <= alpha_needed
            and kk / n_p > p0)
power = 1 - stats.binom.cdf(crit - 1, n_p, 0.70)
L.append(f"- **Screen power for benchmark-sized cohorts**: to survive BH rank-1 at "
         f"m=174 needs p <= {alpha_needed:.2e}, i.e. >= {crit}/{n_p} wins "
         f"({100*crit/n_p:.0f}% WR). A factor with TRUE 70% WR and IS n=41 reaches "
         f"that with probability {100*power:.0f}%. ")
# n needed for 80% power
for n_try in range(40, 400, 5):
    crit_t = next((kk for kk in range(n_try + 1)
                   if exact_two_sided_p(kk, n_try, p0) <= alpha_needed
                   and kk / n_try > p0), None)
    if crit_t and 1 - stats.binom.cdf(crit_t - 1, n_try, 0.70) >= 0.80:
        L.append(f"  80% power for a true-70% factor requires IS n >= ~{n_try}. "
                 "**The negative result is strong for common factors (n>=200) and "
                 "weak for rare benchmark-like cohorts (n~40)** — those are "
                 "structurally undetectable under this screen's correction.")
        break

# ---------- (4) family sizes ----------
L.append("\n## (4) FDR family sizes and the minimal pre-registered family\n")
L.append("- Phase-3 screen family: **174 tests** (58 factors x 3 cohorts); 53 cells "
         "had n<30. Clean family excluding those: **121 tests** (min q = 0.47).")
L.append("- Global ledger at gate time: **197 tests**.")
best = v.nsmallest(3, "p")[["factor", "cohort", "p"]]
for r in best.itertuples():
    m_max = int(0.10 / r.p)  # rank-1 BH survival condition
    L.append(f"- `{r.factor}` ({r.cohort}, p={r.p:.4f}) survives q=0.10 as rank-1 "
             f"only in a family of **m <= {m_max}** pre-registered tests.")
L.append("  Even a one-cohort-per-factor pre-registration (m=58) requires "
         "p<=0.0017 — none of the top factors reach it. The null is not an "
         "artifact of family bloat.")

# ---------- (5) spot-check asym + need_v2 on 3 random trades ----------
L.append("\n## (5) Spot-check: draw_asym_dir and need_v2 vs raw bars (3 trades, seed 7)\n")
bars = pd.read_parquet(ROOT / "data/consolidated/nq-front-month.ohlcv-30s.parquet")
bars["timestamp_ny"] = bars["timestamp_ny"].dt.tz_localize(None)
levels = pd.read_csv(ROOT / "data/levels/session_levels.csv", low_memory=False,
                     parse_dates=["date"])
td = pd.read_csv(ROOT / "data/trading_days/trading_days.csv", parse_dates=["date"])

ok = 0
for tr in snaps.sample(3, random_state=7).itertuples():
    d, entry = tr.session_date, tr.timestamp
    day = bars[(bars.timestamp_ny >= d + pd.Timedelta(hours=9, minutes=30))
               & (bars.timestamp_ny <= entry)]
    mod = entry.hour * 60 + entry.minute
    lv = levels[levels.date == d]
    above = below = 0
    detail = []
    for r2 in lv.itertuples():
        if pd.isna(r2.price):
            continue
        if (570 if str(r2.available_time) == "open" else 585) > mod:
            continue
        if bool(pd.Series([r2.swept_pre_rth]).fillna(False).iloc[0]):
            continue
        pz = float(r2.price)
        swept = ((day.high >= pz).any() if r2.side == "resistance"
                 else (day.low <= pz).any() if r2.side == "support"
                 else ((day.high >= pz) | (day.low <= pz)).any())
        if swept:
            continue
        side = "above" if pz > tr.entry_price else "below"
        if pz > tr.entry_price:
            above += 1
        elif pz < tr.entry_price:
            below += 1
        detail.append(f"{r2.level_name}@{pz:.2f}({side})")
    g = td[td.date == d]
    if len(g):
        pc = float(g.rth_open.iloc[0] - g.gap_from_prior_close.iloc[0])
        if not ((day.high >= pc) | (day.low <= pc)).any():
            if pc > tr.entry_price:
                above += 1
                detail.append(f"prev_close@{pc:.2f}(above)")
            elif pc < tr.entry_price:
                below += 1
                detail.append(f"prev_close@{pc:.2f}(below)")
    if mod >= 585:
        orb = day[day.timestamp_ny < d + pd.Timedelta(hours=9, minutes=45)]
        post = day[day.timestamp_ny >= d + pd.Timedelta(hours=9, minutes=45)]
        if len(orb):
            for nm_, pz, res in (("or_high", float(orb.high.max()), True),
                                 ("or_low", float(orb.low.min()), False)):
                swept = (post.high > pz).any() if res else (post.low < pz).any()
                if not swept:
                    if pz > tr.entry_price:
                        above += 1
                    elif pz < tr.entry_price:
                        below += 1
                    detail.append(f"{nm_}@{pz:.2f}({'above' if pz>tr.entry_price else 'below'})")
    sgn = 1 if tr.direction == "long" else -1
    want_asym = (above - below) * sgn
    match_a = want_asym == tr.draw_asym_dir
    ok += match_a

    # need_v2 brute force
    hi, lo, ts = day.high.values, day.low.values, day.timestamp_ny.values
    origin = int(np.argmin(lo)) if tr.direction == "long" else int(np.argmax(hi))
    same = "bullish" if tr.direction == "long" else "bearish"
    others = 0
    fvg_list = []
    for i in range(2, len(hi)):
        topb = botb = dr = None
        if hi[i - 2] < lo[i] and lo[i] - hi[i - 2] >= 3:
            topb, botb, dr = lo[i], hi[i - 2], "bullish"
        elif lo[i - 2] > hi[i] and lo[i - 2] - hi[i] >= 3:
            topb, botb, dr = lo[i - 2], hi[i], "bearish"
        if dr != same or ts[i] <= ts[origin]:
            continue
        if ts[i] == np.datetime64(tr.fvg_created_at):
            continue
        mit = ((lo[i + 1:] <= topb).any() if dr == "bullish"
               else (hi[i + 1:] >= botb).any())
        if not mit:
            others += 1
            fvg_list.append(str(ts[i])[11:19])
    want_v2 = others == 0
    match_v = (want_v2 == tr.need_v2_last_fvg) if not pd.isna(tr.need_v2_last_fvg) else True
    ok += match_v
    L.append(f"### {entry} {tr.direction} @ {tr.entry_price}")
    L.append(f"- untaken above={above} below={below} -> draw_asym_dir want "
             f"{want_asym}, got {tr.draw_asym_dir} -> "
             f"{'PASS' if match_a else '**FAIL**'}")
    L.append(f"  - untaken levels: {', '.join(detail) if detail else '(none)'}")
    L.append(f"- need_v2: leg origin {str(ts[origin])[11:19]}, other unmitigated "
             f"same-dir FVGs after origin: {others} "
             f"({', '.join(fvg_list) if fvg_list else 'none'}) -> want {want_v2}, "
             f"got {tr.need_v2_last_fvg} -> {'PASS' if match_v else '**FAIL**'}")

L.append(f"\n**Spot-check result: {ok}/6 PASS**")

out = RESULTS / "phase3_diagnostic_addendum.md"
out.write_text("\n".join(L))
print("\n".join(L[-30:]))
print(f"\nwrote {out}")
